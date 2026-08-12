"""Builders that let a test state its own premise.

Naming a real recipe was, for a while, the only way for a test to say "a recipe
like this". That is fine while the corpus is seven files and stops being fine at
two hundred: the premise ends up as arithmetic against someone else's cake
(``batch_yield_g * 0.5613``, divided by an ``rw:unitMass`` read out of the
recipe file), and an assertion counting one finding across the whole library
breaks the day an eighth recipe honestly contains the same thing.

So the premise gets built here instead, and the corpus keeps the assertions that
are genuinely about the real data.

**Everything goes out as a JSON-LD document and comes back through
``Recipe.parse``.** Instantiating the dataclasses would be shorter and would
quietly stop testing the reader: the builder would drift away from the on-disk
format, and a test could then assert behaviour no recipe file can actually
produce.

    recipe = build_recipe(ingredients=[ingredient("eggs", count=4, unit_mass=50),
                                       ingredient("flour", mass=200)])
    result = resolve(build_library(recipe), recipe.id)

One thing deliberately absent: there is no ``batch_policy=`` on
``build_recipe``, because a recipe document does not carry one -- the reader
only reads ``rw:batchPolicy`` off a ``rw:ComponentUse``. It is on ``component``,
and ``resolve()`` takes a ``BatchPolicy`` directly. Offering it on the recipe
would emit a key the reader ignores, which is exactly the lie this module exists
to prevent.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping, Sequence

from custom_components.recipe_wizard.core.duration import format_duration
from custom_components.recipe_wizard.core.library import FoodBank, Library
from custom_components.recipe_wizard.core.model import Recipe, RecipeFamily

#: Units the real documents write as UN/CEFACT codes. Anything else goes out as
#: ``unitText``, which is what the recipes do for kitchen units.
_UNIT_CODES = {"g": "GRM", "kg": "KGM", "ml": "MLT", "l": "LTR"}


@lru_cache(maxsize=1)
def food_bank() -> FoodBank:
    """The real food bank, read once.

    Not mocked: densities and per-unit masses are the data the corpus resolves
    against, and a test premise built on invented ones would pass against a
    library that cannot exist.
    """
    return FoodBank.load()


# ---------------------------------------------------------------------------
# Leaf nodes
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _quantity(spec: Any, default_unit: str = "") -> dict | None:
    """A ``QuantitativeValue`` node from a number, a pair, or a literal dict.

    ``250`` takes the default unit for the field it was passed to; ``(1, "cup")``
    names its own; ``(2.5, "cup", "2 1/2 cups")`` adds the source's own display
    text. A dict passes straight through for the awkward cases.
    """
    if spec is None:
        return None
    if isinstance(spec, Mapping):
        return dict(spec)
    if isinstance(spec, (int, float)):
        value, unit, display = float(spec), default_unit, None
    else:
        parts = list(spec)
        value = float(parts[0])
        unit = parts[1] if len(parts) > 1 else default_unit
        display = parts[2] if len(parts) > 2 else None
    node: dict[str, Any] = {"@type": "QuantitativeValue", "value": value}
    code = _UNIT_CODES.get(unit)
    if code:
        node["unitCode"] = code
    elif unit:
        node["unitText"] = unit
    if display:
        node["rw:display"] = display
    return node


def _iso(value: Any) -> str | None:
    """A duration, given either as ISO 8601 or as a plain number of minutes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return format_duration(float(value) * 60)
    return str(value)


def _reference(value: Any) -> dict:
    return {"@id": value} if isinstance(value, str) else dict(value)


def _is_labelled_pair(value: Any) -> bool:
    """``("#dry-mix", "Dry mix")`` is one product; ``("#a", "#b")`` is two."""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(part, str) for part in value)
        and value[0].startswith("#")
        and not value[1].startswith("#")
    )


def portion(
    *,
    fraction: float | None = None,
    mass: Any = None,
    volume: Any = None,
    remainder: bool = False,
    approximate: bool = False,
    text: str | None = None,
) -> dict:
    """How much of one thing a step takes: a fraction, a measure, or the rest."""
    node: dict[str, Any] = {}
    if fraction is not None:
        node["rw:fraction"] = fraction
    if mass is not None:
        node["rw:mass"] = _quantity(mass, "g")
    if volume is not None:
        node["rw:volume"] = _quantity(volume, "ml")
    if remainder:
        node["rw:remainder"] = True
    if approximate:
        node["rw:approximate"] = True
    if text:
        node["rw:text"] = text
    return node


