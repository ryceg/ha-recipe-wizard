"""Scheduling, and the constraints that stop it ruining the food."""

import pytest
from conftest import COFFEE_BC
from support import build_recipe, ingredient, step

from custom_components.recipe_wizard.core import check_plan, rigid_chains, schedule
from custom_components.recipe_wizard.core.graph import recipe_graph
from custom_components.recipe_wizard.core.resolve import effective_recipe, resolve
from custom_components.recipe_wizard.core.schedule import (
    dependencies,
    topological_order,
)
from custom_components.recipe_wizard.core.validate import ERROR


def _starts(plan):
    return {s.step_id: s.start_s for s in plan.steps}


# ---------------------------------------------------------------------------
# What gets planned: the effective document, not the one on disk
# ---------------------------------------------------------------------------


def test_a_variant_is_planned_from_the_steps_it_inherited(library):
    """The live bug: ``schedule(library.recipe(id))`` gave a 0-minute plan.

    The coffee buttercream's document is a patch list -- no ingredients, no
    steps -- so planning it off disk produced nothing at all for a recipe that
    takes six and a half minutes.
    """
    plan = schedule(resolve(library, COFFEE_BC, strict=False))
    assert [s.step_id for s in plan.steps] == [
        "#cream-butter", "#add-sugar", "#finish",
    ]
    assert plan.total_s == pytest.approx(6.5 * 60, abs=1)


def test_a_bare_recipe_is_still_planned_unchanged(cake):
    """A level-0 scrape has no resolution and still has to be planned."""
    assert effective_recipe(cake) is cake
    assert schedule(cake).total_s > 0


def test_scaling_does_not_disturb_the_plan(library, brownies):
    """Portions scale; times do not. A doubled tray is not a longer recipe.

    Which is the point of ``rw:bakeTimeByVessel``: bake time comes from the
    vessel, not the batch mass, so the resolver warns and refuses to touch it.
    """
    single = schedule(resolve(library, brownies.id))
    doubled = schedule(resolve(library, brownies.id, requires_batches=2))
    assert doubled.total_s == single.total_s


# ---------------------------------------------------------------------------
# Just-in-time is the default, and earliest-start is wrong
# ---------------------------------------------------------------------------


def test_the_plan_is_self_consistent(cake, brownies):
    for recipe in (cake, brownies):
        plan = schedule(recipe)
        assert check_plan(recipe, _starts(plan)) == []
        assert not plan.findings


def test_prep_is_scheduled_when_it_is_needed_not_as_early_as_possible(brownies):
    """Earliest-start melts the chocolate at t=0 and lets the batter set solid.

    Nothing in the graph forces the batter to be mixed after the peanut butter
    has frozen, so an ASAP plan does it two hours early. Scheduling backwards
    from the finish makes just-in-time the default.
    """
    asap = schedule(brownies, strategy="asap")
    jit = schedule(brownies)

    assert asap.step("#melt").start_s == 0
    assert jit.step("#melt").start_s > 100 * 60
    assert jit.step("#pour-half").start_s - jit.step("#add-dry").end_s <= 10 * 60


def test_the_cake_melts_its_butter_and_milk_while_the_eggs_beat(cake):
    """Which is what the source's own prose says to do."""
    plan = schedule(cake)
    melt = plan.step("#melt-butter-milk")
    beat = plan.step("#beat-to-ribbon")
    assert beat.start_s <= melt.start_s <= beat.end_s
    assert plan.step("#temper-batter").start_s - melt.end_s <= 5 * 60


def test_the_oven_preheat_still_lands_before_the_bake(brownies):
    """A step nothing depends on floats to the end under backward scheduling.

    The brownies preheat had no dependant at all, so the first backward plan
    put it after the bake. The lead edge is what anchors it.
    """
    plan = schedule(brownies)
    assert plan.step("#preheat").end_s <= plan.step("#bake").start_s + 1


def test_the_cakes_preheat_lead_is_honoured(cake):
    plan = schedule(cake)
    assert plan.step("#preheat").start_s == 0
    assert plan.step("#beat-eggs").start_s == pytest.approx(20 * 60, abs=1)


# ---------------------------------------------------------------------------
# Maximum delays: do not let it sit
# ---------------------------------------------------------------------------


