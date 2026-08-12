"""Structured recipe format and resolver for the Home Assistant Recipe Wizard.

No Home Assistant dependency lives in here on purpose: the integration wraps
this library, which keeps the resolver testable on its own.
"""

from .adjust import AdjustmentError, apply_adjustments
from .compare import Comparison, compare
from .dish import Dish, resolve_dish
from .importer import import_page, import_url
from .library import Food, FoodBank, Library, LibraryError
from .mass import ingredient_mass
from .model import (
    Adjustment,
    BatchPolicy,
    ComponentUse,
    ConsumeRef,
    Ingredient,
    Portion,
    Recipe,
    RecipeFamily,
    Step,
    Storage,
    Vessel,
)
from .render import blocks, ingredients_for_step, render_table, uses_of
from .resolve import (
    BatchConstraintError,
    Resolution,
    ResolvedIngredient,
    UnresolvableComponent,
    materialise,
    resolve,
    resolve_component,
    vessel_warnings,
)
from .schedule import Plan, check_plan, rigid_chains, schedule
from .units import Quantity, UnitError
from .validate import Finding, validate_library, validate_recipe

__all__ = [
    "Adjustment",
    "AdjustmentError",
    "BatchConstraintError",
    "BatchPolicy",
    "ComponentUse",
    "Comparison",
    "ConsumeRef",
    "Dish",
    "Finding",
    "Food",
    "FoodBank",
    "Ingredient",
    "Library",
    "LibraryError",
    "Plan",
    "Portion",
    "Quantity",
    "Recipe",
    "RecipeFamily",
    "Resolution",
    "ResolvedIngredient",
    "Step",
    "Storage",
    "UnitError",
    "UnresolvableComponent",
    "Vessel",
    "apply_adjustments",
    "blocks",
    "check_plan",
    "compare",
    "import_page",
    "import_url",
    "ingredient_mass",
    "ingredients_for_step",
    "materialise",
    "render_table",
    "resolve",
    "resolve_component",
    "resolve_dish",
    "rigid_chains",
    "schedule",
    "uses_of",
    "validate_library",
    "validate_recipe",
    "vessel_warnings",
]
