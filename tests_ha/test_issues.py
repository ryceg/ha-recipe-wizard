"""Repair cards for broken recipes, and the far harder promise not to nag.

The failure mode this file is really named after is the second one. Raising a
card per finding is easy and would make the repairs panel useless within a week:
a level-0 scrape is *supposed* to read as a scrape, a source that says "a splash
of milk" is *supposed* to leave a mass unresolved, and a user who dismisses those
learns to dismiss the one that means their frosting will never appear in a
cook-along. So the shipped corpus -- which has three warnings and no errors -- is
the premise of the first test here, and it must raise nothing at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN
from custom_components.recipe_wizard.issues import ISSUE_PREFIX
from tests.support import ingredient, step
from tests_ha.support import write_recipe

#: Patched where the coordinator looks it up, not where it is defined.
_VALIDATE = "custom_components.recipe_wizard.coordinator.error_findings"

#: A level-2 document whose step consumes something no row and no step provides.
#: ``dangling-consume`` is an *error* and names the step, which is the pair of
#: facts every assertion below rests on.
GHOST = {
    "name": "Ghost cake",
    "enrichment_level": 2,
    "ingredients": [ingredient("flour", mass=200)],
    "steps": [
        step(
            "#mix",
            consumes=["#flour", "#nothing-like-this"],
            produces=("#result", "Result"),
        )
    ],
}
GHOST_ID = "urn:recipe:test/ghost-cake"

#: The same shape with nothing missing, for the fix-it-and-the-card-goes case.
MENDED = {
    "name": "Ghost cake",
    "enrichment_level": 2,
    "ingredients": [ingredient("flour", mass=200)],
    "steps": [step("#mix", consumes=["#flour"], produces=("#result", "Result"))],
}

#: A level-2 document with a spare ingredient: one ``unused-ingredient``
#: *warning* and no error. The document a cook is still working on.
SPARE = {
    "name": "Spare salt",
    "enrichment_level": 2,
    "ingredients": [ingredient("flour", mass=200), ingredient("salt", mass=5)],
    "steps": [step("#mix", consumes=["#flour"], produces=("#result", "Result"))],
}


def issue(hass: HomeAssistant, recipe_id: str) -> ir.IssueEntry | None:
    """The card for one document, if there is one."""
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_PREFIX}{recipe_id}")


def ours(hass: HomeAssistant) -> set[str]:
    """Every issue id this integration currently holds."""
    return {
        issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN
    }


@pytest.fixture
async def with_a_broken_recipe(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
) -> MockConfigEntry:
    """The corpus plus one document the validator reports an error on."""
    write_recipe(recipes_dir / "ghost.json", **GHOST)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_RECIPES_DIR: str(recipes_dir)})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_shipped_corpus_raises_nothing_despite_its_warnings(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The rule this module exists to keep. Every recipe in ``recipes/`` carries
    warnings and infos -- a butter row whose mass and volume columns disagree, a
    cocoa measured by volume -- and every one of them is the correct outcome for
    a source that says what it says. A card for any of them would be a card
    nobody can ever clear."""
    assert ours(hass) == set()


async def test_a_document_with_errors_raises_one_card_naming_the_node(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry
):
    """``Finding.node`` is canonical under the graph's id rule precisely so a
    fixer can be sent at one place in the file. A card that said "this recipe has
    a problem" would send them re-reading the whole document."""
    card = issue(hass, GHOST_ID)

    assert card is not None
    assert card.translation_placeholders is not None
    assert card.translation_placeholders["name"] == "Ghost cake"
    assert card.translation_placeholders["recipe"] == GHOST_ID
    assert "#mix" in card.translation_placeholders["findings"]
    assert "dangling-consume" in card.translation_placeholders["findings"]


async def test_the_card_offers_no_button_it_could_not_honour(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry
):
    """``is_fixable`` is false because the fix is an edit to a JSON document the
    integration only ever reads -- a promise made in the removal instructions and
    in ``docs/format.md``. A Fix button would have to write to the user's recipes
    or apologise."""
    card = issue(hass, GHOST_ID)

    assert card is not None
    assert not card.is_fixable
    assert card.severity is ir.IssueSeverity.WARNING


