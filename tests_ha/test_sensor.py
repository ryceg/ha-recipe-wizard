"""The cook-along on a screen, and the ways it could quietly lie.

The failure modes these are named after are all ones the surface would survive
looking healthy: a state that silently stops updating because a step's text grew
past 255 characters, a doubled tray showing the single-batch dollop, a frosting
step labelled with the cake's name, a timer presented as a promise when the
recipe says the doneness decides, and file I/O in a property -- which does not
look like anything at all until the event loop stalls in someone's kitchen.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import DOMAIN
from custom_components.recipe_wizard.cursor import (
    OPTION_COOK_ALONG,
    SavedCursor,
    async_save_cursor,
)
from tests.support import component, ingredient, step
from tests_ha.support import write_recipe

STEP = "sensor.recipe_wizard_current_step"
TIMER = "sensor.recipe_wizard_step_timer"

BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"
CAKE = "urn:recipe:rte/vanilla-cake"
COFFEE_BUTTERCREAM = "urn:recipe:local/coffee-buttercream"


async def start(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    recipe_id: str,
    *,
    cursor: int = 0,
    batches: float = 1.0,
) -> None:
    """Put the cursor somewhere, the way an action does, and let it settle."""
    async_save_cursor(
        hass,
        entry,
        SavedCursor(recipe_id=recipe_id, batches=batches).moved_to(cursor),
    )
    await hass.async_block_till_done()


@pytest.fixture
async def cooking(hass: HomeAssistant, loaded_entry: MockConfigEntry):
    """The brownies, doubled, at the dollop step -- the corpus's hardest line."""
    await start(hass, loaded_entry, BROWNIES, cursor=11, batches=2)
    return loaded_entry


# --- what the state is -----------------------------------------------------


