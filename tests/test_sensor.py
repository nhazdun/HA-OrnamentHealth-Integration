"""Tests for biomarker sensors, unit handling and history import."""

from __future__ import annotations

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ornament_health.const import DOMAIN

from .conftest import DATE_NEW, DATE_OLD, PROFILE_ID


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

    state = hass.states.get("sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy")
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

    state = hass.states.get("sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy")
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

    state = hass.states.get("sensor.ornament_test_person_anemia_ferritin")
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

    state = hass.states.get("sensor.ornament_test_person_urine_ph_urine")
    assert state.state == "5.0"
    assert "unit_of_measurement" not in state.attributes


async def test_duplicate_timestamps_collapse_to_current_reading(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """One reading per instant, and it is the one Ornament lists first."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_urine_prothrombin_time")
    assert state.state == "11.5"
    assert state.attributes["measurement_count"] == 2
    assert [point["value"] for point in state.attributes["history"]] == [10.4, 11.5]
    assert state.attributes["previous_value"] == 10.4
    assert state.attributes["trend"] == "up"


async def test_qualitative_biomarker_reads_as_wording(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A qualitative result shows its wording, not the raw 0/1 or the unit."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_urine_mucus_urine_qualitative")
    assert state.state == "Detected"
    assert "unit_of_measurement" not in state.attributes
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == ["Undetected", "Detected"]
    assert state.attributes["normal_options"] == ["Undetected"]
    assert state.attributes["previous_value"] == "Undetected"
    assert [point["value"] for point in state.attributes["history"]] == [
        "Undetected",
        "Detected",
    ]
    assert "state_class" not in state.attributes


async def test_qualitative_biomarker_has_no_statistics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Wording cannot go into long-term statistics, so none is written."""
    await _setup(hass, config_entry)
    await async_wait_recording_done(hass)

    statistic_id = "sensor.ornament_test_person_urine_mucus_urine_qualitative"
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
    assert statistic_id not in stats


async def test_profile_level_sensors(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostic sensors summarise the profile."""
    await _setup(hass, config_entry)

    assert (
        hass.states.get("sensor.ornament_test_person_biomarkers_tracked").state == "5"
    )
    assert (
        hass.states.get("sensor.ornament_test_person_abnormal_biomarkers").state == "2"
    )
    assert (
        hass.states.get("sensor.ornament_test_person_last_laboratory").state
        == "Test Lab"
    )
    assert (
        hass.states.get("binary_sensor.ornament_test_person_abnormal_results").state
        == "on"
    )


async def test_biomarkers_are_grouped_into_category_devices(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Each lab panel is its own device, hanging off the profile."""
    await _setup(hass, config_entry)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    # 5 biomarkers + 4 diagnostics + 1 binary sensor + 2 buttons
    assert len(entries) == 12

    profile_device = device_registry.async_get_device(
        identifiers={(DOMAIN, PROFILE_ID)}
    )
    assert profile_device is not None

    # Vitamins, Anemia and Urine, each linked back to the profile.
    panels = [
        device
        for device in dr.async_entries_for_config_entry(
            device_registry, config_entry.entry_id
        )
        if device.id != profile_device.id
    ]
    assert {device.name for device in panels} == {
        "Ornament Test Person Vitamins",
        "Ornament Test Person Anemia",
        "Ornament Test Person Urine",
    }
    assert all(device.via_device_id == profile_device.id for device in panels)

    vitamin_d = entity_registry.async_get(
        "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy"
    )
    assert (
        device_registry.async_get(vitamin_d.device_id).name
        == "Ornament Test Person Vitamins"
    )

    # Profile-level sensors stay on the profile device itself.
    tracked = entity_registry.async_get(
        "sensor.ornament_test_person_biomarkers_tracked"
    )
    assert tracked.device_id == profile_device.id


async def test_reference_ranges_are_numeric(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Reference bounds are numbers, usable in templates and charts."""
    await _setup(hass, config_entry)

    attributes = hass.states.get(
        "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy"
    ).attributes
    for key in ("reference_min", "reference_max", "optimal_min", "optimal_max"):
        assert isinstance(attributes[key], (int, float))
        assert not isinstance(attributes[key], bool)


async def test_history_imported_into_statistics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Past measurements land in long-term statistics at their own dates."""
    await _setup(hass, config_entry)
    await async_wait_recording_done(hass)

    statistic_id = "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy"
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
    assert hass.states.get("sensor.ornament_test_person_anemia_ferritin") is not None


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
    assert (
        hass.states.get("sensor.ornament_test_person_anemia_ferritin").state
        == "unavailable"
    )
