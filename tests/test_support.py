"""The builder and the fixtures the other tests state their premises with.

These properties are easy to lose silently, and every other test in the suite
depends on them, so they are asserted rather than assumed.
"""

from support import (
    build_library,
    build_recipe,
    component,
    ingredient,
    portion,
    step,
    storage_option,
)

from custom_components.recipe_wizard.core import validate_recipe
from custom_components.recipe_wizard.core.resolve import resolve


def test_a_stated_premise_reaches_the_model_through_the_reader():
    """A builder that emitted keys the reader ignores would make every premise
    a lie, and the tests using it would pass while asserting nothing.

    So it emits JSON-LD and hands it to ``Recipe.parse``, and this checks the
    properties that are worth stating actually arrive: the shape of a quantity,
    the ``rw:`` prefix, a portion on a consume edge, and the nested nodes.
    """
    frosting = build_recipe(name="Frosting", ingredients=[ingredient("butter", mass=250)])
    recipe = build_recipe(
        name="Premise",
        ingredients=[
            ingredient("eggs", count=(4, "large"), unit_mass=52.5, discrete=True),
            ingredient("milk", volume=(1, "cup"), food="food:milk-full-fat"),
            ingredient("vanilla", volume=(3, "tsp"), food="food:vanilla-extract",
                       scaling="sublinear", optional=True),
        ],
        steps=[
            step("#beat", consumes=["#eggs"], produces=("#beaten", "Beaten eggs"),
                 duration=30, attention="passive"),
            step("#fold",
                 consumes=["#beaten", "#vanilla", "#frosting",
                           ("#milk", portion(fraction=0.5, text="half the milk"))],
                 produces=("#batter", "Batter"),
                 max_delay_after=[("#beat", "PT1M", "the foam subsides")]),
        ],
        components=[component("Frosting", recipe=frosting.id, requires_batches=2)],
        storage=[storage_option("frozen", keeps="P3M")],
        vessel=("20 cm round tin", 2, 560),
        batch_constraints=(200, None, "the paddle does not reach less"),
        measurement_system="AU",
    )

    eggs = recipe.ingredient("#eggs")
    assert (eggs.count.value, eggs.count.unit) == (4, "large")
    assert eggs.unit_mass.value == 52.5 and eggs.discrete
    assert recipe.ingredient("#milk").volume.unit == "cup"
    assert recipe.ingredient("#vanilla").scaling == "sublinear"
    assert recipe.ingredient("#vanilla").optional

    assert recipe.step("#beat").duration.seconds == 30 * 60
    assert recipe.step("#beat").attention == "passive"
    assert recipe.step("#fold").portion_of("#milk").fraction == 0.5
    assert recipe.step("#fold").max_delay_after[0].from_step == "#beat"

    assert recipe.components[0].requires_batches == 2.0
    assert recipe.storage[0].keeps.nominal, "months have no fixed length"
    assert recipe.vessel.total_capacity_g == 1120
    assert recipe.batch_constraints.min_yield_g == 200
    assert recipe.measurement_system == "AU"
    assert recipe.enrichment_level == 3, "inferred from the graph, not declared"

    # And it resolves against the real food bank, so a premise built here is a
    # premise a recipe file could state.
    result = resolve(build_library(recipe, frosting), recipe.id)
    assert result.batch_yield_g == 4 * 52.5 + 250 * 1.032, \
        "4 eggs at their stated unit mass, plus a 250 mL Australian cup of milk"


def test_a_recipe_nobody_added_a_defect_to_validates_clean():
    """Otherwise a test asserting "exactly one finding of this class" is really
    asserting how much noise the builder's defaults happen to make."""
    recipe = build_recipe()
    assert validate_recipe(recipe, build_library(recipe)) == []


# ---------------------------------------------------------------------------
# Fixture isolation. These two run in order, and the second is the assertion.
# ---------------------------------------------------------------------------


def test_a_test_may_add_to_and_mutate_its_own_library(library, level0, cake):
    """Which tests do constantly: a component's batches, a step's consumes, a
    whole test document registered so the resolver can find it."""
    assert "urn:recipe:test/level0" in library.recipes
    cake.ingredients.clear()


def test_and_the_next_test_inherits_none_of_it(library, cake):
    """The leak the ``library`` fixture was rewritten to close.

    It was session-scoped and mutable, and the level-0 scrape was added to it
    with no teardown, so a test document was part of the corpus for every test
    that ran afterwards -- including the assertion about what the whole library
    validates to.
    """
    assert "urn:recipe:test/level0" not in library.recipes
    assert cake.ingredient("#flour") is not None
