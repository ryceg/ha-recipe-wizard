"""The Modernist row-blocking, which is derived rather than authored."""

from conftest import BROWNIES, CAKE, COFFEE_BC, VANILLA_BC
from support import build_recipe, component, ingredient, step

from custom_components.recipe_wizard.core.render import (
    blocks,
    first_use,
    ingredients_for_step,
    render_table,
    uses_of,
)
from custom_components.recipe_wizard.core.resolve import resolve


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
    table = render_table(resolve(library, BROWNIES), width=100)
    assert "(in 2" in table, "the label wraps, so only the head is on one line"


def test_small_quantities_do_not_round_to_zero(library, brownies):
    """0.375 g of salt rendering as "0 g" reads as an authoring error."""
    table = render_table(resolve(library, BROWNIES), width=100)
    assert " 0 g" not in table
    assert "0.4 g" in table, "1/8 tsp of cooking salt"


# ---------------------------------------------------------------------------
# One document, one scale: the table's columns have to agree with each other
# ---------------------------------------------------------------------------


def test_a_variant_renders_the_steps_and_ingredients_it_inherited(library):
    """The live bug. The coffee buttercream's own file is a patch list.

    Zero ingredients and zero steps on disk, so a renderer reading the document
    off disk printed a header and nothing else. Both columns now come from the
    resolution's effective recipe.
    """
    table = render_table(resolve(library, COFFEE_BC, strict=False), width=100)
    assert "espresso concentrate" in table, "the variant's own substitution"
    assert "unsalted butter" in table, "inherited from the base"
    assert "Cream butter using paddle" in table, "the base's procedure"
    assert "450 g" in table, "500 g of icing sugar, scaled by the variant's 0.9"


def test_the_procedure_column_comes_from_the_same_scale_as_the_weights(library):
    """Scaled masses beside single-batch portions was the other half of the bug.

    ``render_table`` used to take a recipe *and* a resolution, and read the
    weight column off one and everything else off the other. It takes one
    argument now, so the doubled brownies cannot print 500 g of peanut butter
    against a step that still says two tablespoons.
    """
    doubled = resolve(library, BROWNIES, requires_batches=2)
    table = render_table(doubled, width=100)
    assert "500 g" in table, "250 g of peanut butter, doubled"
    dollop = next(s for s in doubled.steps if s.id == "#dollop")
    assert dollop.portion_of("#peanut-butter").describe() == "4 tbsp"


# ---------------------------------------------------------------------------
# Level 0
# ---------------------------------------------------------------------------


def test_a_scraped_recipe_still_renders_its_ingredients(library, level0):
    table = render_table(resolve(library, level0.id, strict=False), width=90)
    assert "500 g beef mince" in table
    assert "olive oil" in table


def test_an_unresolved_recipe_still_renders(library):
    """A level-0 scrape has no resolution at all and must still be readable."""
    table = render_table(library.recipe(VANILLA_BC), width=90)
    assert "unsalted butter" in table
    assert "Cream butter using paddle" in table


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
    table = render_table(resolve(library, CAKE, strict=False), width=100)
    assert "100.0%" in table, "flour is the basis"
    assert "120.0%" in table, "300 g sugar against 250 g flour"


def test_every_step_appears_exactly_once(library):
    for recipe_id in (VANILLA_BC, CAKE):
        recipe = library.recipe(recipe_id)
        rendered = [s.id for b in blocks(recipe) for s in b.steps]
        assert sorted(rendered) == sorted(s.id for s in recipe.steps)


def test_two_steps_sharing_a_position_do_not_collapse_into_one_block():
    """The blocking rule is "the first step that consumes it", and it was read as
    "the first position *number*".

    Two ingredients first used by two different steps that a document numbers the
    same were filed as one block, and the block then swallowed both steps -- so
    the table said the flour and the butter go in together and that sifting is
    part of creaming. No recipe in the corpus repeats a position, which is why
    nothing caught it; ``rw:position`` is a display number and the format never
    promised it was unique.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250), ingredient("butter", mass=100)],
        steps=[
            step("#sift", consumes=["#flour"], produces=("#dry", "Dry mix"),
                 position=1),
            step("#cream", consumes=["#butter"],
                 produces=("#creamed", "Creamed butter"), position=1),
            step("#combine", consumes=["#dry", "#creamed"],
                 produces=("#dough", "Dough"), position=2),
        ],
    )
    result = [b for b in blocks(recipe) if b.ingredient_ids]

    assert [b.ingredient_ids for b in result] == [["#flour"], ["#butter"]]
    assert [[s.id for s in b.steps] for b in result] == [
        ["#sift"], ["#cream", "#combine"],
    ]
    assert [b.result for b in result] == ["Dry mix", "Dough"]


def test_a_step_naming_a_sub_recipe_by_its_full_id_still_lists_it():
    """The asymmetry bug, at the line that had both rules in it.

    ``ingredients_for_step`` resolved the ingredient through the tolerant
    ``recipe.ingredient()`` and then matched the component with ``c.id == ref``,
    so a step naming its own frosting ``urn:recipe:.../cake#frosting`` showed the
    cook the baked layers and nothing to put on them.
    """
    doc_id = "urn:recipe:test/long-form-table"
    recipe = build_recipe(
        id=doc_id,
        ingredients=[ingredient("flour", mass=250)],
        components=[component("Vanilla buttercream", id="#frosting",
                              recipe="urn:recipe:test/frosting")],
        steps=[
            step("#bake", consumes=[f"{doc_id}#flour"],
                 produces=("#layers", "Baked layers")),
            step("#assemble", consumes=["#layers", f"{doc_id}#frosting"],
                 produces=("#cake", "Frosted cake")),
        ],
    )

    assert [label for _, label, _ in ingredients_for_step(recipe, "#assemble")] == [
        "Baked layers", "Vanilla buttercream",
    ]
    table = render_table(recipe, width=100)
    assert "Vanilla buttercream (sub-" in table, (
        "the label wraps mid-word, so only the head is on one line"
    )
