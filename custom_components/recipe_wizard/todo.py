"""The shopping list, as a to-do list you can tick off.

``core/shopping.py`` already does all of the work and says so in its own last
paragraph: ``describe()`` is the buy line, ``breakdown()`` is the mise-en-place,
and nothing in the library knows the word "todo". This module is the translation
into Home Assistant's vocabulary and the three decisions that translation forces.

**One item per shopping line, and the summary is ``describe()`` verbatim.** Not
``f"{line.name} {line.total_g} g"``, ever. ``total_g`` is deliberately ``None``
the moment any contributor could not be weighed, and a surface that reached for
``measured_g`` to have a number to show would undo the one judgement the library
module exists to make. So a complete line reads *"unsalted butter: 680 g"* and an
incomplete one reads *"plain flour: at least 500 g, plus 1 line with no weight"*,
and this module never formats a mass itself.

**The description is the merge.** Doubling ``recipes/vanilla-cake.json`` merges
230 g of butter *cut into cubes* for the cake with the buttercream's 450 g into
one 680 g line to buy, and the whole reason that merge is allowed is that
"cubed" survives it. So a line with more than one contribution carries
``breakdown()`` as its description; a line with one carries just its
preparation, because "500 g - My Very Best Vanilla Cake" under "plain flour:
500 g" is length without information. That is the same rule
``ShoppingList.report()`` argues for the CLI, and following it rather than
re-litigating it keeps the two surfaces saying the same thing.

**Cited components are on the list and carry no quantity.** ``docs/format.md`` is
explicit that a component pointing at a book is *excluded from the quantities
rather than silently contributing nothing*, so ``ShoppingList.to_find`` becomes
items too -- *"Chicken stock: not in the library - see Dinner, p.308"*, with the
dish that wants it in the description. There is no number in that sentence and
this module does not add one.

## What happens to a tick

The list is regenerated from the recipes every time the coordinator sees the
directory change, so anything the user did to it has to live somewhere else and
be re-applied. Two kinds of user input, two different rules, both in one
``Store`` keyed on the config entry:

* **Ticks and dropped lines are the trip.** They are keyed on a uid derived from
  the *food*, not the position, so re-reading the recipes cannot move them (see
  ``_LineItem``). They survive a refresh and a restart, and they are cleared only
  when the user themselves points the list at a different recipe or batch size --
  a tick against the cake means nothing against the qeema. Setting the *same*
  target again is a no-op, so an automation that calls the action on a schedule
  cannot wipe a trip that is half done.
* **Items the user typed are theirs.** "Bin bags" is not derived from anything,
  survives every refresh, every restart and every change of target, and goes away
  only when it is deleted. Nothing in this module ever destroys one.

That leaves one case where a write cannot be honoured: renaming a computed line,
or editing its description. Those words come out of the recipe and the next
refresh would silently overwrite them, so they are **refused** with a message
rather than accepted and lost -- except when the new value equals the old one,
which is what the to-do panel sends back every time you tick a box.

Reordering is not supported. The line order is the root recipe's own ingredient
order followed by each component's new foods, which ``core/shopping.py`` argues
is information; supporting a move would mean storing a permutation that the next
edit to a recipe invalidates.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import RecipeLibraryCoordinator, RecipeWizardConfigEntry
from .core.library import Library
from .core.model import Recipe
from .core.shopping import ShoppingLine, ShoppingList, shopping_list
from .entity import RecipeWizardEntity

_LOGGER = logging.getLogger(__name__)

#: Silver ``parallel-updates``. Every read is served out of the library the
#: coordinator has already loaded, so there is nothing to serialise.
PARALLEL_UPDATES = 0

#: The entity service that says what the list is for. Named ``set_shopping_list``
#: rather than anything shorter so it cannot collide with the cook-along actions.
SERVICE_SET_SHOPPING_LIST = "set_shopping_list"
ATTR_RECIPE = "recipe"
ATTR_BATCHES = "batches"
ATTR_INCLUDE_OPTIONAL = "include_optional"

SET_SHOPPING_LIST_SCHEMA = {
    vol.Required(ATTR_RECIPE): cv.string,
    # Half a batch is a real thing to shop for; zero and negatives are not, and
    # the library would raise on them further in than a user could follow.
    vol.Optional(ATTR_BATCHES, default=1.0): vol.All(
        vol.Coerce(float), vol.Range(min=0, min_included=False)
    ),
    vol.Optional(ATTR_INCLUDE_OPTIONAL, default=True): cv.boolean,
}

STORAGE_VERSION = 1

#: The uid prefix that tells a typed item from a computed one without a lookup,
#: which is what ``async_delete_todo_items`` needs to know before it decides
#: whether "delete" means gone or dropped. The computed uids are prefixed too --
#: ``line:food:``, ``line:row:``, ``find:`` -- so the three can never collide.
_MANUAL = "manual:"


@dataclass(frozen=True, slots=True)
class ShoppingTarget:
    """What the list is currently for. The only thing there is to select.

    A todo entity per recipe would put two hundred lists in the state machine to
    make one of them useful, which ``docs/format.md`` § Scope rules out for the
    same reason it rules out an entity per step. So there is one list and this
    says which dish it is showing.
    """

    recipe_id: str
    batches: float = 1.0
    include_optional: bool = True


@dataclass(frozen=True, slots=True)
class _LineItem:
    """A computed item, before the trip's ticks are laid over it.

    ``uid`` has to survive the list being rebuilt from disk, so it is derived
    from what the line *is* rather than where it sits: the food id where there is
    one, and the contributing recipe's own ingredient id where there is not --
    ``core/shopping.py`` guarantees an unlinked row is exactly one contribution.
    The one case that needs more than that is one sub-recipe used twice by the
    same parent, which produces two lines agreeing on both; ``_computed_items``
    numbers the repeats, because they are two separate things to buy.
    """

    uid: str
    summary: str
    description: str | None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecipeWizardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One list per entry, and the action that points it at a recipe.

    The action is an *entity* service rather than one registered in
    ``async_setup``: it does nothing but change one entity's list, so letting
    Home Assistant resolve the entity from the call target is both less code and
    a better error than looking the entry up by hand. Bronze ``action-setup``
    exempts entity services for exactly this reason -- they cannot outlive the
    entity they act on, so there is no "unknown action" to be misled by.
    """
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.shopping_list"
    )
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_SET_SHOPPING_LIST,
        SET_SHOPPING_LIST_SCHEMA,
        "async_set_shopping_list",
    )
    async_add_entities([ShoppingListTodoEntity(entry.runtime_data.coordinator, store)])


