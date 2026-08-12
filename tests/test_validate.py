"""Validation, including the conflicts the real recipes actually contain."""

from conftest import CHOCOLATE_BC
from support import (
    build_library,
    build_recipe,
    component,
    ingredient,
    insert_step,
    portion,
    step,
    storage_option,
)

from custom_components.recipe_wizard.core import (
    validate_library,
    validate_recipe,
    worst_level,
)
from custom_components.recipe_wizard.core.__main__ import _report, main
from custom_components.recipe_wizard.core.adjust import apply_adjustments
from custom_components.recipe_wizard.core.graph import recipe_graph
from custom_components.recipe_wizard.core.model import ConsumeRef, Portion
from custom_components.recipe_wizard.core.validate import ERROR, WARNING, Finding


def test_the_library_has_no_errors(library):
    """The one assertion whose subject really is the corpus.

    Every recipe on disk resolves, schedules and links up. This is the contract
    the enrichment skill iterates against, and it is the only thing a new
    recipe is allowed to break.
    """
    errors = [f for f in validate_library(library) if f.level == ERROR]
    assert errors == [], "\n".join(str(f) for f in errors)


# ---------------------------------------------------------------------------
# A finding names the node, not only the document
# ---------------------------------------------------------------------------


def test_a_finding_names_the_node_and_not_only_the_recipe(library, brownies):
    """The brownies' "divided" salt flakes: a real gap in a real source.

    Every finding used to carry the recipe id and nothing else, so the only thing
    saying *which* of the document's ten ingredient rows was under-portioned was
    the English message -- and two of the ten are salt. The corpus is being lifted
    from level 0 by a skill iterating against this module, and a skill that wants
    to fix ``#salt-flakes`` should not have to parse a sentence to learn its name.
    """
    finding = next(f for f in validate_recipe(brownies, library)
                   if f.code == "portions-under-whole")

    assert finding.recipe == brownies.id
    assert finding.node == "#salt-flakes"
    found = recipe_graph(brownies).node(finding.node)
    assert (found.label, found.is_ingredient) == ("salt flakes", True), \
        "canonical under the library's one lookup rule, so a caller can resolve it"
    assert "#salt-flakes" in str(finding), "and a human still gets one clear line"


def test_a_node_id_in_a_finding_survives_a_step_inserted_above_it():
    """Which is the whole reason it is worth carrying one.

    ``docs/format.md`` Principle 5: ``#step-3`` breaks every patch targeting it
    the moment a step is inserted above, and ``apply_adjustments`` renumbers every
    position after an insert. A finding that located its node positionally would
    be stale before the skill got round to acting on it.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#preheat", text="Preheat the oven."),
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter")),
            step("#bake", consumes=["#batter"], produces=("#loaf", "Loaf")),
        ],
        adjustments=[insert_step(step("#grease", text="Grease the tin."),
                                 after="#preheat")],
    )
    library = build_library(recipe)

    def dangling(document):
        return {f.node for f in validate_recipe(document, library)
                if f.code == "dangling-step"}

    assert dangling(recipe) == {"#preheat"}
    assert recipe.step("#bake").position == 3

    patched, _ = apply_adjustments(recipe, recipe.adjustments)

    assert patched.step("#bake").position == 4, "every position after it moved"
    assert "#preheat" in dangling(patched), "and the node is still the same node"


def test_a_component_finding_names_the_use_and_not_the_sub_recipe(library, cake):
    """The cake's storage conflict is about the cake's *use* of the buttercream.

    Sending a fixer at ``urn:recipe:rte/vanilla-buttercream`` would send them at a
    document that is not wrong -- the buttercream really does want the fridge. The
    node is ``#frosting``, where the parent's overrides already live.
    """
    finding = next(f for f in validate_recipe(cake, library)
                   if f.code == "storage-conflict")

    assert finding.node == "#frosting"
    assert recipe_graph(cake).node(finding.node).is_component


# ---------------------------------------------------------------------------
# One report shape: scheduling defects are findings too
# ---------------------------------------------------------------------------


def test_a_scheduling_defect_reaches_the_validation_report():
    """It could not, before. ``validate_recipe`` never called ``check_plan``.

    So a document whose constraints contradict each other validated clean and
    misbehaved only when somebody thought to ask for a plan -- and the enrichment
    skill's loop reads ``--validate``. A three-hour floor and a back-to-back
    ceiling on the same edge cannot both hold.
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
    findings = validate_recipe(recipe, build_library(recipe))

    codes = {f.code for f in findings}
    assert "schedule-unsettled" in codes
    assert {f.node for f in findings if f.code == "schedule-max-delay"} == {"#bake"}
    assert worst_level(findings) == ERROR