def test_batter_and_pouring_form_a_rigid_chain(cake):
    chains = rigid_chains(cake)
    assert ["#final-mix", "#pour-pans"] in chains
    assert ["#bang-pans", "#bake"] in chains


def test_making_the_batter_an_hour_ahead_is_rejected(cake):
    plan = schedule(cake)
    starts = _starts(plan)
    for step_id in ("#pour-pans", "#bang-pans", "#bake", "#cool-in-pan",
                    "#cool-out", "#assemble"):
        starts[step_id] += 3600

    findings = check_plan(cake, starts)
    delay = next(f for f in findings if f.code == "schedule-max-delay")
    assert delay.node == "#pour-pans"
    assert delay.recipe == cake.id
    assert "air bubbles subside" in delay.message


# ---------------------------------------------------------------------------
# Minimum delays: do not rush it
# ---------------------------------------------------------------------------


def test_brownies_cannot_be_cut_before_they_have_chilled(brownies):
    """The twin that was missing. Without a floor the planner says cut them now."""
    plan = schedule(brownies)
    gap = plan.step("#cut").start_s - plan.step("#cool-counter").end_s
    assert gap == pytest.approx(3 * 3600, abs=1)


def test_cutting_early_is_rejected_with_its_reason(brownies):
    plan = schedule(brownies)
    starts = _starts(plan)
    starts["#cut"] -= 2 * 3600

    findings = check_plan(brownies, starts)
    early = next(f for f in findings if f.code == "schedule-min-delay")
    assert early.node == "#cut"
    assert "peanut butter oozes" in early.message


def test_serving_waits_for_the_brownies_to_come_back_to_temperature(brownies):
    plan = schedule(brownies)
    gap = plan.step("#serve").start_s - plan.step("#cut").start_s
    assert gap >= 15 * 60


def test_minimum_delays_stretch_the_total_time(brownies):
    """A 32 minute bake inside a seven hour recipe."""
    plan = schedule(brownies)
    assert plan.total_s == pytest.approx(7 * 3600, abs=15 * 60)
    assert plan.active_s < 20 * 60


# ---------------------------------------------------------------------------
# A scheduling defect is a finding, in the report's one shape
# ---------------------------------------------------------------------------


def test_a_lead_before_naming_no_step_is_reported_as_a_finding():
    """It used to be a bare string on ``Plan.warnings``.

    So the constraint was silently dropped -- the exact failure ``leadBefore``
    exists to prevent -- and the only record of it was a sentence in a list that
    nothing counted, nothing gave a severity, and ``--validate`` never saw.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter")),
            step("#bake", consumes=["#batter"], produces=("#loaf", "Loaf"),
                 lead_before=[("#preheat", "PT20M", "the oven must be at 180C")]),
        ],
    )
    plan = schedule(recipe)

    finding = next(f for f in plan.findings
                   if f.code == "schedule-unknown-lead")
    assert finding.level == ERROR
    assert finding.node == "#bake", "the step carrying the bad rw:leadBefore"
    assert "#preheat" in finding.message, "quoted as the author wrote it"


def test_contradictory_constraints_name_the_step_they_broke_at():
    """"Did not settle" says a plan is wrong without saying where.

    A three-hour floor and a back-to-back ceiling on the same edge cannot both
    hold, and the planner can only report that it gave up. Checking the plan it
    gave up on is what turns that into a node: the pair is unknowable, the step
    whose start time ends up wrong is not.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter")),
            step("#bake", consumes=["#batter"], produces=("#loaf", "Loaf"),
                 min_delay_after=[("#mix", "PT1H", "it has to prove")],
                 max_delay_after=[("#mix", "PT0S", "the bubbles subside")]),
        ],
    )
    plan = schedule(recipe)

    unsettled = next(f for f in plan.findings if f.code == "schedule-unsettled")
    assert unsettled.node is None, "the defect is a pair of constraints, not a step"

    broken = check_plan(recipe, {s.step_id: s.start_s for s in plan.steps})
    assert [f.node for f in broken] == ["#bake"]
    assert [f.code for f in broken] == ["schedule-max-delay"]


# ---------------------------------------------------------------------------
# Graph mechanics
# ---------------------------------------------------------------------------


def test_hands_on_and_hands_off_time_do_not_double_count(cake):
    plan = schedule(cake)
    assert plan.active_s + plan.unattended_s <= plan.total_s + 1