class ShoppingListTodoEntity(RecipeWizardEntity, TodoListEntity):
    """The shopping list for whatever the cook is shopping for.

    Read-only would have been much simpler and much less use: the point of a
    shopping list is ticking things off it while standing in a shop. So the
    mutations are all supported and the module docstring above says where each
    kind of change is kept and why none of them can be lost.
    """

    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        # Declared because the to-do panel sends the description back with every
        # update, so an entity that refused the field could not be ticked from
        # the UI at all. On a typed item it is honoured; on a computed one an
        # actual change is refused, see ``async_update_todo_item``.
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self, coordinator: RecipeLibraryCoordinator, store: Store[dict[str, Any]]
    ) -> None:
        """Empty until ``async_added_to_hass`` has read the store off disk."""
        super().__init__(coordinator, "shopping_list")
        self._store = store
        self._target: ShoppingTarget | None = None
        self._label: str | None = None
        self._computed: list[_LineItem] = []
        self._completed: set[str] = set()
        self._dropped: set[str] = set()
        self._manual: list[TodoItem] = []
        self._resolves = True
        self._rebuilding = asyncio.Lock()
        self._attr_todo_items = []

    # -- availability and identity -------------------------------------------

    @property
    def available(self) -> bool:
        """Unavailable when the library will not load *or* the dish will not resolve.

        The second half matters because the target is validated when it is set,
        so a resolution that fails later means a recipe was edited underneath a
        trip in progress. Showing the last good list would tell the cook their
        edit worked (``tests_ha/test_init.py`` makes the same argument about the
        library); showing an empty one would say there is nothing to buy. Going
        unavailable says neither, and the reason is in the log.
        """
        return super().available and self._resolves

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the list is for. Not the list -- that is what the items are.

        A dashboard showing a to-do card needs a heading, and "which recipe is
        this" is the one thing the items themselves cannot say.
        """
        if self._target is None:
            return {}
        return {
            "recipe": self._label,
            "recipe_id": self._target.recipe_id,
            "batches": self._target.batches,
            "include_optional": self._target.include_optional,
        }

    # -- the computed half ---------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Subscribe to the coordinator, read the trip, then build the list."""
        await super().async_added_to_hass()
        await self._async_load()
        await self._async_rebuild()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Resolving a dish is far too much work for a state write.

        ``shopping_list()`` resolves the whole tree and reads no files, but it is
        seconds of arithmetic at two hundred recipes and it must not run on the
        event loop, so the refresh schedules the rebuild instead of doing it. The
        task is owned by the config entry so an unload cancels it rather than
        leaving it to write state into a removed entity.
        """
        self.coordinator.config_entry.async_create_task(
            self.hass,
            self._async_rebuild(),
            name=f"{DOMAIN} shopping list rebuild",
        )

    async def _async_rebuild(self) -> None:
        """Recompute the lines, keep the ticks, write the state."""
        async with self._rebuilding:
            library = self.coordinator.data
            target = self._target
            if library is None or target is None:
                self._computed = []
                self._label = None
                self._resolves = True
            else:
                try:
                    listing = await self._async_resolve(library, target)
                # ``LibraryError`` is a ``LookupError`` and
                # ``BatchConstraintError`` a ``ValueError``, so these two cover
                # everything the resolver raises by design.
                except (LookupError, ValueError) as err:
                    # Not raised: the coordinator is fine and the other platforms
                    # are fine. Only this list is broken, and ``available`` is how
                    # one entity says so.
                    _LOGGER.error(
                        "Cannot build a shopping list for %s: %s",
                        target.recipe_id,
                        err,
                    )
                    self._resolves = False
                else:
                    self._resolves = True
                    self._label = listing.label
                    self._computed = _computed_items(listing)
            self._apply()
            self.async_write_ha_state()

    async def _async_resolve(
        self, library: Library, target: ShoppingTarget
    ) -> ShoppingList:
        """``shopping_list()``, in the executor, because it resolves a whole dish."""
        return await self.hass.async_add_executor_job(
            partial(
                shopping_list,
                library,
                target.recipe_id,
                batches=target.batches,
                include_optional=target.include_optional,
            )
        )

    @callback
    def _apply(self) -> None:
        """Lay the trip over the computed lines and hand the result to Home Assistant.

        Computed lines first in the library's own first-use order, then the
        things to go and find, then whatever the user typed -- which is where
        they added it.
        """
        items = [
            TodoItem(
                uid=item.uid,
                summary=item.summary,
                description=item.description,
                status=(
                    TodoItemStatus.COMPLETED
                    if item.uid in self._completed
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for item in self._computed
            if item.uid not in self._dropped
        ]
        # Copies, so a caller that mutates what it was handed cannot edit the
        # stored item behind the entity's back.
        items.extend(replace(item) for item in self._manual)
        self._attr_todo_items = items

    # -- the action ----------------------------------------------------------

    async def async_set_shopping_list(
        self, recipe: str, batches: float, include_optional: bool
    ) -> None:
        """Point the list at a dish, and check it resolves before saving it.

        Resolving here rather than on the next refresh is Silver
        ``action-exceptions``. "buttercream" matching three recipes, or a variant
        whose base is not in the library, is something the caller can fix, and
        being told while they are still looking at the call is worth an executor
        hop. Storing the target first and failing on the next poll would leave an
        unavailable list and a log line nobody is reading.
        """
        library = self.coordinator.data
        if library is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="library_not_loaded"
            )
        found = _find_recipe(library, recipe)
        target = ShoppingTarget(found.id, batches, include_optional)
        try:
            listing = await self._async_resolve(library, target)
        except (LookupError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="recipe_unresolvable",
                translation_placeholders={"recipe": found.name, "detail": str(err)},
            ) from err

        if target != self._target:
            # A new trip. The ticks belonged to the old one -- butter ticked off
            # for the cake is not butter bought for the brownies. Typed items are
            # not part of a trip and are deliberately untouched.
            self._completed.clear()
            self._dropped.clear()
        self._target = target
        self._resolves = True
        self._label = listing.label
        self._computed = _computed_items(listing)
        await self._async_commit()

    # -- the mutations -------------------------------------------------------

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add something the recipes know nothing about.

        The reason this feature is supported at all: a list you cannot add bin
        bags to is not the list you take to the shop. It is stored, so it
        survives the refresh that rebuilds everything around it.
        """
        self._manual.append(
            TodoItem(
                uid=f"{_MANUAL}{uuid.uuid4().hex}",
                summary=item.summary,
                description=item.description,
                status=item.status or TodoItemStatus.NEEDS_ACTION,
            )
        )
        await self._async_commit()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Tick anything; rewrite only what the user wrote in the first place."""
        uid = item.uid or ""
        for index, existing in enumerate(self._manual):
            if existing.uid == uid:
                self._manual[index] = TodoItem(
                    uid=uid,
                    summary=item.summary,
                    description=item.description,
                    status=item.status or TodoItemStatus.NEEDS_ACTION,
                )
                await self._async_commit()
                return

        computed = self._line(uid)
        if computed is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="item_gone",
                translation_placeholders={"item": item.summary or uid},
            )
        # Normalised, because an empty description and no description are the
        # same thing and the panel is entitled to send either.
        if (item.summary or "") != computed.summary or (item.description or None) != (
            computed.description or None
        ):
            # An edit that the next refresh would silently throw away. Refusing
            # leaves the user's words in front of them with a reason; accepting
            # would lose them somewhere between now and the next recipe change.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="computed_item_read_only",
                translation_placeholders={"item": computed.summary},
            )
        if item.status == TodoItemStatus.COMPLETED:
            self._completed.add(uid)
        else:
            self._completed.discard(uid)
        await self._async_commit()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete a typed item; drop a computed one for the rest of this trip.

        Two behaviours because the two kinds of item are two different things. A
        typed item is gone -- it existed only because someone typed it. A
        computed line cannot be deleted, because the recipe still calls for it,
        so it is dropped from *this* list and comes back with the next one. That
        is what makes ``todo.remove_completed_items`` -- clear the shelf, keep
        shopping -- work on a list most of whose items are derived.
        """
        gone = set(uids)
        self._manual = [item for item in self._manual if item.uid not in gone]
        for uid in gone:
            if not uid.startswith(_MANUAL):
                self._dropped.add(uid)
                self._completed.discard(uid)
        await self._async_commit()

    # -- persistence ---------------------------------------------------------

    async def _async_load(self) -> None:
        """Read the target and the trip back. Anything unreadable is ignored.

        A stored file that has been hand-edited into nonsense must not stop the
        entity being created: an empty list the user can re-point is recoverable,
        a platform that failed to set up is not.
        """
        stored = await self._store.async_load()
        if not stored:
            return
        target = stored.get("target") or {}
        if target.get("recipe_id"):
            try:
                self._target = ShoppingTarget(
                    recipe_id=str(target["recipe_id"]),
                    batches=float(target.get("batches", 1.0)),
                    include_optional=bool(target.get("include_optional", True)),
                )
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring an unreadable stored shopping-list target")
        self._completed = {str(uid) for uid in stored.get("completed") or ()}
        self._dropped = {str(uid) for uid in stored.get("dropped") or ()}
        self._manual = [
            TodoItem(
                uid=str(row["uid"]),
                summary=row.get("summary"),
                description=row.get("description"),
                status=(
                    TodoItemStatus.COMPLETED
                    if row.get("status") == TodoItemStatus.COMPLETED
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for row in stored.get("manual") or ()
            if isinstance(row, dict) and row.get("uid")
        ]

    async def _async_commit(self) -> None:
        """Rebuild the item list, publish it, and write the store.

        Written every time rather than on a delay: a tick and a typed item happen
        at human speed, the file is a few hundred bytes, and the cost of a
        debounce is losing the last thing the user did if Home Assistant is
        killed rather than stopped.
        """
        self._apply()
        self.async_write_ha_state()
        await self._store.async_save(
            {
                "target": (
                    None
                    if self._target is None
                    else {
                        "recipe_id": self._target.recipe_id,
                        "batches": self._target.batches,
                        "include_optional": self._target.include_optional,
                    }
                ),
                # Sorted so the file does not churn on set order alone.
                "completed": sorted(self._completed),
                "dropped": sorted(self._dropped),
                "manual": [
                    {
                        "uid": item.uid,
                        "summary": item.summary,
                        "description": item.description,
                        # The literal, not the enum: a StrEnum through the JSON
                        # encoder is a subclass of ``str`` and not every encoder
                        # in the stack promises to treat it as one.
                        "status": (
                            TodoItemStatus.COMPLETED.value
                            if item.status == TodoItemStatus.COMPLETED
                            else TodoItemStatus.NEEDS_ACTION.value
                        ),
                    }
                    for item in self._manual
                ],
            }
        )

    @callback
    def _line(self, uid: str) -> _LineItem | None:
        """The computed line with this uid, if it is still on the list."""
        for item in self._computed:
            if item.uid == uid and uid not in self._dropped:
                return item
        return None


def _computed_items(listing: ShoppingList) -> list[_LineItem]:
    """Every line to buy and every component to go and find, as items.

    The occurrence counter is here rather than in the uid helpers because it is a
    property of the whole list: the same sub-recipe used twice gives two lines
    that agree on recipe and ingredient id, and they are two separate things to
    buy. ``ShoppingList.lines`` is deterministic in first-use order, so numbering
    them by position is stable across a rebuild.
    """
    seen: dict[str, int] = {}
    items: list[_LineItem] = []

    def unique(base: str) -> str:
        count = seen[base] = seen.get(base, 0) + 1
        return base if count == 1 else f"{base}~{count}"

    for line in listing.lines:
        items.append(
            _LineItem(
                uid=unique(_line_uid(line)),
                summary=line.describe(),
                description=_line_description(line),
            )
        )
    for cited in listing.to_find:
        items.append(
            _LineItem(
                uid=unique(f"find:{cited.needed_by}:{cited.use.id}"),
                summary=cited.describe(),
                description=f"For {cited.needed_by}",
            )
        )
    return items


def _line_uid(line: ShoppingLine) -> str:
    """A key for a shopping line that a rebuild cannot move.

    The food where there is one, so a tick follows the butter through an edit
    that reorders the recipe. Where there is no ``rw:food`` the line is exactly
    one contribution by construction (``core/shopping.py`` on why an unlinked row
    merges with nothing), so the recipe and ingredient ids identify it.
    """
    if line.food_id:
        return f"line:food:{line.food_id}"
    first = line.contributions[0]
    return f"line:row:{first.recipe_id}:{first.ingredient_id}"


def _line_description(line: ShoppingLine) -> str | None:
    """The mise-en-place under the buy line, or nothing to say.

    ``ShoppingList.report()``'s rule, kept identical so the panel and the CLI do
    not disagree about the same row: several recipes want the food, so show which
    one wanted which part of it -- that is what the merge would otherwise have
    lost. One recipe wants it prepared, so show the preparation. One recipe wants
    it as it comes, so say nothing rather than repeat the summary back.
    """
    if len(line.contributions) > 1:
        return "\n".join(line.breakdown())
    if line.preparations:
        return line.preparations[0]
    return None


def _find_recipe(library: Library, needle: str) -> Recipe:
    """The recipe a caller meant, by ``@id`` or by part of its name.

    The same three rules the CLI's ``_find`` uses, because an automation writer
    should be able to type what they type at the command line. It is copied
    rather than shared: ``core/__main__.py`` raises ``SystemExit``, which is the
    right answer for a command and not something an action can catch. A public
    ``Library.find()`` would let both callers share the matching and is noted in
    the handover.
    """
    if needle in library.recipes:
        return library.recipes[needle]
    lowered = needle.strip().lower()
    matches = [
        recipe
        for recipe in library
        if lowered in recipe.name.lower() or lowered in recipe.id.lower()
    ]
    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="recipe_not_found",
            translation_placeholders={"recipe": needle},
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="recipe_ambiguous",
            translation_placeholders={
                "recipe": needle,
                "matches": ", ".join(sorted(recipe.name for recipe in matches)),
            },
        )
    return matches[0]
