"""Buttons to sync with Ornament on demand."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OrnamentConfigEntry, OrnamentCoordinator
from .entity import OrnamentEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrnamentConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sync buttons on the profile device."""
    coordinator = entry.runtime_data
    async_add_entities(
        [OrnamentSyncButton(coordinator), OrnamentResyncButton(coordinator)]
    )


class OrnamentSyncButton(OrnamentEntity, ButtonEntity):
    """Fetch from Ornament now instead of waiting for the next poll."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cloud-sync"
    _attr_translation_key = "sync"

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "sync")

    async def async_press(self) -> None:
        """Refresh and import anything new."""
        await self.coordinator.async_resync(clear=False)


class OrnamentResyncButton(OrnamentEntity, ButtonEntity):
    """Throw away the imported history and build it again from scratch."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:database-refresh"
    _attr_translation_key = "resync"

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "resync")

    async def async_press(self) -> None:
        """Clear stored statistics, then re-import every measurement."""
        await self.coordinator.async_resync(clear=True)
