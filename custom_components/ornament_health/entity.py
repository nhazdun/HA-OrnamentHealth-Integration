"""Shared entity base for Ornament Health."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import OrnamentCoordinator


class OrnamentEntity(CoordinatorEntity[OrnamentCoordinator]):
    """Base entity bound to the device representing one person."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OrnamentCoordinator,
        key: str,
        category: str | None = None,
        category_id: int | None = None,
    ) -> None:
        """Initialise the entity, on the profile or one of its categories."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.profile_id}_{key}"
        profile_device = (DOMAIN, coordinator.profile_id)

        if category and category_id is not None:
            # Each lab panel becomes its own device, so a profile with 150
            # biomarkers reads as a handful of panels instead of one long list.
            self._attr_device_info = DeviceInfo(
                identifiers={
                    (DOMAIN, f"{coordinator.profile_id}_category_{category_id}")
                },
                manufacturer=MANUFACTURER,
                model="Biomarker panel",
                name=f"Ornament {coordinator.profile_name} {category}",
                via_device=profile_device,
                configuration_url="https://ornament.health",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={profile_device},
                manufacturer=MANUFACTURER,
                model="Health profile",
                name=f"Ornament {coordinator.profile_name}",
                configuration_url="https://ornament.health",
            )
