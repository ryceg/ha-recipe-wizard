"""The four things a cook does to a cook-along: start it, move, and stop.

Four, and no more. An action per imaginable dashboard gesture is the speculative
generality this project cuts, so each of these had to answer "what taps this?":
**start** comes from a recipe picker, **next** and **previous** are the two
buttons the cook presses with the back of a knuckle, and **stop** is how they say
the tray is out. A ``go_to_step`` was written and removed -- reaching a step means
picking one from a list the dashboard would have to build, and a bare integer into
a dish whose numbering shifts when a recipe is edited is a footgun rather than a
feature. ``validate_library`` was considered and cut: the validator is the
contract an *enrichment loop* iterates against from the command line, and nothing
in a kitchen would call it.

**Registered in ``async_setup``, not ``async_setup_entry``** (Bronze
``action-setup``): an action that disappears with a failed entry makes an
automation report "unknown action", which sends the user hunting for a typo
instead of telling them the truth. So these exist from startup and resolve the
entry per call.

**No target and no entry id in any of them.** ``single_config_entry`` is true in
the manifest, so there is exactly one recipe library and exactly one entry to
find; asking a cook which one they meant would be a field with one possible value.

**Every failure a cook can cause is a ``ServiceValidationError``** with a message
that names the thing -- the recipe id they typed, the position they are already at
-- and everything else is a ``HomeAssistantError`` (Silver ``action-exceptions``).
The line between them is whose fault it is, not how deep in the stack it happened:
a name that matches three recipes is the cook's to fix, a document whose steps
cannot be put in an order is not.

A batch that a recipe cannot physically make is neither. ``resolve_dish`` is
deliberately not strict -- "a dish is built to be shown" -- so asking for a tenth
of a batch of something with a 500 g minimum comes back as a warning carried on
the resolution rather than as an exception. That is the right call and is left
alone here: the cook-along starts, and the sensor puts the warning on the screen
where the cook can read it and decide.
"""

from __future__ import annotations

import logging
from functools import partial

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .core.cookalong import CookAlong, cook_along
from .core.library import Library, LibraryError
from .coordinator import RecipeWizardConfigEntry
from .cursor import SavedCursor, async_save_cursor, locate_saved, saved_cursor

_LOGGER = logging.getLogger(__name__)

SERVICE_START_COOK_ALONG = "start_cook_along"
SERVICE_NEXT_STEP = "next_step"
SERVICE_PREVIOUS_STEP = "previous_step"
SERVICE_STOP_COOK_ALONG = "stop_cook_along"

ATTR_RECIPE_ID = "recipe_id"
ATTR_BATCHES = "batches"

#: ``batches`` is a plain factor and propagates into every component, so half a
#: batch is as meaningful as three. Nought is not: it would resolve a dish of
#: nothing and read as a bug rather than as a request.
START_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE_ID): cv.string,
        vol.Optional(ATTR_BATCHES, default=1.0): vol.All(
            vol.Coerce(float), vol.Range(min=0, min_included=False)
        ),
    }
)


@callback
def async_register_actions(hass: HomeAssistant) -> None:
    """Register all four. Called once, from ``async_setup``."""
    hass.services.async_register(
        DOMAIN, SERVICE_START_COOK_ALONG, _async_start_cook_along, schema=START_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_NEXT_STEP, _async_next_step)
    hass.services.async_register(DOMAIN, SERVICE_PREVIOUS_STEP, _async_previous_step)
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_COOK_ALONG, _async_stop_cook_along
    )


# --- the handlers ----------------------------------------------------------


async def _async_start_cook_along(call: ServiceCall) -> None:
    """Resolve the dish, then put the cursor on its first step.

    The dish is resolved *before* anything is written down, so a recipe that
    cannot be scaled to the batch asked for fails the call and leaves whatever the
    cook was doing before untouched.
    """
    hass = call.hass
    entry = _loaded_entry(hass)
    library = _library(entry)
    recipe_id = _match_recipe(library, call.data[ATTR_RECIPE_ID])
    batches = call.data[ATTR_BATCHES]

    dish = await _async_cook_along(hass, library, recipe_id, batches)
    _LOGGER.debug(
        "Starting cook-along for %s at %g batches: %d steps",
        recipe_id,
        batches,
        dish.total_steps(),
    )
    async_save_cursor(
        hass,
        entry,
        SavedCursor(recipe_id=recipe_id, batches=batches).moved_to(0, dish.at(0)),
    )


async def _async_next_step(call: ServiceCall) -> None:
    """Forward one. Past the last step is *finished*, not an error.

    The dish is resolved to find out how many steps it has, because a cursor that
    ran past the end would leave the sensor saying "finished" while *previous*
    walked back through positions the cook was never on.
    """
    hass = call.hass
    entry = _loaded_entry(hass)
    saved = _running(entry)
    dish = await _async_cook_along(
        hass, _library(entry), saved.recipe_id, saved.batches
    )
    here = _here(dish, saved)

    if here >= dish.total_steps():
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="already_finished"
        )
    async_save_cursor(hass, entry, saved.moved_to(here + 1, dish.at(here + 1)))


