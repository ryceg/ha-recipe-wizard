"""Every path through the config flow, which is a Bronze rule in its own right.

The flow's whole substance is ``test-before-configure``: it loads the library
before writing an entry, so each distinct failure gets its own key and its own
message. These tests assert the *key*, because that is what selects the sentence
out of ``strings.json``; asserting the sentence would make improving the wording a
red build.

The reconfigure half is Gold ``reconfiguration-flow`` and is tested for what the
rule is actually for: not that a second form exists, but that following a moved
recipe folder keeps everything hanging off the entry -- the entity registry
entries a dashboard points at, and the cook-along position in the entry's
options. Deleting and re-adding the integration would pass a test that only
checked the new path was stored.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN
from custom_components.recipe_wizard.cursor import (
    OPTION_COOK_ALONG,
    SavedCursor,
    async_save_cursor,
)
from custom_components.recipe_wizard.loader import RecipeLibraryError
from tests_ha.support import write_recipe

_LOAD = "custom_components.recipe_wizard.config_flow.load_library"


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_the_form_offers_the_configuration_directory(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """``<config>/recipes`` is where the recipes go once installed, so it is the
    only default worth offering -- a user who followed the docs can press Submit."""
    hass.config.config_dir = str(tmp_path)
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    defaults = result["data_schema"]({})
    assert defaults[CONF_RECIPES_DIR] == str(tmp_path / "recipes")


async def test_a_readable_directory_creates_the_entry(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """The happy path, end to end: the flow loads the corpus and the entry it
    writes then sets up."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(recipes_dir)}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Recipe Wizard"
    assert result["data"] == {CONF_RECIPES_DIR: str(recipes_dir)}


async def test_a_relative_path_is_read_against_the_configuration_directory(
    hass: HomeAssistant, recipes_dir: Path, tmp_path: Path, custom_integration: None
):
    """"recipes" is the obvious thing to type. Read against the process's working
    directory it would land somewhere no user has ever looked, so it is stored
    absolute and resolved against the configuration directory."""
    hass.config.config_dir = str(tmp_path)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: "recipes"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_RECIPES_DIR: str(recipes_dir)}


async def test_surrounding_whitespace_is_not_a_setup_failure(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """A path pasted out of a terminal arrives with a newline on it."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: f"  {recipes_dir}  "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_RECIPES_DIR: str(recipes_dir)}


async def test_a_missing_directory_is_reported_and_the_form_recovers(
    hass: HomeAssistant, recipes_dir: Path, tmp_path: Path, custom_integration: None
):
    """The commonest mistake, and the one the form has to be able to recover from
    without the user starting again. The path goes into ``{detail}`` so the message
    can name what was not found."""
    missing = tmp_path / "typo"
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(missing)}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "directory_not_found"}
    assert str(missing) in result["description_placeholders"]["detail"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(recipes_dir)}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_directory_with_no_recipes_is_reported(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """Accepting an empty directory would produce an integration with nothing in
    it and no explanation of why."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(empty)}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_recipes"}


async def test_a_broken_document_is_reported_by_name(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """With 200 recipes, "one of them is broken" is not actionable and the file
    name is."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    write_recipe(recipes / "fine.json", name="Fine cake")
    (recipes / "half-written.json").write_text('{"@type": "Recipe"', encoding="utf-8")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(recipes)}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_recipe"}
    assert "half-written.json" in result["description_placeholders"]["detail"]


async def test_a_recipe_with_no_identity_is_reported_rather_than_indexed(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """Identity lives in the ``@id``. The library raises rather than inventing one,
    and the flow has to phrase that instead of propagating a ``LibraryError``."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "nameless.json").write_text(
        json.dumps({"@type": "Recipe", "name": "No identity"}), encoding="utf-8"
    )

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(recipes)}
    )

    assert result["errors"] == {"base": "invalid_recipe"}


async def test_an_unreadable_food_bank_gets_its_own_message(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """A broken install is a different instruction from a broken recipe, so it
    cannot share a key. Raised through the seam the flow actually catches."""
    with patch(_LOAD, side_effect=RecipeLibraryError("foods_unreadable", "bad bank")):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RECIPES_DIR: str(recipes_dir)}
        )

    assert result["errors"] == {"base": "foods_unreadable"}
    assert result["description_placeholders"]["detail"] == "bad bank"


async def test_an_unexpected_error_does_not_leave_the_user_with_a_dead_form(
    hass: HomeAssistant, recipes_dir: Path, custom_integration: None
):
    """Anything the library can raise that this integration has not thought about
    yet still has to come back as a form with a message, not a traceback in a log
    the user is not reading."""
    with patch(_LOAD, side_effect=RuntimeError("something new")):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_RECIPES_DIR: str(recipes_dir)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


# --- reconfiguring -------------------------------------------------------


