"""Reducing a line to grams, and the table that does it once per recipe.

``ingredient_mass`` had no direct test: everything asserted about it arrived
through the resolver or the validator, so its behaviour was pinned by whatever
arguments its callers happened to pass rather than by anything about the
function. Its two interesting outputs -- *why* a mass is doubtful, and what the
non-optional lines add up to -- are what other modules were re-deriving for
themselves, so those get tested here, at the one place that decides them.
"""

import pytest
from support import build_library, build_recipe, food_bank, ingredient

from custom_components.recipe_wizard.core import resolve
from custom_components.recipe_wizard.core.mass import (
    DENSITY_MISSING,
    DENSITY_UNCERTAIN,
    FORM_UNKNOWN,
    NO_MEASURE,
    ingredient_mass,
    mass_table,
)
from custom_components.recipe_wizard.core.model import Ingredient

# ---------------------------------------------------------------------------
# Why a mass is doubtful, decided once
# ---------------------------------------------------------------------------


def _mass(node: dict, canonical: str = "metric"):
    """One line, reduced. Built as a document node so the reader is in the loop."""
    return ingredient_mass(Ingredient.parse(node), food_bank(), canonical=canonical)


def test_a_form_sensitive_food_with_no_form_does_not_blame_the_density():
    """Dutch cocoa is 0.42 g/mL sifted and nothing like it scooped.

    The premise is in the food bank: cocoa powder is ``form_sensitive`` with a
    low-confidence density. The line below measures it by volume and names no
    form, so the fixable problem is the missing form, not the density -- and
    telling the author to "prefer a mass" when what the line needs is
    ``rw:form`` sends them at the wrong thing.
    """
    result = _mass(ingredient("cocoa powder", volume=(0.5, "cup"),
                              food="food:cocoa-powder-dutch"))
    assert result.source == "volume"
    assert result.confidence == "low"
    assert result.reason == FORM_UNKNOWN


def test_naming_the_form_leaves_only_the_densitys_own_uncertainty():
    """The qeema's ginger, which is the case that separates the two reasons.

    ``food:ginger`` is form-sensitive *and* has a density nobody trusts, and
    the recipe already states ``rw:form: minced``. So the line has done what it
    can and the remaining doubt is the bank's. Reporting this one as a missing
    form asks for something the document already gives.
    """
    result = _mass(ingredient("ginger", volume=(4, "tsp"), form="minced",
                              food="food:ginger"))
    assert result.confidence == "low"
    assert result.reason == DENSITY_UNCERTAIN


def test_a_stated_mass_has_nothing_to_explain():
    result = _mass(ingredient("plain flour", mass=250))
    assert (result.grams, result.source, result.confidence) == (250, "mass", "high")
    assert result.reason is None, "a reason on a trustworthy mass is noise"


def test_an_unconvertible_volume_is_not_confused_with_a_line_stating_nothing():
    """Two different failures that both come out as ``grams=None``.

    "1 cup of something the bank has no density for" is a gap in the food bank;
    "salt" with no measure at all is a gap in the document. They are fixed in
    different files, so a caller has to be able to tell them apart.
    """
    no_density = _mass(ingredient("mystery powder", volume=(1, "cup")))
    no_measure = _mass(ingredient("salt"))

    assert no_density.grams is None and no_density.reason == DENSITY_MISSING
    assert no_measure.grams is None and no_measure.reason == NO_MEASURE


def test_a_to_taste_line_is_not_a_failure_to_reduce():
    """The qeema's coriander garnish. Nothing is wrong, so nothing is reported."""
    result = _mass(ingredient("coriander leaves", to_taste=True))
    assert result.grams is None
    assert result.confidence == "n/a"
    assert result.reason is None
    assert result.warnings == []


# ---------------------------------------------------------------------------
# The table: one definition of the batch
# ---------------------------------------------------------------------------


def test_the_input_total_is_what_the_resolver_calls_the_yield():
    """The number the validator used to compute for itself, differently.

    Its own batch total counted the optional milk, so an ingredient's share was
    measured against a quantity nothing else in the system called a yield --
    and the threshold that decided a finding was tuned against that quantity.
    """
    recipe = build_recipe(ingredients=[
        ingredient("butter", mass=250),
        ingredient("icing sugar", mass=500),
        ingredient("milk", mass=60, optional=True),
    ])
    table = mass_table(recipe, food_bank())

    assert table.input_total_g == pytest.approx(750), "the optional milk is not batter"
    assert resolve(build_library(recipe), recipe.id).batch_yield_g == pytest.approx(
        table.input_total_g
    ), "one definition of the batch, not two"


def test_the_input_total_is_the_inputs_and_not_the_yield():
    """The qeema loses a fifth of itself to the pan.

    An ingredient's share has to be measured against a total of its own kind.
    Divide input masses by a post-evaporation yield and a recipe like this one
    has ingredients summing to 125% of itself.
    """
    recipe = build_recipe(
        ingredients=[ingredient("beef mince", mass=500),
                     ingredient("water", mass=500)],
        mass_loss_factor=0.2,
    )
    table = mass_table(recipe, food_bank())

    assert table.input_total_g == pytest.approx(1000)
    assert resolve(build_library(recipe), recipe.id).batch_yield_g == pytest.approx(800)


def test_a_divergent_line_is_reported_once_and_not_once_per_reader():
    """The failure that made the resolver throw warnings away.

    200 g in one column against 200 mL of butter (182 g) in the other is the
    chocolate buttercream's 18% divergence in miniature. The resolver used to
    reduce every line twice and discard the second result's warnings purely so
    this would not print twice; the table makes the warning reachable once.
    """
    recipe = build_recipe(ingredients=[
        ingredient("unsalted butter", mass=200, volume=(200, "ml"),
                   food="food:butter-unsalted"),
    ])
    table = mass_table(recipe, food_bank())

    assert len([w for w in table.warnings if "disagree" in w]) == 1
    resolved = resolve(build_library(recipe), recipe.id)
    assert len([w for w in resolved.warnings if "disagree" in w]) == 1


def test_the_table_refuses_a_line_the_recipe_does_not_have():
    """``None`` already means "could not be reduced to grams".

    Returning it for "not in this recipe" as well is the flattening the table
    exists to undo: the caller cannot tell a bad reference from a bad density.
    """
    recipe = build_recipe(ingredients=[ingredient("flour", mass=250)])
    table = mass_table(recipe, food_bank())

    assert table.grams("#flour") == pytest.approx(250)
    with pytest.raises(KeyError):
        table.result("#not-in-this-recipe")
