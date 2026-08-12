"""Reducing an ingredient line to grams, and catching sources that disagree.

RecipeTin Eats' chocolate buttercream lists 200 g of butter in its metric
column and 3/4 cup (170 g) in its cups column — an 18% divergence inside one
recipe. A scraper that silently prefers one column produces a 1:1.5 frosting
from one page and a 1:1.8 frosting from another and never says so. So when a
line carries more than one measure, they are cross-checked and disagreements
are reported rather than resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .library import FoodBank
from .model import Ingredient
from .units import MeasurementSystem, UnitError, relative_difference, to_grams

#: Conversions disagreeing by more than this are reported.
DIVERGENCE_THRESHOLD = 0.05


@dataclass(slots=True)
class MassResult:
    grams: float | None
    source: str
    """Which measure won: mass, count, volume, or none."""
    warnings: list[str] = field(default_factory=list)
    confidence: str = "high"


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
        detail = "no density in the food bank" if ing.volume is not None else "no measures given"
        warnings.append(f"{ing.name}: cannot be reduced to grams ({detail})")
        return MassResult(None, "none", warnings, "none")

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
            if key == "volume":
                confidence = food.density_confidence if food else "low"
            return MassResult(candidates[key], key, warnings, confidence)

    key = keys[0]
    return MassResult(candidates[key], key, warnings, "low")
