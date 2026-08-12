"""Scheduling, and the constraints that stop it ruining the food."""

import pytest

from custom_components.recipe_wizard.core import check_plan, rigid_chains, schedule
from custom_components.recipe_wizard.core.schedule import dependencies, topological_order


def _starts(plan):
    return {s.step_id: s.start_s for s in plan.steps}


# ---------------------------------------------------------------------------
# Just-in-time is the default, and earliest-start is wrong
# ---------------------------------------------------------------------------


def test_the_plan_is_self_consistent(cake, brownies):
    for recipe in (cake, brownies):
        plan = schedule(recipe)
        assert check_plan(recipe, _starts(plan)) == []
        assert not plan.warnings


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

    violations = check_plan(cake, starts)
    delay = next(v for v in violations if v.kind == "max-delay")
    assert delay.step_id == "#pour-pans"
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

    violations = check_plan(brownies, starts)
    early = next(v for v in violations if v.kind == "min-delay")
    assert early.step_id == "#cut"
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
# Graph mechanics
# ---------------------------------------------------------------------------


def test_hands_on_and_hands_off_time_do_not_double_count(cake):
    plan = schedule(cake)
    assert plan.active_s + plan.unattended_s <= plan.total_s + 1


def test_dependencies_come_from_the_dataflow_graph(cake):
    deps = dependencies(cake)
    assert "#bake" in deps["#cool-in-pan"]
    assert deps["#preheat"] == set()


def test_topological_order_covers_every_step(cake):
    ordered = topological_order(cake)
    assert len(ordered) == len(cake.steps)
    positions = {step.id: i for i, step in enumerate(ordered)}
    assert positions["#beat-eggs"] < positions["#add-sugar"] < positions["#beat-to-ribbon"]