async def _async_previous_step(call: ServiceCall) -> None:
    """Back one, which is also how a cook returns from *finished* to the last step."""
    hass = call.hass
    entry = _loaded_entry(hass)
    saved = _running(entry)
    # Resolved here where it once was not, because "back one" is one step back
    # from where the cook *is*, and that is a lookup by id rather than the index
    # last written down. A step inserted above them moves the index and not them.
    dish = await _async_cook_along(
        hass, _library(entry), saved.recipe_id, saved.batches
    )
    here = _here(dish, saved)
    if here <= 0:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="at_the_first_step"
        )
    async_save_cursor(hass, entry, saved.moved_to(here - 1, dish.at(here - 1)))


async def _async_stop_cook_along(call: ServiceCall) -> None:
    """Put the kitchen back to idle.

    Deliberately silent when nothing is running: stopping a stopped cook-along is
    what a dashboard button does when it is pressed twice, and an error toast for
    it would be noise rather than information.
    """
    hass = call.hass
    entry = _loaded_entry(hass)
    async_save_cursor(hass, entry, SavedCursor())


def _here(dish: CookAlong, saved: SavedCursor) -> int:
    """The index the cook is actually on, however the cursor was written.

    ``locate_saved`` answers by step id, which is the position of record;
    this turns that back into the index the movement actions add to. Where the
    id names nothing -- the step was deleted out from under a running
    cook-along -- it falls back to the saved index rather than refusing to
    move, because the cook is standing in a kitchen and needs to get on. The
    sensor reports the same situation as *unknown*, which is where they find
    out that the recipe moved under them."""
    here = locate_saved(dish, saved)
    return saved.cursor if here is None else here.cursor


# --- resolving the premise of a call ---------------------------------------


def _loaded_entry(hass: HomeAssistant) -> RecipeWizardConfigEntry:
    """The one loaded entry, or the truth about why there is not one.

    This is the reason the actions register in ``async_setup``: "Recipe Wizard is
    not set up" is a different instruction from "that action does not exist", and
    only the first one is actionable.
    """
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return entries[0]


def _library(entry: RecipeWizardConfigEntry) -> Library:
    """The library the coordinator has already loaded."""
    library = entry.runtime_data.coordinator.data
    if library is None:  # pragma: no cover - a loaded entry has been refreshed
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return library


def _running(entry: RecipeWizardConfigEntry) -> SavedCursor:
    """The saved cursor, provided there is a cook-along to move."""
    saved = saved_cursor(entry)
    if not saved.running:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_cooking"
        )
    return saved


def _match_recipe(library: Library, wanted: str) -> str:
    """The ``@id`` a cook meant, or an error that quotes what they typed.

    Nobody types ``urn:recipe:rte/peanut-butter-stuffed-brownies`` into a service
    call, and the command-line tool has always accepted "brownies", so this
    accepts the same thing: an exact ``@id`` first, then a substring of an id or a
    name. Matching is a dictionary walk over the loaded library -- no file I/O --
    so it is safe on the event loop, and it happens before the executor hop so a
    typo comes back as a typo rather than as a lookup failure from three frames
    down.

    Several matches is an error rather than a guess (``docs/format.md`` Principle
    3): "buttercream" is three recipes in this corpus, and starting the wrong one
    is worse than being asked again.
    """
    if wanted in library.recipes:
        return wanted
    needle = wanted.strip().lower()
    matches = [
        recipe.id
        for recipe in library
        if needle in recipe.id.lower() or needle in recipe.name.lower()
    ]
    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_such_recipe",
            translation_placeholders={"recipe_id": wanted},
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ambiguous_recipe",
            translation_placeholders={
                "recipe_id": wanted,
                "matches": ", ".join(sorted(matches)),
            },
        )
    return matches[0]


async def _async_cook_along(
    hass: HomeAssistant, library: Library, recipe_id: str | None, batches: float
) -> CookAlong:
    """Resolve the dish in the executor, and name whose problem a failure is.

    ``LibraryError`` here is not a typo -- ``_match_recipe`` has already checked
    the id -- but a component pointing at a recipe that is not in the folder,
    which is the same instruction to the cook either way: something the recipe
    refers to is missing.
    """
    assert recipe_id is not None
    try:
        return await hass.async_add_executor_job(
            partial(cook_along, library, recipe_id, batches=batches)
        )
    except LibraryError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_such_recipe",
            translation_placeholders={"recipe_id": str(err)},
        ) from err
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cook_along_failed",
            translation_placeholders={
                "recipe_id": recipe_id,
                "detail": str(err),
            },
        ) from err
