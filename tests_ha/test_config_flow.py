"""Every path through the config flow, which is a Bronze rule in its own right.

The flow's whole substance is ``test-before-configure``: it loads the library
before writing an entry, so each distinct failure gets its own key and its own
message. These tests assert the *key*, because that is what selects the sentence
out of ``strings.json``; asserting the sentence would make improving the wording a
red build.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN
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