def ingredient(
    name: str,
    *,
    id: str | None = None,
    food: Any = None,
    mass: Any = None,
    volume: Any = None,
    count: Any = None,
    unit_mass: Any = None,
    scaling: str = "linear",
    optional: bool = False,
    to_taste: bool = False,
    discrete: bool = False,
    form: str | None = None,
    preparation: str | None = None,
    required_state: Any = None,
    substitutes: Sequence[str] = (),
    note: str | None = None,
    original_text: str | None = None,
) -> dict:
    """One ``rw:Ingredient`` row, identified by ``#`` plus a slug of its name.

    ``mass`` is grams, ``volume`` millilitres and ``count`` a bare number unless
    a ``(value, unit)`` pair says otherwise::

        ingredient("flour", mass=250)
        ingredient("milk", volume=(1, "cup"), food="food:milk-full-fat")
        ingredient("eggs", count=(4, "large"), unit_mass=52.5, discrete=True)

    ``food`` is needed only where the mass has to come out of the food bank -- a
    volume needs a density, a count needs a per-unit mass unless ``unit_mass``
    states one. Where the row states its own mass, naming a food is noise.
    """
    node: dict[str, Any] = {
        "@id": id or f"#{_slug(name)}",
        "@type": "rw:Ingredient",
        "name": name,
    }
    if food is not None:
        node["rw:food"] = (
            {"@id": food} if isinstance(food, str)
            else {"@id": food[0], "name": food[1]}
        )
    for key, value, unit in (
        ("rw:mass", mass, "g"),
        ("rw:volume", volume, "ml"),
        ("rw:count", count, ""),
        ("rw:unitMass", unit_mass, "g"),
    ):
        quantity = _quantity(value, unit)
        if quantity is not None:
            node[key] = quantity
    node["rw:scaling"] = scaling
    if optional:
        node["rw:optional"] = True
    if to_taste:
        node["rw:toTaste"] = True
    if discrete:
        node["rw:discrete"] = True
    for key, value in (
        ("rw:form", form),
        ("rw:preparation", preparation),
        ("rw:note", note),
        ("rw:originalText", original_text),
    ):
        if value is not None:
            node[key] = value
    if required_state is not None:
        node["rw:requiredState"] = required_state
    if substitutes:
        node["rw:substitutes"] = [_reference(s) for s in substitutes]
    return node


