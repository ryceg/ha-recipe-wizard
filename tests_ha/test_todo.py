"""The shopping list as a to-do list: what the cook must not lose.

Two things this suite is really about. First, that a number the library refused to
state never appears on an item -- the whole of ``core/shopping.py`` is one
argument for refusing, and a surface is the only place that refusal can be
quietly undone. Second, that nothing the user did to the list is destroyed by the
list being rebuilt from the recipes, which happens every time the folder changes.

Premises are built with ``tests/support.py`` where the subject is a shape the
corpus does not contain -- an unweighed line, a cited component, one sub-recipe
used twice. The doubled vanilla cake is used directly, because "230 g of butter
cut into cubes merges with the buttercream's 450 g into 680 g to buy" is an
assertion about the real data.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.todo import TodoItemStatus, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import DOMAIN
from custom_components.recipe_wizard.todo import SERVICE_SET_SHOPPING_LIST
from tests.support import component, ingredient
from tests_ha.support import write_recipe

ENTITY_ID = "todo.recipe_wizard_shopping_list"
CAKE = "urn:recipe:rte/vanilla-cake"
BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"


# --- helpers ---------------------------------------------------------------


async def set_list(hass: HomeAssistant, recipe: str, **extra: Any) -> None:
    """Point the list at a recipe, the way an automation would."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SHOPPING_LIST,
        {"entity_id": ENTITY_ID, "recipe": recipe, **extra},
        blocking=True,
    )
    await hass.async_block_till_done()


async def items(hass: HomeAssistant) -> list[dict[str, Any]]:
    """The list, read through ``todo.get_items`` rather than off the entity.

    The service is what an automation and the panel see, so a test reading it
    cannot pass against an entity whose items never reach either.
    """
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": ENTITY_ID},
        blocking=True,
        return_response=True,
    )
    return response[ENTITY_ID]["items"]


async def item_saying(hass: HomeAssistant, fragment: str) -> dict[str, Any]:
    """The one item whose summary contains ``fragment``."""
    matches = [i for i in await items(hass) if fragment in i["summary"]]
    assert len(matches) == 1, f"{fragment!r} matched {[m['summary'] for m in matches]}"
    return matches[0]


async def tick(hass: HomeAssistant, uid: str, summary: str, **extra: Any) -> None:
    """Tick an item off exactly as the to-do panel does.

    The panel sends the whole item back on every update -- the summary and the
    description alongside the new status -- so a test that sent only ``status``
    would not exercise the path the user actually takes.
    """
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": ENTITY_ID,
            "item": uid,
            "rename": summary,
            "status": TodoItemStatus.COMPLETED,
            **extra,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A coordinator poll, which is what rebuilds the computed lines."""
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def status_of(item: dict[str, Any]) -> str:
    return item["status"]


# --- identity --------------------------------------------------------------


async def test_the_unique_id_survives_the_recipe_folder_being_renamed(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The recipe directory is the one thing the user configures. A unique id
    derived from it would orphan every tick and every dashboard card the day they
    tidied their folders."""
    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity is not None
    assert entity.unique_id == f"{loaded_entry.entry_id}_shopping_list"


