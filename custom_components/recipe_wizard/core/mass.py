"""Reducing an ingredient line to grams, and catching sources that disagree.

RecipeTin Eats' chocolate buttercream lists 200 g of butter in its metric
column and 3/4 cup (170 g) in its cups column — an 18% divergence inside one
recipe. A scraper that silently prefers one column produces a 1:1.5 frosting
from one page and a 1:1.8 frosting from another and never says so. So when a
line carries more than one measure, they are cross-checked and disagreements
are reported rather than resolved.

A line is reduced once per recipe, into a ``MassTable``. It used to be reduced
up to four times, because the only way to get the grams was a call that also
produced the warnings, and every caller wanted a different subset -- so each of
them called again for the part the last flattening had lost. The table holds the
whole answer and lets callers ask.

That includes asking *why* a mass is doubtful. Both of the validator's density
findings come out of one low-confidence volume conversion, and which one fires
was being decided by re-fetching the ``Food`` and re-reading ``form_sensitive``
off it -- a second copy of a decision made here. ``MassResult.reason`` carries
it instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .library import FoodBank
from .model import Ingredient, Recipe
from .units import MeasurementSystem, UnitError, relative_difference, to_grams

#: Conversions disagreeing by more than this are reported.
DIVERGENCE_THRESHOLD = 0.05

# Why a mass is worth less than a stated weight. These are reason *codes*, not
# messages: the qeema's ginger and the brownies' cocoa powder both come out of
# here with a shaky volume conversion, but they are shaky for different reasons
# and only the caller knows how to say so to whoever is reading. The validator
# used to re-fetch the Food and re-read ``form_sensitive`` to work out which
# case it had -- re-deriving a decision that was already made below.
#: The food's density depends on a cut or pack the line did not name. *"The
#: 3 cup measure for 350 g is for elbow macaroni only."*
FORM_UNKNOWN = "form-unknown"
#: The food bank has a density and does not trust it -- the qeema's ginger.
DENSITY_UNCERTAIN = "density-uncertain"
#: A volume was given and the food bank has no density for it at all.
DENSITY_MISSING = "density-missing"
#: The line states no mass, no volume and no count.
NO_MEASURE = "no-measure"


@dataclass(slots=True)
class MassResult:
    grams: float | None
    source: str
    """Which measure won: mass, count, volume, or none."""
    warnings: list[str] = field(default_factory=list)
    confidence: str = "high"
    reason: str | None = None
    """Why ``confidence`` is not ``high``, as one of the codes above.

    ``None`` whenever the mass is as good as it gets. This exists so a caller
    can *explain* a doubtful mass without going back to the food bank for the
    fields this module already consulted; it is deliberately a code and not a
    sentence, because the wording belongs to whoever is doing the telling --
    the validator's finding and a cook-along's ingredient row want to say very
    different things about the same shaky 4 g of ginger.
    """


def ingredient_mass(
    ing: Ingredient,
    foods: FoodBank,
    system: MeasurementSystem = "metric",
    *,
    canonical: str = "metric",
) -> MassResult:
    """Reduce an ingredient to grams, preferring the recipe's canonical column."""
    food = foods.get(ing.food.id if ing.food else None)
    density = food.density_g_per_ml if food else None
    unit_mass = None
    if ing.unit_mass is not None:
        unit_mass = ing.unit_mass.value
    elif food and food.unit_mass_g:
        unit_mass = food.unit_mass_g

    candidates: dict[str, float] = {}
    warnings: list[str] = []

    if ing.mass is not None:
        try:
            candidates["mass"] = to_grams(ing.mass, system=system)
        except UnitError as exc:
            warnings.append(f"{ing.name}: {exc}")
    if ing.count is not None and unit_mass is not None:
        candidates["count"] = ing.count.value * unit_mass
    if ing.volume is not None and density is not None:
        try:
            candidates["volume"] = to_grams(
                ing.volume, system=system, density_g_per_ml=density
            )
        except UnitError as exc:
            warnings.append(f"{ing.name}: {exc}")

    if not candidates:
        if ing.to_taste:
            return MassResult(None, "none", [], "n/a")
        missing_density = ing.volume is not None
        detail = "no density in the food bank" if missing_density else "no measures given"
        warnings.append(f"{ing.name}: cannot be reduced to grams ({detail})")
        return MassResult(
            None, "none", warnings, "none",
            DENSITY_MISSING if missing_density else NO_MEASURE,
        )

    # Cross-check every pair that is actually present.
    keys = list(candidates)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            diff = relative_difference(candidates[a], candidates[b])
            if diff > DIVERGENCE_THRESHOLD:
                warnings.append(
                    f"{ing.name}: {a} says {candidates[a]:.0f} g but {b} says "
                    f"{candidates[b]:.0f} g ({diff:.0%} apart) - source columns disagree"
                )

    preference = ["mass", "count", "volume"]
    if canonical in ("US", "AU", "cups", "volume"):
        preference = ["volume", "mass", "count"]
    for key in preference:
        if key in candidates:
            confidence = "high"
            reason = None
            if key == "volume":
                confidence = food.density_confidence if food else "low"
                if confidence != "high":
                    # Which of the two it is, decided here rather than by
                    # whoever reports it: cocoa powder is form-sensitive and
                    # sifted-vs-scooped is the whole difference, where the
                    # qeema's ginger has one form and a density nobody trusts.
                    reason = (
                        FORM_UNKNOWN
                        if food is not None and food.form_sensitive and ing.form is None
                        else DENSITY_UNCERTAIN
                    )
            return MassResult(candidates[key], key, warnings, confidence, reason)

    key = keys[0]
    return MassResult(candidates[key], key, warnings, "low")


