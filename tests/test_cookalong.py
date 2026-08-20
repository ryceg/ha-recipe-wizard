"""The cook-along: the join every caller was making by hand, and getting wrong.

Each test is named after the failure it prevents. Four of them are failures that
had already happened in shipped callers: a variant cooked as an empty recipe, a
doubled portion shown at single scale, a mass shown against the wrong document,
and a timer that dropped the doneness it was supposed to display.
"""

import pytest
from conftest import BROWNIES, CAKE, COFFEE_BC, VANILLA_BC
from support import build_library, build_recipe, component, ingredient, portion, step

from custom_components.recipe_wizard.core.cookalong import (
    FINISHES_ON_CLOCK,
    FINISHES_ON_COOK,
    FINISHES_ON_STATE,
    cook_along,
    cook_along_from_dish,
    step_ingredients,
)
from custom_components.recipe_wizard.core.dish import resolve_dish
from custom_components.recipe_wizard.core.resolve import resolve
from custom_components.recipe_wizard.core.schedule import schedule

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


def test_a_step_naming_things_by_their_full_id_still_shows_their_masses(library):
    """The asymmetry bug, end to end and at the point it costs the cook something.

    Two halves. ``ingredients_for_step`` matched a component with ``c.id == ref``
    while resolving the ingredient beside it through the tolerant lookup, so a
    fully-qualified reference to the frosting produced no row at all. And a row
    that *was* produced carried the reference as the step had written it, so the
    mass lookup -- keyed by the ingredient's own ``@id`` -- missed, and the flour
    arrived with a name and no weight. Both are fixed by reporting a resolved
    reference under the node's own id.
    """
    doc_id = "urn:recipe:test/long-form-cook"
    frosting = build_recipe(
        name="Buttercream", ingredients=[ingredient("butter", mass=250)],
    )
    parent = build_recipe(
        id=doc_id,
        name="Frosted cake",
        ingredients=[ingredient("flour", mass=250)],
        components=[component("Buttercream", id="#frosting", recipe=frosting.id)],
        steps=[
            step("#bake", consumes=[f"{doc_id}#flour"],
                 produces=("#layers", "Baked layers")),
            step("#frost", consumes=["#layers", f"{doc_id}#frosting"],
                 produces=("#cake", "Frosted cake")),
        ],
    )
    cook = cook_along(build_library(parent, frosting), parent.id)

    flour = next(i for i in cook.step("#bake").ingredients if i.id == "#flour")
    assert flour.row_mass_g == pytest.approx(250), "the weight, not just the name"

    layer, butter = cook.step("#frost").ingredients
    assert layer.name == "Baked layers"
    assert butter.name == "Buttercream"
    assert butter.row_mass_g == pytest.approx(
        cook.components[0].resolution.produced_g
    ), "what the sub-recipe will actually make"


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


# ---------------------------------------------------------------------------
# What decides a step is over
# ---------------------------------------------------------------------------


def _one_step(**kwargs):
    """A one-step recipe, cooked along, so the premise is the step itself."""
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[step("#do-it", consumes=["#flour"],
                    produces=("#thing", "Thing"), **kwargs)],
    )
    dish = cook_along(build_library(recipe), recipe.id)
    return dish.steps[0]


def test_a_state_decides_a_step_even_when_a_time_is_given():
    """The brownies bake for 32 minutes *until* the edges are firmish.

    The whole format doc turns on the state being authoritative and the time
    being an estimate of it, and until this property existed every surface
    decided that privately -- so the timer sensor called all three kinds of
    number an estimate and the planner called none of them one.
    """
    cooked = _one_step(duration="PT32M", doneness="edges firmish, centre jiggling")

    assert cooked.finishes_on == FINISHES_ON_STATE
    assert cooked.time_is_estimate, "32 min is an estimate of the state"


def test_a_stated_time_with_no_state_is_the_instruction_and_not_an_estimate():
    """"Beat the eggs for 30 seconds on speed 6" is not estimating anything.

    Hedging it is not harmless: a surface that marks its certain numbers
    uncertain has nothing left to mark its uncertain ones with.
    """
    cooked = _one_step(duration="PT30S")

    assert cooked.finishes_on == FINISHES_ON_CLOCK
    assert not cooked.time_is_estimate


def test_a_step_with_neither_is_finished_by_the_cook_doing_it():
    """Whisking the dry ingredients waits for nothing.

    The planner assumes a minute so the graph has a length, which is scaffolding
    and not a claim -- so this is not a one-minute clock step.
    """
    cooked = _one_step()

    assert cooked.finishes_on == FINISHES_ON_COOK
    assert not cooked.time_is_estimate
    assert cooked.timer is None


def test_when_the_clock_starts_is_a_different_question_from_what_ends_it():
    """A timer that starts on an event still ends on the clock.

    ``rw:timerStartsWhen`` is why the timer sensor shows no timestamp -- nothing
    knows when the water came back to the boil -- and folding it into this
    property would make a step nobody can time look like a step nothing times.
    """
    cooked = _one_step(duration="PT3M", timer_starts_when="the water returns to the boil")

    assert cooked.finishes_on == FINISHES_ON_CLOCK
    assert cooked.timer_starts_when is not None


def test_the_plan_says_how_much_of_its_total_a_state_decides(brownies):
    """"Total 7 hr" reads as a promise, and most of the brownies is not one."""
    plan = schedule(brownies)

    assert plan.state_decided_s > 0, "the freeze and the bake both end on a state"
    assert plan.state_decided_s < plan.total_s
    stated = sum(entry.duration_s for entry in plan.steps
                 if entry.doneness is not None)
    assert plan.state_decided_s == pytest.approx(stated)


