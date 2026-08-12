"""Units and quantity arithmetic.

Mass is the canonical dimension: everything the resolver does with quantities
eventually reduces to grams. Volume is display-first and lossy, and converting
it needs a density for the specific food. Count needs a per-unit mass.

The measurement system matters more than it looks. A tablespoon is 20 mL in
Australia and 14.79 mL in the US, and a cup is 250 mL vs 236.6 mL. RecipeTin
Eats is Australian, so "2-4 tablespoons milk" there is 40-80 mL, not 30-60 mL.
Guessing wrong is a 35% error on that line. Every recipe therefore declares the
system its volume measures were written in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MeasurementSystem = Literal["metric", "US", "AU"]
Dimension = Literal["mass", "volume", "count"]

#: Mass units, in grams. ``stick`` is a mass-by-convention (a quarter pound of
#: butter), not a volume, which is why it lives here.
_MASS_G: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "oz": 28.349523125,
    "lb": 453.59237,
    "stick": 113.3980925,
}

#: Volume units, in millilitres, per measurement system.
_VOLUME_ML: dict[str, dict[str, float]] = {
    "metric": {"tsp": 5.0, "tbsp": 15.0, "cup": 250.0},
    "US": {"tsp": 4.92892159375, "tbsp": 14.78676478125, "cup": 236.5882365,
           "floz": 29.5735295625},
    "AU": {"tsp": 5.0, "tbsp": 20.0, "cup": 250.0},
}

#: Volume units that mean the same thing everywhere.
_VOLUME_ML_UNIVERSAL: dict[str, float] = {"ml": 1.0, "l": 1000.0}

_COUNT_UNITS = {"", "each", "ea", "unit", "units", "whole", "large", "medium",
                "small", "clove", "cloves", "sprig", "sprigs"}

_ALIASES: dict[str, str] = {
    # UN/CEFACT codes fold to the canonical short unit, so a quantity written
    # as GRM and one written as g compare equal rather than being two spellings.
    "grm": "g", "kgm": "kg", "mlt": "ml", "ltr": "l",
    "cmt": "cm", "mmt": "mm", "inh": "in",
    "onz": "oz", "lbr": "lb",
    "gram": "g", "grams": "g", "grammes": "g", "gm": "g", "gs": "g",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg",
    "millilitre": "ml", "millilitres": "ml", "milliliter": "ml",
    "milliliters": "ml", "mls": "ml",
    "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp", "t": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbs": "tbsp",
    "tbsps": "tbsp", "tblsp": "tbsp", "T": "tbsp",
    "cups": "cup", "c": "cup",
    "ounce": "oz", "ounces": "oz", "ozs": "oz",
    "pound": "lb", "pounds": "lb", "lbs": "lb",
    "sticks": "stick",
    "fluid ounce": "floz", "fl oz": "floz", "fl. oz.": "floz",
    "centimetre": "cm", "centimeter": "cm", "centimetres": "cm",
    "inches": "in", '"': "in",
}


class UnitError(ValueError):
    """A unit could not be recognised, or a conversion is not possible."""


def normalise_unit(unit: str | None) -> str:
    """Fold a unit string to its canonical lowercase key."""
    if unit is None:
        return ""
    raw = unit.strip()
    # Case-sensitive aliases first: "T" is tablespoon, "t" is teaspoon.
    if raw in ("T", "t"):
        return _ALIASES[raw]
    key = raw.lower().rstrip(".")
    return _ALIASES.get(key, key)


def dimension_of(unit: str) -> Dimension:
    """Classify a normalised unit."""
    u = normalise_unit(unit)
    if u in _MASS_G:
        return "mass"
    if u in _VOLUME_ML_UNIVERSAL:
        return "volume"
    for table in _VOLUME_ML.values():
        if u in table:
            return "volume"
    if u in _COUNT_UNITS:
        return "count"
    raise UnitError(f"unrecognised unit {unit!r}")


@dataclass(frozen=True, slots=True)
class Quantity:
    """A measured amount, tagged with the unit it was written in.

    ``display`` preserves the source's own rendering ("2 1/2 cups", "1 bar /
    15 psi") so nothing is lost when the numeric value is normalised.

    ``max_value`` makes the quantity a range. Sources write these constantly --
    "1-3 tsp sugar, if needed", "8-10 slices Swiss cheese", "2-4 tbsp milk" --
    and collapsing a range to a scalar loses the cook's latitude. ``value`` is
    the low end and is what arithmetic uses, so a range behaves like the scalar
    it would otherwise have been.
    """

    value: float
    unit: str = ""
    display: str | None = None
    max_value: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit", normalise_unit(self.unit))
        if self.max_value is not None and self.max_value < self.value:
            raise UnitError(
                f"range maximum {self.max_value} is below its minimum {self.value}"
            )

    @property
    def dimension(self) -> Dimension:
        return dimension_of(self.unit)

    def scaled(self, factor: float) -> "Quantity":
        """Multiply the value, dropping ``display`` since it no longer holds."""
        return Quantity(
            self.value * factor,
            self.unit,
            None,
            None if self.max_value is None else self.max_value * factor,
        )

    def __str__(self) -> str:
        if self.display:
            return self.display
        low = f"{self.value:g}"
        span = low if self.max_value is None else f"{low}-{self.max_value:g}"
        return f"{span} {self.unit}".strip()

    @classmethod
    def from_jsonld(cls, node: dict | None) -> "Quantity | None":
        """Read a schema.org QuantitativeValue-shaped node.

        Accepts ``unitCode`` (UN/CEFACT) or ``unitText`` (kitchen units), and
        carries ``rw:display`` through as the display string. ``maxValue``
        (schema.org's own name for it) or ``rw:maxValue`` makes it a range.
        """
        if node is None:
            return None
        if not isinstance(node, dict):
            raise UnitError(f"expected a quantity object, got {node!r}")
        value = node.get("value", node.get("minValue"))
        if value is None:
            raise UnitError(f"quantity is missing 'value': {node!r}")
        unit = node.get("unitCode") or node.get("unitText") or ""
        maximum = node.get("maxValue", node.get("rw:maxValue"))
        return cls(
            float(value),
            unit,
            node.get("rw:display"),
            None if maximum is None else float(maximum),
        )


def to_millilitres(qty: Quantity, system: MeasurementSystem) -> float:
    """Convert a volume quantity to millilitres under the given system."""
    unit = qty.unit
    if unit in _VOLUME_ML_UNIVERSAL:
        return qty.value * _VOLUME_ML_UNIVERSAL[unit]
    table = _VOLUME_ML.get(system)
    if table is None:
        raise UnitError(f"unknown measurement system {system!r}")
    if unit in table:
        return qty.value * table[unit]
    raise UnitError(f"{unit!r} is not a volume unit in the {system} system")


def to_grams(
    qty: Quantity,
    *,
    system: MeasurementSystem = "metric",
    density_g_per_ml: float | None = None,
    unit_mass_g: float | None = None,
) -> float:
    """Reduce any quantity to grams.

    Volume needs ``density_g_per_ml`` and count needs ``unit_mass_g``; both come
    from the food record rather than the recipe. Raising rather than guessing is
    deliberate — a silently assumed density is how a frosting ends up 18% out.
    """
    dim = qty.dimension
    if dim == "mass":
        return qty.value * _MASS_G[qty.unit]
    if dim == "volume":
        if density_g_per_ml is None:
            raise UnitError(
                f"cannot convert {qty} to grams without a density for this food"
            )
        return to_millilitres(qty, system) * density_g_per_ml
    if unit_mass_g is None:
        raise UnitError(
            f"cannot convert count {qty} to grams without a per-unit mass"
        )
    return qty.value * unit_mass_g


def relative_difference(a: float, b: float) -> float:
    """Symmetric relative difference, used by the unit-divergence check."""
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b))
