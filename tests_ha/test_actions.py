"""The four actions, and the cursor they move.

Two things are being defended here. The first is that a cook is told the truth
about their own mistake: a recipe that is not there is named, an ambiguous name is
not guessed at, and "no cook-along is running" is not reported as "unknown
action". The second is that the cursor is *written down* -- ``entry.runtime_data``
is gone on restart, and a cook who restarts Home Assistant during the brownies'
three-hour chill should come back to the chill.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.actions import (
    SERVICE_NEXT_STEP,
    SERVICE_PREVIOUS_STEP,
    SERVICE_START_COOK_ALONG,
    SERVICE_STOP_COOK_ALONG,
)
from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN
from custom_components.recipe_wizard.cursor import saved_cursor
from tests.support import ingredient, step
from tests_ha.support import write_recipe

STEP = "sensor.recipe_wizard_current_step"
BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"


async def call(hass: HomeAssistant, service: str, **data) -> None:
    """Call one of ours and wait for the sensors to catch up."""
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    await hass.async_block_till_done()


@pytest.fixture
async def cooking(hass: HomeAssistant, loaded_entry: MockConfigEntry):
    """A doubled tray of brownies, on its first step."""
    await call(hass, SERVICE_START_COOK_ALONG, recipe_id="brownies", batches=2)
    return loaded_entry


# --- the four --------------------------------------------------------------


async def test_starting_puts_the_cursor_on_the_first_step(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """A cook-along that started on step 2, or on nothing, is not a cook-along."""
    assert hass.states.get(STEP).state == "1/16"
    saved = saved_cursor(cooking)
    assert (saved.recipe_id, saved.batches, saved.cursor) == (BROWNIES, 2.0, 0)
    assert saved.started_at is not None


async def test_a_partial_name_finds_the_recipe_a_cook_meant(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """Nobody types urn:recipe:rte/peanut-butter-stuffed-brownies into a service
    call. The command-line tool has always taken "brownies"."""
    assert saved_cursor(cooking).recipe_id == BROWNIES


async def test_next_and_previous_move_one_step(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """The two buttons a cook presses with the back of a knuckle."""
    await call(hass, SERVICE_NEXT_STEP)
    await call(hass, SERVICE_NEXT_STEP)
    assert hass.states.get(STEP).state == "3/16"

    await call(hass, SERVICE_PREVIOUS_STEP)
    assert hass.states.get(STEP).state == "2/16"


async def test_stopping_leaves_the_kitchen_idle(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """Stop has to clear the recipe, not only the position: a cursor of 0 with a
    recipe still attached is step one of something nobody is making."""
    await call(hass, SERVICE_STOP_COOK_ALONG)
    assert hass.states.get(STEP).state == "idle"
    assert saved_cursor(cooking).recipe_id is None


async def test_stopping_twice_is_not_an_error(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """A dashboard button pressed twice is not a mistake worth a toast."""
    await call(hass, SERVICE_STOP_COOK_ALONG)
    await call(hass, SERVICE_STOP_COOK_ALONG)
    assert hass.states.get(STEP).state == "idle"


# --- what a cook is told ---------------------------------------------------


async def test_a_recipe_that_is_not_there_is_named(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """"No recipe found" sends a cook to the logs. Quoting what they typed sends
    them to the spelling, which is where the problem is."""
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, SERVICE_START_COOK_ALONG, recipe_id="lasagne")
    assert "lasagne" in str(err.value)
    assert hass.states.get(STEP).state == "idle"


async def test_a_name_matching_several_recipes_is_refused_not_guessed(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """"buttercream" is three recipes in this corpus. Starting the wrong one is
    worse than being asked again (``docs/format.md`` Principle 3)."""
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, SERVICE_START_COOK_ALONG, recipe_id="buttercream")
    assert "vanilla-buttercream" in str(err.value)
    assert hass.states.get(STEP).state == "idle"


async def test_moving_with_nothing_on_the_go_says_so(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Not an exception from three frames down about a cursor of None."""
    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_NEXT_STEP)
    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_PREVIOUS_STEP)


async def test_going_back_from_the_first_step_says_where_the_cook_is(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """Clamping silently would leave a cook tapping Back and watching nothing
    happen, unsure whether the button or the recipe is broken."""
    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_PREVIOUS_STEP)
    assert hass.states.get(STEP).state == "1/16"


async def test_the_last_step_advances_to_finished_and_no_further(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """A cursor that ran past the end would leave the sensor reading "finished"
    while Back walked through positions the cook was never on."""
    for _ in range(16):
        await call(hass, SERVICE_NEXT_STEP)
    assert hass.states.get(STEP).state == "finished"

    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_NEXT_STEP)

    await call(hass, SERVICE_PREVIOUS_STEP)
    assert hass.states.get(STEP).state == "16/16"


