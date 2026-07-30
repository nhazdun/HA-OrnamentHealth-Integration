"""Tests for biomarker sensors, unit handling and history import."""

from __future__ import annotations

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ornament_health.const import (
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_TOKEN,
    DOMAIN,
)

from .conftest import (
    BIOMARKERS_PAYLOAD,
    CATEGORIES_PAYLOAD,
    DATE_NEW,
    DATE_OLD,
    PROFILE_ID,
    PROFILES_PAYLOAD,
    SUBMISSIONS_PAYLOAD,
    THESAURUS_PAYLOAD,
    TOKEN,
    UNITS_PAYLOAD,
)


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

    state = hass.states.get(
        "sensor.ornament_test_person_iron_regulatory_proteins_ferritin"
    )
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

    state = hass.states.get("sensor.ornament_test_person_urinalysis_ph_urine")
    assert state.state == "5.0"
    assert "unit_of_measurement" not in state.attributes


async def test_duplicate_timestamps_collapse_to_current_reading(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """One reading per instant, and it is the one Ornament lists first."""
    await _setup(hass, config_entry)

    state = hass.states.get("sensor.ornament_test_person_urinalysis_prothrombin_time")
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

    state = hass.states.get(
        "sensor.ornament_test_person_urinalysis_mucus_urine_qualitative"
    )
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

    statistic_id = "sensor.ornament_test_person_urinalysis_mucus_urine_qualitative"
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
        "Ornament Test Person Iron regulatory proteins",
        "Ornament Test Person Urinalysis",
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
    assert (
        hass.states.get("sensor.ornament_test_person_iron_regulatory_proteins_ferritin")
        is not None
    )


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
        hass.states.get(
            "sensor.ornament_test_person_iron_regulatory_proteins_ferritin"
        ).state
        == "unavailable"
    )


async def test_ukrainian_names_come_from_the_bundled_dictionary(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
) -> None:
    """Ornament has no Ukrainian catalogue, so the bundled titles are used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id="uk-profile",
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
        options={"language": "uk"},
    )
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    coordinator = entry.runtime_data
    assert coordinator.thesaurus.biomarker_title(187) == "Вітамін D, 25-гідрокси"
    assert coordinator.thesaurus.category_title(21) == "Вітаміни"
    # Anything the bundle does not cover keeps the name Ornament supplied.
    assert coordinator.thesaurus.biomarker_title(88) == "Феритин"


async def test_units_fall_back_when_language_has_no_catalogue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An empty unit list for a language must not strip the sensors' units."""
    base = "https://api.ornament.health"
    aioclient_mock.get(
        f"{base}/accounting-api/public/v1.0/healer/linked-profiles",
        json=PROFILES_PAYLOAD,
    )
    aioclient_mock.get(
        f"{base}/medical-data-api/public/v1.0/profile/biomarkers",
        json=BIOMARKERS_PAYLOAD,
    )
    aioclient_mock.get(
        f"{base}/medical-data-api/public/v1.0/profile/submissions",
        json=SUBMISSIONS_PAYLOAD,
    )
    aioclient_mock.post(
        f"{base}/thesaurus-api/public/v1.1/biomarkers", json=THESAURUS_PAYLOAD
    )
    # Ukrainian returns nothing; English is what actually has the catalogue.
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.1/measurement-units?lang=uk", json=[]
    )
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.1/measurement-units?lang=en",
        json=UNITS_PAYLOAD,
    )
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.0/biomarker-categories?lang=uk", json=[]
    )
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.0/biomarker-categories?lang=en",
        json=CATEGORIES_PAYLOAD,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id="uk-units",
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
        options={"language": "uk"},
    )
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    vitamin_d = entry.runtime_data.data.biomarkers[187]
    assert vitamin_d.unit == "ng/mL"
    assert vitamin_d.category == "Вітаміни"


async def test_cache_from_an_older_schema_is_discarded(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A cache written before a field existed is refetched, not reused."""
    from custom_components.ornament_health.coordinator import STORAGE_VERSION

    store = Store(hass, STORAGE_VERSION, "ornament_health.thesaurus.en")
    await store.async_save(
        {
            # No "schema" key: written by a version that knew nothing of
            # biomaterials, so the cached entries lack them.
            "digest": "OLD",
            "biomarkers": {
                "187": {
                    "title": "Vitamin D, 25-Hydroxy",
                    "category_id": 21,
                    "is_unitless": False,
                    "unit_factors": {"56": 2.4773},
                }
            },
            "units": {"56": "ng/mL"},
            "categories": {"21": "Vitamins"},
        }
    )

    await _setup(hass, config_entry)

    assert config_entry.runtime_data.data.biomarkers[187].biomaterial == "Blood"


async def test_cache_without_units_is_refetched(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A cached dictionary missing units cannot be trusted."""
    from custom_components.ornament_health.coordinator import STORAGE_VERSION

    store = Store(hass, STORAGE_VERSION, "ornament_health.thesaurus.en")
    await store.async_save(
        {
            "digest": "STALE",
            "biomarkers": {
                "187": {
                    "title": "Vitamin D, 25-Hydroxy",
                    "category_id": 21,
                    "is_unitless": False,
                    "unit_factors": {"56": 2.4773},
                }
            },
            "units": {},
            "categories": {},
        }
    )

    await _setup(hass, config_entry)

    assert (
        hass.states.get(
            "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy"
        ).attributes["unit_of_measurement"]
        == "ng/mL"
    )


async def test_qualitative_wording_is_translated(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
) -> None:
    """Detected/Undetected read in Ukrainian, while real units stay untouched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id="uk-wording",
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
        options={"language": "uk"},
    )
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    biomarkers = entry.runtime_data.data.biomarkers
    assert biomarkers[531].options == ["Не виявлено", "Виявлено"]
    assert biomarkers[531].label(1.0) == "Виявлено"
    # ng/mL is an international unit and must not be renamed.
    assert biomarkers[187].unit == "ng/mL"


async def test_biomaterial_icon_and_synonyms(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Sensors say what the sample was and carry the spelled-out names."""
    await _setup(hass, config_entry)

    vitamin_d = hass.states.get(
        "sensor.ornament_test_person_vitamins_vitamin_d_25_hydroxy"
    )
    assert vitamin_d.attributes["biomaterial"] == "Blood"
    assert vitamin_d.attributes["synonyms"] == ["Calcidiol"]
    # Vitamins has an icon of its own, which wins over the blood default.
    assert vitamin_d.attributes["icon"] == "mdi:pill"

    urine = hass.states.get("sensor.ornament_test_person_urinalysis_ph_urine")
    assert urine.attributes["biomaterial"] == "Urine"
    assert urine.attributes["icon"] == "mdi:cup-water"


async def test_names_in_extra_languages(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
) -> None:
    """Asking for extra languages adds a names attribute."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id="multilingual",
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
        options={"language": "en", "name_languages": ["uk"]},
    )
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    names = entry.runtime_data.data.biomarkers[187].names
    assert names == {"uk": "Вітамін D, 25-гідрокси"}


async def test_no_extra_downloads_without_the_option(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Nothing multilingual is fetched unless it was asked for."""
    await _setup(hass, config_entry)

    assert entry_names(hass, config_entry) == {}


def entry_names(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    """Return the multilingual names recorded for vitamin D."""
    return entry.runtime_data.data.biomarkers[187].names
