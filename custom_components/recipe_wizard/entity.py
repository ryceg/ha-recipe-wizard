"""The base entity every platform subclasses.

Bronze ``common-modules`` names this file, and there are two things in it that
every platform has to agree on rather than each inventing its own.

**The unique id is the entry id plus a key, never anything off disk.** The
obvious id for a shopping list is the recipe it is for, and it would be wrong:
the recipe directory is the one thing the user configures, so a cook who renames
``recipes/`` to ``recipes-old/`` and re-adds the integration would get a second
set of entities and lose the ticks, the history and the dashboard cards attached
to the first. The entry id survives that, and it is what
``entity-unique-id`` actually wants.

**There is one device, and it is not a device.** Nothing here is hardware --
``integration_type`` is ``service`` and ``quality_scale.yaml`` exempts every
device rule for that reason. But a device entry is the only thing in Home
Assistant that groups entities under a heading in the UI, so the integration
registers exactly one, with ``entry_type=DeviceEntryType.SERVICE`` so it is
listed as a service rather than pretending to be a machine in the kitchen. Every
entity in every platform hangs off it, which is why the ``DeviceInfo`` is built
here once instead of per platform.

Module-scope ``homeassistant`` imports are correct here: ADR 0002 confines the
deferred-import pattern to ``__init__.py``, the one module the CLI runs through.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RecipeLibraryCoordinator

#: The device's name. Fixed, like the entry title: there is one library.
DEVICE_NAME = "Recipe Wizard"


class RecipeWizardEntity(CoordinatorEntity[RecipeLibraryCoordinator]):
    """Coordinator-backed, named by its translation key, on the one device.

    Deliberately empty of anything to do with recipes. The shopping list and the
    cook-along sensors share the identity and the availability rules and nothing
    else, and a base class that also knew what a shopping line was would have to
    be edited by whichever platform came second.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: RecipeLibraryCoordinator, key: str) -> None:
        """``key`` distinguishes this entity from the others on the same entry.

        It is part of the unique id and nothing else -- the visible name comes
        from ``_attr_translation_key`` and ``strings.json``, so renaming what a
        user sees never moves an entity id (Bronze ``has-entity-name`` and Gold
        ``entity-translations``).
        """
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )
