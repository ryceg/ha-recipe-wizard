"""The in-memory model, and the JSON-LD reader that produces it.

The on-disk format keeps the schema.org core valid and untouched (``@type:
Recipe``, ``recipeIngredient`` as strings, ``recipeInstructions`` as
``HowToStep``) and hangs the structure off an ``rw:`` namespace alongside it.
This module strips the prefix on the way in; nothing downstream should have to
care about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .duration import Duration, parse_duration
from .units import MeasurementSystem, Quantity


def _get(node: dict, *names: str, default: Any = None) -> Any:
    """Read a property, tolerating the ``rw:`` prefix being present or not."""
    for name in names:
        for key in (name, f"rw:{name}"):
            if key in node:
                return node[key]
    return default


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ref(value: Any) -> str | None:
    """Pull an ``@id`` out of a reference node, or accept a bare string id."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("@id")
    raise ValueError(f"not a reference: {value!r}")


def _refs(value: Any) -> list[str]:
    return [r for r in (_ref(v) for v in _as_list(value)) if r]


# --------------------------------------------------------------------------
# Leaf types
# --------------------------------------------------------------------------


@dataclass(slots=True)
class FoodRef:
    """A pointer into the food bank, plus the name the recipe used for it."""

    id: str | None
    name: str | None = None

    @classmethod
    def parse(cls, node: Any) -> "FoodRef | None":
        if node is None:
            return None
        if isinstance(node, str):
            return cls(node, None)
        return cls(node.get("@id"), node.get("name"))


@dataclass(slots=True)
class RequiredState:
    """A precondition on an ingredient, and how long reaching it takes.

    Butter "softened" is not a garnish detail -- it is a scheduling input. The
    lead time is what lets the planner say "take the butter out now".
    """

    description: str
    lead_time: Duration | None = None
    procedure: str | None = None

    @classmethod
    def parse(cls, node: Any) -> "RequiredState | None":
        if node is None:
            return None
        if isinstance(node, str):
            return cls(node)
        return cls(
            description=_get(node, "description", default=""),
            lead_time=parse_duration(_get(node, "leadTime")),
            procedure=_get(node, "procedure"),
        )


@dataclass(slots=True)
class Storage:
    """One storage option: a method, how long it keeps, how long it is *good*.

    These are two different questions and conflating them misreports both. The
    coffee cake keeps 3-4 days, but "the streusel stays nice and crunchy for 2
    days, then starts to soften" -- the cake is perfectly safe on day 3 and no
    longer what it was. ``keeps`` is edibility; ``quality_window`` is the
    texture the recipe was aiming at.
    """

    method: str
    keeps: Duration | None = None
    quality_window: Duration | None = None
    quality_note: str | None = None
    note: str | None = None
    condition: str | None = None
    """When this option applies -- "unless the climate is very hot"."""

    @classmethod
    def parse(cls, node: dict) -> "Storage":
        return cls(
            method=_get(node, "method", default="unspecified"),
            keeps=parse_duration(_get(node, "keeps")),
            quality_window=parse_duration(_get(node, "qualityWindow")),
            quality_note=_get(node, "qualityNote"),
            note=_get(node, "note"),
            condition=_get(node, "condition"),
        )


@dataclass(slots=True)
class BatchConstraints:
    """Hard limits on how far a recipe can be scaled, and why.

    You cannot make 200 g of buttercream: the whisk does not reach it. The
    reason travels with the limit so the resolver can explain a refusal.
    """

    min_yield_g: float | None = None
    max_yield_g: float | None = None
    reason: str | None = None

    @classmethod
    def parse(cls, node: dict | None) -> "BatchConstraints":
        if not node:
            return cls()
        min_q = Quantity.from_jsonld(_get(node, "minYield"))
        max_q = Quantity.from_jsonld(_get(node, "maxYield"))
        return cls(
            min_yield_g=None if min_q is None else min_q.value,
            max_yield_g=None if max_q is None else max_q.value,
            reason=_get(node, "reason"),
        )


@dataclass(slots=True)
class Vessel:
    """What the recipe is cooked in, and what it will hold.

    Only consulted when a recipe is scaled. Double a cake and you have 2.4 kg
    of batter and two tins that hold 1.1 kg between them; the useful thing the
    format can say is "that will not fit, and here are the tin counts the
    source gives times for".
    """

    name: str
    count: int = 1
    capacity: Quantity | None = None

    @classmethod
    def parse(cls, node: dict | None) -> "Vessel | None":
        if not node:
            return None
        return cls(
            name=_get(node, "name", default="vessel"),
            count=int(_get(node, "count", default=1)),
            capacity=Quantity.from_jsonld(_get(node, "capacity")),
        )

    @property
    def total_capacity_g(self) -> float | None:
        if self.capacity is None:
            return None
        return self.capacity.value * self.count