def step(
    id: str,
    *,
    text: str | None = None,
    consumes: Sequence[Any] = (),
    produces: Any = (),
    attention: str = "active",
    duration: Any = None,
    duration_max: Any = None,
    doneness: str | None = None,
    position: int | None = None,
    max_delay_after: Sequence[Any] = (),
    min_delay_after: Sequence[Any] = (),
    lead_before: Sequence[Any] = (),
    vessel_options: Sequence[Any] = (),
    may_pause_after: bool = False,
    timer_starts_when: str | None = None,
    safety_note: str | None = None,
) -> dict:
    """One ``HowToStep``, as a node in the dataflow graph.

    ``consumes`` takes bare ids, or ``(id, portion(...))`` pairs where the step
    only takes part of something. ``produces`` takes an id, an ``(id, label)``
    pair, or a list of either. Durations are ISO 8601 or a number of minutes::

        step("#whisk-dry", consumes=["#flour", "#salt"], produces=("#dry", "Dry mix"))
        step("#bake", consumes=["#pans"], duration=30, attention="unattended")
        step("#cut", min_delay_after=[("#cool", "PT3H", "the filling oozes")])
    """
    node: dict[str, Any] = {"@type": "HowToStep", "@id": id}
    if position is not None:
        node["position"] = position
    node["text"] = text if text is not None else _slug(id).replace("-", " ").capitalize() + "."

    consumed = []
    for entry in consumes:
        if isinstance(entry, str):
            consumed.append({"@id": entry})
        elif isinstance(entry, Mapping):
            consumed.append(dict(entry))
        else:
            ref, share = entry
            consumed.append({"@id": ref, "rw:portion": share})
    if consumed:
        node["rw:consumes"] = consumed

    if isinstance(produces, (str, Mapping)):
        produced: list[Any] = [produces]
    elif _is_labelled_pair(produces):
        produced = [produces]  # one (id, label) pair rather than two bare ids
    else:
        produced = list(produces)
    emitted = []
    for entry in produced:
        if isinstance(entry, str):
            emitted.append({"@id": entry})
        elif isinstance(entry, Mapping):
            emitted.append(dict(entry))
        else:
            emitted.append({"@id": entry[0], "name": entry[1]})
    if emitted:
        node["rw:produces"] = emitted

    node["rw:attention"] = attention
    if duration is not None:
        node["totalTime"] = _iso(duration)
    if duration_max is not None:
        node["rw:durationMax"] = _iso(duration_max)
    if doneness is not None:
        node["rw:doneness"] = doneness
    if timer_starts_when is not None:
        node["rw:timerStartsWhen"] = timer_starts_when
    if safety_note is not None:
        node["rw:safetyNote"] = safety_note
    if may_pause_after:
        node["rw:mayPauseAfter"] = True

    for key, entries in (("rw:maxDelayAfter", max_delay_after),
                         ("rw:minDelayAfter", min_delay_after)):
        constraints = []
        for entry in entries:
            if isinstance(entry, Mapping):
                constraints.append(dict(entry))
                continue
            parts = list(entry)
            constraint = {"rw:from": {"@id": parts[0]}, "rw:limit": _iso(parts[1])}
            if len(parts) > 2:
                constraint["rw:reason"] = parts[2]
            constraints.append(constraint)
        if constraints:
            node[key] = constraints

    leads = []
    for entry in lead_before:
        if isinstance(entry, Mapping):
            leads.append(dict(entry))
            continue
        parts = list(entry)
        lead = {"rw:step": {"@id": parts[0]}, "rw:lead": _iso(parts[1])}
        if len(parts) > 2:
            lead["rw:reason"] = parts[2]
        leads.append(lead)
    if leads:
        node["rw:leadBefore"] = leads

    options = []
    for entry in vessel_options:
        if isinstance(entry, Mapping):
            options.append(dict(entry))
            continue
        parts = list(entry)
        option = {"rw:vessel": parts[0]}
        if len(parts) > 1:
            option["totalTime"] = _iso(parts[1])
        if len(parts) > 2:
            option["rw:note"] = parts[2]
        options.append(option)
    if options:
        node["rw:bakeTimeByVessel"] = options

    return node


def insert_step(new_step: Mapping, *, after: str | None = None) -> dict:
    """An ``rw:InsertStep`` patch operation, for ``adjustments=``.

    The one operation whose effect is on the rest of the document: it renumbers
    every ``rw:position`` after the anchor, which is exactly why
    ``docs/format.md`` Principle 5 forbids ``#step-3``. A test whose subject is
    what survives that -- a validator finding still naming the node it named
    before the insert -- has to be able to write the patch without hand-authoring
    JSON-LD, which is where the premise stops being visible.

    ``after`` names the step to insert below; left out, the step goes last.
    """
    node: dict[str, Any] = {"@type": "rw:InsertStep", "rw:step": dict(new_step)}
    if after is not None:
        node["rw:after"] = {"@id": after}
    return node


def component(
    label: str,
    *,
    id: str | None = None,
    recipe: str | None = None,
    family: str | None = None,
    requires_batches: float | None = None,
    requires_mass: Any = None,
    batch_policy: Any = None,
    optional: bool = False,
    presentation: str | None = None,
    citation: Mapping | None = None,
    adjustments: Sequence[Mapping] = (),
    make_ahead: Mapping | None = None,
) -> dict:
    """A parent's ``rw:ComponentUse`` of a sub-recipe.

    ``batch_policy`` is a ``(mode, basis)`` pair -- this is the one place a
    document carries one.
    """
    node: dict[str, Any] = {
        "@id": id or f"#{_slug(label)}",
        "@type": "rw:ComponentUse",
        "rw:label": label,
    }
    if recipe is not None:
        node["rw:recipe"] = {"@id": recipe}
    if family is not None:
        node["rw:family"] = {"@id": family}
    if requires_mass is not None:
        node["rw:requires"] = _quantity(requires_mass, "g")
    else:
        node["rw:requires"] = {"rw:batches": 1 if requires_batches is None
                               else requires_batches}
    if batch_policy is not None:
        if isinstance(batch_policy, Mapping):
            node["rw:batchPolicy"] = dict(batch_policy)
        else:
            mode, basis = batch_policy
            node["rw:batchPolicy"] = {"rw:mode": mode, "rw:basis": {"@id": basis}}
    if optional:
        node["rw:optional"] = True
    if presentation is not None:
        node["rw:presentation"] = presentation
    if citation is not None:
        node["rw:citation"] = dict(citation)
    if adjustments:
        node["rw:adjustments"] = [dict(a) for a in adjustments]
    if make_ahead is not None:
        node["rw:makeAhead"] = dict(make_ahead)
    return node


