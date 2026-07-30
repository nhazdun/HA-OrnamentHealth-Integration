"""The Ornament Health integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OrnamentClient
from .const import (
    CONF_SCAN_INTERVAL_HOURS,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_IMPORT_HISTORY,
)
from .coordinator import OrnamentConfigEntry, OrnamentCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: OrnamentConfigEntry) -> bool:
    """Set up Ornament Health from a config entry."""
    client = OrnamentClient(async_get_clientsession(hass), entry.data[CONF_TOKEN])
    coordinator = OrnamentCoordinator(hass, entry, client)

    interval_hours = entry.options.get(CONF_SCAN_INTERVAL_HOURS)
    if interval_hours:
        coordinator.update_interval = timedelta(hours=int(interval_hours))
    else:
        coordinator.update_interval = DEFAULT_SCAN_INTERVAL

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

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

    async def _async_import_history(call: ServiceCall) -> None:
        """Re-import every biomarker's history into long-term statistics."""
        entries: list[OrnamentConfigEntry] = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if hasattr(entry, "runtime_data")
        ]
        for entry in entries:
            coordinator = entry.runtime_data
            await coordinator.async_request_refresh()
            for callback_fn in list(coordinator.history_importers):
                await callback_fn(force=True)

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, _async_import_history)