@dataclass(slots=True)
class VesselOption:
    """One row of a source's "other tins and times" table.

    Deliberately a lookup and never interpolated: three shallower 20 cm layers
    bake in 22 minutes where two deeper ones take 30. Bake time is not a
    function of batch mass.
    """

    vessel: str
    duration: Duration | None = None
    note: str | None = None

    @classmethod
    def parse(cls, node: dict) -> "VesselOption":
        return cls(
            vessel=_get(node, "vessel", default=""),
            duration=parse_duration(node.get("totalTime") or _get(node, "duration")),
            note=_get(node, "note"),
        )


@dataclass(slots=True)
class Portion:
    """How much of a thing a single step takes.

    Sources split things constantly and in three different ways: by fraction
    ("just over half the sauce"), by measure ("1 cup crumb mixture") and by
    remainder ("scrunch the remaining crumb"). Without this a step either
    consumes all of something or none of it, which renders the whole 250 g of
    peanut butter against step 2 and leaves step 12's "dollop 2 tbsp across the
    surface" with no ingredient at all.

    Portions are for display, never resolved to a mass. Nobody weighs half a
    Bolognese, and a confidently wrong "1,612 g" is worse than "just over half".
    """

    fraction: float | None = None
    quantity: Quantity | None = None
    remainder: bool = False
    approximate: bool = False
    text: str | None = None
    """The source's own words, preferred over any generated phrasing."""

    @property
    def is_whole(self) -> bool:
        return (
            self.fraction is None
            and self.quantity is None
            and not self.remainder
        )

    def scaled(self, factor: float) -> "Portion":
        """Fractions are scale-invariant; absolute measures are not."""
        if self.quantity is None:
            return self
        return Portion(
            self.fraction,
            self.quantity.scaled(factor),
            self.remainder,
            self.approximate,
            None if factor != 1 else self.text,
        )

    def describe(self) -> str:
        if self.text:
            return self.text
        if self.remainder:
            return "the rest"
        if self.quantity is not None:
            return str(self.quantity)
        if self.fraction is not None:
            about = "about " if self.approximate else ""
            for value, word in ((0.5, "half"), (0.25, "a quarter"),
                                (0.75, "three quarters"), (1 / 3, "a third"),
                                (2 / 3, "two thirds")):
                if abs(self.fraction - value) < 0.02:
                    return f"{about}{word}"
            return f"{about}{self.fraction:.0%}"
        return "all"

    @classmethod
    def parse(cls, node: Any) -> "Portion":
        if node is None:
            return cls()
        if isinstance(node, str):
            return cls(text=node)
        fraction = _get(node, "fraction")
        return cls(
            fraction=None if fraction is None else float(fraction),
            quantity=Quantity.from_jsonld(
                _get(node, "mass") or _get(node, "volume") or _get(node, "quantity")
            ),
            remainder=bool(_get(node, "remainder", default=False)),
            approximate=bool(_get(node, "approximate", default=False)),
            text=_get(node, "text"),
        )


@dataclass(slots=True)
class ConsumeRef:
    """A step's use of one ingredient, component or intermediate."""

    ref: str
    portion: Portion = field(default_factory=Portion)

    @classmethod
    def parse(cls, node: Any) -> "ConsumeRef | None":
        ref = _ref(node)
        if ref is None:
            return None
        portion = Portion()
        if isinstance(node, dict):
            portion = Portion.parse(_get(node, "portion"))
        return cls(ref, portion)


@dataclass(slots=True)
class DelayConstraint:
    """A bound on the gap between finishing one step and starting another.

    ``maximum`` is the constraint that stops a scheduler helpfully suggesting
    the cake batter be made ahead. ``minimum`` is its twin, and its absence was
    just as wrong: the brownies must chill at least three hours before cutting,
    and without a floor the planner cheerfully says cut them now.
    """

    from_step: str
    limit: Duration
    kind: str = "maximum"
    """``maximum`` or ``minimum``."""
    reason: str | None = None

    @classmethod
    def parse(cls, node: dict, kind: str = "maximum") -> "DelayConstraint":
        limit = parse_duration(_get(node, "limit"))
        if limit is None:
            raise ValueError(f"{kind} delay requires a 'limit'")
        from_step = _ref(_get(node, "from"))
        if from_step is None:
            raise ValueError(f"{kind} delay requires a 'from' step reference")
        return cls(from_step, limit, kind, _get(node, "reason"))