@dataclass(slots=True)
class MassTable:
    """Every ingredient line of one recipe, reduced to grams exactly once.

    This exists because the same line used to be reduced up to four times per
    recipe -- twice in the resolver, twice more in the validator -- and each
    caller then flattened the answer differently. The resolver kept the grams
    and threw away the warnings so as not to report the chocolate buttercream's
    18% butter divergence twice; the validator kept the warnings and summed the
    grams into a batch total that included the optional milk and ignored the
    mass loss factor, so the denominator it measured an ingredient's share
    against was a number nothing else in the system called a yield.

    So the table holds the whole ``MassResult`` and lets callers ask what they
    need of it. Each warning is reachable exactly once, which is what makes
    double-reporting a thing you have to opt into rather than something you
    have to remember to avoid.
    """

    results: dict[str, MassResult]
    """Keyed by ingredient ``@id``, in the order the document lists them."""
    input_total_g: float
    """The one definition of the batch: the sum of the non-optional lines that
    could be reduced to grams, *before* any mass loss factor.

    The inputs, not the yield. An ingredient's share of the batch has to be
    measured against a total of the same kind, or the shares of a recipe that
    evaporates 20% of itself -- the qeema -- would sum to 125%.
    """

    def grams(self, ingredient_id: str) -> float | None:
        """One line's mass, or ``None`` where it could not be reduced to one."""
        return self.results[ingredient_id].grams

    def result(self, ingredient_id: str) -> MassResult:
        """One line's full result: grams, source, confidence, reason, warnings.

        Raises ``KeyError`` for a line the recipe does not have. That is a bug
        in the caller rather than a missing measurement, and returning ``None``
        for it would conflate the two -- exactly the flattening this class
        exists to undo.
        """
        return self.results[ingredient_id]

    @property
    def warnings(self) -> list[str]:
        """Every line's warnings, in document order, each appearing once."""
        return [w for result in self.results.values() for w in result.warnings]


def mass_table(recipe: Recipe, foods: FoodBank) -> MassTable:
    """Reduce every line of a recipe to grams, once.

    The recipe carries both systems this needs: an Australian tablespoon is
    20 mL against the US 14.79, and ``rw:canonicalUnitSystem`` says which of a
    source's parallel columns to trust when they disagree.
    """
    results: dict[str, MassResult] = {}
    total = 0.0
    for ing in recipe.ingredients:
        result = ingredient_mass(
            ing,
            foods,
            recipe.measurement_system,
            canonical=recipe.canonical_unit_system,
        )
        results[ing.id] = result
        if result.grams is not None and not ing.optional:
            total += result.grams
    return MassTable(results, total)
