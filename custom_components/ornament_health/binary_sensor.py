"""Binary sensor flagging out-of-range results for a profile."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OrnamentConfigEntry, OrnamentCoordinator
from .entity import OrnamentEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrnamentConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the abnormal results binary sensor."""
    async_add_entities([OrnamentAbnormalBinarySensor(entry.runtime_data)])


class OrnamentAbnormalBinarySensor(OrnamentEntity, BinarySensorEntity):
    """On while any biomarker sits outside its reference range."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "abnormal"

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "abnormal")

    @property
    def is_on(self) -> bool:
        """Return whether at least one biomarker is abnormal."""
        return self.coordinator.data.abnormal_count > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the abnormal biomarker count."""
        return {"abnormal_count": self.coordinator.data.abnormal_count}
