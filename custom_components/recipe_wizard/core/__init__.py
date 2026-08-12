"""Structured recipe format and resolver for the Home Assistant Recipe Wizard.

No Home Assistant dependency lives in here on purpose: the integration wraps
this library, which keeps the resolver testable on its own.
"""

from .adjust import AdjustmentError, apply_adjustments
from .compare import Comparison, compare
from .cookalong import (
    CookAlong,
    CookStep,
    CursorStep,
    StepIngredient,
    cook_along,
    cook_along_from_dish,
    step_ingredients,
)
from .dish import Dish, resolve_dish
from .graph import Input, Node, RecipeGraph, Use, recipe_graph
from .importer import import_page, import_url
from .library import Food, FoodBank, Library, LibraryError
from .mass import MassResult, MassTable, ingredient_mass, mass_table
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
    effective_recipe,
    materialise,
    resolve,
    resolve_component,
    vessel_warnings,
)
from .schedule import Plan, check_plan, rigid_chains, schedule
from .units import Quantity, UnitError
from .validate import Finding, validate_library, validate_recipe, worst_level

__all__ = [
    "Adjustment",
    "AdjustmentError",
    "BatchConstraintError",
    "BatchPolicy",
    "ComponentUse",
    "Comparison",
    "ConsumeRef",
    "CookAlong",
    "CookStep",
    "CursorStep",
    "Dish",
    "Finding",
    "Food",
    "FoodBank",
    "Ingredient",
    "Input",
    "Library",
    "LibraryError",
    "MassResult",
    "MassTable",
    "Node",
    "Plan",
    "Portion",
    "Quantity",
    "Recipe",
    "RecipeFamily",
    "RecipeGraph",
    "Resolution",
    "ResolvedIngredient",
    "Step",
    "StepIngredient",
    "Storage",
    "UnitError",
    "UnresolvableComponent",
    "Use",
    "Vessel",
    "apply_adjustments",
    "blocks",
    "check_plan",
    "compare",
    "cook_along",
    "cook_along_from_dish",
    "effective_recipe",
    "import_page",
    "import_url",
    "ingredient_mass",
    "ingredients_for_step",
    "mass_table",
    "materialise",
    "recipe_graph",
    "render_table",
    "resolve",
    "resolve_component",
    "resolve_dish",
    "rigid_chains",
    "schedule",
    "step_ingredients",
    "uses_of",
    "validate_library",
    "validate_recipe",
    "vessel_warnings",
    "worst_level",
]