def moved(recipes_dir: Path, tmp_path: Path) -> Path:
    """The corpus, somewhere else. What a user does with a bigger disk."""
    target = tmp_path / "moved-recipes"
    shutil.copytree(recipes_dir, target)
    return target


async def test_the_reconfigure_form_opens_on_the_folder_in_use(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The user step suggests ``<config>/recipes`` because a new user has nowhere
    else to have put them. Reconfiguring is an edit to a string that already
    exists, and offering the default again would make the commonest case --
    correcting a typo in a long path -- a retype."""
    result = await loaded_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    defaults = result["data_schema"]({})
    assert defaults[CONF_RECIPES_DIR] == loaded_entry.data[CONF_RECIPES_DIR]


async def test_reconfiguring_moves_the_entry_to_the_new_folder(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path, tmp_path: Path
):
    """The whole point of the rule: a moved folder should be a form, not a
    delete-and-re-add."""
    elsewhere = moved(recipes_dir, tmp_path)
    result = await loaded_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(elsewhere)}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data[CONF_RECIPES_DIR] == str(elsewhere)
    assert loaded_entry.runtime_data.coordinator.recipes_dir == elsewhere


async def test_reconfiguring_keeps_the_entities_a_dashboard_points_at(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path, tmp_path: Path
):
    """``entity.py`` builds every unique id out of ``entry_id``, and the reason it
    does is this: a cook who moves their recipes must not lose the history, the
    cards and the automations naming these entities. Re-adding the integration
    would give them a second set with ``_2`` on the end."""
    registry = er.async_get(hass)
    before = {
        entity.entity_id: entity.unique_id
        for entity in registry.entities.get_entries_for_config_entry_id(
            loaded_entry.entry_id
        )
    }
    assert before

    elsewhere = moved(recipes_dir, tmp_path)
    result = await loaded_entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(elsewhere)}
    )
    await hass.async_block_till_done()

    after = {
        entity.entity_id: entity.unique_id
        for entity in registry.entities.get_entries_for_config_entry_id(
            loaded_entry.entry_id
        )
    }
    assert after == before


async def test_reconfiguring_leaves_a_cook_along_on_the_step_it_was_on(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path, tmp_path: Path
):
    """``data_updates`` rather than ``data``, and nothing touching ``options``.
    The cursor lives in the entry's options so that a restart during the
    brownies' three-hour chill comes back to the chill; moving the folder in the
    meantime must not be worse than a restart."""
    async_save_cursor(
        hass,
        loaded_entry,
        SavedCursor(
            recipe_id="urn:recipe:rte/peanut-butter-stuffed-brownies", batches=2
        ).moved_to(11),
    )
    await hass.async_block_till_done()

    elsewhere = moved(recipes_dir, tmp_path)
    result = await loaded_entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(elsewhere)}
    )
    await hass.async_block_till_done()

    saved = loaded_entry.options[OPTION_COOK_ALONG]
    assert saved["recipe_id"] == "urn:recipe:rte/peanut-butter-stuffed-brownies"
    assert saved["cursor"] == 11
    assert saved["batches"] == 2


async def test_a_new_folder_that_will_not_load_changes_nothing(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, tmp_path: Path
):
    """The same test-before-configure promise, on the step where breaking it is
    worse: a stored path to nowhere would take a working integration down at the
    next restart, and the cook would have no form left to correct it in."""
    was = loaded_entry.data[CONF_RECIPES_DIR]
    result = await loaded_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(tmp_path / "typo")}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "directory_not_found"}
    assert loaded_entry.data[CONF_RECIPES_DIR] == was


async def test_the_reconfigure_form_recovers_after_an_error(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path, tmp_path: Path
):
    """Both steps share ``_async_checked_directory``, so both have to recover the
    same way -- a failed attempt leaves the form up, not the flow dead."""
    elsewhere = moved(recipes_dir, tmp_path)
    result = await loaded_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(tmp_path / "typo")}
    )
    assert result["errors"] == {"base": "directory_not_found"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECIPES_DIR: str(elsewhere)}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert loaded_entry.data[CONF_RECIPES_DIR] == str(elsewhere)


async def test_reconfiguring_is_not_refused_as_a_second_entry(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``single_config_entry`` aborts a *second* flow, and a reconfigure flow of
    the entry that already exists is not one. Home Assistant exempts
    ``SOURCE_RECONFIGURE`` from that check; if it ever stopped doing so, this
    integration would silently lose its only way to be reconfigured."""
    result = await loaded_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM


async def test_a_second_entry_is_refused(
    hass: HomeAssistant, config_entry: MockConfigEntry, custom_integration: None
):
    """Bronze ``unique-config-entry``. There is one recipe library, so a second
    entry could only ever be a duplicate; ``single_config_entry`` in the manifest
    is what makes Home Assistant say so before the form is even shown."""
    config_entry.add_to_hass(hass)

    result = await _start(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
