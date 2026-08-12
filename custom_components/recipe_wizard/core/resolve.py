"""The resolver: base + variants + patches + scale -> real numbers.

Order matters, and getting it wrong is silent rather than loud. Adjustments are
expressed at *base yield*, so they are applied before scaling. Apply them the
other way round and a parent's "make the sugar 180 g" override becomes 120 g
once the batch is scaled down, with nothing to indicate anything went wrong.

    1. load base
    2. apply the variant chain, base-first
    3. apply the parent's local adjustments
    4. compute batch yield
    5. compute the required amount (mass, or coverage resolved against yield)
    6. raw scale factor = required / yield
    7. apply the batch policy (discrete rounding, whole batches)
    8. check batch constraints
    9. scale, honouring each ingredient's own scaling mode
   10. report what is actually produced, and the leftover
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .adjust import apply_adjustments
from .library import Library
from .mass import ingredient_mass
from .model import (
    Adjustment,
    BatchPolicy,
    ComponentUse,
    MakeAhead,
    Recipe,
    RequiredState,
    Step,
    Storage,
)
from .units import Quantity


class BatchConstraintError(ValueError):
    """The requested amount falls outside what the recipe can physically make."""


class UnresolvableComponent(LookupError):
    """A component is a citation to something not in the library.

    Modernist's "see page 121" and RecipeTin's cookbook-only flavours are the
    same shape: referenced, renderable, not expandable. The resolver refuses
    rather than inventing quantities, and the shopping list skips it.
    """

    def __init__(self, use: ComponentUse) -> None:
        self.use = use
        cite = use.citation or {}
        where = cite.get("name") or use.recipe_ref or use.label
        page = cite.get("rw:page") or cite.get("page")
        detail = f"{where}, p.{page}" if page else str(where)
        super().__init__(f"{use.label!r} is not in the library: see {detail}")


@dataclass(slots=True)
class ResolvedIngredient:
    id: str
    name: str
    food_id: str | None
    mass_g: float | None
    base_mass_g: float | None
    scaling: str
    optional: bool = False
    to_taste: bool = False
    required_state: RequiredState | None = None
    note: str | None = None
    confidence: str = "high"
    display: str | None = None

    def __str__(self) -> str:
        suffix = " (optional)" if self.optional else ""
        if self.to_taste:
            return f"{self.name}, to taste"
        if self.mass_g is None:
            return f"{self.name}{suffix}"
        return f"{self.mass_g:.0f} g {self.name}{suffix}"


@dataclass(slots=True)
class Resolution:
    """A fully materialised recipe at a specific scale."""

    recipe_id: str
    name: str
    label: str
    scale: float
    batch_yield_g: float | None
    requested_g: float | None
    produced_g: float | None
    ingredients: list[ResolvedIngredient] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    storage: list[Storage] = field(default_factory=list)
    make_ahead: MakeAhead | None = None
    warnings: list[str] = field(default_factory=list)
    change_log: list[str] = field(default_factory=list)

    #: Differences below this fraction of the request are treated as met.
    TOLERANCE = 0.02

    @property
    def leftover_g(self) -> float | None:
        """Surplus over what was asked for. Negative means a shortfall.

        A small shortfall is expected rather than a bug: ingredients marked
        ``sublinear`` (leavening, seasoning, extracts) deliberately do not scale
        with the rest, so the batch does not land exactly on the target.
        """
        if self.produced_g is None or self.requested_g is None:
            return None
        return self.produced_g - self.requested_g

    @property
    def meets_request(self) -> bool:
        leftover = self.leftover_g
        if leftover is None or self.requested_g in (None, 0):
            return True
        return leftover >= -abs(self.requested_g) * self.TOLERANCE

    def summary(self) -> str:
        parts = [f"{self.label or self.name}: x{self.scale:.3g}"]
        if self.produced_g is not None:
            parts.append(f"makes {self.produced_g:.0f} g")
        if self.requested_g is not None:
            parts.append(f"needs {self.requested_g:.0f} g")
        leftover = self.leftover_g
        if leftover is not None and self.requested_g:
            share = leftover / self.requested_g
            if share > self.TOLERANCE:
                parts.append(f"leftover {leftover:.0f} g")
            elif share < -self.TOLERANCE:
                parts.append(f"SHORT by {abs(leftover):.0f} g")
        return ", ".join(parts)


def _merge_variant_metadata(base: Recipe, variant: Recipe) -> None:
    """Let a variant override identity and claims without restating quantities."""
    base.id = variant.id
    if variant.name:
        base.name = variant.name
    if variant.url:
        base.url = variant.url
    if variant.family:
        base.family = variant.family
    if variant.covers:
        base.covers = variant.covers
    if variant.storage:
        base.storage = variant.storage
    if variant.batch_constraints.min_yield_g is not None:
        base.batch_constraints = variant.batch_constraints
    if variant.notes:
        base.notes = [*base.notes, *variant.notes]


def materialise(
    library: Library,
    recipe_id: str,
    *,
    adjustments: list[Adjustment] | None = None,
) -> tuple[Recipe, list[str]]:
    """Steps 1-3: everything that happens at base yield, before scaling."""
    chain = library.variant_chain(recipe_id)
    recipe = chain[0].copy()
    log: list[str] = []

    for variant in chain[1:]:
        recipe, sub_log = apply_adjustments(recipe, variant.adjustments)
        _merge_variant_metadata(recipe, variant)
        log.append(f"variant: {variant.name}")
        log.extend(f"  {entry}" for entry in sub_log)

    if adjustments:
        recipe, local_log = apply_adjustments(recipe, adjustments)
        log.append("local adjustments:")
        log.extend(f"  {entry}" for entry in local_log)

    return recipe, log


def batch_yield_grams(
    recipe: Recipe, library: Library
) -> tuple[float | None, list[str], dict[str, float | None]]:
    """Step 4. Returns the yield, any warnings, and each ingredient's mass.

    ``sumOfInputs`` is exact for anything uncooked and close enough elsewhere
    with a loss factor: Modernist's carrot soup sums to 1325.5 g against a
    stated 1.3 kg, which is the ~2% the pressure cooker takes off.
    """
    warnings: list[str] = []
    masses: dict[str, float | None] = {}
    total = 0.0
    for ing in recipe.ingredients:
        result = ingredient_mass(
            ing,
            library.foods,
            recipe.measurement_system,
            canonical=recipe.canonical_unit_system,
        )
        masses[ing.id] = result.grams
        warnings.extend(result.warnings)
        if result.grams is not None and not ing.optional:
            total += result.grams

    if recipe.yield_basis in ("sumOfInputs", "measured"):
        if recipe.yield_basis == "sumOfInputs":
            return total * (1 - recipe.mass_loss_factor), warnings, masses

    for quantity in recipe.stated_yield:
        try:
            if quantity.dimension == "mass":
                from .units import to_grams

                return to_grams(quantity), warnings, masses
        except Exception:  # noqa: BLE001 - a bad yield unit is not fatal here
            continue

    if total > 0:
        warnings.append(
            f"{recipe.name!r} states no mass yield; falling back to the sum of "
            f"its inputs ({total:.0f} g)"
        )
        return total * (1 - recipe.mass_loss_factor), warnings, masses
    return None, warnings, masses


def _apply_batch_policy(
    recipe: Recipe,
    policy: BatchPolicy,
    raw_scale: float,
    masses: dict[str, float | None],
) -> tuple[float, list[str]]:
    """Step 7. Reconcile a fractional scale with things that come in whole units."""
    warnings: list[str] = []
    if policy.mode in ("scale", None):
        return raw_scale, warnings
    if policy.mode == "fixed":
        if abs(raw_scale - 1.0) > 0.01:
            warnings.append(
                f"{recipe.name!r} does not scale; making one full batch instead "
                f"of x{raw_scale:.2f}"
            )
        return 1.0, warnings
    if policy.mode == "wholeBatches":
        batches = max(1, math.ceil(raw_scale - 1e-9))
        if batches != raw_scale:
            warnings.append(f"rounded up to {batches} whole batch(es)")
        return float(batches), warnings

    if policy.mode in ("roundUpToWholeUnit", "roundToWholeUnit"):
        if not policy.basis:
            warnings.append("batch policy needs a 'basis' ingredient; scaling freely")
            return raw_scale, warnings
        ing = recipe.ingredient(policy.basis)
        if ing is None:
            warnings.append(
                f"batch policy basis {policy.basis!r} is not an ingredient of "
                f"{recipe.name!r}; scaling freely"
            )
            return raw_scale, warnings
        base_count = ing.count.value if ing.count is not None else None
        if base_count is None and ing.unit_mass is not None:
            base_mass = masses.get(ing.id)
            if base_mass:
                base_count = base_mass / ing.unit_mass.value
        if not base_count:
            warnings.append(
                f"{ing.name!r} has no countable amount to round on; scaling freely"
            )
            return raw_scale, warnings

        wanted = base_count * raw_scale
        rounded = (
            math.ceil(wanted - 1e-9)
            if policy.mode == "roundUpToWholeUnit"
            else max(1, round(wanted))
        )
        rounded = max(1, rounded)
        new_scale = rounded / base_count
        if abs(new_scale - raw_scale) > 1e-9:
            warnings.append(
                f"{wanted:.2f} {ing.name} rounded to {rounded:g}; batch renormalised "
                f"from x{raw_scale:.3g} to x{new_scale:.3g}"
            )
        return new_scale, warnings

    warnings.append(f"unknown batch policy {policy.mode!r}; scaling freely")
    return raw_scale, warnings


def _scale_factor_for(ing_scaling: str, scale: float) -> float:
    """Per-ingredient scaling behaviour. Not everything is linear."""
    if ing_scaling == "fixed":
        return 1.0
    if ing_scaling == "sublinear":
        return scale**0.5
    return scale


def resolve(
    library: Library,
    recipe_id: str,
    *,
    requires_mass: Quantity | None = None,
    requires_batches: float = 1.0,
    batch_policy: BatchPolicy | None = None,
    adjustments: list[Adjustment] | None = None,
    label: str | None = None,
    strict: bool = True,
) -> Resolution:
    """Materialise a recipe at whatever scale the caller needs.

    Scale comes from a mass, or from a batch count. Batches are what parents
    actually ask for -- doubling a cake doubles its frosting, and that
    propagates as a plain factor with no geometry involved.
    """
    recipe, change_log = materialise(library, recipe_id, adjustments=adjustments)
    batch_yield, warnings, masses = batch_yield_grams(recipe, library)

    # Steps 5 and 6: what does the caller need, and what factor is that?
    requested_g: float | None = None
    if requires_mass is not None:
        from .units import to_grams

        requested_g = to_grams(requires_mass)
        raw_scale = 1.0 if batch_yield in (None, 0) else requested_g / batch_yield
    else:
        raw_scale = requires_batches
        if batch_yield is not None:
            requested_g = batch_yield * requires_batches

    # Step 7
    policy = batch_policy or BatchPolicy()
    scale, policy_warnings = _apply_batch_policy(recipe, policy, raw_scale, masses)
    warnings.extend(policy_warnings)

    # Steps 9-10: scale, then recompute what is actually produced. Recomputing
    # matters because 'fixed' ingredients do not scale, so the yield is not
    # linear in the scale factor.
    resolved: list[ResolvedIngredient] = []
    produced = 0.0
    for ing in recipe.ingredients:
        base = masses.get(ing.id)
        factor = _scale_factor_for(ing.scaling, scale)
        scaled = None if base is None else base * factor
        if scaled is not None and not ing.optional:
            produced += scaled
        result = ingredient_mass(
            ing, library.foods, recipe.measurement_system,
            canonical=recipe.canonical_unit_system,
        )
        resolved.append(
            ResolvedIngredient(
                id=ing.id,
                name=ing.name,
                food_id=ing.food.id if ing.food else None,
                mass_g=scaled,
                base_mass_g=base,
                scaling=ing.scaling,
                optional=ing.optional,
                to_taste=ing.to_taste,
                required_state=ing.required_state,
                note=ing.note,
                confidence=result.confidence,
                display=str(ing.volume) if ing.volume else None,
            )
        )
    produced_g = produced * (1 - recipe.mass_loss_factor) if produced else None

    # Step 8, deferred to here so the message can quote the real produced mass.
    limits = recipe.batch_constraints
    if produced_g is not None and limits.min_yield_g and produced_g < limits.min_yield_g:
        message = (
            f"{recipe.name!r} cannot be made at {produced_g:.0f} g: its minimum "
            f"batch is {limits.min_yield_g:.0f} g"
            + (f" ({limits.reason})" if limits.reason else "")
        )
        if strict:
            raise BatchConstraintError(message)
        warnings.append(message)
    if produced_g is not None and limits.max_yield_g and produced_g > limits.max_yield_g:
        message = (
            f"{recipe.name!r} cannot be made at {produced_g:.0f} g: its maximum "
            f"batch is {limits.max_yield_g:.0f} g"
            + (f" ({limits.reason})" if limits.reason else "")
        )
        if strict:
            raise BatchConstraintError(message)
        warnings.append(message)

    warnings.extend(vessel_warnings(recipe, scale, produced_g))

    return Resolution(
        recipe_id=recipe.id,
        name=recipe.name,
        label=label or recipe.name,
        scale=scale,
        batch_yield_g=batch_yield,
        requested_g=requested_g,
        produced_g=produced_g,
        ingredients=resolved,
        steps=scaled_steps(recipe, scale),
        storage=recipe.storage,
        warnings=warnings,
        change_log=change_log,
    )


def scaled_steps(recipe: Recipe, scale: float) -> list[Step]:
    """Steps with their absolute portions scaled.

    Fractions are scale-invariant -- half the sauce is half the sauce at any
    batch size -- but "1 cup of the crumb mixture" is not, and a doubled recipe
    needs two.
    """
    if abs(scale - 1.0) < 1e-9:
        return recipe.steps
    from copy import deepcopy

    steps = deepcopy(recipe.steps)
    for step in steps:
        for consumed in step.consumes:
            consumed.portion = consumed.portion.scaled(scale)
    return steps


def vessel_warnings(
    recipe: Recipe, scale: float, produced_g: float | None
) -> list[str]:
    """What the cook needs to hear when a recipe is scaled.

    Doubling is a routine thing to do and it is where a format that only scales
    ingredient quantities becomes actively misleading. Double the cake and you
    have 2.4 kg of batter, two tins that hold 1.1 kg between them, and a bake
    time that is emphatically not 60 minutes.
    """
    if abs(scale - 1.0) < 1e-9:
        return []

    out: list[str] = []
    vessel = recipe.vessel
    capacity = vessel.total_capacity_g if vessel else None
    if capacity and produced_g and produced_g > capacity * 1.02:
        needed = produced_g / (capacity / vessel.count)
        out.append(
            f"scaled to x{scale:g} this makes {produced_g:.0f} g, but "
            f"{vessel.count} x {vessel.name} holds about {capacity:.0f} g - "
            f"you need roughly {needed:.0f} of them"
        )

    for step in recipe.steps:
        if not step.vessel_options:
            continue
        options = ", ".join(
            f"{o.vessel}: {o.duration.human()}" if o.duration else o.vessel
            for o in step.vessel_options
        )
        out.append(
            f"do not scale the time on step {step.position}; it comes from the "
            f"vessel, not the quantity. Options given: {options}"
        )
        break

    return out


def resolve_component(
    library: Library, use: ComponentUse, *, strict: bool = True
) -> Resolution:
    """Resolve a parent's use of a sub-recipe."""
    if not use.resolvable or (use.recipe_ref is None and use.citation is not None):
        raise UnresolvableComponent(use)

    # A family is a browsing tag, not a resolution mechanism -- nothing falls
    # back through it, because swapping one sibling for another is something a
    # cook does by reading both recipes, not something the resolver does.
    recipe_ref = use.recipe_ref
    if recipe_ref is None:
        raise UnresolvableComponent(use)

    resolution = resolve(
        library,
        recipe_ref,
        requires_mass=use.requires_mass,
        requires_batches=use.requires_batches,
        batch_policy=use.batch_policy,
        adjustments=use.adjustments,
        label=use.label,
        strict=strict,
    )
    resolution.make_ahead = use.make_ahead
    return resolution
