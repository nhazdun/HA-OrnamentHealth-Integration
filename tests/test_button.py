"""Tests for the sync and resync buttons."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

SYNC = "button.ornament_test_person_sync_now"
RESYNC = "button.ornament_test_person_resync_all_data"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration and wait for everything to settle."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    """Press a button and wait for it to finish."""
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_buttons_created(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Both buttons exist on the profile device."""
    await _setup(hass, config_entry)

    assert hass.states.get(SYNC) is not None
    assert hass.states.get(RESYNC) is not None


async def test_sync_button_keeps_existing_statistics(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Sync now refreshes without discarding what was imported."""
    await _setup(hass, config_entry)

    with patch(
        "custom_components.ornament_health.coordinator.async_clear_statistics"
    ) as clear:
        await _press(hass, SYNC)

    clear.assert_not_called()


async def test_resync_button_clears_then_reimports(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Resync wipes the stored statistics before importing again."""
    await _setup(hass, config_entry)

    with (
        patch(
            "custom_components.ornament_health.coordinator.async_clear_statistics"
        ) as clear,
        patch(
            "custom_components.ornament_health.sensor.async_import_measurements"
        ) as import_measurements,
    ):
        await _press(hass, RESYNC)

    cleared = clear.call_args.args[1]
    # Numeric biomarkers only - qualitative ones never had statistics.
    assert "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy" in cleared
    assert (
        "sensor.ornament_test_person_urinalysis_mucus_urine_qualitative" not in cleared
    )

    reimported = {call.args[1] for call in import_measurements.call_args_list}
    assert "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy" in reimported
