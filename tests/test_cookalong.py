"""The cook-along: the join every caller was making by hand, and getting wrong.

Each test is named after the failure it prevents. Four of them are failures that
had already happened in shipped callers: a variant cooked as an empty recipe, a
doubled portion shown at single scale, a mass shown against the wrong document,
and a timer that dropped the doneness it was supposed to display.
"""

import pytest
from conftest import BROWNIES, CAKE, COFFEE_BC, VANILLA_BC
from support import build_library, build_recipe, ingredient, portion, step

from custom_components.recipe_wizard.core.cookalong import (
    cook_along,
    cook_along_from_dish,
    step_ingredients,
)
from custom_components.recipe_wizard.core.dish import resolve_dish
from custom_components.recipe_wizard.core.resolve import resolve

#: The one recipe in the corpus with an *optional* whole component.
QEEMA = "urn:recipe:rte/qeema"


# ---------------------------------------------------------------------------
# The steps come from the effective recipe, never from the document on disk
# ---------------------------------------------------------------------------


def test_a_variant_cooks_the_steps_it_inherited(library):
    """The live bug, from the cook's side.

    ``recipes/coffee-buttercream.json`` is a patch list: it declares two
    adjustments and nothing else. A cook-along reading ``library.recipe(id)``
    offers a recipe with no steps, no ingredients and no timers -- which is
    worse than an error, because it looks like an answer.
    """
    cook = cook_along(library, COFFEE_BC)

    assert [s.step_id for s in cook.steps] == [
        "#cream-butter", "#add-sugar", "#finish",
    ]
    assert cook.plan.total_s > 0
    first = cook.steps[0]
    assert [i.name for i in first.ingredients] == ["unsalted butter"]
    assert first.ingredients[0].row_mass_g == pytest.approx(250)
    finish = cook.step("#finish")
    assert "espresso concentrate" in [i.name for i in finish.ingredients], (
        "the variant's own substitution, on the base's step"
    )


def test_the_steps_are_in_the_order_they_are_to_be_done(library):
    """Document order is not cooking order: the cake melts its butter and milk
    in the middle of beating the eggs, which is what the source's own prose
    says and what the planner derives."""
    cook = cook_along(library, CAKE)
    assert [s.step_id for s in cook.steps] == [s.step_id for s in cook.plan.steps]
    order = [s.step_id for s in cook.steps]
    assert order.index("#melt-butter-milk") < order.index("#whisk-dry")
    assert order.index("#whisk-dry") < order.index("#fold-flour")


# ---------------------------------------------------------------------------
# Scale: portions and masses have to come from the same batch
# ---------------------------------------------------------------------------


def test_a_doubled_batch_doubles_an_absolute_portion_and_the_mass(library):
    """"Dollop 2 tbsp across the surface" is 4 tbsp in a doubled tray.

    Both halves used to come from different places -- the mass from the
    resolution and the portion from the unscaled document -- so this is the
    combination that was silently wrong in every rendering at scale.
    """
    cook = cook_along(library, BROWNIES, batches=2)
    dollop = cook.step("#dollop")
    peanut = next(i for i in dollop.ingredients if i.id == "#peanut-butter")

    assert peanut.portion.describe() == "4 tbsp"
    assert peanut.row_mass_g == pytest.approx(500)
    assert peanut.describe() == "smooth peanut butter: 4 tbsp (of 500 g)"


def test_a_fraction_is_not_scaled(library):
    """Half the batter is half the batter at any batch size. Scaling a fraction
    would ask the cook for all of it twice."""
    cook = cook_along(library, BROWNIES, batches=2)
    pour = cook.step("#pour-half")
    batter = next(i for i in pour.ingredients if i.id == "#brownie-batter")
    assert batter.portion.describe() == "half"
    assert batter.describe() == "Brownie batter: half"


def test_a_portion_is_never_resolved_to_a_mass(library):
    """Nobody weighs half a Bolognese, and a confident "1,612 g" is worse than
    "just over half". The row's mass is shown beside the portion, not multiplied
    into it."""
    cook = cook_along(library, BROWNIES)
    peanut = next(
        i for i in cook.step("#dollop").ingredients if i.id == "#peanut-butter"
    )
    assert peanut.row_mass_g == pytest.approx(250), "the whole row, not the 2 tbsp"
    assert not peanut.takes_whole_row


