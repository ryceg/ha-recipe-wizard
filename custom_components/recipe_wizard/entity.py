"""What every Recipe Wizard entity is, before it is a sensor or a to-do list.

Bronze ``common-modules`` names this file, and there is a real reason for it here
rather than a convention to satisfy: the cook-along sensors and the shopping list
are the same *thing* to Home Assistant -- one local library, no accounts, no
devices -- so identity, grouping and availability have to be decided once. Two
platforms each inventing a ``unique_id`` scheme is how a rename in one of them
orphans an entity in the registry.

**The identity is the config entry, not anything off disk.** ``entry_id`` is
generated once when the entry is created and never changes; the recipe directory
in ``entry.data`` is a path the user is free to move. The obvious id for a
shopping list is the recipe it is for, and it would be wrong for the same reason:
a cook who renames ``recipes/`` to ``recipes-old/`` and re-adds the integration
would get a second set of entities and lose the ticks, the history and every
dashboard card and automation pointing at the first. That is what
``entity-unique-id`` is actually asking for.

**There is one device, and it is not a device.** Nothing here is hardware, and
``quality_scale.yaml`` marks the whole Gold device rule exempt for that reason.
But a device entry is the only thing in Home Assistant that groups entities under
a heading in the UI, so the integration registers exactly one, with
``entry_type=DeviceEntryType.SERVICE`` so it is listed as a service rather than
pretending to be a machine in the kitchen. Every entity in every platform hangs
off it, which is why the ``DeviceInfo`` is built here once instead of per
platform.

Nothing cook-along-specific belongs in this file. It is shared with the shopping
list, which has no cursor and no steps, and a base class that also knew what a
shopping line was would have to be edited by whichever platform came second.

Module-scope ``homeassistant`` imports are correct here: ADR 0002 confines the
deferred-import pattern to ``__init__.py``, the one module the CLI runs through.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RecipeLibraryCoordinator

#: What the grouping device is called. Fixed rather than read from
#: ``entry.title`` -- which is itself fixed, because there is only ever one entry
#: -- since a device that renamed itself when a user renamed the entry would
#: change every entity's suggested object id under them.
DEVICE_NAME = "Recipe Wizard"


class RecipeWizardEntity(CoordinatorEntity[RecipeLibraryCoordinator]):
    """An entity backed by the one loaded recipe library.

    Subclasses get, for free: unavailability when the library will not load
    (``CoordinatorEntity`` plus the coordinator's ``UpdateFailed``, Silver
    ``entity-unavailable``), a subscription that is removed on entity removal
    (Bronze ``entity-event-setup``), a stable ``unique_id`` (Bronze
    ``entity-unique-id``), and the entity-name behaviour Bronze
    ``has-entity-name`` asks for -- so a subclass sets a ``translation_key`` and
    the UI reads "Recipe Wizard Current step".

    ``key`` is the entity's own stable half of the ``unique_id``. It is written
    once, in code, and must never be derived from a recipe name or a file path:
    it is what survives the user renaming what they see. The visible name comes
    from ``_attr_translation_key`` and ``strings.json`` instead (Gold
    ``entity-translations``), so renaming never moves an entity id.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: RecipeLibraryCoordinator, key: str) -> None:
        """Take the coordinator every entity reads, and this entity's key."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=DEVICE_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )
