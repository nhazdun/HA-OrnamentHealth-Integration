"""Sensors exposing every Ornament biomarker, with its full history."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_BIOMARKER_ID,
    ATTR_BIOMATERIAL,
    ATTR_CATEGORY,
    ATTR_FIRST_MEASURED_AT,
    ATTR_HISTORY,
    ATTR_IS_ABNORMAL,
    ATTR_MEASURED_AT,
    ATTR_MEASUREMENT_COUNT,
    ATTR_NAMES,
    ATTR_NORMAL_OPTIONS,
    ATTR_OPTIMAL_MAX,
    ATTR_OPTIMAL_MIN,
    ATTR_PREVIOUS_MEASURED_AT,
    ATTR_PREVIOUS_VALUE,
    ATTR_REFERENCE_MAX,
    ATTR_REFERENCE_MIN,
    ATTR_STATUS,
    ATTR_SYNONYMS,
    ATTR_TREND,
    CONF_HISTORY_ATTRIBUTE_LIMIT,
    CONF_IMPORT_HISTORY,
    DEFAULT_HISTORY_ATTRIBUTE_LIMIT,
    DEFAULT_IMPORT_HISTORY,
    STATUS_ABNORMAL,
)
from .coordinator import OrnamentConfigEntry, OrnamentCoordinator
from .entity import OrnamentEntity
from .icons import biomarker_icon
from .model import Biomarker
from .statistics import async_import_measurements

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OrnamentConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one sensor per biomarker plus a few profile level sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        OrnamentBiomarkerSensor(coordinator, biomarker_id)
        for biomarker_id in sorted(coordinator.data.biomarkers)
    ]
    entities.extend(
        [
            OrnamentBiomarkerCountSensor(coordinator),
            OrnamentAbnormalCountSensor(coordinator),
            OrnamentLastReportSensor(coordinator),
            OrnamentLaboratorySensor(coordinator),
        ]
    )
    async_add_entities(entities)

    known_ids = set(coordinator.data.biomarkers)

    @callback
    def _async_add_new_biomarkers() -> None:
        """Create sensors for biomarkers that appear in later lab reports."""
        new_ids = set(coordinator.data.biomarkers) - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            OrnamentBiomarkerSensor(coordinator, biomarker_id)
            for biomarker_id in sorted(new_ids)
        )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_biomarkers))


class OrnamentBiomarkerSensor(OrnamentEntity, SensorEntity):
    """A single biomarker, holding its latest value and its whole history."""

    def __init__(self, coordinator: OrnamentCoordinator, biomarker_id: int) -> None:
        """Initialise the biomarker sensor."""
        biomarker = coordinator.data.biomarkers.get(biomarker_id)
        super().__init__(
            coordinator,
            f"biomarker_{biomarker_id}",
            category=biomarker.category if biomarker else None,
            category_id=biomarker.category_id if biomarker else None,
        )
        self._biomarker_id = biomarker_id
        self._imported_through: datetime | None = None
        self._attr_icon = biomarker_icon(
            biomarker.category_id if biomarker else None,
            biomarker.biomaterial_id if biomarker else None,
        )
        if biomarker is not None:
            self._attr_name = biomarker.title
            if biomarker.is_qualitative:
                # An outcome such as Detected is a state, not a measurement, so
                # it carries no unit and no statistics.
                self._attr_device_class = SensorDeviceClass.ENUM
                self._attr_options = biomarker.options
            else:
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self._attr_native_unit_of_measurement = biomarker.unit

    @property
    def _biomarker(self) -> Biomarker | None:
        """Return the current data for this biomarker."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.biomarkers.get(self._biomarker_id)

    @property
    def available(self) -> bool:
        """Return whether the biomarker is still present in the account."""
        return super().available and self._biomarker is not None

    @property
    def native_value(self) -> float | str | None:
        """Return the most recent result."""
        biomarker = self._biomarker
        if biomarker is None or biomarker.latest is None:
            return None
        return biomarker.label(biomarker.latest.value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the lab reported the newest value in."""
        biomarker = self._biomarker
        if biomarker is None:
            return self._attr_native_unit_of_measurement
        return None if biomarker.is_qualitative else biomarker.unit

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return reference ranges, trend and the measurement history."""
        biomarker = self._biomarker
        if biomarker is None or biomarker.latest is None:
            return None

        attributes: dict[str, Any] = {
            ATTR_BIOMARKER_ID: biomarker.id,
            ATTR_CATEGORY: biomarker.category,
            ATTR_BIOMATERIAL: biomarker.biomaterial,
            ATTR_STATUS: "abnormal" if biomarker.is_abnormal else "normal",
            ATTR_IS_ABNORMAL: biomarker.is_abnormal,
            ATTR_MEASURED_AT: biomarker.latest.timestamp.isoformat(),
            ATTR_MEASUREMENT_COUNT: len(biomarker.measurements),
            ATTR_FIRST_MEASURED_AT: biomarker.measurements[0].timestamp.isoformat(),
        }

        if biomarker.is_qualitative:
            attributes[ATTR_NORMAL_OPTIONS] = biomarker.normal_options
        else:
            attributes[ATTR_REFERENCE_MIN] = biomarker.reference_min
            attributes[ATTR_REFERENCE_MAX] = biomarker.reference_max
            attributes[ATTR_OPTIMAL_MIN] = biomarker.optimal_min
            attributes[ATTR_OPTIMAL_MAX] = biomarker.optimal_max

        previous = biomarker.previous
        if previous is not None:
            attributes[ATTR_PREVIOUS_VALUE] = biomarker.label(previous.value)
            attributes[ATTR_PREVIOUS_MEASURED_AT] = previous.timestamp.isoformat()
            if not biomarker.is_qualitative:
                attributes[ATTR_TREND] = biomarker.trend

        if biomarker.synonyms:
            attributes[ATTR_SYNONYMS] = biomarker.synonyms
        if biomarker.names:
            attributes[ATTR_NAMES] = biomarker.names

        limit = int(
            self.coordinator.config_entry.options.get(
                CONF_HISTORY_ATTRIBUTE_LIMIT, DEFAULT_HISTORY_ATTRIBUTE_LIMIT
            )
        )
        if limit:
            attributes[ATTR_HISTORY] = [
                {
                    "date": measurement.timestamp.isoformat(),
                    "value": biomarker.label(measurement.value),
                }
                for measurement in biomarker.measurements[-limit:]
            ]
        return attributes

    async def async_added_to_hass(self) -> None:
        """Register for updates and backfill the history once known."""
        await super().async_added_to_hass()
        self.coordinator.history_importers.append(self.async_import_history)
        self.async_on_remove(
            lambda: self.coordinator.history_importers.remove(self.async_import_history)
        )
        biomarker = self._biomarker
        if biomarker is not None and not biomarker.is_qualitative:
            self.coordinator.statistic_ids.add(self.entity_id)
            self.async_on_remove(
                lambda: self.coordinator.statistic_ids.discard(self.entity_id)
            )
        await self.async_import_history()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the new state and import any newly published measurements."""
        super()._handle_coordinator_update()
        self.coordinator.config_entry.async_create_task(
            self.hass,
            self.async_import_history(),
            name=f"ornament_health import {self.entity_id}",
        )

    async def async_import_history(self, force: bool = False) -> None:
        """Push this biomarker's measurements into long-term statistics."""
        biomarker = self._biomarker
        if biomarker is None or not biomarker.measurements:
            return
        if biomarker.is_qualitative:
            # Long-term statistics only hold numbers, and Detected is not one.
            return
        if not self.coordinator.config_entry.options.get(
            CONF_IMPORT_HISTORY, DEFAULT_IMPORT_HISTORY
        ):
            return

        latest = biomarker.measurements[-1].timestamp
        if not force and self._imported_through == latest:
            return
        if force:
            # A resync may have wiped the stored statistics, so never skip.
            self._imported_through = None

        await async_import_measurements(
            self.hass, self.entity_id, biomarker.unit, biomarker.measurements
        )
        self._imported_through = latest


class OrnamentBiomarkerCountSensor(OrnamentEntity, SensorEntity):
    """How many biomarkers the profile has on record."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:counter"
    _attr_translation_key = "biomarker_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "biomarker_count")

    @property
    def native_value(self) -> int:
        """Return the number of biomarkers."""
        return len(self.coordinator.data.biomarkers)


class OrnamentAbnormalCountSensor(OrnamentEntity, SensorEntity):
    """How many biomarkers are currently out of their reference range."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"
    _attr_translation_key = "abnormal_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "abnormal_count")

    @property
    def native_value(self) -> int:
        """Return the number of abnormal biomarkers."""
        return self.coordinator.data.abnormal_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List which biomarkers are abnormal."""
        return {
            "biomarkers": sorted(
                biomarker.title
                for biomarker in self.coordinator.data.biomarkers.values()
                if biomarker.status == STATUS_ABNORMAL
            )
        }


class OrnamentLastReportSensor(OrnamentEntity, SensorEntity):
    """When the most recent lab report was taken."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "last_report"

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "last_report")

    @property
    def native_value(self) -> datetime | None:
        """Return the newest submission date."""
        submission = self.coordinator.data.latest_submission
        return submission.timestamp if submission else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the newest submission."""
        submission = self.coordinator.data.latest_submission
        return {
            "laboratory": submission.laboratory if submission else None,
            "results_in_report": submission.entry_count if submission else None,
            "reports_total": len(self.coordinator.data.submissions),
        }


class OrnamentLaboratorySensor(OrnamentEntity, SensorEntity):
    """Which lab produced the most recent report."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:hospital-building"
    _attr_translation_key = "last_laboratory"

    def __init__(self, coordinator: OrnamentCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "last_laboratory")

    @property
    def native_value(self) -> str | None:
        """Return the laboratory name."""
        submission = self.coordinator.data.latest_submission
        return submission.laboratory if submission else None