@dataclass(slots=True)
class Parameter:
    """A designed axis of variation, with the options its author sanctioned."""

    id: str
    name: str
    target: str | None = None
    default: str | None = None
    options: list[dict] = field(default_factory=list)

    @classmethod
    def parse(cls, node: dict) -> "Parameter":
        return cls(
            id=node.get("@id", ""),
            name=_get(node, "name", default=""),
            target=_ref(_get(node, "target")),
            default=_ref(_get(node, "default")),
            options=_as_list(_get(node, "options")),
        )


# --------------------------------------------------------------------------
# Ingredients, steps, components
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Ingredient:
    """One line of the ingredient table."""

    id: str
    name: str
    food: FoodRef | None = None
    recipe_ref: str | None = None
    preparation: str | None = None
    form: str | None = None
    """Shape or cut, where it changes the density. "The 3 cup measure for 350g
    is for elbow macaroni only" -- density belongs to a food *and a form*."""
    mass: Quantity | None = None
    volume: Quantity | None = None
    count: Quantity | None = None
    scaling: str = "linear"
    """One of linear, fixed, sublinear, toTaste."""
    optional: bool = False
    to_taste: bool = False
    discrete: bool = False
    unit_mass: Quantity | None = None
    required_state: RequiredState | None = None
    substitutes: list[FoodRef] = field(default_factory=list)
    original_text: str | None = None
    note: str | None = None

    @classmethod
    def parse(cls, node: dict) -> "Ingredient":
        food_node = _get(node, "food")
        food = FoodRef.parse(food_node)
        recipe_ref = None
        if isinstance(food_node, dict) and food_node.get("@type") == "Recipe":
            recipe_ref = food_node.get("@id")
        return cls(
            id=node.get("@id", ""),
            name=_get(node, "name") or (food.name if food else "") or "",
            food=food,
            recipe_ref=recipe_ref,
            preparation=_get(node, "preparation"),
            form=_get(node, "form"),
            mass=Quantity.from_jsonld(_get(node, "mass")),
            volume=Quantity.from_jsonld(_get(node, "volume")),
            count=Quantity.from_jsonld(_get(node, "count")),
            scaling=_get(node, "scaling", default="linear"),
            optional=bool(_get(node, "optional", default=False)),
            to_taste=bool(_get(node, "toTaste", default=False)),
            discrete=bool(_get(node, "discrete", default=False)),
            unit_mass=Quantity.from_jsonld(_get(node, "unitMass")),
            required_state=RequiredState.parse(_get(node, "requiredState")),
            substitutes=[
                f for f in (FoodRef.parse(s) for s in _as_list(_get(node, "substitutes")))
                if f
            ],
            original_text=_get(node, "originalText"),
            note=_get(node, "note"),
        )

    @classmethod
    def from_source_text(cls, text: str, index: int) -> "Ingredient":
        """Lift a bare ``recipeIngredient`` string into an ingredient row.

        Every scraped recipe arrives as nothing but these. Dropping them meant
        a scraped recipe rendered with no ingredient column at all -- not
        degraded, absent. Nothing is parsed out of the string here; that is the
        enrichment skill's job. The string simply becomes a visible row.
        """
        return cls(
            id=f"#ing-{index}",
            name=text.strip(),
            original_text=text.strip(),
        )

    def copy(self) -> "Ingredient":
        from copy import deepcopy

        return deepcopy(self)


@dataclass(slots=True)
class Product:
    """An intermediate a step emits -- the "paste" in the middle of a recipe."""

    id: str
    name: str | None = None

    @classmethod
    def parse(cls, node: Any) -> "Product":
        if isinstance(node, str):
            return cls(node)
        return cls(node.get("@id", ""), node.get("name"))


