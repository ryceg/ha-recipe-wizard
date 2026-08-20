"""``icons.json`` against what actually exists, in both directions.

Gold ``icon-translations`` is the sort of rule that is trivially satisfied and
then quietly stops being true: a third platform arrives, or a fifth action, and
nothing anywhere goes red -- the entity simply renders with Home Assistant's
generic dot and nobody notices for a release. So these tests do not check that
the file exists or that it holds sensible icons. They enumerate the entities Home
Assistant actually registered and the actions it actually accepted, and demand
that the file and the running integration name exactly the same set.

The reverse direction matters as much: an icon left behind for a deleted action
is a line nobody dares remove because nobody can tell what it was for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import DOMAIN

ICONS = Path(__file__).resolve().parents[1] / "custom_components" / "recipe_wizard"


@pytest.fixture
def icons() -> dict:
    """The shipped file, read the way Home Assistant reads it."""
    return json.loads((ICONS / "icons.json").read_text(encoding="utf-8"))


def test_every_icon_is_an_mdi_name(icons: dict):
    """Home Assistant will not render anything else, and an icon that does not
    render is indistinguishable from the one nobody wrote."""
    values = [
        icon
        for platform in icons["entity"].values()
        for entry in platform.values()
        for icon in [entry["default"], *entry.get("state", {}).values()]
    ]
    values += [action["service"] for action in icons["services"].values()]

    assert values
    assert all(icon.startswith("mdi:") for icon in values)


async def test_every_entity_that_exists_has_an_icon(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, icons: dict
):
    """Taken from the entity registry rather than from a list written here, so a
    platform added without an icon fails this rather than being remembered."""
    registered = {
        (entity.domain, entity.translation_key)
        for entity in er.async_get(hass).entities.get_entries_for_config_entry_id(
            loaded_entry.entry_id
        )
    }
    described = {
        (platform, key)
        for platform, entries in icons["entity"].items()
        for key in entries
    }

    assert registered
    assert registered == described


async def test_every_action_that_exists_has_an_icon(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, icons: dict
):
    """All five: the four cook-along actions registered in ``async_setup`` and
    the entity service the todo platform registers. They are registered in two
    different places and there is one file, which is the whole point of the rule
    saying "every action"."""
    registered = set(hass.services.async_services_for_domain(DOMAIN))

    assert len(registered) == 5
    assert registered == set(icons["services"])


async def test_the_icons_file_names_nothing_that_is_not_there(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, icons: dict
):
    """The direction that rots silently. Both sets above are already equalities,
    so this asserts the thing they are equalities *for*: the file describes the
    integration as it is, not as it once was."""
    entity_keys = {
        key for entries in icons["entity"].values() for key in entries
    }
    strings = json.loads((ICONS / "strings.json").read_text(encoding="utf-8"))
    named_in_strings = {
        key for entries in strings["entity"].values() for key in entries
    }

    assert entity_keys == named_in_strings
    assert set(icons["services"]) == set(strings["services"])
