"""The Recipe Wizard Home Assistant integration.

The Home Assistant glue lands here -- ``async_setup``, ``async_setup_entry``,
``async_unload_entry``. The library it wraps is the ``core`` subpackage.

Keep ``homeassistant`` imports out of module scope in this file. Importing
``custom_components.recipe_wizard.core`` runs this module first, so a top-level
``from homeassistant... import`` here would make the CLI and the library tests
require Home Assistant to be installed. Use ``TYPE_CHECKING`` for annotations
and import inside the function bodies; ``tests/test_packaging.py`` enforces it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .const import CONF_RECIPES_DIR

if TYPE_CHECKING:
    # Annotations only. ``from __future__ import annotations`` makes every
    # annotation in this file a string, so nothing below evaluates these.
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .coordinator import RecipeWizardConfigEntry

# Plain strings, not ``homeassistant.const.Platform``: importing that here is
# exactly what ADR 0002 forbids, and ``Platform`` is a ``StrEnum`` whose members
# equal these strings anyway. If you are adding a platform, append its name --
# do not "fix" this by importing the enum.
PLATFORMS: list[str] = ["sensor", "todo"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register everything that must exist even when the entry is not loaded.

    Bronze ``action-setup``: an action registered in ``async_setup_entry``
    disappears when the entry fails to load, so an automation calling it reports
    "unknown action" instead of "that config entry is not loaded" -- the first
    sends the user looking for a typo, the second tells them the truth.

    The cook-along actions are in ``actions.py``, imported here rather than at
    module scope per ADR 0002. They take no runtime data: each handler resolves
    the one loaded entry itself and raises ``ServiceValidationError`` when there
    is not one.

    ``recipe_wizard.set_shopping_list`` is deliberately *not* here: it changes one
    todo entity's list and nothing else, so it is an entity service registered in
    ``todo.py``, which ``action-setup`` exempts. This is still where anything
    acting on the library rather than on one entity belongs.
    """
    from .actions import async_register_actions

    async_register_actions(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry
) -> bool:
    """Load the library once, off the event loop, and hand it to the platforms."""
    from .coordinator import RecipeLibraryCoordinator, RecipeWizardData

    coordinator = RecipeLibraryCoordinator(
        hass, entry, Path(entry.data[CONF_RECIPES_DIR])
    )
    # Raises ``ConfigEntryNotReady`` when the directory has gone missing or a
    # document will not parse, so Home Assistant retries rather than leaving a
    # loaded entry with no library behind it (Bronze ``test-before-setup``).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = RecipeWizardData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry
) -> bool:
    """Unload the platforms; the coordinator goes with the runtime data.

    There is nothing else to tear down. The library is plain objects and the
    polling stops when the coordinator loses its last listener, which
    ``async_unload_platforms`` arranges by removing the entities.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
