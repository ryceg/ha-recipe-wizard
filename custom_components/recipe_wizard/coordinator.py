"""The one loaded ``Library``, kept fresh, and what ``entry.runtime_data`` holds.

**Why poll a local directory at all.** Recipes are added and enriched outside
Home Assistant — ``python -m recipe_wizard --import <URL>``, then the enrichment
loop, then ``--validate``. A cook-along that cannot see the recipe until the next
restart is the sort of bad experience nobody files as a bug; they just stop using
it. So the library is polled, which makes ``iot_class: local_polling`` true and
Bronze's ``appropriate-polling`` a real rule here rather than an exempt one.

**Why polling it is cheap.** The interval compares
``loader.library_fingerprint`` — one ``stat`` per document — and only parses when
one has moved. At the ~200 recipes the format doc plans for, an unchanged
interval is a few hundred ``stat`` calls a quarter of an hour, in the executor.

**Why the executor, every time.** ``Library.load()`` reads files. Blocking the
event loop is the commonest defect in custom integrations, and it is the reason
this integration cannot reach Platinum (``async-dependency``): the library is a
synchronous, stdlib-only resolver and that is the right shape for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .core.library import Library
from .issues import async_reconcile_issues, error_findings
from .loader import RecipeLibraryError, library_fingerprint, load_library

_LOGGER = logging.getLogger(__name__)


class RecipeLibraryCoordinator(DataUpdateCoordinator[Library]):
    """Holds the ``Library`` every entity reads, and reloads it when disk moves.

    ``coordinator.data`` is a ``core.library.Library``: the plain, Home
    Assistant-free object the resolver takes. An entity wanting a cook-along calls
    ``core.cookalong.cook_along(coordinator.data, recipe_id, batches=...)`` in the
    executor and holds its own cursor — see ``core/cookalong.py`` on why nothing
    here is stateful over one.
    """

    config_entry: RecipeWizardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: RecipeWizardConfigEntry,
        recipes_dir: Path,
    ) -> None:
        """Set the interval from ``const`` so there is one place to argue about it."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.recipes_dir = recipes_dir
        self._fingerprint: tuple[object, ...] | None = None

    @property
    def recipe_count(self) -> int:
        """How many recipes are loaded, or zero before the first refresh."""
        return 0 if self.data is None else len(self.data)

    async def _async_update_data(self) -> Library:
        """One executor hop per interval, whether or not anything changed.

        ``RecipeLibraryError`` becomes ``UpdateFailed`` so the first refresh
        raises ``ConfigEntryNotReady`` (Bronze ``test-before-setup``) and a later
        one marks the entities unavailable with the reason attached, rather than
        leaving them showing a library that is no longer on disk.

        Validation is a second executor hop and only on a real reload -- the
        identity check is exact, because ``_load_if_changed`` returns
        ``self.data`` itself when nothing moved. It is not folded into the first
        hop: that one exists to make the fingerprint and the load it guards
        atomic, and hanging a third concern off it would blur what the atomicity
        is for. Gold ``repair-issues`` is what this is; ``issues.py`` says why it
        raises a card for errors alone.
        """
        try:
            library = await self.hass.async_add_executor_job(self._load_if_changed)
        except RecipeLibraryError as err:
            raise UpdateFailed(str(err)) from err

        if library is not self.data:
            by_document = await self.hass.async_add_executor_job(
                error_findings, library
            )
            async_reconcile_issues(self.hass, by_document)
        return library

    def _load_if_changed(self) -> Library:
        """Runs in the executor: fingerprint first, parse only on a change.

        One executor job rather than two, so the fingerprint and the load it
        guards cannot be interleaved with a write. ``self.data`` is the only copy
        of the library -- returning it unchanged is what "no reload" means here.

        The fingerprint is recorded only after a *successful* load. That is what
        makes a broken document retry on the next interval rather than latching on
        a fingerprint whose parse never finished.
        """
        fingerprint = library_fingerprint(self.recipes_dir)
        if self.data is not None and fingerprint == self._fingerprint:
            return self.data
        library = load_library(self.recipes_dir)
        self._fingerprint = fingerprint
        _LOGGER.debug(
            "Loaded %d recipes and %d families from %s",
            len(library.recipes),
            len(library.families),
            self.recipes_dir,
        )
        return library


@dataclass(slots=True)
class RecipeWizardData:
    """What ``entry.runtime_data`` holds.

    A dataclass rather than the coordinator on its own, and never
    ``hass.data[DOMAIN]``: a platform reads ``entry.runtime_data.coordinator``
    with the type checker watching, and the next thing the integration needs to
    keep per entry — the cook-along cursors, most likely — gets a named field here
    instead of a second dictionary somewhere else.
    """

    coordinator: RecipeLibraryCoordinator


#: What a platform should annotate its ``async_setup_entry`` with, so
#: ``entry.runtime_data`` is typed rather than ``Any``.
RecipeWizardConfigEntry = ConfigEntry[RecipeWizardData]
