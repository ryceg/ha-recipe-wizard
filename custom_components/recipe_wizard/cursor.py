"""Where the cook is, and how it survives a restart.

``core/cookalong.py`` is stateless over a cursor on purpose, so something outside
it has to hold "which step am I on". This module is that something, and it makes
two decisions worth arguing.

**The cursor is persisted in the config entry's options.** Not in
``entry.runtime_data``, which is gone on restart -- and a cook who restarts Home
Assistant while the brownies are in their three-hour chill is exactly the cook
this surface exists for. Not on a ``RestoreEntity`` either, for three reasons:
the cursor is one fact that several entities and every action read, so the entity
that happened to restore it would quietly become its owner; a restored state is a
string and would have to be parsed back into a number; and it is not one fact but
four -- which recipe, how many batches, which step, and when the cook arrived at
it -- because "finished" cannot be told from "not started" without knowing whether
a recipe is on the go at all. The entry's options are a dict Home Assistant
already persists, and ``async_update_entry`` is the only sanctioned way to write
one. It is also what notifies the sensors, which is why nothing here mutates the
entry directly.

**The resolved dish is cached beside the cursor.** ``cook_along()`` reads files.
Home Assistant calls ``native_value`` on every state write, so a sensor property
must never resolve anything; the resolve happens here instead, in the executor,
once per (recipe, batches, library) -- when the cursor moves or when the library
reloads -- and the entities read the answer that is already sitting there.

**The moment a step's estimate runs out is a scheduled wake-up, not a poll.**
A step whose end a *state* decides -- the brownies' "32 min, then check: edges
firmish" -- needs the screen to stop counting down and start asking, and it needs
that to happen when the estimate elapses rather than whenever something else
happens to write a state. The alternatives were both worse than a single timer:
polling would mean an interval short enough to matter for a 32-minute bake, and
leaning on the coordinator's fifteen-minute refresh would tell a cook to check
their brownies up to a quarter of an hour late, which for brownies is the whole
ballgame. So each refresh arms one ``async_track_point_in_time`` at the estimate
and cancels the last, and nothing else in the integration watches a clock.

**Optional components are walked, not skipped.** The qeema's mint yogurt is
optional as a whole component, and a cook-along that dropped its steps would hide
work the document lists. Leaving it out is the cook's call at the bench, not a
decision this module gets to make for them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .core.cookalong import FINISHES_ON_STATE, CookAlong, CursorStep, cook_along
from .core.library import Library
from .coordinator import RecipeLibraryCoordinator, RecipeWizardConfigEntry

_LOGGER = logging.getLogger(__name__)

#: The one key under ``entry.options`` this integration writes. Namespaced so a
#: real user-facing option (a default batch size, say) can be added beside it
#: later without a migration.
OPTION_COOK_ALONG = "cook_along"


@dataclass(frozen=True, slots=True)
class SavedCursor:
    """The four facts that survive a restart, and nothing derived from them.

    ``started_at`` is when the cook arrived at this step, not when the recipe
    began: it is the only thing that can turn a step's *stated* duration into a
    wall-clock estimate, and it is reset every time the cursor moves.
    """

    recipe_id: str | None = None
    batches: float = 1.0
    cursor: int = 0
    started_at: datetime | None = None

    @property
    def running(self) -> bool:
        """Whether there is a cook-along at all. ``False`` is the idle state."""
        return self.recipe_id is not None

    def moved_to(self, cursor: int) -> "SavedCursor":
        """The same cook-along at another step, arrived at now."""
        return SavedCursor(
            recipe_id=self.recipe_id,
            batches=self.batches,
            cursor=cursor,
            started_at=dt_util.utcnow(),
        )

    def as_options(self) -> dict[str, Any]:
        """JSON-safe, because this goes into Home Assistant's own entry store."""
        return {
            "recipe_id": self.recipe_id,
            "batches": self.batches,
            "cursor": self.cursor,
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
        }

    @classmethod
    def from_options(cls, raw: Any) -> "SavedCursor":
        """Read one back, forgiving anything a hand-edited entry store may hold.

        A cursor that will not parse falls back to idle rather than raising:
        refusing to set the entry up because a saved position is malformed would
        cost a cook their whole library to save them one step of a cook-along.
        """
        if not isinstance(raw, dict) or not raw.get("recipe_id"):
            return cls()
        try:
            batches = float(raw.get("batches", 1.0))
            cursor = int(raw.get("cursor", 0))
        except (TypeError, ValueError):
            return cls()
        started = raw.get("started_at")
        return cls(
            recipe_id=str(raw["recipe_id"]),
            batches=batches,
            cursor=max(cursor, 0),
            started_at=dt_util.parse_datetime(started) if isinstance(started, str) else None,
        )