async def test_a_warning_only_document_beside_a_broken_one_still_raises_nothing(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """The level is the *producer's* decision, and this is what reading it rather
    than re-deciding it buys: two documents, one card, and the one that is merely
    unfinished is left alone."""
    write_recipe(recipes_dir / "ghost.json", **GHOST)
    write_recipe(recipes_dir / "spare.json", **SPARE)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_RECIPES_DIR: str(recipes_dir)})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ours(hass) == {f"{ISSUE_PREFIX}{GHOST_ID}"}


async def test_two_errors_in_one_document_are_one_card(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """One card per document, not per finding. A half-enriched recipe is one
    afternoon's work on one file, and five cards would report five problems."""
    write_recipe(
        recipes_dir / "ghost.json",
        name="Ghost cake",
        enrichment_level=2,
        ingredients=[ingredient("flour", mass=200)],
        steps=[
            step("#mix", consumes=["#flour", "#nothing-like-this"], produces="#batter"),
            step("#bake", consumes=["#batter", "#nor-this"], produces=("#result", "R")),
        ],
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_RECIPES_DIR: str(recipes_dir)})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ours(hass) == {f"{ISSUE_PREFIX}{GHOST_ID}"}
    card = issue(hass, GHOST_ID)
    assert card is not None
    assert card.translation_placeholders is not None
    findings = card.translation_placeholders["findings"]
    assert "#mix" in findings and "#bake" in findings


async def test_the_card_goes_when_the_recipe_is_fixed(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry, recipes_dir: Path
):
    """A repair that outlives its cause is how a panel stops being read. The poll
    picks the edit up on its own, which is the same fifteen minutes a new recipe
    takes to appear."""
    assert issue(hass, GHOST_ID) is not None

    write_recipe(recipes_dir / "ghost.json", **MENDED)
    await with_a_broken_recipe.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert issue(hass, GHOST_ID) is None


async def test_a_deleted_recipe_takes_its_card_with_it(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry, recipes_dir: Path
):
    """The other way a document stops being wrong. The withdrawal is driven by
    what the validator says now, not by remembering what it said before, so a
    file that is simply gone is handled by the same three lines."""
    (recipes_dir / "ghost.json").unlink()
    await with_a_broken_recipe.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert ours(hass) == set()


async def test_removing_the_integration_takes_its_cards_with_it(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry
):
    """Nothing in Home Assistant sweeps an integration's issues when it is
    deleted, so ``async_remove_entry`` has to. A card about a recipe belonging to
    an integration that is no longer installed is a puzzle with no way to act on
    it."""
    assert issue(hass, GHOST_ID) is not None

    assert await hass.config_entries.async_remove(with_a_broken_recipe.entry_id)
    await hass.async_block_till_done()

    assert ours(hass) == set()


async def test_a_reload_does_not_leave_a_stale_card_behind(
    hass: HomeAssistant, with_a_broken_recipe: MockConfigEntry, recipes_dir: Path
):
    """A reload builds a new coordinator with no memory of what the last one
    raised. Remembering the live cards in the process rather than reading them
    back off the registry would strand this one for ever."""
    write_recipe(recipes_dir / "ghost.json", **MENDED)

    assert await hass.config_entries.async_reload(with_a_broken_recipe.entry_id)
    await hass.async_block_till_done()

    assert ours(hass) == set()


async def test_nothing_is_validated_when_no_document_has_moved(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Validating two hundred documents every quarter of an hour would undo what
    ``appropriate-polling`` is defensible on. The identity check is exact: the
    coordinator hands its own object back when no mtime moved."""
    coordinator = loaded_entry.runtime_data.coordinator
    with patch(_VALIDATE) as validate:
        await coordinator.async_refresh()

    validate.assert_not_called()


async def test_a_changed_document_is_validated_again(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The other half of the same claim: skipping the validation when nothing
    moved is only safe if it really does run when something did."""
    coordinator = loaded_entry.runtime_data.coordinator
    write_recipe(recipes_dir / "later.json", name="Added later")

    with patch(_VALIDATE, return_value={}) as validate:
        await coordinator.async_refresh()

    validate.assert_called_once()