@dataclass(slots=True)
class Step:
    """One numbered instruction, as a node in the dataflow graph."""

    id: str
    position: int
    text: str
    consumes: list[ConsumeRef] = field(default_factory=list)
    produces: list[Product] = field(default_factory=list)
    attention: str = "active"
    """One of active, passive, unattended."""
    duration: Duration | None = None
    duration_max: Duration | None = None
    """Upper end of a range. "Simmer 45 minutes minimum or 1.5-2 hours"."""
    doneness: str | None = None
    """The state that actually decides when the step is finished. Where a
    source gives both, the state is authoritative and the time is an estimate:
    "until most water evaporates but still a bit juicy"."""
    max_delay_after: list[DelayConstraint] = field(default_factory=list)
    min_delay_after: list[DelayConstraint] = field(default_factory=list)
    lead_before: dict[str, Duration] = field(default_factory=dict)
    """Steps that must *start* this long before this one, keyed by step id."""
    tools: list[str] = field(default_factory=list)
    parameters: list[dict] = field(default_factory=list)
    vessel_options: list[VesselOption] = field(default_factory=list)
    timer_starts_when: str | None = None
    safety_note: str | None = None
    may_pause_after: bool = False
    """A sanctioned stopping point -- "stop after step 6, before the cheese"."""

    @property
    def consumed_ids(self) -> list[str]:
        return [c.ref for c in self.consumes]

    def portion_of(self, ref: str) -> Portion | None:
        for consumed in self.consumes:
            if consumed.ref == ref:
                return consumed.portion
        return None

    @classmethod
    def parse(cls, node: dict, fallback_position: int) -> "Step":
        lead = {}
        for entry in _as_list(_get(node, "leadBefore")):
            ref = _ref(_get(entry, "step"))
            amount = parse_duration(_get(entry, "lead"))
            if ref and amount:
                lead[ref] = amount
        duration_node = _get(node, "durationRange")
        duration = parse_duration(node.get("totalTime") or _get(node, "duration"))
        duration_max = parse_duration(_get(node, "durationMax"))
        if duration_node:
            duration = parse_duration(_get(duration_node, "min")) or duration
            duration_max = parse_duration(_get(duration_node, "max")) or duration_max
        return cls(
            id=node.get("@id", f"#step-{fallback_position}"),
            position=int(node.get("position", fallback_position)),
            text=node.get("text", ""),
            consumes=[
                c for c in (ConsumeRef.parse(v) for v in _as_list(_get(node, "consumes")))
                if c
            ],
            produces=[Product.parse(p) for p in _as_list(_get(node, "produces"))],
            attention=_get(node, "attention", default="active"),
            duration=duration,
            duration_max=duration_max,
            doneness=_get(node, "doneness"),
            max_delay_after=[
                DelayConstraint.parse(d, "maximum")
                for d in _as_list(_get(node, "maxDelayAfter"))
            ],
            min_delay_after=[
                DelayConstraint.parse(d, "minimum")
                for d in _as_list(_get(node, "minDelayAfter"))
            ],
            lead_before=lead,
            tools=_refs(node.get("tool")),
            parameters=_as_list(_get(node, "parameters")),
            vessel_options=[
                VesselOption.parse(v) for v in _as_list(_get(node, "bakeTimeByVessel"))
            ],
            timer_starts_when=_get(node, "timerStartsWhen"),
            safety_note=_get(node, "safetyNote"),
            may_pause_after=bool(_get(node, "mayPauseAfter", default=False)),
        )


@dataclass(slots=True)
class BatchPolicy:
    """How to reconcile a fractional scale factor with reality.

    ``roundUpToWholeUnit`` is what a cook actually does: round the discrete
    ingredient (eggs) to a whole number, then renormalise everything else to it.
    """

    mode: str = "scale"
    """One of scale, roundUpToWholeUnit, roundToWholeUnit, wholeBatches, fixed."""
    basis: str | None = None
    """Ingredient id to round on, for the whole-unit modes."""

    @classmethod
    def parse(cls, node: dict | None) -> "BatchPolicy":
        if not node:
            return cls()
        return cls(
            mode=_get(node, "mode", default="scale"),
            basis=_ref(_get(node, "basis")),
        )


@dataclass(slots=True)
class MakeAhead:
    """How far ahead a component may be made, and the state it must be in."""

    max_lead: Duration | None = None
    min_lead: Duration | None = None
    state_at_use: str | None = None

    @classmethod
    def parse(cls, node: dict | None) -> "MakeAhead | None":
        if not node:
            return None
        return cls(
            max_lead=parse_duration(_get(node, "maxLead")),
            min_lead=parse_duration(_get(node, "minLead")),
            state_at_use=_get(node, "stateAtUse"),
        )


@dataclass(slots=True)
class Adjustment:
    """One typed patch operation against a base recipe."""

    op: str
    target: str | None = None
    payload: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, node: dict) -> "Adjustment":
        op = node.get("@type", "").removeprefix("rw:")
        if not op:
            raise ValueError(f"adjustment is missing @type: {node!r}")
        return cls(op=op, target=_ref(_get(node, "target")), payload=node)


