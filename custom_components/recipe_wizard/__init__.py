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

    The two read-only views and the panel's static directory are here for a
    different reason with the same shape: Home Assistant can register a view or a
    static path and offers no way to take either back, so registering them per
    entry would leave a second copy of every route behind on each reload. Both
    answer for themselves while no entry is loaded -- a 503 with a reason, and a
    directory nobody has been given a link to. The *panel* is registered per
    entry, in ``async_setup_entry``, because a panel can be removed and the
    sidebar entry should go when the integration does.
    """
    from .actions import async_register_actions
    from .http import async_register_static_path, async_register_views

    async_register_actions(hass)
    async_register_views(hass)
    await async_register_static_path(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry
) -> bool:
    """Load the library once, off the event loop, and hand it to the platforms.

    The panel goes on last, after the entities exist, and only if the frontend
    bundle is actually being served. A checkout of this repository has no bundle
    in it, and a setup that failed over an absent asset would take the cook-along
    sensors and the shopping list down with it -- so a missing bundle is a warning
    logged once and no sidebar entry, not a failed entry.
    """
    from .coordinator import RecipeLibraryCoordinator, RecipeWizardData
    from .http import async_register_recipe_panel

    coordinator = RecipeLibraryCoordinator(
        hass, entry, Path(entry.data[CONF_RECIPES_DIR])
    )
    # Raises ``ConfigEntryNotReady`` when the directory has gone missing or a
    # document will not parse, so Home Assistant retries rather than leaving a
    # loaded entry with no library behind it (Bronze ``test-before-setup``).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = RecipeWizardData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_recipe_panel(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry
) -> bool:
    """Unload the platforms and take the sidebar entry with them.

    The library is plain objects and the polling stops when the coordinator loses
    its last listener, which ``async_unload_platforms`` arranges by removing the
    entities. The panel is the one thing that does not go on its own, and it is
    removed only when the unload succeeded: a failed unload leaves the entry
    loaded, and a sidebar entry that vanished from a still-running integration
    would be a worse lie than one that stayed.

    The views and the static path are deliberately *not* undone here. Home
    Assistant offers no way to unregister either, and both are harmless without
    an entry behind them -- the views answer 503 with the reason.
    """
    from .http import async_remove_recipe_panel

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_remove_recipe_panel(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: RecipeWizardConfigEntry) -> None:
    """Take the repair cards with the entry.

    Deleting an integration does not sweep the issues it raised, so without this
    a cook who removes Recipe Wizard is left with a card about a recipe belonging
    to an integration that is no longer there -- and no way to act on it. Unload
    is the wrong hook: a reload unloads and sets up again, and clearing there
    would blink every card off and back on.

    Nothing else is removed, and that is a promise the documentation makes in so
    many words: the recipe files are the user's own documents.
    """
    from .issues import async_clear_issues

    async_clear_issues(hass)
