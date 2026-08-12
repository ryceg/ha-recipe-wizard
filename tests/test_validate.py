"""Validation, including the conflicts the real recipes actually contain."""

import pytest

from conftest import BROWNIES, CAKE, CHOCOLATE_BC

from custom_components.recipe_wizard.core import validate_library, validate_recipe
from custom_components.recipe_wizard.core.model import ConsumeRef, Portion
from custom_components.recipe_wizard.core.validate import ERROR


def test_the_library_has_no_errors(library):
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


def test_an_unaccounted_portion_is_reported(library):
    """The brownies' salt flakes are "divided" and only half is ever used.

    Recorded as the source states it rather than guessed at, so the warning is
    correct and stays.
    """
    findings = validate_library(library)
    salt = [f for f in findings if f.code == "portions-under-whole"]
    assert len(salt) == 1
    assert "#salt-flakes" in salt[0].message


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


def test_the_storage_conflict_between_cake_and_frosting_is_reported(library, cake):
    """The buttercream says refrigerate; the cake says do not."""
    conflicts = [f for f in validate_recipe(cake, library)
                 if f.code == "storage-conflict"]
    assert len(conflicts) == 1
    assert "refrigerated" in conflicts[0].message
    assert "authoritative" in conflicts[0].message


def test_form_sensitive_foods_ask_for_a_form(library):
    findings = validate_library(library)
    assert any(f.code == "missing-form" for f in findings)


def test_quality_windows_are_separate_from_keeps(library, cake):
    """The streusel case: safe for longer than it is good for."""
    room = next(s for s in cake.storage if s.method == "room-temperature")
    assert room.keeps.seconds > room.quality_window.seconds
    assert "moist" in room.quality_note