@dataclass(slots=True)
class ComponentUse:
    """A parent recipe's *use* of a sub-recipe.

    Deliberately not a Recipe. The standalone buttercream and the cake's
    buttercream disagree about how much butter goes in, which is only
    expressible if the use and the recipe are different objects.
    """

    id: str
    label: str
    recipe_ref: str | None = None
    family_ref: str | None = None
    citation: dict | None = None
    resolvable: bool = True
    requires_mass: Quantity | None = None
    requires_batches: float = 1.0
    batch_policy: BatchPolicy = field(default_factory=BatchPolicy)
    presentation: str = "auto"
    """One of auto, inline, linked."""
    optional: bool = False
    """Whole components can be optional, not just ingredients -- the coffee
    cake's glaze and the qeema's mint yogurt are both take-it-or-leave-it."""
    make_ahead: MakeAhead | None = None
    adjustments: list[Adjustment] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, node: dict) -> "ComponentUse":
        requires = _get(node, "requires") or {}
        batches = 1.0
        mass = None
        if isinstance(requires, dict):
            if _get(requires, "batches") is not None:
                batches = float(_get(requires, "batches"))
            elif "value" in requires:
                mass = Quantity.from_jsonld(requires)
        citation = _get(node, "citation")
        return cls(
            id=node.get("@id", ""),
            label=_get(node, "label", default="") or "",
            recipe_ref=_ref(_get(node, "recipe")),
            family_ref=_ref(_get(node, "family")),
            citation=citation,
            resolvable=bool(_get(node, "resolvable", default=citation is None)),
            requires_mass=mass,
            requires_batches=batches,
            batch_policy=BatchPolicy.parse(_get(node, "batchPolicy")),
            presentation=_get(node, "presentation", default="auto"),
            optional=bool(_get(node, "optional", default=False)),
            make_ahead=MakeAhead.parse(_get(node, "makeAhead")),
            adjustments=[
                Adjustment.parse(a) for a in _as_list(_get(node, "adjustments"))
            ],
            parameters=dict(_get(node, "parameterSelections", default={}) or {}),
        )