def test_a_scrape_is_not_asked_about_constraints_it_never_declared(library, level0):
    """The plan check is gated with every other graph rule, for the same reason.

    A level-0 document has step text and no ids, so anything a planner said about
    it would be about a graph the document never claimed to have.
    """
    assert not [f for f in validate_recipe(level0, library)
                if f.code.startswith("schedule-")]


def test_the_exit_status_is_the_skill_loops_stop_signal():
    """``worst_level`` was deleted as dead code; it is back with a caller.

    The loop iterates ``--validate`` until there are no errors, and until this
    existed it had to read the printed count back out of stdout to find out
    whether it was done. Warnings deliberately do *not* fail it: a warning
    reflecting a genuine ambiguity in the source is the correct outcome, and a
    loop trying to clear one would invent data.
    """
    where = "urn:recipe:test/x"
    warning = Finding(WARNING, "unit-divergence", where, "18% apart", "#butter")
    error = Finding(ERROR, "dangling-consume", where, "no such node", "#mix")

    assert worst_level([]) is None
    assert worst_level([warning]) == WARNING
    assert worst_level([warning, error]) == ERROR, "the worst wins, not the last"

    assert _report([warning]) == 0, "a genuine ambiguity is not a failure"
    assert _report([warning, error]) == 1
    assert main(["--list", "--validate"]) == 0, "the corpus has no errors today"


# ---------------------------------------------------------------------------
# Level gating: do not judge a scrape by level-3 rules
# ---------------------------------------------------------------------------


def test_a_level_0_scrape_is_not_buried_in_findings(library, level0):
    """The validator is the enrichment skill's success signal.

    Firing graph rules at a document that never claimed to have a graph makes
    it useless for that job -- every scraped recipe would report a cycle of
    errors about links it was never asked to have.
    """
    codes = {f.code for f in validate_recipe(level0, library)}
    assert "positional-step-id" not in codes
    assert "unused-ingredient" not in codes
    assert "no-terminal-product" not in codes
    assert "dangling-consume" not in codes


def test_level_3_rules_do_fire_at_level_3(library, cake):
    recipe = cake.copy()
    recipe.steps[-1].consumes.append(ConsumeRef("#nonexistent"))
    findings = validate_recipe(recipe, library)
    assert any(f.code == "dangling-consume" and f.level == ERROR for f in findings)


def test_a_variant_is_not_told_it_has_no_ingredients(library):
    """It is a patch list; declaring nothing of its own is the point."""
    findings = validate_recipe(library.recipe("urn:recipe:local/coffee-buttercream"),
                               library)
    assert not any(f.code == "no-ingredients" for f in findings)


# ---------------------------------------------------------------------------
# Portions
# ---------------------------------------------------------------------------


def test_two_steps_claiming_all_of_one_thing_is_flagged(library, cake):
    """How the cake's own batter split was found, after it was already written."""
    recipe = cake.copy()
    for step in recipe.steps:
        for consumed in step.consumes:
            if consumed.ref == "#base-batter":
                consumed.portion = Portion()
    findings = validate_recipe(recipe, library)
    assert any(f.code == "unportioned-multiple-use" for f in findings)


def test_portions_summing_over_one_is_an_error(library, brownies):
    recipe = brownies.copy()
    recipe.step("#pour-half").portion_of("#brownie-batter").fraction = 0.9
    for consumed in recipe.step("#cover").consumes:
        if consumed.ref == "#brownie-batter":
            consumed.portion = Portion(fraction=0.9)
    findings = validate_recipe(recipe, library)
    assert any(f.code == "portions-exceed-whole" and f.level == ERROR
               for f in findings)


def test_two_steps_claiming_the_remainder_is_an_error(library, brownies):
    recipe = brownies.copy()
    for consumed in recipe.step("#pour-half").consumes:
        if consumed.ref == "#brownie-batter":
            consumed.portion = Portion(remainder=True)
    findings = validate_recipe(recipe, library)
    assert any(f.code == "multiple-remainders" and f.level == ERROR
               for f in findings)


