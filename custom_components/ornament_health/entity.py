"""Shared entity base for Ornament Health."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import OrnamentCoordinator


class OrnamentEntity(CoordinatorEntity[OrnamentCoordinator]):
    """Base entity bound to the device representing one person."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OrnamentCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.profile_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.profile_id)},
            manufacturer=MANUFACTURER,
            model="Health profile",
            name=f"Ornament {coordinator.profile_name}",
            configuration_url="https://ornament.health",
        )