# --------------------------------------------------------------------------
# Recipe and family
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Recipe:
    """A recipe document."""

    id: str
    name: str
    url: str | None = None
    author: str | None = None
    family: str | None = None
    is_variant_of: str | None = None
    measurement_system: MeasurementSystem = "metric"
    """The system the source's *volume* measures were written in."""
    canonical_unit_system: str = "metric"
    """Which of the source's parallel unit columns to trust."""
    enrichment_level: int = 0
    """0 scraped strings, 1 parsed quantities, 2 ingredients linked to steps,
    3 components and a full graph. Validation is gated on this so level-3 rules
    do not fire against a level-0 document."""
    prep_time: Duration | None = None
    cook_time: Duration | None = None
    total_time: Duration | None = None
    yield_basis: str = "stated"
    """One of sumOfInputs, measured, stated."""
    scaling_basis: str | None = None
    """Ingredient the SCALING column is a percentage of. Stored once; the
    per-ingredient percentages are derived rather than authored."""
    mass_loss_factor: float = 0.0
    stated_yield: list[Quantity] = field(default_factory=list)
    covers: list[str] = field(default_factory=list)
    """What one batch covers, in the source's own words. Displayed, never
    computed with -- "makes enough for a 2 layer 20 cm cake, or 12 cupcakes
    piped" is useful to read and not worth 300 lines of geometry."""
    vessel: Vessel | None = None
    batch_constraints: BatchConstraints = field(default_factory=BatchConstraints)
    ingredients: list[Ingredient] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    components: list[ComponentUse] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    storage: list[Storage] = field(default_factory=list)
    storage_overrides_components: bool = False
    unsuitable_for: list[str] = field(default_factory=list)
    """Negative storage assertions -- "not recommended for freezing"."""
    serves_with: list[dict] = field(default_factory=list)
    """Accompaniments. A flat display-only list: the qeema is the same dish
    whether you serve rice or naan, so this carries no choice semantics and
    does not scale with the recipe."""
    tools: list[dict] = field(default_factory=list)
    difficulty: str | None = None
    notes: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, node: dict) -> "Recipe":
        author = node.get("author")
        if isinstance(author, dict):
            author = author.get("name")
        steps = [
            Step.parse(s, i + 1)
            for i, s in enumerate(_as_list(node.get("recipeInstructions")))
            if isinstance(s, dict)
        ]

        structured = _as_list(_get(node, "ingredients"))
        ingredients = [Ingredient.parse(i) for i in structured]
        if not ingredients:
            # Level-0 fallback. Without this a scraped recipe has no ingredient
            # column whatsoever, which is data loss rather than degradation.
            ingredients = [
                Ingredient.from_source_text(text, index)
                for index, text in enumerate(_as_list(node.get("recipeIngredient")), 1)
                if isinstance(text, str) and text.strip()
            ]

        declared = _get(node, "enrichmentLevel")
        if declared is None:
            declared = cls._infer_level(structured, steps)

        return cls(
            id=node.get("@id", ""),
            name=node.get("name", ""),
            url=node.get("url"),
            author=author,
            family=_ref(_get(node, "family")),
            is_variant_of=_ref(_get(node, "isVariantOf")),
            measurement_system=_get(node, "measurementSystem", default="metric"),
            canonical_unit_system=_get(node, "canonicalUnitSystem", default="metric"),
            enrichment_level=int(declared),
            prep_time=parse_duration(node.get("prepTime")),
            cook_time=parse_duration(node.get("cookTime")),
            total_time=parse_duration(node.get("totalTime")),
            yield_basis=_get(node, "yieldBasis", default="stated"),
            scaling_basis=_ref(_get(node, "scalingBasis")),
            mass_loss_factor=float(_get(node, "massLossFactor", default=0.0)),
            stated_yield=[
                q for q in (Quantity.from_jsonld(y) for y in _as_list(node.get("recipeYield"))
                            if isinstance(y, dict))
                if q
            ],
            covers=[c for c in _as_list(_get(node, "covers")) if isinstance(c, str)],
            vessel=Vessel.parse(_get(node, "vessel")),
            batch_constraints=BatchConstraints.parse(_get(node, "batchConstraints")),
            ingredients=ingredients,
            steps=steps,
            components=[ComponentUse.parse(c) for c in _as_list(_get(node, "components"))],
            parameters=[Parameter.parse(p) for p in _as_list(_get(node, "parameters"))],
            adjustments=[Adjustment.parse(a) for a in _as_list(_get(node, "adjustments"))],
            storage=[Storage.parse(s) for s in _as_list(_get(node, "storage"))],
            storage_overrides_components=bool(
                _get(node, "storageOverridesComponents", default=False)
            ),
            unsuitable_for=[
                s for s in _as_list(_get(node, "unsuitableFor")) if isinstance(s, str)
            ],
            serves_with=[s for s in _as_list(_get(node, "servesWith")) if isinstance(s, dict)],
            tools=_as_list(node.get("tool")),
            difficulty=_get(node, "difficulty"),
            notes=_as_list(_get(node, "notes")),
            raw=node,
        )

    @staticmethod
    def _infer_level(structured: list, steps: list["Step"]) -> int:
        """Work out the enrichment level when the document does not declare it."""
        if not structured:
            return 0
        linked = any(step.consumes for step in steps)
        if not linked:
            return 1
        graphed = any(step.produces for step in steps)
        return 3 if graphed else 2

    def ingredient(self, ingredient_id: str) -> Ingredient | None:
        """Look an ingredient up by id, tolerating a fully-qualified reference."""
        fragment = "#" + ingredient_id.split("#")[-1]
        for ing in self.ingredients:
            if ing.id in (ingredient_id, fragment):
                return ing
        return None

    def step(self, step_id: str) -> Step | None:
        fragment = "#" + step_id.split("#")[-1]
        for st in self.steps:
            if st.id in (step_id, fragment):
                return st
        return None

    def copy(self) -> "Recipe":
        from copy import deepcopy

        return deepcopy(self)


@dataclass(slots=True)
class RecipeFamily:
    """A grouping of sibling recipes that fill the same role.

    Chocolate and vanilla buttercream share no quantities and no method, so
    neither is a variant of the other; they are members of a family.

    A family is a browsing tag, not a resolution mechanism. It was originally
    meant to let a parent ask for "any buttercream" and have the UI offer a
    swap -- but swapping a component is not something anyone wants; you read
    the two recipes instead. So nothing resolves through a family.
    """

    id: str
    name: str
    members: list[str] = field(default_factory=list)
    default: str | None = None

    @classmethod
    def parse(cls, node: dict) -> "RecipeFamily":
        return cls(
            id=node.get("@id", ""),
            name=node.get("name", ""),
            members=_refs(_get(node, "members")),
            default=_ref(_get(node, "default")),
        )
