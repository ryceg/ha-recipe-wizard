"""The cook-along on a screen: which step, and when it might be done.

Two entities, and the second one had to earn its place.

**Current step** is the surface the whole format was designed against. Its state
is the cook's position -- ``"12/16"`` -- and everything they need is in the
attributes: the step text, what it needs *at this batch size*, the timer line, the
doneness, whether they can walk away, and whether they may stop after it.

The state is the position because it cannot be the step text. Home Assistant caps
a state at 255 characters and drops any write that exceeds it, and step text is
prose: the longest in the corpus today is 191 characters, which fits, and building
the primary surface on "no step in the first seven recipes is long" would fail at
recipe fifty by silently not updating. The step *id* was the other candidate and
is worse: ``#add-sugar`` is not unique in a dish, because the cake and its
buttercream both have one, so a dashboard could not tell which page the cook was
on. The position is unique across the dish, is meaningful at a glance, and
answers the question a cook actually asks the screen from across the kitchen.

**Step timer** is a ``timestamp``, which dashboards render as a countdown and
automations can compare, and it exists because that is otherwise a template doing
date arithmetic on a string attribute in every kitchen that wants it. It is
deliberately narrow about when it will answer at all. ``docs/format.md`` is clear
that a stated time is an estimate and the **doneness** is authoritative -- the
brownies bake for *"32 min, then check: edges firmish, centre still jiggling"* --
so this entity never invents a time:

* a step that states no duration gets no timestamp, because the planner's assumed
  minute is scaffolding for the graph, not a number a cook should act on;
* only a step a *state* finishes is called an estimate. "Beat the eggs for 30
  seconds on speed 6" is not estimating anything, and hedging it teaches a cook to
  discount every number on the screen -- including the ones that are estimates;
* and when a state-finished step's estimate elapses, ``awaiting_check`` says so,
  so a card can stop showing a countdown at zero and start asking the question the
  document has always carried the answer to;
* a step whose timer starts on an event rather than on arriving at it
  (``rw:timerStartsWhen``) gets no timestamp either, since nothing here knows when
  the water came back to the boil;
* and what it does answer carries the doneness beside it, so the authoritative
  half is never off the screen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RecipeLibraryCoordinator, RecipeWizardConfigEntry
from .cursor import CookAlongCursor
from .entity import RecipeWizardEntity

#: Silver ``parallel-updates``. Every read is served from the library the
#: coordinator has already loaded and the cook-along the cursor has already
#: resolved, so there is nothing to serialise and no limit to impose.
PARALLEL_UPDATES = 0

#: No cook-along is on the go. A real state rather than *unknown*: an empty
#: kitchen is not a broken sensor, and "unknown" sends a user to the logs.
STATE_IDLE = "idle"

#: Past the last step, including a cursor left beyond a recipe that has since
#: lost steps -- which is a finished cook-along as far as the cook is concerned.
STATE_FINISHED = "finished"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecipeWizardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the one cursor both sensors read, then the sensors.

    The cursor is resolved *before* the entities are added, so the first state
    written is the real one -- a cook-along in progress across a restart shows the
    step the cook left off on, not a flash of "idle" that an automation could
    trigger on.
    """
    coordinator = entry.runtime_data.coordinator
    cursor = CookAlongCursor(coordinator)
    await cursor.async_attach()
    async_add_entities([CurrentStepSensor(coordinator, cursor), StepTimerSensor(coordinator, cursor)])