def test_the_effort_figures_partition_the_whole_timeline(cake, brownies):
    """The header prints them beside a total, which claims they add up to it."""
    for plan in (schedule(cake), schedule(brownies)):
        accounted = plan.active_s + plan.unattended_s + plan.waiting_s
        assert accounted == pytest.approx(plan.total_s, abs=1)


def test_an_enforced_chill_is_neither_hands_on_nor_hands_off(brownies):
    """It used to be neither anything else: the sweep skipped an interval with
    no step running, so the brownies' three-hour chill and the quarter-hour
    back to room temperature -- 195 of the recipe's 420 minutes -- fell out of
    the report between one figure and the next."""
    plan = schedule(brownies)
    assert plan.waiting_s == pytest.approx((3 * 60 + 15) * 60, abs=60)


def test_a_recipe_the_cook_never_waits_through_reports_no_waiting():
    """A "waiting 0 min" the header would have to print on almost every recipe
    is why the figure is only shown where there is some."""
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces="#batter", duration=5),
            step("#bake", consumes=["#batter"], produces="#cake",
                 duration=30, attention="unattended"),
        ],
    )
    plan = schedule(recipe)
    assert plan.waiting_s == 0.0
    assert plan.active_s + plan.unattended_s == pytest.approx(plan.total_s, abs=1)


def test_a_delay_another_branch_works_through_is_not_time_spent_waiting():
    """Waiting is empty timeline, not the presence of a ``minDelayAfter``.

    The delay here is 30 minutes, but the sauce is scheduled just-in-time into
    the middle of it, so ten of those minutes are hands-on and only twenty are
    time the cook is waiting. Counting the constraint rather than sweeping the
    timeline would report all thirty and double-count the sauce.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250), ingredient("cream", mass=100)],
        steps=[
            step("#mix", consumes=["#flour"], produces="#batter", duration=5),
            step("#rest", consumes=["#batter"], produces="#rested",
                 duration=20, attention="unattended"),
            step("#sauce", consumes=["#cream"], produces="#sauced", duration=10),
            step("#serve", consumes=["#rested", "#sauced"], duration=1,
                 min_delay_after=[("#rest", "PT30M", "it has to set")]),
        ],
    )
    plan = schedule(recipe)
    assert plan.waiting_s == pytest.approx(20 * 60, abs=1)
    assert plan.step("#sauce").start_s > plan.step("#rest").end_s


def test_doneness_reaches_the_scheduled_step(brownies):
    """It used to be dropped on the way onto the plan, which is where a timer
    is built from -- so the timer could only ever show the clock, and the clock
    is the estimate."""
    plan = schedule(brownies)
    assert plan.step("#bake").doneness == "edges firmish, centre still jiggling"
    assert plan.step("#freeze-pb").doneness == "firm enough to lift out in one piece"
    assert plan.step("#reline-pan").doneness is None, "not every step has one"


def test_dependencies_come_from_the_dataflow_graph(cake):
    deps = dependencies(cake)
    assert "#bake" in deps["#cool-in-pan"]
    assert deps["#preheat"] == set()


def test_topological_order_covers_every_step(cake):
    ordered = topological_order(cake)
    assert len(ordered) == len(cake.steps)
    positions = {step.id: i for i, step in enumerate(ordered)}
    assert positions["#beat-eggs"] < positions["#add-sugar"] < positions["#beat-to-ribbon"]


def test_a_scheduled_step_is_found_by_either_spelling_of_its_id(cake):
    """``Plan.step`` was a linear scan with an exact-match test, in a module where
    every other id lookup tolerates a fully-qualified reference. The scan is now
    an index built on first use, and the test is the library's one rule."""
    plan = schedule(cake)

    assert plan.step("#bake") is plan.step(f"{cake.id}#bake")
    assert plan.step("#not-a-step-in-this-recipe") is None


def test_planning_from_a_prebuilt_graph_gives_the_same_plan(cake):
    """The index is built by the caller that needs it and passed down: the
    cook-along builds one per dish and hands it to the planner, which is what
    stops ``dependencies`` being recomputed three times per call."""
    graph = recipe_graph(cake)
    from_graph = schedule(graph)
    from_document = schedule(cake)

    assert [(s.step_id, s.start_s) for s in from_graph.steps] == [
        (s.step_id, s.start_s) for s in from_document.steps
    ]
    assert dependencies(graph) is graph.dependencies