def test_step_ingredients_takes_only_a_resolution(library):
    """The interface that makes mixing scales impossible rather than unlikely.

    A form taking a recipe *and* a resolution lets a caller pass a single-batch
    document with doubled masses and get a plausible wrong answer. This one has
    nowhere to put the second document.
    """
    recipe = build_recipe(
        ingredients=[ingredient("peanut butter", mass=250)],
        steps=[
            step("#spread", consumes=[("#peanut-butter", portion(volume=(2, "tbsp")))],
                 produces="#spread-layer"),
        ],
    )
    library = build_library(recipe)

    single = step_ingredients(resolve(library, recipe.id), "#spread")
    doubled = step_ingredients(
        resolve(library, recipe.id, requires_batches=2), "#spread"
    )

    assert single[0].portion.describe() == "2 tbsp"
    assert single[0].row_mass_g == pytest.approx(250)
    assert doubled[0].portion.describe() == "4 tbsp"
    assert doubled[0].row_mass_g == pytest.approx(500)


# ---------------------------------------------------------------------------
# Timers, and the state that actually decides
# ---------------------------------------------------------------------------


def test_a_timer_shows_the_doneness_beside_the_time(library):
    """The § Known gaps entry, quoted verbatim: a timer should say "32 min, then
    check: edges firmish, centre still jiggling". Dropping the state leaves the
    clock looking authoritative, and the oven does not read clocks."""
    cook = cook_along(library, BROWNIES)
    assert cook.step("#bake").timer_label() == (
        "32 min, then check: edges firmish, centre still jiggling"
    )


def test_a_range_shows_both_ends(library):
    """The peanut butter freezes for two to three hours, and the difference
    matters to a cook deciding whether to start after dinner."""
    freeze = cook_along(library, BROWNIES).step("#freeze-pb")
    assert freeze.timer_s == pytest.approx(2 * 3600)
    assert freeze.timer_max_s == pytest.approx(3 * 3600)
    assert freeze.timer_label() == (
        "2 hr-3 hr, then check: firm enough to lift out in one piece"
    )


def test_a_step_with_no_stated_time_offers_no_timer(library):
    """The planner assumes a minute for a step that states none, so the graph
    has a length. Starting a 60-second timer on that assumption would hand the
    cook a number the recipe never gave."""
    reline = cook_along(library, BROWNIES).step("#reline-pan")
    assert reline.timer_s is None
    assert not reline.has_timer
    assert reline.duration_s > 0, "the plan still gives it room"
    assert reline.timer_label() is None


def test_a_state_with_no_time_still_reads_as_the_thing_that_decides(library):
    recipe = build_recipe(
        steps=[step("#reduce", consumes=["#flour"], produces="#done",
                    doneness="the sauce coats the back of a spoon")],
    )
    cook = cook_along(build_library(recipe), recipe.id)
    assert cook.steps[0].timer_label() == (
        "go by: the sauce coats the back of a spoon"
    )


def test_a_sanctioned_stopping_point_reaches_the_cook(library):
    """"Can I do the rest tomorrow?" has an answer in the graph, and the cook
    should not have to guess it."""
    cook = cook_along(library, BROWNIES)
    assert cook.step("#freeze-pb").may_pause_after
    assert not cook.step("#bake").may_pause_after


# ---------------------------------------------------------------------------
# Components: grouped, and deliberately not interleaved
# ---------------------------------------------------------------------------


def test_component_steps_are_grouped_and_not_merged_into_one_timeline(library):
    """The boundary this module stays inside.

    Interleaving the frosting into the cake's timeline while it cools needs
    edges no recipe states, so each dish keeps its own steps and its own plan
    and the walk is document order. The failure this prevents is the opposite
    one: dropping the component's steps entirely, which is what looping
    ``recipe.components`` one level deep and printing masses did.
    """
    cook = cook_along(library, CAKE)

    assert [c.label for c in cook.components] == ["Vanilla buttercream"]
    assert all(s.step_id in {st.id for st in library.recipe(CAKE).steps}
               for s in cook.steps)
    frosting = cook.components[0]
    assert frosting.recipe_id == VANILLA_BC
    assert [s.step_id for s in frosting.steps] == [
        "#cream-butter", "#add-sugar", "#finish",
    ]
    # Two plans, each starting at its own zero. Nothing claims they are one.
    assert frosting.plan.total_s < cook.plan.total_s
    assert frosting.steps[0].start_s == 0

    labels = [entry.label for entry in cook.sequence()]
    assert labels == ["My Very Best Vanilla Cake"] * len(cook.steps) + [
        "Vanilla buttercream"
    ] * len(frosting.steps), "grouped by dish, in document order"


