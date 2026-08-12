"""The glue: setting up, unloading, and the promise that polling makes.

The load-bearing claims here are the ones a later entity will depend on without
checking. ``entry.runtime_data`` holds a typed dataclass rather than a dictionary
in ``hass.data``; the library is parsed off the event loop; a directory that has
gone missing retries rather than loading an entry with nothing behind it; and a
recipe added after setup turns up on its own, which is the only reason this
integration polls at all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN
from tests_ha.support import write_recipe


async def test_setup_puts_the_library_on_runtime_data(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """A platform reads ``entry.runtime_data.coordinator.data``. If this moves to
    ``hass.data[DOMAIN]`` every platform written against it breaks silently."""
    assert loaded_entry.state is ConfigEntryState.LOADED
    library = loaded_entry.runtime_data.coordinator.data
    assert len(library) >= 7
    assert DOMAIN not in hass.data


async def test_the_library_is_parsed_in_the_executor(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Blocking the event loop on file I/O is the commonest defect in a custom
    integration. The harness makes the loop complain about blocking calls, so this
    passing at all is the assertion; the check below is that it really did load."""
    coordinator = loaded_entry.runtime_data.coordinator
    assert coordinator.last_update_success
    assert coordinator.recipe_count == len(coordinator.data)


async def test_unloading_leaves_the_entry_unloaded(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Silver ``config-entry-unloading``: the entry has to come back out cleanly,
    because that is what a reload is made of."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_reloading_survives_a_recipe_folder_that_is_still_there(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Unload then set up again, which is what "reload" does. A coordinator that
    left something behind would fail the second setup rather than the first."""
    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_a_missing_directory_retries_instead_of_loading_the_entry(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """Bronze ``test-before-setup``. Loading the entry anyway would give the user
    an integration with no recipes and no explanation -- and the directory can
    disappear between the config flow and a restart, so this is a real state."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_RECIPES_DIR: str(tmp_path / "gone")}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_broken_document_stops_setup_rather_than_loading_the_rest(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """Refuse rather than guess (``docs/format.md`` Principle 3). Loading six of
    seven recipes and saying nothing would leave a cook looking for a recipe that
    is on disk and not in the list."""
    (recipes_dir / "broken.json").write_text('{"@type": "Recipe"', encoding="utf-8")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_RECIPES_DIR: str(recipes_dir)})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


# --- the poll -------------------------------------------------------------


async def test_an_unchanged_directory_is_not_reparsed(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``appropriate-polling`` is only defensible because the interval stats the
    files and stops. Same object back means nothing was parsed."""
    coordinator = loaded_entry.runtime_data.coordinator
    first = coordinator.data
    await coordinator.async_refresh()
    assert coordinator.data is first


async def test_a_recipe_added_after_setup_appears_without_a_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The reason the integration polls at all. Recipes are imported and enriched
    with the CLI, outside Home Assistant."""
    coordinator = loaded_entry.runtime_data.coordinator
    before = len(coordinator.data)
    document = write_recipe(recipes_dir / "later.json", name="Added later")

    await coordinator.async_refresh()

    assert len(coordinator.data) == before + 1
    assert coordinator.data.recipe(document["@id"]).name == "Added later"


async def test_a_document_broken_after_setup_goes_unavailable_not_stale(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """A library that quietly kept serving the last good parse would tell a cook
    their edit worked. ``UpdateFailed`` is what makes an entity unavailable, and it
    carries the reason with it."""
    coordinator = loaded_entry.runtime_data.coordinator
    target = next(recipes_dir.glob("*.json"))
    target.write_text("{ not json", encoding="utf-8")

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert target.name in str(coordinator.last_exception)


async def test_a_broken_document_retries_on_the_next_interval(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The fingerprint is only recorded after a successful parse. Recording it
    first would latch the failure: the file would look unchanged for ever and a
    fixed document would never be picked up."""
    coordinator = loaded_entry.runtime_data.coordinator
    target = next(recipes_dir.glob("*.json"))
    original = target.read_text(encoding="utf-8")
    target.write_text("{ not json", encoding="utf-8")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success

    target.write_text(original, encoding="utf-8")
    await coordinator.async_refresh()

    assert coordinator.last_update_success


async def test_two_refreshes_at_once_do_not_race(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The fingerprint and the load it guards are one executor job, so they cannot
    interleave. Two concurrent refreshes are otherwise how a half-written file
    becomes a cached library."""
    coordinator = loaded_entry.runtime_data.coordinator
    await asyncio.gather(coordinator.async_refresh(), coordinator.async_refresh())
    assert coordinator.last_update_success