def storage_option(
    method: str,
    *,
    keeps: str | None = None,
    quality_window: str | None = None,
    quality_note: str | None = None,
    condition: str | None = None,
    note: str | None = None,
) -> dict:
    """One storage option. ``keeps`` is edibility, ``quality_window`` is how long
    it is still what the recipe was aiming at; they are different questions."""
    node: dict[str, Any] = {"rw:method": method}
    for key, value in (("rw:keeps", keeps),
                       ("rw:qualityWindow", quality_window),
                       ("rw:qualityNote", quality_note),
                       ("rw:condition", condition),
                       ("rw:note", note)):
        if value is not None:
            node[key] = value
    return node


# ---------------------------------------------------------------------------
# Documents and libraries
# ---------------------------------------------------------------------------

#: What ``build_recipe()`` with nothing named at all is: one ingredient, one step
#: that consumes it. It resolves to 250 g and validates with no findings, so any
#: finding a test sees came from the premise that test stated.
_DEFAULT_INGREDIENTS = (ingredient("flour", mass=250),)


def build_document(
    *,
    id: str | None = None,
    name: str = "Built recipe",
    ingredients: Sequence[Any] | None = None,
    steps: Sequence[Any] | None = None,
    components: Sequence[Mapping] = (),
    storage: Sequence[Mapping] = (),
    storage_overrides_components: bool = False,
    unsuitable_for: Sequence[str] = (),
    enrichment_level: int | None = None,
    yield_basis: str | None = None,
    stated_yield: Sequence[Any] = (),
    mass_loss_factor: float = 0.0,
    scaling_basis: str | None = None,
    covers: Sequence[str] = (),
    vessel: Any = None,
    batch_constraints: Any = None,
    measurement_system: str = "metric",
    canonical_unit_system: str = "metric",
    family: str | None = None,
    variant_of: str | None = None,
    adjustments: Sequence[Mapping] = (),
    notes: Sequence[str] = (),
    extra: Mapping | None = None,
) -> dict:
    """The JSON-LD document ``build_recipe`` parses. See it for the arguments."""
    if ingredients is None:
        ingredients = _DEFAULT_INGREDIENTS
    structured = [i for i in ingredients if not isinstance(i, str)]
    strings = [i for i in ingredients if isinstance(i, str)]

    if steps is None:
        # One step consuming everything, so a built recipe has a complete graph
        # by default and an unused-ingredient finding means the test asked for one.
        consumes = [i["@id"] for i in structured] + [c["@id"] for c in components]
        steps = [step("#mix", text="Combine everything.", consumes=consumes,
                      produces=("#result", "Result"))]

    doc: dict[str, Any] = {
        "@context": ["https://schema.org",
                     {"rw": "https://ha-recipe-wizard.local/vocab#"}],
        "@type": "Recipe",
        "@id": id or f"urn:recipe:test/{_slug(name)}",
        "name": name,
        "rw:measurementSystem": measurement_system,
        "rw:canonicalUnitSystem": canonical_unit_system,
    }
    if enrichment_level is not None:
        doc["rw:enrichmentLevel"] = enrichment_level

    # ``sumOfInputs`` only once there is something to sum: a level-0 scrape of
    # bare strings states no yield at all, and claiming one for it would make the
    # builder unable to express the case.
    if yield_basis is None and structured:
        yield_basis = "sumOfInputs"
    if yield_basis is not None:
        doc["rw:yieldBasis"] = yield_basis
    if mass_loss_factor:
        doc["rw:massLossFactor"] = mass_loss_factor
    if stated_yield:
        doc["recipeYield"] = [_quantity(y, "g") for y in stated_yield]
    if scaling_basis is not None:
        doc["rw:scalingBasis"] = {"@id": scaling_basis}
    if covers:
        doc["rw:covers"] = list(covers)

    if vessel is not None:
        if isinstance(vessel, Mapping):
            doc["rw:vessel"] = dict(vessel)
        else:
            vessel_name, count, capacity = vessel
            doc["rw:vessel"] = {"rw:name": vessel_name, "rw:count": count,
                                "rw:capacity": _quantity(capacity, "g")}
    if batch_constraints is not None:
        if isinstance(batch_constraints, Mapping):
            doc["rw:batchConstraints"] = dict(batch_constraints)
        else:
            parts = list(batch_constraints)
            limits: dict[str, Any] = {}
            if parts[0] is not None:
                limits["rw:minYield"] = _quantity(parts[0], "g")
            if len(parts) > 1 and parts[1] is not None:
                limits["rw:maxYield"] = _quantity(parts[1], "g")
            if len(parts) > 2:
                limits["rw:reason"] = parts[2]
            doc["rw:batchConstraints"] = limits

    if strings:
        doc["recipeIngredient"] = strings
    if structured:
        doc["rw:ingredients"] = structured
    doc["recipeInstructions"] = [
        {"@type": "HowToStep", "text": s, "position": i} if isinstance(s, str) else s
        for i, s in enumerate(steps, 1)
    ]
    if components:
        doc["rw:components"] = [dict(c) for c in components]
    if storage:
        doc["rw:storage"] = [dict(s) for s in storage]
    if storage_overrides_components:
        doc["rw:storageOverridesComponents"] = True
    if unsuitable_for:
        doc["rw:unsuitableFor"] = list(unsuitable_for)
    if family is not None:
        doc["rw:family"] = {"@id": family}
    if variant_of is not None:
        doc["rw:isVariantOf"] = {"@id": variant_of}
    if adjustments:
        doc["rw:adjustments"] = [dict(a) for a in adjustments]
    if notes:
        doc["rw:notes"] = list(notes)
    if extra:
        doc.update(extra)
    return doc