class CookAlongSensor(RecipeWizardEntity, SensorEntity):
    """Shared plumbing: read the cursor, and rewrite when it moves.

    Subscribing to the cursor as well as to the coordinator is not redundant.
    ``CoordinatorEntity`` hears the library reload; only the cursor hears the cook
    tap Next, which does not touch the library at all.
    """

    def __init__(
        self, coordinator: RecipeLibraryCoordinator, cursor: CookAlongCursor, key: str
    ) -> None:
        """Take the cursor alongside the coordinator every entity gets."""
        super().__init__(coordinator, key)
        self.cursor = cursor

    async def async_added_to_hass(self) -> None:
        """Subscribe to the cursor, and unsubscribe when removed."""
        await super().async_added_to_hass()
        self.async_on_remove(self.cursor.async_add_listener(self._handle_cursor_update))

    @callback
    def _handle_cursor_update(self) -> None:
        """The cursor moved, or the dish under it was re-resolved."""
        self.async_write_ha_state()


class CurrentStepSensor(CookAlongSensor):
    """Which step the cook is on, and everything that step needs."""

    _attr_translation_key = "current_step"

    def __init__(
        self, coordinator: RecipeLibraryCoordinator, cursor: CookAlongCursor
    ) -> None:
        """Key ``current_step``: written once, so a rename cannot orphan it."""
        super().__init__(coordinator, cursor, "current_step")

    @property
    def native_value(self) -> str | None:
        """``"12/16"``, ``idle``, ``finished``, or unknown.

        Reads only what the cursor has already resolved. Home Assistant calls
        this on every state write, and ``cook_along()`` reads files.
        """
        if not self.cursor.running:
            return STATE_IDLE
        if self.cursor.problem is not None:
            # Running, but the recipe cannot be resolved right now. The cook is
            # somewhere in it and this entity does not know where, which is what
            # *unknown* means.
            return None
        step = self.cursor.step
        if step is None:
            return STATE_FINISHED
        return f"{step.cursor + 1}/{step.of}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Everything a cook-along card puts on the screen.

        Ordered the way a card reads it: which dish, which page of it, what to
        do, what to get out, and what to wait for.
        """
        cursor = self.cursor
        if not cursor.running:
            return None
        if cursor.problem is not None:
            return {
                "recipe_id": cursor.saved.recipe_id,
                "batches": cursor.saved.batches,
                "problem": cursor.problem,
            }

        dish = cursor.cook_along
        attributes: dict[str, Any] = {
            "dish": None if dish is None else dish.label,
            "batches": cursor.saved.batches,
            "step_number": cursor.saved.cursor + 1,
            "of": cursor.total_steps,
        }
        if dish is not None and dish.resolution.findings:
            # A batch below a recipe's stated minimum, or a tin the doubled
            # mixture will not fit in. The library reports these rather than
            # refusing, because a dish is built to be shown -- so this is the one
            # place a cook can find out before they start creaming butter.
            #
            # The library hands these over as ``Finding``s, and what goes on the
            # screen is still a list of sentences. An attribute is read by
            # dashboard cards and automation templates that this integration does
            # not own, so its shape is a published interface: turning it into a
            # list of dicts to expose a code no kitchen has any use for would
            # break every card reading it, to say nothing new. The level and the
            # code stay where they are useful, which is the validator.
            attributes["warnings"] = [f.message for f in dish.resolution.findings]
        if dish is not None and dish.unresolvable:
            # A component that is a book citation is never expanded and is left
            # off the shopping list on purpose, so the cook-along is the only
            # place left that can tell the cook to go and get the book.
            attributes["cited_components"] = [use.label for use in dish.unresolvable]

        entry = cursor.step
        if entry is None:
            return attributes

        step = entry.step
        # ``label`` is the *use's* label, so a cook halfway through the cake's
        # frosting reads "Vanilla buttercream" rather than the cake's name.
        attributes["recipe"] = entry.label
        attributes["recipe_id"] = entry.recipe_id
        attributes["step_id"] = step.step_id
        attributes["step"] = step.text
        # ``describe()`` is what makes a doubled tray read "4 tbsp smooth peanut
        # butter (of 500 g)" -- the portion scaled, the row's mass scaled, and no
        # arithmetic pretending to know what 4 tbsp of peanut butter weighs.
        attributes["needs"] = [line.describe() for line in step.ingredients]
        attributes["timer"] = step.timer_label()
        attributes["timer_seconds"] = step.timer_s
        attributes["timer_max_seconds"] = step.timer_max_s
        attributes["doneness"] = step.doneness
        attributes["attention"] = step.attention
        attributes["may_pause_after"] = step.may_pause_after
        if step.timer_starts_when is not None:
            attributes["timer_starts_when"] = step.timer_starts_when
        # What actually ends this step, so a card does not have to infer it from
        # which of the other attributes happen to be set. "state" means the food
        # decides and the cook has to look; "clock" means the stated time is the
        # instruction; "cook" means it is done when they have done it.
        attributes["finishes_on"] = step.finishes_on
        if self.cursor.awaiting_check:
            # The estimate has run out on a step whose state decides. This is the
            # "nothing asks" half of the doneness gap: the countdown reaching zero
            # is not the same event as the brownies being done, and until this
            # existed the screen presented them as the same thing.
            attributes["awaiting_check"] = True
        if step.safety_note is not None:
            attributes["safety_note"] = step.safety_note
        if step.produces:
            attributes["produces"] = [
                product.name or product.id for product in step.produces
            ]
        return attributes


class StepTimerSensor(CookAlongSensor):
    """About when the current step will be done, said as an estimate."""

    _attr_translation_key = "step_timer"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: RecipeLibraryCoordinator, cursor: CookAlongCursor
    ) -> None:
        """Key ``step_timer``, for the same reason as the other one."""
        super().__init__(coordinator, cursor, "step_timer")

    @property
    def native_value(self) -> datetime | None:
        """When the step's stated time runs out, or nothing.

        Nothing, rather than a guess, whenever the document does not support the
        arithmetic: no step, no stated duration, no arrival time, or a timer that
        starts on something this integration cannot see. The cursor owns that
        decision now, because the wake-up it arms has to agree with what this
        entity displays -- see ``cursor.estimated_end``.
        """
        return self.cursor.estimated_end

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The timer in the words the library chose, and why it is an estimate."""
        entry = self.cursor.step
        if entry is None:
            return None
        step = entry.step
        attributes: dict[str, Any] = {
            # "32 min, then check: edges firmish, centre still jiggling" -- the
            # number and the state that overrules it, in one line.
            "timer": step.timer_label(),
            "doneness": step.doneness,
            "started_at": self.cursor.saved.started_at,
        }
        attributes["finishes_on"] = step.finishes_on
        if self.native_value is not None and step.time_is_estimate:
            # Only where there is a timestamp *and* something it is an estimate
            # of. This used to be set for every timestamp, which called "beat the
            # eggs for 30 seconds" an estimate -- and a surface that hedges its
            # certain numbers has no way left to mark its uncertain ones. Absent
            # rather than ``False`` where there is nothing to qualify: a card
            # printing "estimated: unknown" is the failure the previous comment
            # here was guarding against, and it still applies.
            attributes["is_estimate"] = True
        if self.cursor.awaiting_check:
            # Past the estimate, still on the step. The countdown a dashboard
            # renders from the timestamp has reached zero and the step is not over.
            attributes["awaiting_check"] = True
        if self.native_value is not None:
            latest = self._ends_at(step.timer_max_s)
            if latest is not None and latest != self.native_value:
                # The brownies' peanut butter freezes for two to three hours. The
                # upper end is not the same claim as the lower one and is not an
                # average of them.
                attributes["latest_estimate"] = latest
        if step.timer_starts_when is not None:
            # Why there is no timestamp: the clock starts on an event at the
            # bench, not on the cook reaching this step.
            attributes["timer_starts_when"] = step.timer_starts_when
        return attributes

    def _ends_at(self, seconds: float | None) -> datetime | None:
        """When the cook arrived, plus a number of seconds -- given both."""
        started = self.cursor.saved.started_at
        if started is None or seconds is None:
            return None
        return started + timedelta(seconds=seconds)