async def test_a_batch_a_recipe_cannot_make_warns_rather_than_refusing(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """``resolve_dish`` is not strict on purpose -- a dish is built to be shown --
    so a tenth of a batch of something with a 500 g minimum resolves, with the
    reason attached. Turning that into a refused call would override a decision the
    library documents; dropping the warning would let a cook start creaming butter
    for a batch their mixer cannot see."""
    document = write_recipe(
        recipes_dir / "big-batch-only.json",
        name="Big batch only",
        ingredients=[ingredient("flour", mass=1000)],
        steps=[step("#mix", consumes=["#flour"], produces=("#dough", "Dough"))],
        batch_constraints=(500, None, "the mixer cannot see less than this"),
    )
    await loaded_entry.runtime_data.coordinator.async_refresh()

    await call(hass, SERVICE_START_COOK_ALONG, recipe_id=document["@id"], batches=0.1)

    state = hass.states.get(STEP)
    assert state.state == "1/1"
    assert any("mixer" in warning for warning in state.attributes["warnings"])


async def test_a_recipe_that_will_not_resolve_is_an_error_not_a_bad_request(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The other side of the same rule. A step graph that cannot be put in an order
    -- here two steps each waiting on the other's product -- is a broken document,
    not something the cook typed wrong, so it is a plain ``HomeAssistantError``
    and the cook is not sent looking for their own mistake."""
    document = write_recipe(
        recipes_dir / "cyclic.json",
        name="Impossible thing",
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#a", consumes=["#flour", "#b-out"], produces=("#a-out", "A")),
            step("#b", consumes=["#a-out"], produces=("#b-out", "B")),
        ],
    )
    await loaded_entry.runtime_data.coordinator.async_refresh()

    with pytest.raises(HomeAssistantError) as err:
        await call(hass, SERVICE_START_COOK_ALONG, recipe_id=document["@id"])
    assert not isinstance(err.value, ServiceValidationError)


async def test_the_batch_count_has_to_be_a_real_batch(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Nought batches would resolve a dish of nothing and read as a bug rather
    than as a request. The schema refuses it before any file is opened."""
    with pytest.raises(vol.Invalid):
        await call(hass, SERVICE_START_COOK_ALONG, recipe_id="brownies", batches=0)


# --- Bronze action-setup ---------------------------------------------------


async def test_the_actions_exist_before_any_entry_is_loaded(
    hass: HomeAssistant, custom_integration: None
):
    """Bronze ``action-setup``. Registered in ``async_setup_entry`` they would
    vanish with a failed entry, and an automation calling one would report
    "unknown action" -- which sends the user looking for a typo in their own YAML
    instead of at the integration that is not loaded."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    for service in (
        SERVICE_START_COOK_ALONG,
        SERVICE_NEXT_STEP,
        SERVICE_PREVIOUS_STEP,
        SERVICE_STOP_COOK_ALONG,
    ):
        assert hass.services.has_service(DOMAIN, service)


async def test_every_action_is_described_for_the_ui(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """An action registered in code but missing from services.yaml, or described in
    services.yaml but not in strings.json, still *works* -- it just shows up in the
    UI as a bare domain and a slug with no way to guess what it wants. hassfest
    catches that in CI; nothing catches it on the desk."""
    descriptions = (await async_get_all_descriptions(hass))[DOMAIN]
    assert set(descriptions) == {
        SERVICE_START_COOK_ALONG,
        SERVICE_NEXT_STEP,
        SERVICE_PREVIOUS_STEP,
        SERVICE_STOP_COOK_ALONG,
    }
    assert set(descriptions[SERVICE_START_COOK_ALONG]["fields"]) == {
        "recipe_id",
        "batches",
    }

    translations = await async_get_translations(hass, "en", "services", {DOMAIN})
    for service, description in descriptions.items():
        prefix = f"component.{DOMAIN}.services.{service}"
        assert translations[f"{prefix}.name"]
        assert translations[f"{prefix}.description"]
        for field in description["fields"]:
            assert translations[f"{prefix}.fields.{field}.name"]
            assert translations[f"{prefix}.fields.{field}.description"]


async def test_an_action_with_no_loaded_entry_says_the_entry_is_not_loaded(
    hass: HomeAssistant, tmp_path: Path, custom_integration: None
):
    """The whole point of registering early: the error names the real problem."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_RECIPES_DIR: str(tmp_path / "gone")}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY

    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_NEXT_STEP)


# --- surviving a restart ---------------------------------------------------


async def test_the_cursor_survives_a_restart(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """``entry.runtime_data`` is gone on restart, so the cursor cannot live only
    there. A cook who restarts Home Assistant during the brownies' three-hour
    chill has to come back to the chill, not to step one."""
    await call(hass, SERVICE_NEXT_STEP)
    await call(hass, SERVICE_NEXT_STEP)
    assert hass.states.get(STEP).state == "3/16"

    assert await hass.config_entries.async_unload(cooking.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(cooking.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(STEP)
    assert state.state == "3/16"
    assert state.attributes["batches"] == 2.0


async def test_the_saved_cursor_is_written_to_the_entry_not_held_in_memory(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """What makes the test above work, asserted directly: the cursor is in the
    entry's options, which Home Assistant persists itself. Anything else would
    need a store of its own and a migration to go with it."""
    await call(hass, SERVICE_NEXT_STEP)
    assert cooking.options["cook_along"] == {
        "recipe_id": BROWNIES,
        "batches": 2.0,
        "cursor": 1,
        "started_at": saved_cursor(cooking).started_at.isoformat(),
    }