async def test_the_state_is_a_position_not_the_step_text(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """A state over 255 characters is dropped by the state machine, so a surface
    built on step text works until the first long step and then stops updating
    with nothing on screen to say so. The text goes in an attribute, which has no
    such limit."""
    state = hass.states.get(STEP)
    assert state.state == "12/16"
    assert len(state.state) <= 255
    assert state.attributes["step"].startswith("Dollop and drizzle")


async def test_the_state_is_idle_before_a_cook_along_starts(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """An empty kitchen is a state, not a fault. "unknown" would send a cook to
    the logs to find out what broke."""
    assert hass.states.get(STEP).state == "idle"
    assert hass.states.get(TIMER).state == "unknown"


async def test_the_state_is_finished_past_the_last_step(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``CookAlong.at`` returns None for both "not started" and "finished", so the
    integration has to tell them apart from the cursor it is holding -- otherwise
    the end of a bake reads the same as never having started one."""
    await start(hass, loaded_entry, BROWNIES, cursor=16)
    assert hass.states.get(STEP).state == "finished"


async def test_a_cursor_left_beyond_a_shortened_recipe_reads_as_finished(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """Recipes are edited outside Home Assistant while a cook-along is saved
    against them. Crashing the platform because a document lost a step would take
    the whole library down over one stale integer."""
    await start(hass, loaded_entry, BROWNIES, cursor=15)
    assert hass.states.get(STEP).state == "16/16"

    document = write_recipe(
        recipes_dir / "peanut-butter-stuffed-brownies.json",
        id=BROWNIES,
        name="Peanut Butter Stuffed Brownies",
        ingredients=[ingredient("flour", mass=250)],
        steps=[step("#mix", consumes=["#flour"], produces=("#batter", "Batter"))],
    )
    assert document["@id"] == BROWNIES
    await loaded_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(STEP).state == "finished"


async def test_a_recipe_deleted_mid_cook_is_unknown_rather_than_idle(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """"idle" would be a claim the integration cannot make -- the cook is still
    standing in front of a half-made tray. Unknown, with the reason attached, is
    the truth."""
    await start(hass, loaded_entry, BROWNIES, cursor=3)
    (recipes_dir / "peanut-butter-stuffed-brownies.json").unlink()
    await loaded_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(STEP)
    assert state.state == "unknown"
    assert BROWNIES in state.attributes["problem"]


# --- what the cook needs ---------------------------------------------------


async def test_a_doubled_tray_asks_for_four_tablespoons_not_two(
    hass: HomeAssistant, cooking: MockConfigEntry
):
    """The bug the library was built to stop, one layer up: the portion has to be
    scaled with the mass. A screen reading "dollop 2 tbsp" beside 500 g of peanut
    butter is what sent a cook to the recipe page instead."""
    needs = hass.states.get(STEP).attributes["needs"]
    assert "smooth peanut butter: 4 tbsp (of 500 g)" in needs


async def test_a_partial_row_names_the_thing_before_the_share(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """"the rest plain yogurt" is not English. The library's ``describe()`` is what
    fixes it and the sensor must not reformat around it."""
    await start(hass, loaded_entry, BROWNIES, cursor=10)
    assert "Brownie batter: the rest" in hass.states.get(STEP).attributes["needs"]


async def test_a_component_step_is_labelled_with_the_component(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """A cook halfway through the cake's frosting is reading the buttercream's
    page. Labelling it "My Very Best Vanilla Cake" would tell them the wrong bowl
    is in front of them."""
    await start(hass, loaded_entry, CAKE, cursor=18)
    attributes = hass.states.get(STEP).attributes
    assert attributes["recipe"] == "Vanilla buttercream"
    assert attributes["recipe_id"] == "urn:recipe:rte/vanilla-buttercream"
    assert attributes["dish"] == "My Very Best Vanilla Cake"
    assert attributes["step_number"] == 19
    assert attributes["of"] == 21


async def test_batches_reach_the_component_not_just_the_root(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Doubling propagates as a plain factor. A doubled cake with a single-batch
    frosting is half a cake's worth of frosting, discovered at assembly."""
    await start(hass, loaded_entry, CAKE, cursor=19, batches=2)
    needs = hass.states.get(STEP).attributes["needs"]
    assert any("1000 g" in line for line in needs), needs


async def test_a_pure_patch_list_still_has_steps(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The coffee buttercream has no steps and no ingredients of its own. Reading
    the document off disk instead of the effective recipe gives an empty
    cook-along, which is the mistake ``core/cookalong.py`` exists to stop -- and
    the substituted flavouring has to be the one on the bench, not the vanilla the
    base recipe names."""
    await start(hass, loaded_entry, COFFEE_BUTTERCREAM, cursor=2)
    state = hass.states.get(STEP)
    assert state.state == "3/3"
    assert state.attributes["recipe"] == "Coffee Buttercream"
    assert any(
        "espresso" in line.lower() for line in state.attributes["needs"]
    ), state.attributes["needs"]


async def test_a_cited_component_is_named_so_the_cook_fetches_the_book(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """A component that is a book citation is never expanded and is left off the
    shopping list on purpose, so the cook-along is the last place that can say
    "go and get Dinner p.308"."""
    document = write_recipe(
        recipes_dir / "cited.json",
        name="Beef with a bought sauce",
        components=[
            component("Sauce from Dinner p.308", citation={"rw:pages": "308"})
        ],
    )
    await loaded_entry.runtime_data.coordinator.async_refresh()
    await start(hass, loaded_entry, document["@id"])

    attributes = hass.states.get(STEP).attributes
    assert attributes["cited_components"] == ["Sauce from Dinner p.308"]


async def test_a_pause_point_is_reported_so_a_cook_can_stop(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The brownies' freeze is a sanctioned stopping point, and "can I do the rest
    tomorrow?" deserves a straight answer rather than a guess from the timer."""
    await start(hass, loaded_entry, BROWNIES, cursor=2)
    attributes = hass.states.get(STEP).attributes
    assert attributes["may_pause_after"] is True
    assert attributes["attention"] == "unattended"


# --- the timer -------------------------------------------------------------


async def test_the_bake_timer_carries_the_doneness_that_overrules_it(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """A timer showing 32 minutes and nothing else tells the cook the oven decides.
    The state is authoritative and the time is an estimate, and the phrasing has to
    carry that round the right way."""
    await start(hass, loaded_entry, BROWNIES, cursor=12)
    attributes = hass.states.get(TIMER).attributes
    assert attributes["timer"] == (
        "32 min, then check: edges firmish, centre still jiggling"
    )
    assert attributes["doneness"] == "edges firmish, centre still jiggling"
    assert attributes["is_estimate"] is True


async def test_the_timer_estimate_is_the_arrival_time_plus_the_stated_time(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``device_class: timestamp`` is the whole reason this entity exists -- a
    dashboard renders it as a countdown and an automation can compare it. It has
    to be the step's own stated time, not the plan's window, which includes waiting
    for other steps."""
    await start(hass, loaded_entry, BROWNIES, cursor=12)
    started = dt_util.parse_datetime(
        loaded_entry.options[OPTION_COOK_ALONG]["started_at"]
    )
    state = hass.states.get(TIMER)
    # A timestamp state is written to the second, so the comparison is too.
    assert dt_util.parse_datetime(state.state) == (
        started + timedelta(minutes=32)
    ).replace(microsecond=0)


async def test_a_range_keeps_its_upper_end_separate(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The peanut butter freezes for two to three hours. Averaging them would
    invent a number no recipe states, and dropping the upper end would tell a cook
    the tray is ready an hour early."""
    await start(hass, loaded_entry, BROWNIES, cursor=2)
    state = hass.states.get(TIMER)
    started = state.attributes["started_at"]
    assert dt_util.parse_datetime(state.state) == (
        started + timedelta(hours=2)
    ).replace(microsecond=0)
    assert state.attributes["latest_estimate"] == started + timedelta(hours=3)


async def test_a_step_with_no_stated_time_gets_no_timestamp(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The planner assumes a minute for a step that states none, so the graph has a
    length. Starting a 60-second timer on that assumption is a lie a cook could
    act on."""
    await start(hass, loaded_entry, BROWNIES, cursor=14)
    assert hass.states.get(STEP).attributes["timer"] is None
    assert hass.states.get(TIMER).state == "unknown"


async def test_a_timer_that_starts_on_an_event_gets_no_timestamp(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """"once the water returns to the boil" is not the moment the cook reached the
    step, and nothing here can see the pan. The phrase is reported instead."""
    document = write_recipe(
        recipes_dir / "boiled.json",
        name="Boiled thing",
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step(
                "#boil",
                consumes=["#flour"],
                produces=("#done", "Done"),
                duration=10,
                timer_starts_when="the water returns to the boil",
            )
        ],
    )
    await loaded_entry.runtime_data.coordinator.async_refresh()
    await start(hass, loaded_entry, document["@id"])

    assert hass.states.get(TIMER).state == "unknown"
    attributes = hass.states.get(TIMER).attributes
    assert attributes["timer_starts_when"] == "the water returns to the boil"
    assert hass.states.get(STEP).attributes["timer_seconds"] == 600


# --- the entity contract ---------------------------------------------------


async def test_both_entities_have_a_unique_id_that_survives_a_moved_folder(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Bronze ``entity-unique-id``. Keying on the recipe directory would make
    "I moved my recipes to a bigger disk" look like a new set of entities, and
    every dashboard card and history graph would point at the old ones."""
    registry = er.async_get(hass)
    entry_id = loaded_entry.entry_id
    unique_ids = {
        registry.async_get(entity_id).unique_id for entity_id in (STEP, TIMER)
    }
    assert unique_ids == {f"{entry_id}_current_step", f"{entry_id}_step_timer"}
    assert not any(str(loaded_entry.data) in uid for uid in unique_ids)


async def test_both_entities_group_under_one_service_device(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Nothing here is a device, but a device entry is what groups entities in the
    UI, so there is one and it says what it really is."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    device_ids = {entities.async_get(entity_id).device_id for entity_id in (STEP, TIMER)}
    assert len(device_ids) == 1
    device = devices.async_get(device_ids.pop())
    assert device.name == "Recipe Wizard"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.identifiers == {(DOMAIN, loaded_entry.entry_id)}


async def test_reading_the_state_does_not_touch_the_library(
    hass: HomeAssistant, cooking: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
):
    """Home Assistant calls ``native_value`` on every state write and
    ``cook_along()`` reads files. Resolving in a property is how a custom
    integration blocks the event loop in a kitchen and not in a test."""
    import custom_components.recipe_wizard.cursor as cursor_module

    calls: list[str] = []
    real = cursor_module.cook_along

    def counted(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(cursor_module, "cook_along", counted)

    for _ in range(5):
        # A forced update is what a state write looks like from the inside: Home
        # Assistant asks the entity for its value and its attributes again.
        await async_update_entity(hass, STEP)
    assert hass.states.get(STEP).state == "12/16"
    assert calls == []


async def test_the_dish_is_resolved_once_for_a_cursor_that_only_moves(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
):
    """Tapping Next walks a dish that has not changed. Re-resolving the tree on
    every tap is work no cook asked for, on a device that is also running the rest
    of their house."""
    import custom_components.recipe_wizard.cursor as cursor_module

    calls: list[str] = []
    real = cursor_module.cook_along

    def counted(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(cursor_module, "cook_along", counted)

    await start(hass, loaded_entry, BROWNIES, cursor=0)
    for position in range(1, 5):
        await start(hass, loaded_entry, BROWNIES, cursor=position)

    assert calls == [BROWNIES]
    assert hass.states.get(STEP).state == "5/16"


async def test_a_library_that_will_not_load_makes_the_sensors_unavailable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """Silver ``entity-unavailable``. A sensor that kept showing the last good step
    would tell a cook their edit worked."""
    await start(hass, loaded_entry, BROWNIES, cursor=1)
    next(recipes_dir.glob("*.json")).write_text("{ not json", encoding="utf-8")
    await loaded_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(STEP).state == "unavailable"
    assert hass.states.get(TIMER).state == "unavailable"
