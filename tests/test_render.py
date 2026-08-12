"""The Modernist row-blocking, which is derived rather than authored."""

from conftest import BROWNIES, CAKE, VANILLA_BC

from recipe_wizard.render import (
    blocks,
    first_use,
    ingredients_for_step,
    render_table,
    uses_of,
)
from recipe_wizard.resolve import resolve


# ---------------------------------------------------------------------------
# Portions: the cook-along view
# ---------------------------------------------------------------------------


def test_a_split_ingredient_reaches_both_of_its_steps(library, brownies):
    """The failure that ranked above every modelling gap.

    Without portions the whole 250 g of peanut butter renders against step 2
    and step 12's "dollop 2 tbsp across the surface" shows no ingredient at all.
    """
    spread = dict((n, p) for _, n, p in ingredients_for_step(brownies, "#spread-pb"))
    dollop = dict((n, p) for _, n, p in ingredients_for_step(brownies, "#dollop"))

    assert spread["smooth peanut butter"].describe() == "all but the reserved 2 tbsp"
    assert dollop["smooth peanut butter"].describe() == "2 tbsp"


def test_intermediates_appear_in_the_cook_along_view(library, brownies):
    """"Half the brownie batter" is what the cook needs told, and it is not
    an ingredient."""
    pour = dict((n, p) for _, n, p in ingredients_for_step(brownies, "#pour-half"))
    cover = dict((n, p) for _, n, p in ingredients_for_step(brownies, "#cover"))
    assert pour["Brownie batter"].describe() == "half"
    assert cover["Brownie batter"].describe() == "the rest"


def test_fractions_are_described_in_words(library, brownies):
    portions = {p.describe() for _, p in uses_of(brownies, "#brownie-batter")}
    assert portions == {"half", "the rest"}


def test_the_table_flags_an_ingredient_used_more_than_once(library, brownies):
    table = render_table(brownies, resolve(library, BROWNIES), width=100)
    assert "(in 2" in table, "the label wraps, so only the head is on one line"


def test_small_quantities_do_not_round_to_zero(library, brownies):
    """0.375 g of salt rendering as "0 g" reads as an authoring error."""
    table = render_table(brownies, resolve(library, BROWNIES), width=100)
    assert " 0 g" not in table
    assert "0.4 g" in table, "1/8 tsp of cooking salt"


# ---------------------------------------------------------------------------
# Level 0
# ---------------------------------------------------------------------------


def test_a_scraped_recipe_still_renders_its_ingredients(library, level0):
    table = render_table(level0, resolve(library, level0.id, strict=False), width=90)
    assert "500 g beef mince" in table
    assert "olive oil" in table


def test_ingredients_block_by_the_step_that_first_uses_them(library):
    recipe = library.recipe(VANILLA_BC)
    result = blocks(recipe)
    grouped = [b.ingredient_ids for b in result if b.ingredient_ids]
    assert grouped == [["#butter"], ["#icing-sugar"], ["#vanilla", "#milk"]]


def test_each_block_carries_the_steps_up_to_the_next_blocks_first_use(library):
    recipe = library.recipe(VANILLA_BC)
    result = [b for b in blocks(recipe) if b.ingredient_ids]
    assert [[s.position for s in b.steps] for b in result] == [[1], [2], [3]]


def test_each_block_is_closed_by_the_result_it_produces(library):
    """The "RESULT column" question: it is a labelled rule, and it is derived."""
    recipe = library.recipe(VANILLA_BC)
    result = [b for b in blocks(recipe) if b.ingredient_ids]
    assert [b.result for b in result] == [
        "Creamed butter",
        "Buttercream base",
        "Vanilla buttercream",
    ]


def test_steps_before_any_ingredient_get_their_own_block(library):
    """Preheating and lining pans would otherwise vanish from the table."""
    recipe = library.recipe(CAKE)
    head = blocks(recipe)[0]
    assert head.ingredient_ids == []
    assert [s.id for s in head.steps] == ["#preheat", "#prep-pans"]


def test_a_sub_recipe_appears_in_the_ingredient_column(library):
    """Exactly how Modernist prints "Stove-Top Carotene Butter, see page 121"."""
    recipe = library.recipe(CAKE)
    final = [b for b in blocks(recipe) if b.ingredient_ids][-1]
    assert final.ingredient_ids == ["#frosting"]
    assert final.result == "Frosted vanilla cake"


def test_first_use_ignores_later_uses(library):
    recipe = library.recipe(CAKE)
    uses = first_use(recipe)
    assert uses["#flour"] == 3
    assert uses["#butter"] == 7


def test_scaling_column_is_derived_from_the_basis(library):
    """Baker's percentages against flour, computed rather than stored."""
    recipe = library.recipe(CAKE)
    assert recipe.scaling_basis == "#flour"
    table = render_table(recipe, resolve(library, CAKE, strict=False), width=100)
    assert "100.0%" in table, "flour is the basis"
    assert "120.0%" in table, "300 g sugar against 250 g flour"


def test_every_step_appears_exactly_once(library):
    for recipe_id in (VANILLA_BC, CAKE):
        recipe = library.recipe(recipe_id)
        rendered = [s.id for b in blocks(recipe) for s in b.steps]
        assert sorted(rendered) == sorted(s.id for s in recipe.steps)