def build_recipe(**kwargs: Any) -> Recipe:
    """A ``Recipe``, built by emitting JSON-LD and reading it back.

    Named arguments, all optional:

    ``id``, ``name``
        Identity. ``id`` defaults to ``urn:recipe:test/`` plus a slug of the name.
    ``ingredients``
        ``ingredient(...)`` nodes, or bare strings for a level-0 scrape, which go
        out as ``recipeIngredient`` and nothing else. Defaults to 250 g of flour.
    ``steps``
        ``step(...)`` nodes, or bare strings for a scrape (no ``@id``, so the
        reader assigns a positional one). Defaults to a single step consuming
        every ingredient and component.
    ``components``, ``storage``, ``storage_overrides_components``,
    ``unsuitable_for``, ``covers``, ``notes``, ``family``, ``variant_of``,
    ``adjustments``
        As their ``rw:`` properties.
    ``enrichment_level``
        Declared. Left out, the reader infers it, which is usually what a test
        wants to assert against rather than dictate.
    ``yield_basis``, ``stated_yield``, ``mass_loss_factor``, ``scaling_basis``
        Yield. ``yield_basis`` defaults to ``sumOfInputs`` when there is anything
        to sum, so a built recipe has a mass yield without stating one.
    ``vessel``
        ``(name, count, capacity_g)``.
    ``batch_constraints``
        ``(min_g, max_g, reason)``; any of them may be ``None``.
    ``measurement_system``, ``canonical_unit_system``
        Default ``metric`` -- an AU tablespoon is 20 mL against the US 14.79, so
        a test whose subject is volume has to say which it means.
    ``extra``
        Raw keys merged into the document, for anything not worth an argument.
    """
    return Recipe.parse(build_document(**kwargs))


def build_library(*documents: Any, foods: FoodBank | None = None) -> Library:
    """A ``Library`` holding built recipes, plus the real food bank.

    Takes ``Recipe`` objects from ``build_recipe``, ``RecipeFamily`` objects, or
    raw documents, which go through ``add_document`` as a corpus file would.
    """
    library = Library()
    library.foods = foods or food_bank()
    for entry in documents:
        if isinstance(entry, Recipe):
            library.recipes[entry.id] = entry
        elif isinstance(entry, RecipeFamily):
            library.families[entry.id] = entry
        else:
            library.add_document(entry)
    return library