async def test_the_entities_group_under_one_service_not_a_pretend_device(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """There is no hardware here, and ``quality_scale.yaml`` exempts every device
    rule for that reason -- but a device entry is the only thing that groups
    entities in the UI, so there is exactly one and it is marked a service."""
    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity is not None and entity.device_id is not None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert device.name == "Recipe Wizard"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.identifiers == {(DOMAIN, loaded_entry.entry_id)}


async def test_the_list_can_be_ticked_added_to_and_cleared_but_not_reordered(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """A read-only list is much less use in a kitchen, so the mutations are
    supported. Reordering is not: the line order is the recipe's own ingredient
    order, and storing a permutation of it would be invalidated by the next edit
    to the recipe."""
    features = hass.states.get(ENTITY_ID).attributes["supported_features"]
    assert features & TodoListEntityFeature.CREATE_TODO_ITEM
    assert features & TodoListEntityFeature.UPDATE_TODO_ITEM
    assert features & TodoListEntityFeature.DELETE_TODO_ITEM
    assert features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    assert not features & TodoListEntityFeature.MOVE_TODO_ITEM


async def test_the_list_exists_before_a_recipe_is_chosen(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """One list, not one per recipe -- two hundred todo entities of computed state
    is what ``docs/format.md`` § Scope rules out. So the entity has to exist
    before anything has selected a dish, or an automation could not add to it."""
    assert hass.states.get(ENTITY_ID).state == "0"
    assert await items(hass) == []
    assert "recipe" not in hass.states.get(ENTITY_ID).attributes


# --- what an item says -----------------------------------------------------


async def test_a_merged_line_is_one_thing_to_buy_and_two_to_have_ready(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The doubled cake, which is the premise the whole shopping module was
    written against: 230 g of butter cut into cubes for the cake and 450 g for
    the buttercream are one 680 g line to buy. If the description lost the
    breakdown, the merge would have thrown away the mise-en-place."""
    await set_list(hass, CAKE, batches=2)

    butter = await item_saying(hass, "unsalted butter")

    assert butter["summary"] == "unsalted butter: 680 g"
    assert butter["description"] == (
        "230 g, cut into cubes - My Very Best Vanilla Cake\n450 g - Vanilla buttercream"
    )


async def test_a_single_contribution_carries_its_preparation_and_not_itself(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """``ShoppingList.report()``'s rule, kept: repeating "500 g - Vanilla cake"
    under "plain flour: 500 g" is length without information, but "sifted" is the
    thing the cook has to do before they start."""
    await set_list(hass, CAKE, batches=2)

    assert (await item_saying(hass, "soft icing sugar"))["description"] == "sifted"
    assert "description" not in await item_saying(hass, "plain flour")


async def test_a_line_with_no_total_never_shows_a_number_it_does_not_have(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """``total_g`` is ``None`` the moment one contributor could not be weighed,
    and ``measured_g`` is a floor rather than a total. An item summary built from
    the parts instead of from ``describe()`` would present 200 g as the answer."""
    document = write_recipe(
        recipes_dir / "tahini.json",
        name="Tahini test",
        ingredients=[
            ingredient("tahini", id="#weighed", mass=200, food="food:tahini"),
            ingredient(
                "tahini", id="#poured", volume=(2, "tbsp"), food="food:tahini"
            ),
        ],
    )
    await refresh(hass, loaded_entry)
    await set_list(hass, document["@id"])

    tahini = await item_saying(hass, "tahini")

    assert tahini["summary"] == "tahini: at least 200 g, plus 1 line with no weight"
    assert tahini["description"] == "200 g - Tahini test\n2 tbsp - Tahini test"


async def test_a_scraped_line_with_no_weight_at_all_says_so(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """A level-0 document is a list of strings, and it must still be shoppable.
    "0 g milk" is the same false statement as a guess, in a cheaper disguise."""
    document = write_recipe(
        recipes_dir / "scraped.json",
        name="Scraped",
        ingredients=["a splash of milk"],
    )
    await refresh(hass, loaded_entry)
    await set_list(hass, document["@id"])

    assert (await item_saying(hass, "milk"))["summary"] == (
        "a splash of milk: no weight given"
    )


async def test_a_cited_component_is_a_thing_to_find_and_never_a_quantity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """``docs/format.md`` § ComponentUse: a cited component is excluded from the
    quantities *rather than silently contributing nothing*. It has to be on the
    list, and there is no number this integration is allowed to invent for it."""
    document = write_recipe(
        recipes_dir / "cited.json",
        name="With a citation",
        components=[
            component("Chicken stock", citation={"name": "Dinner", "rw:page": 308})
        ],
    )
    await refresh(hass, loaded_entry)
    await set_list(hass, document["@id"])

    stock = await item_saying(hass, "Chicken stock")

    assert stock["summary"] == (
        "Chicken stock: not in the library - see Dinner, p.308"
    )
    assert stock["description"] == "For With a citation"
    assert not re.search(r"\d+\s*(g|ml)\b", stock["summary"])


async def test_leaving_the_optional_parts_out_drops_the_component(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The qeema without the mint yogurt. An optional *component* is skipped; an
    optional ingredient inside a part you are making is not, because its food may
    be one another part needs -- so the salt shrinks rather than vanishing."""
    await set_list(hass, "urn:recipe:rte/qeema", include_optional=False)

    summaries = [i["summary"] for i in await items(hass)]

    assert not any("plain yogurt" in s for s in summaries)
    assert "cooking salt: 2.2 g" in summaries


# --- what happens to a tick ------------------------------------------------


async def test_a_tick_survives_the_recipes_being_read_again(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The list is regenerated from the recipes on every poll. A tick stored
    against the item's position, or not stored at all, would disappear the first
    time the cook saved a recipe while standing in the shop."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")
    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    write_recipe(recipes_dir / "unrelated.json", name="Something else")
    await refresh(hass, loaded_entry)

    assert status_of(await item_saying(hass, "unsalted butter")) == "completed"


async def test_a_tick_survives_a_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Reloading the entry is what a restart is, as far as stored state goes. A
    trip that resets when Home Assistant updates itself mid-shop is a trip the
    cook redoes from memory."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")
    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert status_of(await item_saying(hass, "unsalted butter")) == "completed"
    assert hass.states.get(ENTITY_ID).attributes["batches"] == 2.0


async def test_switching_recipe_does_not_carry_a_tick_across(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Butter ticked off for the cake is not butter bought for the brownies. Both
    lines key on the same food, which is exactly why the trip has to be cleared
    when the target changes rather than merged over the new list."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")
    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    await set_list(hass, BROWNIES)

    assert status_of(await item_saying(hass, "unsalted butter")) == "needs_action"


async def test_setting_the_same_target_again_does_not_wipe_a_half_done_trip(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """An automation that sets the list on a schedule, or a second tap on a
    dashboard button, must not be the thing that loses twenty ticks."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")
    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    await set_list(hass, CAKE, batches=2)

    assert status_of(await item_saying(hass, "unsalted butter")) == "completed"


async def test_one_sub_recipe_used_twice_is_two_things_to_buy(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """An unlinked row merges with nothing, including another spelling of itself,
    so a parent using one sub-recipe twice gets two identical lines. They agree on
    recipe and ingredient id, so a uid built from those alone would tick both at
    once and buy half of what the dish needs."""
    write_recipe(
        recipes_dir / "sub.json",
        id="urn:recipe:test/sub",
        name="Sub",
        ingredients=["a pinch of something"],
    )
    parent = write_recipe(
        recipes_dir / "parent.json",
        name="Parent",
        ingredients=[ingredient("flour", mass=100)],
        components=[
            component("First use", id="#one", recipe="urn:recipe:test/sub"),
            component("Second use", id="#two", recipe="urn:recipe:test/sub"),
        ],
    )
    await refresh(hass, loaded_entry)
    await set_list(hass, parent["@id"])

    pinches = [i for i in await items(hass) if "a pinch" in i["summary"]]
    assert len(pinches) == 2
    await tick(hass, pinches[0]["uid"], pinches[0]["summary"])

    after = [i for i in await items(hass) if "a pinch" in i["summary"]]
    assert [status_of(i) for i in after] == ["completed", "needs_action"]


# --- what happens to something the user typed ------------------------------


async def test_something_the_user_typed_survives_a_refresh_and_a_restart(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """Bin bags are not derived from anything, so nothing that rebuilds the
    derived list is allowed to touch them. This is the rule the whole storage
    layer exists for."""
    await set_list(hass, CAKE, batches=2)
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": ENTITY_ID, "item": "bin bags", "description": "the big ones"},
        blocking=True,
    )
    await hass.async_block_till_done()

    write_recipe(recipes_dir / "unrelated.json", name="Something else")
    await refresh(hass, loaded_entry)
    assert await item_saying(hass, "bin bags")

    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert (await item_saying(hass, "bin bags"))["description"] == "the big ones"


async def test_something_the_user_typed_survives_changing_the_recipe(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Starting a new trip clears the ticks, which belonged to the old one. It
    must not clear what the cook typed, which belonged to them."""
    await set_list(hass, CAKE, batches=2)
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": ENTITY_ID, "item": "bin bags"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await set_list(hass, BROWNIES)

    assert await item_saying(hass, "bin bags")


async def test_a_typed_item_can_be_renamed(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The other half of refusing to rename a computed line: an item whose words
    came from the user is the one item whose words the user may change."""
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": ENTITY_ID, "item": "bin bags"},
        blocking=True,
    )
    await hass.async_block_till_done()
    typed = await item_saying(hass, "bin bags")

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": ENTITY_ID, "item": typed["uid"], "rename": "bin liners"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert await item_saying(hass, "bin liners")


async def test_ticking_from_the_panel_is_not_mistaken_for_a_rename(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The to-do panel sends the summary and the description back with every
    status change. Refusing any update that carries a summary would make a
    computed line impossible to tick from the UI at all, which is the one thing
    the list is for."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")

    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    assert status_of(await item_saying(hass, "unsalted butter")) == "completed"


async def test_renaming_a_computed_line_is_refused_rather_than_lost(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The words come out of the recipe, so the next poll would overwrite them.
    Accepting the edit and discarding it silently is the failure this prevents --
    refusing leaves the cook's text in front of them with a reason."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "todo",
            "update_item",
            {
                "entity_id": ENTITY_ID,
                "item": butter["uid"],
                "rename": "salted butter, 2 blocks",
            },
            blocking=True,
        )

    assert (await item_saying(hass, "unsalted butter"))["summary"] == butter["summary"]


async def test_clearing_the_ticked_lines_keeps_them_off_only_until_the_next_trip(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """"Remove completed items" is how a cook clears the shelf they have already
    filled, and it has to work on a list most of whose items are computed. A
    computed line cannot really be deleted -- the recipe still calls for it -- so
    it is dropped from this trip and comes back with the next one."""
    await set_list(hass, CAKE, batches=2)
    butter = await item_saying(hass, "unsalted butter")
    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    await hass.services.async_call(
        "todo", "remove_completed_items", {"entity_id": ENTITY_ID}, blocking=True
    )
    await hass.async_block_till_done()
    assert not [i for i in await items(hass) if "unsalted butter" in i["summary"]]

    write_recipe(recipes_dir / "unrelated.json", name="Something else")
    await refresh(hass, loaded_entry)
    assert not [i for i in await items(hass) if "unsalted butter" in i["summary"]]

    await set_list(hass, BROWNIES)
    assert await item_saying(hass, "unsalted butter")


# --- choosing the recipe ---------------------------------------------------


async def test_a_recipe_can_be_named_by_part_of_its_name(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The same three rules the CLI matches on, so an automation writer can type
    what they type at the command line rather than a urn."""
    await set_list(hass, "Qeema")

    assert hass.states.get(ENTITY_ID).attributes["recipe_id"] == "urn:recipe:rte/qeema"


async def test_a_name_matching_nothing_is_reported_and_changes_nothing(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """Silver ``action-exceptions``. Storing the target and failing on the next
    poll would leave the cook with an unavailable list and no idea why."""
    await set_list(hass, CAKE, batches=2)

    with pytest.raises(ServiceValidationError):
        await set_list(hass, "sourdough")

    assert hass.states.get(ENTITY_ID).attributes["recipe_id"] == CAKE


async def test_a_name_matching_several_recipes_names_them(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The corpus has three buttercreams. Telling the caller only that it was
    ambiguous leaves them guessing which three."""
    with pytest.raises(ServiceValidationError, match="buttercream"):
        await set_list(hass, "buttercream")


async def test_a_recipe_that_will_not_resolve_is_refused_when_it_is_chosen(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """A variant whose base is not in the library parses fine and resolves to
    nothing. Checking at the moment the cook chooses it is worth an executor hop,
    because that is when they are looking at the answer."""
    document = write_recipe(
        recipes_dir / "orphan.json",
        name="Orphan variant",
        variant_of="urn:recipe:test/nowhere",
    )
    await refresh(hass, loaded_entry)

    with pytest.raises(ServiceValidationError):
        await set_list(hass, document["@id"])


async def test_a_recipe_deleted_underneath_a_trip_goes_unavailable_not_stale(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, recipes_dir: Path
):
    """The same argument ``test_init`` makes about the library, one level down: a
    list that kept showing the last good answer would tell the cook their edit
    worked. Unavailable says neither that nor "nothing to buy"."""
    document = write_recipe(recipes_dir / "temporary.json", name="Temporary")
    await refresh(hass, loaded_entry)
    await set_list(hass, document["@id"])
    assert hass.states.get(ENTITY_ID).state != "unavailable"

    (recipes_dir / "temporary.json").unlink()
    await refresh(hass, loaded_entry)

    assert hass.states.get(ENTITY_ID).state == "unavailable"


async def test_the_state_counts_what_is_left_to_buy(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
):
    """The entity state is the platform's own: how many items still need doing.
    It is the number a dashboard badge shows, so it has to move when a line is
    ticked."""
    await set_list(hass, CAKE, batches=2)
    before = int(hass.states.get(ENTITY_ID).state)
    butter = await item_saying(hass, "unsalted butter")

    await tick(hass, butter["uid"], butter["summary"], description=butter["description"])

    assert int(hass.states.get(ENTITY_ID).state) == before - 1
