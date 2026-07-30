"""The Ornament Health integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OrnamentClient
from .config_flow import scan_interval_minutes
from .const import (
    CONF_TOKEN,
    DOMAIN,
    SERVICE_IMPORT_HISTORY,
    SERVICE_RESYNC,
)
from .coordinator import OrnamentConfigEntry, OrnamentCoordinator
from .entity import profile_device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: OrnamentConfigEntry) -> bool:
    """Set up Ornament Health from a config entry."""
    client = OrnamentClient(async_get_clientsession(hass), entry.data[CONF_TOKEN])
    coordinator = OrnamentCoordinator(hass, entry, client)

    coordinator.update_interval = timedelta(
        minutes=scan_interval_minutes(entry.options)
    )

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Register the person's own device up front: the per-category panels point
    # at it with via_device, and that link is only recorded if the target
    # already exists when the panel is created.
    device_registry.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **profile_device_info(coordinator)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrnamentConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: OrnamentConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration wide services once."""
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORY):
        return

    def _loaded_coordinators() -> list[OrnamentCoordinator]:
        return [
            entry.runtime_data
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if hasattr(entry, "runtime_data")
        ]

    async def _async_import_history(call: ServiceCall) -> None:
        """Re-import every biomarker's history into long-term statistics."""
        for coordinator in _loaded_coordinators():
            await coordinator.async_resync(clear=False)

    async def _async_resync(call: ServiceCall) -> None:
        """Discard the imported history and build it again from scratch."""
        for coordinator in _loaded_coordinators():
            await coordinator.async_resync(clear=True)

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, _async_import_history)
    hass.services.async_register(DOMAIN, SERVICE_RESYNC, _async_resync)
