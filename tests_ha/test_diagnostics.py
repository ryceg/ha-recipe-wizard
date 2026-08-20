"""The diagnostics dump, and the one thing it must never contain.

A diagnostics download is attached to a public issue by a user who has not read
it. There are no credentials here to redact, so the usual test -- "assert the
password came out as ``**REDACTED**``" -- has no subject. The subject is the
recipes: the user's own writing, frequently somebody else's copyright, and the
thing a dump of this integration would be full of if nobody had thought about it.
So the assertions below are mostly negative, and they are run against the real
corpus rather than a built premise, because "no step text" is only worth
asserting against text that actually exists.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR
from custom_components.recipe_wizard.cursor import SavedCursor, async_save_cursor
from custom_components.recipe_wizard.diagnostics import (
    async_get_config_entry_diagnostics,
)

BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"


async def dump(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """The diagnostics for an entry, as the download would hold them."""
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_the_dump_is_json_and_nothing_in_it_needs_redacting(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """It has to survive being serialised -- Home Assistant writes it out as JSON
    -- and it has to hold nothing that a redaction pass would be needed for. The
    two are one test because the serialised form is what the second one reads."""
    text = json.dumps(await dump(hass, loaded_entry))

    assert "REDACTED" not in text


async def test_no_step_text_and_no_finding_message_reaches_the_dump(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The line this module draws. A finding's ``code`` and ``node`` are the
    machine-readable half and are what an issue report needs; its ``message`` is
    prose built by interpolating strings out of the document, and several steps
    in the corpus are a paragraph of somebody's recipe."""
    from custom_components.recipe_wizard.core.validate import validate_library

    library = loaded_entry.runtime_data.coordinator.data
    text = json.dumps(await dump(hass, loaded_entry))

    for recipe in library:
        for recipe_step in recipe.steps:
            assert recipe_step.text
            assert recipe_step.text not in text
    for finding in validate_library(library):
        assert finding.message
        assert finding.message not in text


async def test_no_quantity_or_preparation_reaches_the_dump(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The other half of the same rule. Note what is deliberately *not* asserted:
    an ingredient's name cannot be kept out, because semantic ids are made of it
    -- ``#salt-flakes`` contains "salt". The id is in scope and the row is not,
    which is what "how much, prepared how" being absent actually means."""
    library = loaded_entry.runtime_data.coordinator.data
    text = json.dumps(await dump(hass, loaded_entry))

    for recipe in library:
        for row in recipe.ingredients:
            if row.preparation:
                assert row.preparation not in text
            if row.original_text:
                assert row.original_text not in text


async def test_the_dump_says_where_the_recipes_are_and_how_far_they_are_lifted(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """What the file is actually for. Most reports about a recipe "not working"
    are a level-0 scrape being asked to do a level-3 thing, and the histogram
    says so without anybody having to name a recipe."""
    data = await dump(hass, loaded_entry)

    assert data["entry"]["recipes_dir"] == loaded_entry.data[CONF_RECIPES_DIR]
    assert data["library"]["recipes"] == len(
        loaded_entry.runtime_data.coordinator.data.recipes
    )
    assert data["library"]["foods"] > 0
    assert sum(data["library"]["enrichment_levels"].values()) == data["library"][
        "recipes"
    ]
    assert data["coordinator"]["last_update_success"] is True


async def test_every_finding_is_named_by_code_and_node(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The corpus carries warnings and infos on purpose, and they are exactly
    what a maintainer wants to see -- which node, which stable code, how many of
    each."""
    data = await dump(hass, loaded_entry)

    assert data["findings"]["detail"]
    assert data["findings"]["by_level"]["warning"] > 0
    codes = {finding["code"] for finding in data["findings"]["detail"]}
    assert codes == set(data["findings"]["by_code"])
    assert all(
        set(finding) == {"level", "code", "recipe", "node"}
        for finding in data["findings"]["detail"]
    )


async def test_a_cook_along_appears_as_a_position_not_as_a_step(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Which recipe and how far in is what makes a bug report about the cook-along
    diagnosable. Resolving it into the step's words would put the recipe back into
    a file the whole design is about keeping it out of."""
    async_save_cursor(
        hass, loaded_entry, SavedCursor(recipe_id=BROWNIES, batches=2).moved_to(11)
    )
    await hass.async_block_till_done()

    data = await dump(hass, loaded_entry)

    assert data["cook_along"]["running"] is True
    assert data["cook_along"]["recipe_id"] == BROWNIES
    assert data["cook_along"]["cursor"] == 11
    assert data["cook_along"]["batches"] == 2
    assert "step" not in data["cook_along"]


async def test_the_dump_reads_the_library_off_the_event_loop(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``validate_library`` walks every document and builds a mass table for each.
    The harness makes the loop complain about blocking calls, so this passing at
    all is the assertion; the check is that it really did validate."""
    data = await dump(hass, loaded_entry)

    assert isinstance(data["findings"]["detail"], list)
