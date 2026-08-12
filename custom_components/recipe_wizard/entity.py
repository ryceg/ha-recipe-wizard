"""What every Recipe Wizard entity is, before it is a sensor or a to-do list.

Bronze ``common-modules`` names this file, and there is a real reason for it here
rather than a convention to satisfy: the cook-along sensors and the shopping list
are the same *thing* to Home Assistant -- one local library, no accounts, no
devices -- so identity, grouping and availability have to be decided once. Three
platforms each inventing a ``unique_id`` scheme is how a rename in one of them
orphans an entity in the registry.

**The identity is the config entry, not the recipe directory.** ``entry_id`` is
generated once when the entry is created and never changes; the directory in
``entry.data`` is a path the user is free to move. A ``unique_id`` built from the
path would make "I moved my recipes to a bigger disk" look like a new set of
entities, dropping every dashboard card, automation and history graph pointing at
the old ones.

**One device for the whole integration.** Nothing here is a device --
``integration_type`` is ``service`` and ``quality_scale.yaml`` exempts every
device rule -- but a device entry is the only thing that groups entities under one
heading in the UI, so there is one, marked ``DeviceEntryType.SERVICE`` to say what
it really is.

Nothing cook-along-specific belongs in this file. It is shared with the shopping
list, which has no cursor and no steps.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RecipeLibraryCoordinator

#: What the grouping device is called. Fixed rather than read from
#: ``entry.title``, which is also fixed (``config_flow.TITLE``) because there is
#: only ever one entry -- and a device that renamed itself when a user renamed the
#: entry would change every entity's suggested object id under them.
DEVICE_NAME = "Recipe Wizard"


class RecipeWizardEntity(CoordinatorEntity[RecipeLibraryCoordinator]):
    """A Home Assistant entity backed by the one loaded recipe library.

    Subclasses get, for free: unavailability when the library will not load
    (``CoordinatorEntity`` plus the coordinator's ``UpdateFailed``, Silver
    ``entity-unavailable``), a subscription that is removed on entity removal
    (Bronze ``entity-event-setup``), a stable ``unique_id`` (Bronze
    ``entity-unique-id``), and the entity-name behaviour Bronze
    ``has-entity-name`` asks for -- so a subclass sets a ``translation_key`` and
    the UI reads "Recipe Wizard Current step".

    ``key`` is the entity's own stable half of the ``unique_id``. It is written
    once, in code, and must never be derived from a recipe name or a file path:
    it is what survives an entity being renamed by the user.
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