def test_an_unaccounted_portion_is_reported():
    """The brownies' salt flakes are "divided" and only half is ever used.

    Recorded as the source states it rather than guessed at, so the warning is
    correct and stays. The rule is asserted here against a recipe built to
    contain exactly that gap: counting one such finding across the library said
    nothing about the rule and everything about there being only seven recipes.
    """
    recipe = build_recipe(
        ingredients=[ingredient("salt flakes", mass=8)],
        steps=[step("#season",
                    consumes=[("#salt-flakes",
                               portion(fraction=0.5, text="half the salt flakes"))],
                    produces=("#seasoned", "Seasoned brownies"))],
    )
    findings = validate_recipe(recipe, build_library(recipe))

    unaccounted = [f for f in findings if f.code == "portions-under-whole"]
    assert len(unaccounted) == 1
    assert "#salt-flakes" in unaccounted[0].message
    assert "50%" in unaccounted[0].message


# ---------------------------------------------------------------------------
# Graph shape
# ---------------------------------------------------------------------------


def test_a_step_nothing_depends_on_is_flagged(library, brownies):
    """How the brownies came to preheat their oven after the bake."""
    recipe = brownies.copy()
    recipe.step("#bake").lead_before.clear()
    findings = validate_recipe(recipe, library)
    dangling = [f for f in findings if f.code == "dangling-step"]
    assert any("#preheat" in f.message for f in dangling)


def test_a_step_cycle_is_caught(library, cake):
    recipe = cake.copy()
    recipe.step("#whisk-dry").consumes.append(ConsumeRef("#finished-batter"))
    findings = validate_recipe(recipe, library)
    assert any(f.code == "step-cycle" for f in findings)


def test_a_component_consumed_by_its_full_id_is_not_called_dangling():
    """A spurious ERROR against a document that is correct.

    "Known" was a set of literal ``@id`` strings, so a step naming its own
    frosting ``urn:recipe:.../cake#frosting`` -- which is legal, since identity
    lives in ``@id`` -- was reported as consuming something that is not an
    ingredient, a component or produced by any step. The validator is the
    enrichment skill's success signal, and a rule that fires spuriously is worse
    than a rule that does not exist.
    """
    doc_id = "urn:recipe:test/long-form-consume"
    frosting = build_recipe(
        name="Buttercream", ingredients=[ingredient("butter", mass=250)],
    )
    recipe = build_recipe(
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
    codes = {f.code for f in validate_recipe(recipe, build_library(recipe, frosting))}

    assert "dangling-consume" not in codes
    assert "unused-ingredient" not in codes, "the flour is consumed, the long way"
    assert "unused-component" not in codes
    assert "no-terminal-product" not in codes


def test_a_target_written_two_ways_is_one_target_for_the_portion_rules():
    """Otherwise a document takes 60% of the same batter twice and gets a shrug.

    Portions were grouped by the reference each step happened to write, so the
    same intermediate under two spellings became two targets of 60% each -- both
    under the whole, so the overdraw went unreported and two spurious
    "only 60% accounted for" warnings went out instead.
    """
    doc_id = "urn:recipe:test/split-two-ways"
    recipe = build_recipe(
        id=doc_id,
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter")),
            step("#pour", consumes=[("#batter", portion(fraction=0.6))],
                 produces=("#tray-one", "First tray")),
            step("#pour-again",
                 consumes=[(f"{doc_id}#batter", portion(fraction=0.6))],
                 produces=("#tray-two", "Second tray")),
        ],
    )
    findings = validate_recipe(recipe, build_library(recipe))

    overdrawn = [f for f in findings if f.code == "portions-exceed-whole"]
    assert [f.level for f in overdrawn] == [ERROR]
    assert "120%" in overdrawn[0].message
    assert not any(f.code == "portions-under-whole" for f in findings)


def test_an_unused_ingredient_is_flagged(library, cake):
    recipe = cake.copy()
    for step in recipe.steps:
        step.consumes = [c for c in step.consumes if c.ref != "#oil"]
    findings = validate_recipe(recipe, library)
    assert any(f.code == "unused-ingredient" for f in findings)


# ---------------------------------------------------------------------------
# Real conflicts in the real data
# ---------------------------------------------------------------------------


def test_the_butter_divergence_is_reported(library):
    findings = validate_recipe(library.recipe(CHOCOLATE_BC), library)
    assert "unit-divergence" in {f.code for f in findings}