def test_a_plan_whose_every_step_the_clock_decides_reports_none():
    """A recipe with no states in it has nothing soft to report.

    Built rather than borrowed, and it was borrowed once: this asserted that the
    *cake* reports none, which was true of the corpus on the day it was written
    and stopped being true the moment the cake's "until golden brown and a
    toothpick comes out clean" was lifted into a ``rw:doneness``. The premise is
    "a recipe whose every step the clock decides", so the recipe saying that is
    the one the test should build -- ``tests/support.py``'s whole argument.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter"),
                 duration="PT5M"),
            step("#rest", consumes=["#batter"], produces=("#rested", "Rested"),
                 duration="PT1H"),
        ],
    )

    plan = schedule(resolve(build_library(recipe), recipe.id))

    assert plan.state_decided_s == 0


def test_a_state_with_no_stated_time_is_a_step_to_check_not_soft_time():
    """The cake whisks "until smooth and foamy" and gives no time for it.

    The planner lays that out at its assumed minute so the graph has a length,
    and counting the minute here reported scaffolding as time a state decides --
    which is the assumed minute being treated as data, the one thing every other
    part of this module refuses to do. Caught by reading ``--plan`` after
    enriching the cake, not by a test.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#whisk", consumes=["#flour"], produces=("#smooth", "Smooth"),
                 doneness="smooth and foamy"),
            step("#bake", consumes=["#smooth"], produces=("#loaf", "Loaf"),
                 duration="PT30M", doneness="a skewer comes out clean"),
        ],
    )

    plan = schedule(resolve(build_library(recipe), recipe.id))

    assert plan.state_decided_s == pytest.approx(30 * 60), (
        "the bake's stated half hour, and nothing for the whisk"
    )
    assert plan.step("#whisk").duration_s > 0, (
        "the premise: the whisk does occupy the timeline, it just states no time"
    )
    assert plan.step("#whisk").stated_s is None


# ---------------------------------------------------------------------------
# Addressing a position: by id, because an index is #step-3
# ---------------------------------------------------------------------------


def test_a_step_is_found_by_its_id_and_the_recipe_it_belongs_to(library):
    cook = cook_along(library, CAKE)
    found = cook.locate(CAKE, "#bake")
    assert found is not None
    assert found.step.step_id == "#bake"
    assert cook.at(found.cursor).step.step_id == "#bake"


def test_a_step_id_is_matched_bare_or_fully_qualified(library):
    """``graph.py``'s rule: a reference means the same thing written either way,
    and a saved cursor may hold either."""
    cook = cook_along(library, CAKE)
    bare = cook.locate(CAKE, "#bake")
    qualified = cook.locate(CAKE, f"{CAKE}#bake")
    assert bare is not None and qualified is not None
    assert bare.cursor == qualified.cursor


def test_the_recipe_is_needed_because_a_step_id_is_not_unique_in_a_dish(library):
    """The cake and its buttercream both have an ``#add-sugar``. Addressing one
    by id alone would find whichever came first in the walk."""
    cook = cook_along(library, CAKE)
    owners = {
        entry.recipe_id
        for entry in cook.sequence()
        if entry.step.step_id == "#add-sugar"
    }
    assert len(owners) == 2, "premise: two recipes in this dish use #add-sugar"
    for owner in owners:
        found = cook.locate(owner, "#add-sugar")
        assert found is not None and found.recipe_id == owner


def test_a_step_that_is_no_longer_in_the_dish_is_not_found(library):
    assert cook_along(library, CAKE).locate(CAKE, "#no-such-step") is None


def test_a_step_added_to_a_component_does_not_move_the_step_the_cook_is_on():
    """The whole reason a saved position is a pair and not an index.

    The walk is the parent's steps then the component's, so inserting a step
    *into the component* -- a different file, one nobody was editing -- renumbers
    every position from there on. The id does not move, which is what a saved
    cursor has to be addressed by.
    """
    def library_with(extra_frosting_steps):
        frosting = build_recipe(
            id="urn:recipe:test/frosting",
            name="Buttercream",
            ingredients=[ingredient("butter", mass=250)],
            steps=[
                *extra_frosting_steps,
                step("#cream-butter", consumes=["#butter"],
                     produces=("#creamed", "Creamed butter")),
            ],
        )
        parent = build_recipe(
            id="urn:recipe:test/frosted",
            name="Frosted cake",
            ingredients=[ingredient("flour", mass=250)],
            components=[component("Buttercream", id="#frosting",
                                  recipe=frosting.id)],
            steps=[
                step("#bake", consumes=["#flour"],
                     produces=("#layers", "Baked layers")),
                step("#frost", consumes=["#layers", "#frosting"],
                     produces=("#cake", "Frosted cake")),
            ],
        )
        return build_library(parent, frosting), parent.id

    library, parent_id = library_with([])
    before = cook_along(library, parent_id)
    creaming = before.locate("urn:recipe:test/frosting", "#cream-butter")
    assert creaming is not None

    # The same dish with one step added ahead of the creaming, inside the
    # component: the butter now has to be softened before it can be creamed.
    grown_library, parent_id = library_with([
        step("#soften", consumes=["#butter"], produces=("#soft", "Softened butter")),
    ])
    after = cook_along(grown_library, parent_id)
    assert after.total_steps() == before.total_steps() + 1, "premise: it grew"
    moved = after.locate("urn:recipe:test/frosting", "#cream-butter")
    assert moved is not None
    assert moved.cursor == creaming.cursor + 1, "the index moved"
    assert after.at(creaming.cursor).step.step_id != "#cream-butter", (
        "and the old index now names a different step"
    )
