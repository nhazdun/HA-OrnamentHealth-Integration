"""Tests for biomarker sensors, unit handling and history import."""

from __future__ import annotations

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ornament_health.const import DOMAIN

from .conftest import DATE_NEW, DATE_OLD


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration and wait for everything to settle."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_biomarker_sensors_created(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Every biomarker becomes a sensor named from the dictionary."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_vitamin_d_25_hydroxy")
    assert state is not None
    assert state.state == "12.21"
    assert state.attributes["unit_of_measurement"] == "ng/mL"
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["category"] == "Vitamins"
    assert state.attributes["status"] == "normal"
    assert state.attributes["measurement_count"] == 2


async def test_reference_range_converted_to_sensor_unit(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Canonical reference ranges are expressed in the unit the lab used."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_vitamin_d_25_hydroxy")
    assert state.attributes["reference_min"] == 20.0
    assert state.attributes["reference_max"] == 80.0
    assert state.attributes["optimal_min"] == 30.0
    assert state.attributes["optimal_max"] == 50.0


async def test_history_converted_when_lab_changes_unit(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Older readings are converted into the newest reading's unit."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_ferritin")
    assert state.state == "200.0"
    assert state.attributes["unit_of_measurement"] == "ng/mL"
    # 1.0 mcg/L canonical == 1.0 / 0.00224719 ng/mL
    history = state.attributes["history"]
    assert len(history) == 2
    assert round(history[0]["value"], 1) == 445.0
    assert history[1]["value"] == 200.0
    assert state.attributes["trend"] == "down"
    assert state.attributes["is_abnormal"] is True


async def test_unitless_biomarker(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Unitless biomarkers get no unit of measurement."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_ph_urine")
    assert state.state == "5.0"
    assert "unit_of_measurement" not in state.attributes


async def test_duplicate_timestamps_collapse_to_current_reading(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """One reading per instant, and it is the one Ornament lists first."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_prothrombin_time")
    assert state.state == "11.5"
    assert state.attributes["measurement_count"] == 2
    assert [point["value"] for point in state.attributes["history"]] == [10.4, 11.5]
    assert state.attributes["previous_value"] == 10.4
    assert state.attributes["trend"] == "up"


async def test_profile_level_sensors(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostic sensors summarise the profile."""
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.ornament_test_person_biomarkers_tracked").state == "4"
    assert hass.states.get("sensor.ornament_test_person_abnormal_biomarkers").state == "1"
    assert (
        hass.states.get("sensor.ornament_test_person_last_laboratory").state
        == "Test Lab"
    )
    assert (
        hass.states.get("binary_sensor.ornament_test_person_abnormal_results").state
        == "on"
    )


async def test_entities_are_registered_to_one_device(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """All entities belong to the device representing the person."""
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    assert len(entries) == 9  # 4 biomarkers + 4 diagnostics + 1 binary sensor
    assert len({entry.device_id for entry in entries}) == 1


async def test_history_imported_into_statistics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Past measurements land in long-term statistics at their own dates."""
    await _setup(hass, config_entry)
    await async_wait_recording_done(hass)

    statistic_id = "sensor.ornament_test_person_vitamin_d_25_hydroxy"
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(DATE_OLD - 3600),
        None,
        {statistic_id},
        "hour",
        None,
        {"mean"},
    )

    points = stats[statistic_id]
    assert len(points) >= 2
    means = {point["start"]: point["mean"] for point in points}
    assert means[float(DATE_OLD)] == 25.0
    assert means[float(DATE_NEW)] == 12.21


async def test_setup_without_recorder(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Sensors still work when statistics cannot be written."""
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.ornament_test_person_ferritin") is not None


async def test_service_registered(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The import_history service is available after setup."""
    await _setup(hass, config_entry)
    assert hass.services.has_service(DOMAIN, "import_history")


async def test_unload(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Unloading removes the entities."""
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.ornament_test_person_ferritin") is None