def test_a_component_stored_differently_from_its_parent_is_reported():
    """The buttercream says refrigerate; the cake says do not.

    Storage is not inherited or intersected, and the parent declaring itself
    authoritative silences nothing -- picking one quietly is what makes a
    component containing raw egg dangerous. Built as a pair, because a count of
    one conflict in the cake breaks as soon as the cake gains a second component
    with storage of its own, which says nothing about this rule.
    """
    frosting = build_recipe(
        name="Buttercream",
        ingredients=[ingredient("butter", mass=250)],
        storage=[storage_option("refrigerated", keeps="P7D")],
    )
    parent = build_recipe(
        name="Frosted cake",
        ingredients=[ingredient("flour", mass=250)],
        components=[component("Buttercream", recipe=frosting.id)],
        steps=[
            step("#bake", consumes=["#flour"], produces=("#layers", "Baked layers")),
            step("#frost", consumes=["#layers", "#buttercream"],
                 produces=("#cake", "Frosted cake")),
        ],
        storage=[storage_option("room-temperature", keeps="P4D",
                                condition="unless the climate is very hot")],
        storage_overrides_components=True,
    )

    conflicts = [f for f in validate_recipe(parent, build_library(parent, frosting))
                 if f.code == "storage-conflict"]
    assert len(conflicts) == 1
    assert "refrigerated" in conflicts[0].message
    assert "authoritative" in conflicts[0].message


def test_form_sensitive_foods_ask_for_a_form(library):
    findings = validate_library(library)
    assert any(f.code == "missing-form" for f in findings)


# ---------------------------------------------------------------------------
# One definition of the batch
# ---------------------------------------------------------------------------


def test_a_density_finding_is_weighed_against_the_non_optional_batch():
    """The share was measured against a total nothing else called a yield.

    The denominator used to be a local sum of *every* line, so a document
    carrying a substantial optional element -- the buttercream's milk, a curry's
    optional cream -- diluted every other line's share and could push a real
    finding under the negligible threshold. The 4.5 g of cayenne below is 0.89%
    of all the lines together and 1.27% of the batch it is actually seasoning;
    only the second number is the one the resolver would call the yield, and
    only the second number reports it.
    """
    recipe = build_recipe(ingredients=[
        ingredient("beef mince", mass=350),
        ingredient("cayenne pepper", volume=(2, "tsp"),
                   food="food:cayenne-ground"),
        ingredient("cream", mass=150, optional=True),
    ])
    findings = validate_recipe(recipe, build_library(recipe))

    assert [f.code for f in findings if f.code == "low-confidence-density"] == [
        "low-confidence-density"
    ], "1.27% of the batch it seasons is not negligible"


def test_a_quibble_over_a_trace_ingredient_is_still_suppressed():
    """The other half of the rule, which the new denominator must not break.

    Nobody weighs 1 1/4 tsp of cumin. Being 30% out on 2.8 g of a 900 g curry
    changes nothing, and reporting it buries the findings that do matter --
    which is the whole reason the threshold exists.
    """
    recipe = build_recipe(ingredients=[
        ingredient("beef mince", mass=900),
        ingredient("cumin powder", volume=(1.25, "tsp"),
                   food="food:cumin-ground"),
    ])
    findings = validate_recipe(recipe, build_library(recipe))

    assert not any(f.code == "low-confidence-density" for f in findings)


# ---------------------------------------------------------------------------
# The validator asks mass.py why, rather than working it out again
# ---------------------------------------------------------------------------


def test_a_line_that_already_names_its_form_is_not_asked_for_one():
    """The qeema's ginger, which states rw:form and still has a shaky density.

    Both findings come from one low-confidence volume conversion, and which of
    them fires used to be decided here by re-fetching the Food and re-reading
    ``form_sensitive`` off it -- a second copy of a decision ``mass.py`` had
    already made, free to drift from it. Telling an author to give ``rw:form``
    when the document gives one sends them at the wrong thing.
    """
    def codes(**extra):
        recipe = build_recipe(ingredients=[
            ingredient("ginger", volume=(4, "tsp"), food="food:ginger", **extra),
        ])
        return {f.code for f in validate_recipe(recipe, build_library(recipe))}

    assert "missing-form" in codes()
    assert "low-confidence-density" in codes(form="minced")
    assert "missing-form" not in codes(form="minced")


def test_quality_windows_are_separate_from_keeps(library, cake):
    """The streusel case: safe for longer than it is good for."""
    room = next(s for s in cake.storage if s.method == "room-temperature")
    assert room.keeps.seconds > room.quality_window.seconds
    assert "moist" in room.quality_note