def saved_cursor(entry: RecipeWizardConfigEntry) -> SavedCursor:
    """What is written down for this entry right now."""
    return SavedCursor.from_options(entry.options.get(OPTION_COOK_ALONG))


@callback
def async_save_cursor(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry, saved: SavedCursor
) -> None:
    """Write the cursor down, which is also how the sensors hear about it.

    ``async_update_entry`` rather than assignment: it is what persists the entry
    and what runs its update listeners, and mutating ``entry.options`` in place
    would do neither -- the cook would advance a step and watch nothing change
    until the next restart, when it would change to a position they had left.
    """
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPTION_COOK_ALONG: saved.as_options()}
    )


class CookAlongCursor:
    """The cursor, the dish it points into, and who to tell when either moves.

    One per config entry, created by the sensor platform and kept alive by the
    entities that read it. Every attribute below is already computed: a caller
    reading ``step`` does no I/O, which is the whole point of the class.
    """

    def __init__(self, coordinator: RecipeLibraryCoordinator) -> None:
        """Take the coordinator; the entry and ``hass`` come off it."""
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.entry = coordinator.config_entry
        self.saved = saved_cursor(self.entry)
        self.cook_along: CookAlong | None = None
        self.step: CursorStep | None = None
        self.problem: str | None = None
        """Why the saved cursor could not be resolved -- a recipe deleted from
        under a running cook-along, most plausibly. The sensor reports *unknown*
        rather than *idle* for this, because it genuinely does not know which step
        the cook is on and saying "idle" would be a claim it cannot make."""
        self._resolved_for: tuple[str, float] | None = None
        self._resolved_from: Library | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._cancel_check: CALLBACK_TYPE | None = None
        """Cancels the wake-up armed for the current step's estimate."""

    # -- lifecycle -----------------------------------------------------------

    async def async_attach(self) -> None:
        """Resolve what is saved, then follow the entry and the library.

        Both subscriptions are unregistered when the entry unloads, so a reload
        does not leave a second cursor listening to the first one's coordinator.
        """
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._async_entry_updated)
        )
        self.entry.async_on_unload(
            self.coordinator.async_add_listener(self._handle_library_update)
        )
        # Registered once, and cancels whichever wake-up is armed at the time:
        # the unsubscribe changes on every refresh, so registering the current
        # one would leave a later timer running past an unload.
        self.entry.async_on_unload(self._cancel_check_timer)
        await self.async_refresh()

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Subscribe an entity, and hand back the removal it registers."""
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    # -- what moved ----------------------------------------------------------

    async def _async_entry_updated(
        self, hass: HomeAssistant, entry: RecipeWizardConfigEntry
    ) -> None:
        """The cursor was written: an action ran, or the cook tapped Next."""
        await self.async_refresh()

    @callback
    def _handle_library_update(self) -> None:
        """The library was re-read. A step may have been added under the cursor.

        The coordinator notifies synchronously and the re-resolve is executor
        work, so this schedules it. Tracked on the entry, so an unload waits for
        it rather than logging a task that outlived its integration.
        """
        self.entry.async_create_task(
            self.hass, self.async_refresh(), name="recipe_wizard cook-along refresh"
        )

    async def async_refresh(self) -> None:
        """Bring ``step`` in line with what is saved, then tell the entities.

        The resolve is skipped when the recipe, the batch count and the library
        object are all the ones it was last done for, which is the common case:
        tapping Next moves a cursor through a dish that has not changed.
        """
        saved = saved_cursor(self.entry)
        library = self.coordinator.data
        self.saved = saved

        if not saved.running or library is None:
            self._forget()
        elif (
            self.cook_along is None
            or library is not self._resolved_from
            or self._resolved_for != (saved.recipe_id, saved.batches)
        ):
            await self._async_resolve(library, saved)

        self.step = (
            None if self.cook_along is None else self.cook_along.at(saved.cursor)
        )
        self._arm_check_timer()
        for update_callback in list(self._listeners):
            update_callback()

    async def _async_resolve(self, library: Library, saved: SavedCursor) -> None:
        """Build the cook-along for the saved cursor, in the executor.

        A failure here is not a reason to break the entity. The recipe a cook
        started can be deleted or renamed on disk while they are cooking it --
        recipes are edited outside Home Assistant, which is why this integration
        polls at all -- and the honest answer to "which step am I on" then is
        that it is not known.
        """
        assert saved.recipe_id is not None
        try:
            self.cook_along = await self.hass.async_add_executor_job(
                partial(
                    cook_along, library, saved.recipe_id, batches=saved.batches
                )
            )
        except Exception as err:  # noqa: BLE001 - see the docstring
            _LOGGER.warning(
                "Cannot follow the cook-along for %s at %g batches: %s",
                saved.recipe_id,
                saved.batches,
                err,
            )
            self._forget()
            self.problem = str(err)
        else:
            self.problem = None
            self._resolved_for = (saved.recipe_id, saved.batches)
            self._resolved_from = library

    @callback
    def _forget(self) -> None:
        """Drop the resolved dish, so nothing stale is served for a new cursor."""
        self._cancel_check_timer()
        self.cook_along = None
        self.step = None
        self.problem = None
        self._resolved_for = None
        self._resolved_from = None

    # -- what the entities read ---------------------------------------------

    @property
    def running(self) -> bool:
        """Whether a cook-along is on the go, wherever the cursor has got to."""
        return self.saved.running

    @property
    def total_steps(self) -> int:
        """Every step in the dish, the root's and its components' together."""
        return 0 if self.cook_along is None else self.cook_along.total_steps()

    @property
    def estimated_end(self) -> datetime | None:
        """When the current step's stated time runs out, or ``None``.

        Lives here rather than on the sensor that displays it because the wake-up
        below has to know the same moment, and two copies of "when does this step
        end" is one too many -- the timer sensor computed this privately and the
        cursor would have had to re-derive it to schedule anything.

        ``None`` wherever the arithmetic is not supported by the document: no step,
        no arrival time, no stated duration, or a timer that starts on an event at
        the bench (``rw:timerStartsWhen``) that nothing here can observe.
        """
        entry = self.step
        if entry is None or self.saved.started_at is None:
            return None
        step = entry.step
        if step.timer_starts_when is not None or step.timer_s is None:
            return None
        return self.saved.started_at + timedelta(seconds=step.timer_s)

    @property
    def awaiting_check(self) -> bool:
        """The estimate has run out and the cook has not said the state is met.

        Only ever true for a step a *state* finishes. A step that finishes on the
        clock is done when its time is up -- there is nothing to check -- and
        saying otherwise would make the flag mean "the number reached zero",
        which a card can already see for itself.

        A state-finished step that states *no* time never reaches this: there is no
        estimate to elapse. ``finishes_on`` is what tells a card to prompt for
        those, from the moment the cook arrives.
        """
        end = self.estimated_end
        if end is None or self.step is None:
            return False
        if self.step.step.finishes_on != FINISHES_ON_STATE:
            return False
        return dt_util.utcnow() >= end

    @callback
    def _cancel_check_timer(self) -> None:
        """Cancel the armed wake-up, if there is one."""
        if self._cancel_check is not None:
            self._cancel_check()
            self._cancel_check = None

    @callback
    def _arm_check_timer(self) -> None:
        """Wake the sensors when the current step's estimate elapses.

        Armed only where it would change something: a state-finished step whose
        estimate is still in the future. A clock-finished step needs no wake-up
        because nothing about it changes when its time is up -- the countdown a
        dashboard renders from the timestamp is the whole of it.
        """
        self._cancel_check_timer()
        end = self.estimated_end
        if end is None or self.step is None:
            return
        if self.step.step.finishes_on != FINISHES_ON_STATE:
            return
        if end <= dt_util.utcnow():
            return

        @callback
        def _elapsed(_now: datetime) -> None:
            """The estimate has passed. Nothing moved; what it *means* changed."""
            self._cancel_check = None
            for update_callback in list(self._listeners):
                update_callback()

        self._cancel_check = async_track_point_in_time(self.hass, _elapsed, end)

    @property
    def finished(self) -> bool:
        """Running, resolvable, and past the last step.

        Also true for a cursor left pointing beyond a recipe that has since lost
        steps. ``CookAlong.at`` returns ``None`` for that on purpose, and
        "finished" is a better answer to a cook than an error is.
        """
        return self.running and self.cook_along is not None and self.step is None
