"""Validation, including the conflicts the real recipes actually contain."""

from conftest import CHOCOLATE_BC
from support import (
    build_library,
    build_recipe,
    component,
    ingredient,
    portion,
    step,
    storage_option,
)

from custom_components.recipe_wizard.core import validate_library, validate_recipe
from custom_components.recipe_wizard.core.model import ConsumeRef, Portion
from custom_components.recipe_wizard.core.validate import ERROR


def test_the_library_has_no_errors(library):
    """The one assertion whose subject really is the corpus.

    Every recipe on disk resolves, schedules and links up. This is the contract
    the enrichment skill iterates against, and it is the only thing a new
    recipe is allowed to break.
    """
    errors = [f for f in validate_library(library) if f.level == ERROR]
    assert errors == [], "\n".join(str(f) for f in errors)


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