def test_a_component_use_shows_what_it_will_make(library):
    """The step that consumes the frosting is the one place the cook needs to
    know how much frosting there is, and the mass belongs to the child's
    resolution rather than to any of the cake's ingredient rows."""
    cook = cook_along(library, CAKE)
    frosting = next(
        i for i in cook.step("#assemble").ingredients if i.id == "#frosting"
    )
    assert frosting.name == "Vanilla buttercream"
    assert frosting.row_mass_g == pytest.approx(
        cook.components[0].resolution.produced_g
    )


def test_doubling_a_dish_doubles_its_components(library):
    """A parent asks for batches, and the cook-along has to show the frosting
    that is actually on the bench -- with the cake's local "make the butter
    225 g" override still applied, at base yield, before the doubling."""
    cook = cook_along(library, CAKE, batches=2)
    frosting = cook.components[0]
    butter = next(
        i for i in frosting.step("#cream-butter").ingredients if i.id == "#butter"
    )
    assert frosting.scale == pytest.approx(2)
    assert butter.row_mass_g == pytest.approx(450), "225 g override, doubled"


def test_an_optional_component_can_be_left_out(library):
    """The qeema is dinner with or without the mint yogurt, and a cook who is
    not making it should not be walked through it."""
    cook = cook_along(library, QEEMA)
    yogurt = cook.components[0]
    assert yogurt.optional

    with_it = cook.sequence()
    without = cook.sequence(include_optional=False)
    assert len(with_it) - len(without) == len(yogurt.steps)
    assert cook.total_steps(include_optional=False) == len(cook.steps)
    assert all(entry.of == len(without) for entry in without), (
        "the count the cook sees has to match the walk they are on"
    )


# ---------------------------------------------------------------------------
# The cursor: held by the caller, advanced by nobody here
# ---------------------------------------------------------------------------


def test_asking_for_the_same_cursor_twice_gives_the_same_step(library):
    """Stateless on purpose. Home Assistant holds "which step am I on" and
    restores it after a restart; a module that also advanced something would
    put the same state in two places."""
    cook = cook_along(library, BROWNIES)
    assert cook.at(3).step.step_id == cook.at(3).step.step_id
    assert cook.at(0).cursor == 0
    assert cook.at(1).step is not cook.at(0).step


def test_a_cursor_off_the_end_is_not_an_error(library):
    """"Not started" and "finished" are ordinary states for the entity holding
    the cursor, and a recipe edited under a saved cursor must not crash the
    integration on the next restart."""
    cook = cook_along(library, COFFEE_BC)
    assert cook.at(-1) is None
    assert cook.at(len(cook.steps)) is None
    assert cook.at(len(cook.steps) - 1).is_last


def test_the_cursor_spans_the_whole_tree(library):
    """One cursor, not one per recipe: the integration holds a single number."""
    cook = cook_along(library, CAKE)
    sequence = cook.sequence()
    assert len(sequence) == cook.total_steps()
    assert [entry.cursor for entry in sequence] == list(range(len(sequence)))
    assert sequence[-1].recipe_id == VANILLA_BC


# ---------------------------------------------------------------------------
# Degrading rather than refusing
# ---------------------------------------------------------------------------


def test_a_level_0_scrape_still_has_a_cook_along(library, level0):
    """Nothing is linked, so no step lists an ingredient -- but the text, the
    order and the count are all still there, and a scraped recipe is most of the
    library until the enrichment skill has been at it."""
    cook = cook_along(library, level0.id)
    assert len(cook.steps) == 3
    assert cook.steps[0].text.startswith("Heat the oil")
    assert cook.steps[0].ingredients == []
    assert cook.at(2).is_last


def test_a_cited_component_is_reported_rather_than_dropped(library):
    """Modernist's "see page 121" is referenced, renderable and not expandable.
    The cook still has to be told to go and get the book."""
    recipe = build_recipe(
        name="Cites a book",
        components=[{
            "@id": "#sauce",
            "@type": "rw:ComponentUse",
            "rw:label": "Bolognese",
            "rw:citation": {"name": "Dinner", "rw:page": 308},
        }],
    )
    cook = cook_along(build_library(recipe), recipe.id)
    assert [use.label for use in cook.unresolvable] == ["Bolognese"]
    assert cook.components == []


def test_a_dish_already_resolved_is_not_resolved_again(library):
    """The CLI and the validator both build a ``Dish`` for other reasons."""
    dish = resolve_dish(library, CAKE, batches=2)
    cook = cook_along_from_dish(dish)
    assert cook.resolution is dish.resolution
    assert cook.components[0].resolution is dish.components[0].resolution
