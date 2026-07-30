"""Coordinator that keeps one Ornament profile in sync with Home Assistant."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BiomarkerDefinition,
    OrnamentApiError,
    OrnamentAuthError,
    OrnamentClient,
    Thesaurus,
)
from .const import (
    CONF_LANGUAGE,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .model import Biomarker, Measurement, OrnamentData, Submission

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Keep at most this many significant digits after converting between units, so a
# 12.21 ng/mL reading does not surface as 12.209999999999999.
SIGNIFICANT_DIGITS = 10
REFERENCE_TOLERANCE = 0.001

type OrnamentConfigEntry = ConfigEntry[OrnamentCoordinator]


class OrnamentCoordinator(DataUpdateCoordinator[OrnamentData]):
    """Fetch biomarkers for a profile and shape them for Home Assistant."""

    config_entry: OrnamentConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OrnamentConfigEntry,
        client: OrnamentClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data.get(CONF_PROFILE_NAME, '')}".strip(),
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.profile_id: str = entry.data[CONF_PROFILE_ID]
        self.profile_name: str = entry.data.get(CONF_PROFILE_NAME) or self.profile_id
        self.language: str = entry.options.get(
            CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        )
        self.thesaurus = Thesaurus()
        # Sensors register a coroutine here so the import_history service can
        # re-run the statistics backfill for every entity at once.
        self.history_importers: list[Callable[..., Awaitable[None]]] = []
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.thesaurus.{self.language}"
        )
        self._thesaurus_loaded = False

    async def _async_setup(self) -> None:
        """Load the static dictionaries once before the first refresh."""
        await self._async_load_thesaurus_cache()

    async def _async_load_thesaurus_cache(self) -> None:
        """Restore the cached biomarker dictionary from disk."""
        cached = await self._store.async_load()
        if not cached:
            return
        definitions: dict[int, BiomarkerDefinition] = {}
        for raw_id, item in (cached.get("biomarkers") or {}).items():
            try:
                biomarker_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            definitions[biomarker_id] = BiomarkerDefinition(
                id=biomarker_id,
                title=item.get("title") or f"Biomarker {biomarker_id}",
                category_id=item.get("category_id"),
                is_unitless=bool(item.get("is_unitless")),
                unit_factors={
                    int(unit_id): float(factor)
                    for unit_id, factor in (item.get("unit_factors") or {}).items()
                },
            )
        self.thesaurus = Thesaurus(
            biomarkers=definitions,
            units={
                int(unit_id): title
                for unit_id, title in (cached.get("units") or {}).items()
            },
            categories={
                int(category_id): title
                for category_id, title in (cached.get("categories") or {}).items()
            },
            digest=cached.get("digest"),
        )
        self._thesaurus_loaded = bool(definitions)

    async def _async_save_thesaurus_cache(self, needed_ids: set[int]) -> None:
        """Persist only the dictionary entries this profile actually uses.

        The full dictionary is ~1.6 MB for ~5000 biomarkers while a profile
        typically references a couple of hundred, so caching the subset keeps
        the store small without costing an extra download.
        """
        await self._store.async_save(
            {
                "digest": self.thesaurus.digest,
                "biomarkers": {
                    str(biomarker_id): {
                        "title": definition.title,
                        "category_id": definition.category_id,
                        "is_unitless": definition.is_unitless,
                        "unit_factors": {
                            str(unit_id): factor
                            for unit_id, factor in definition.unit_factors.items()
                        },
                    }
                    for biomarker_id, definition in self.thesaurus.biomarkers.items()
                    if biomarker_id in needed_ids
                },
                "units": {
                    str(unit_id): title
                    for unit_id, title in self.thesaurus.units.items()
                },
                "categories": {
                    str(category_id): title
                    for category_id, title in self.thesaurus.categories.items()
                },
            }
        )

    async def _async_refresh_thesaurus(self, force: bool = False) -> None:
        """Download the dictionaries when the cached copy is stale."""
        digest = None if force else self.thesaurus.digest
        definitions, new_digest = await self.client.async_get_thesaurus(
            self.language, digest
        )
        if definitions is not None:
            self.thesaurus.biomarkers = definitions
        self.thesaurus.digest = new_digest
        if not self.thesaurus.units:
            self.thesaurus.units = await self.client.async_get_units(self.language)
        if not self.thesaurus.categories:
            self.thesaurus.categories = await self.client.async_get_categories()
        self._thesaurus_loaded = True

    async def _async_update_data(self) -> OrnamentData:
        """Fetch the profile's biomarkers and submissions."""
        try:
            if not self._thesaurus_loaded:
                await self._async_refresh_thesaurus()

            payload = await self.client.async_get_biomarkers(self.profile_id)
            needed_ids = {
                int(item["id"])
                for item in payload.get("biomarkers", [])
                if item.get("id") is not None
            }
            # A brand new biomarker will be missing from the cached subset, so
            # pull a fresh dictionary ignoring the digest we hold.
            if needed_ids - set(self.thesaurus.biomarkers):
                await self._async_refresh_thesaurus(force=True)

            data = OrnamentData(
                biomarkers=self._parse_biomarkers(payload),
                submissions=await self._async_fetch_submissions(),
            )
        except OrnamentAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OrnamentApiError as err:
            raise UpdateFailed(str(err)) from err

        await self._async_save_thesaurus_cache(set(data.biomarkers))
        return data

    async def _async_fetch_submissions(self) -> list[Submission]:
        """Return lab reports, tolerating an unavailable submissions endpoint."""
        try:
            payload = await self.client.async_get_submissions(self.profile_id)
        except OrnamentApiError as err:
            _LOGGER.debug("Could not load submissions: %s", err)
            return []

        submissions: list[Submission] = []
        for item in payload.get("submissions", []):
            if item.get("isDeleted"):
                continue
            date = item.get("date")
            laboratory = (item.get("laboratory") or {}).get("title")
            submissions.append(
                Submission(
                    sid=str(item.get("sid")),
                    timestamp=(
                        dt_util.utc_from_timestamp(date)
                        if isinstance(date, (int, float)) and item.get("hasDate", True)
                        else None
                    ),
                    laboratory=laboratory,
                    entry_count=len(item.get("entries") or []),
                )
            )
        return submissions

    def _parse_biomarkers(self, payload: dict[str, Any]) -> dict[int, Biomarker]:
        """Turn the raw API payload into biomarkers with a consistent unit."""
        refs = payload.get("refs") or {}
        biomarkers: dict[int, Biomarker] = {}

        for item in payload.get("biomarkers", []):
            try:
                biomarker_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            # Ornament returns entries newest first, and a single lab report can
            # carry two readings of one biomarker with the same timestamp (a
            # result and its control value). Sorting oldest first while reversing
            # ties keeps the reading Ornament treats as current at the end.
            entries = [
                entry
                for _, entry in sorted(
                    enumerate(
                        entry
                        for entry in item.get("entries") or []
                        if entry.get("date")
                    ),
                    key=lambda pair: (pair[1]["date"], -pair[0]),
                )
            ]
            if not entries:
                continue

            definition = self.thesaurus.biomarkers.get(biomarker_id)
            is_unitless = bool(item.get("isUnitless")) or (
                definition.is_unitless if definition else False
            )

            # Ornament stores every value twice: `value` in a canonical unit and
            # `originalValue` in whatever unit the lab used. Pin the sensor to
            # the newest entry's unit and convert the rest through the canonical
            # value, so a lab switching units does not corrupt the history.
            target_unit_id = entries[-1].get("originalUnitId")
            options = self.thesaurus.unit_options(target_unit_id)
            # A qualitative result is already 0 or 1 - converting it through a
            # unit factor would be meaningless.
            factor = (
                None
                if options
                else self._unit_factor(definition, target_unit_id, entries)
            )

            # Uploading the same lab report twice leaves two entries with one
            # timestamp, and a report can also pair a result with its control
            # value. Keeping one reading per instant stops the duplicate from
            # becoming the "previous" value and flattening the trend.
            by_timestamp: dict[int, Measurement] = {}
            for entry in entries:
                value = self._entry_value(entry, target_unit_id, factor)
                if value is None:
                    continue
                by_timestamp[entry["date"]] = Measurement(
                    timestamp=dt_util.utc_from_timestamp(entry["date"]),
                    value=value,
                )
            measurements = [by_timestamp[key] for key in sorted(by_timestamp)]
            if not measurements:
                continue

            reference = refs.get(str(biomarker_id)) or {}
            common = self._convert_range(reference.get("common"), factor)
            optimal = self._convert_range(
                reference.get("optimal") or reference.get("paidOptimal"), factor
            )

            category_id = item.get("categoryId")
            if category_id is None and definition is not None:
                category_id = definition.category_id

            biomarkers[biomarker_id] = Biomarker(
                id=biomarker_id,
                title=self.thesaurus.biomarker_title(biomarker_id),
                unit=None if is_unitless else self.thesaurus.unit_title(target_unit_id),
                category=self.thesaurus.category_title(category_id),
                category_id=category_id,
                status=item.get("status"),
                measurements=measurements,
                reference_min=common[0],
                reference_max=common[1],
                optimal_min=optimal[0],
                optimal_max=optimal[1],
                options=options,
            )
        return biomarkers

    @staticmethod
    def _unit_factor(
        definition: BiomarkerDefinition | None,
        unit_id: int | None,
        entries: list[dict[str, Any]],
    ) -> float | None:
        """Return canonical-value-per-original-unit for the target unit."""
        if definition is not None and unit_id is not None:
            factor = definition.unit_factors.get(unit_id)
            if factor:
                return factor
        # Fall back to deriving the factor from an entry recorded in that unit.
        for entry in reversed(entries):
            if entry.get("originalUnitId") != unit_id:
                continue
            try:
                original = float(entry["originalValue"])
                canonical = float(entry["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if original:
                return canonical / original
        return None

    @classmethod
    def _entry_value(
        cls, entry: dict[str, Any], target_unit_id: int | None, factor: float | None
    ) -> float | None:
        """Return an entry's value expressed in the sensor's unit."""
        if entry.get("originalUnitId") == target_unit_id:
            try:
                return float(entry["originalValue"])
            except (KeyError, TypeError, ValueError):
                pass
        if factor:
            try:
                return cls._round(float(entry["value"]) / factor)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                return None
        try:
            return float(entry["value"])
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def _convert_range(
        cls, values: Any, factor: float | None
    ) -> tuple[float | None, float | None]:
        """Convert a canonical reference range into the sensor's unit."""
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            return None, None
        try:
            low, high = float(values[0]), float(values[1])
        except (TypeError, ValueError):
            return None, None
        if factor:
            low = cls._round_reference(low / factor)
            high = cls._round_reference(high / factor)
        return low, high

    @staticmethod
    def _round_reference(value: float) -> float:
        """Return the tidiest number that still means the same limit.

        Ornament derives its canonical ranges with slightly different factors
        than it publishes, so dividing back leaves noise: a 20-80 ng/mL vitamin D
        range comes out as 20.0-80.0064. Reference limits are guide rails rather
        than precise measurements, so take the shortest representation that stays
        within a tenth of a percent of the converted value.
        """
        for digits in range(2, SIGNIFICANT_DIGITS + 1):
            candidate = float(f"%.{digits}g" % value)
            if abs(candidate - value) <= abs(value) * REFERENCE_TOLERANCE:
                return candidate
        return value

    @staticmethod
    def _round(value: float, digits: int = SIGNIFICANT_DIGITS) -> float:
        """Drop floating point noise introduced by unit conversion."""
        return float(f"%.{digits}g" % value)
