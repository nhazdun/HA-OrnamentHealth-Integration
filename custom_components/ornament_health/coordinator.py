"""Coordinator that keeps one Ornament profile in sync with Home Assistant."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    QUALITATIVE_SEPARATOR,
    BiomarkerDefinition,
    OrnamentApiError,
    OrnamentAuthError,
    OrnamentClient,
    Thesaurus,
)
from .const import (
    CONF_LANGUAGE,
    CONF_NAME_LANGUAGES,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .model import Biomarker, Measurement, OrnamentData, Submission
from .statistics import async_clear_statistics

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Bumped whenever the cached dictionary gains a field OR is filled differently -
# borrowing synonyms counts, since an older cache holds the empty lists the API
# returned. A stale cache is refetched rather than migrated: it is a copy of a
# public dictionary, not user data.
CACHE_SCHEMA = 3
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
        # language -> {biomarker id: title}, for the optional multilingual names
        self.extra_names: dict[str, dict[int, str]] = {}
        # Sensors register a coroutine here so a resync can re-run the
        # statistics backfill for every entity at once, and add their entity_id
        # so the old statistics can be cleared first.
        self.history_importers: list[Callable[..., Awaitable[None]]] = []
        self.statistic_ids: set[str] = set()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.thesaurus.{self.language}"
        )
        self._thesaurus_loaded = False

    async def _async_setup(self) -> None:
        """Load the static dictionaries once before the first refresh."""
        await self._async_load_thesaurus_cache()
        # The cache holds whatever names were current when it was written, so
        # re-apply the bundled ones in case they were updated since.
        await self._async_apply_bundled_translations()

    async def async_resync(self, *, clear: bool) -> None:
        """Re-read everything from Ornament and rebuild the history.

        With clear set, the stored statistics are discarded first, so a run
        recovers from bad data rather than merging on top of it.
        """
        if clear:
            async_clear_statistics(self.hass, sorted(self.statistic_ids))
            # Force the dictionary to be fetched again rather than trusting the
            # cached digest, in case a biomarker was renamed upstream.
            self.thesaurus.digest = None
            self._thesaurus_loaded = False

        await self.async_refresh()
        for import_history in list(self.history_importers):
            await import_history(force=True)

    async def _async_load_thesaurus_cache(self) -> None:
        """Restore the cached biomarker dictionary from disk."""
        cached = await self._store.async_load()
        if not cached or cached.get("schema") != CACHE_SCHEMA:
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
                biomaterial_id=item.get("biomaterial_id"),
                is_unitless=bool(item.get("is_unitless")),
                synonyms=list(item.get("synonyms") or []),
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
            biomaterials={
                int(material_id): title
                for material_id, title in (cached.get("biomaterials") or {}).items()
            },
            digest=cached.get("digest"),
        )
        # Units carry both the symbol and the wording of qualitative results, so
        # a cache without them is incomplete and must be refetched.
        self._thesaurus_loaded = bool(definitions) and bool(self.thesaurus.units)

    async def _async_save_thesaurus_cache(self, needed_ids: set[int]) -> None:
        """Persist only the dictionary entries this profile actually uses.

        The full dictionary is ~1.6 MB for ~5000 biomarkers while a profile
        typically references a couple of hundred, so caching the subset keeps
        the store small without costing an extra download.
        """
        await self._store.async_save(
            {
                "schema": CACHE_SCHEMA,
                "digest": self.thesaurus.digest,
                "biomarkers": {
                    str(biomarker_id): {
                        "title": definition.title,
                        "category_id": definition.category_id,
                        "biomaterial_id": definition.biomaterial_id,
                        "is_unitless": definition.is_unitless,
                        "synonyms": definition.synonyms,
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
                "biomaterials": {
                    str(material_id): title
                    for material_id, title in self.thesaurus.biomaterials.items()
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
            await self._async_borrow_synonyms()
        self.thesaurus.digest = new_digest
        # Ornament answers with an empty list for a language it has no catalogue
        # for - Ukrainian being one - so fall back rather than end up with
        # unnamed panels and sensors that lost their unit.
        if not self.thesaurus.units:
            self.thesaurus.units = await self._async_fetch_with_fallback(
                self.client.async_get_units
            )
        if not self.thesaurus.categories:
            self.thesaurus.categories = await self._async_fetch_with_fallback(
                self.client.async_get_categories
            )
        if not self.thesaurus.biomaterials:
            self.thesaurus.biomaterials = await self._async_fetch_with_fallback(
                self.client.async_get_biomaterials
            )
        await self._async_apply_bundled_translations()
        await self._async_refresh_extra_names()
        self._thesaurus_loaded = True

    def _configured_name_languages(self) -> list[str]:
        """Return the extra languages to fetch names in."""
        chosen = self.config_entry.options.get(CONF_NAME_LANGUAGES) or []
        return [code for code in chosen if code != self.language]

    async def _async_refresh_extra_names(self) -> None:
        """Fetch biomarker names in the additional languages, if any.

        Each language is a separate ~1.6 MB dictionary, so nothing is fetched
        unless the user asked for it.
        """
        wanted = set(self._configured_name_languages())
        for stale in set(self.extra_names) - wanted:
            del self.extra_names[stale]

        for language in sorted(wanted - set(self.extra_names)):
            try:
                definitions, _ = await self.client.async_get_thesaurus(language)
            except OrnamentApiError as err:
                _LOGGER.debug("Could not load %s names: %s", language, err)
                continue
            if not definitions:
                continue
            names = {key: value.title for key, value in definitions.items()}
            bundled = await self._async_load_bundled(language)
            names.update(
                {
                    int(raw_id): title
                    for raw_id, title in (bundled.get("biomarkers") or {}).items()
                }
            )
            self.extra_names[language] = names

    async def _async_borrow_synonyms(self) -> None:
        """Take synonyms from the English dictionary when a language has none.

        Ornament lists synonyms for English, Russian and German but leaves them
        empty for others, and they are the only place a bare abbreviation like
        ALT is spelled out as "Alanine aminotransferase".
        """
        if self.language == DEFAULT_LANGUAGE:
            return
        if any(item.synonyms for item in self.thesaurus.biomarkers.values()):
            return

        try:
            english, _ = await self.client.async_get_thesaurus(DEFAULT_LANGUAGE)
        except OrnamentApiError as err:
            _LOGGER.debug("Could not borrow synonyms: %s", err)
            return
        if not english:
            return
        for biomarker_id, definition in self.thesaurus.biomarkers.items():
            if (source := english.get(biomarker_id)) is not None:
                definition.synonyms = source.synonyms

    async def _async_load_bundled(self, language: str) -> dict[str, dict[str, str]]:
        """Read the catalogue this integration ships for a language, if any."""
        path = Path(__file__).parent / "translations" / f"thesaurus.{language}.json"

        def _load() -> dict[str, dict[str, str]]:
            if not path.is_file():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _LOGGER.warning("Could not read bundled translations at %s", path)
                return {}

        return await self.hass.async_add_executor_job(_load)

    async def _async_fetch_with_fallback(
        self, fetch: Callable[[str], Awaitable[dict[int, str]]]
    ) -> dict[int, str]:
        """Fetch a dictionary, retrying in English if the language has none."""
        result = await fetch(self.language)
        if not result and self.language != DEFAULT_LANGUAGE:
            result = await fetch(DEFAULT_LANGUAGE)
        return result

    async def _async_apply_bundled_translations(self) -> None:
        """Overlay names for languages Ornament does not translate itself.

        Ornament ships Russian, German and Spanish but not Ukrainian, so the
        titles for those languages are kept in the integration and laid over
        whatever the API returned.
        """
        path = (
            Path(__file__).parent / "translations" / f"thesaurus.{self.language}.json"
        )

        def _load() -> dict[str, dict[str, str]]:
            if not path.is_file():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _LOGGER.warning("Could not read bundled translations at %s", path)
                return {}

        bundled = await self.hass.async_add_executor_job(_load)
        if not bundled:
            return

        for raw_id, title in (bundled.get("units") or {}).items():
            current = self.thesaurus.units.get(int(raw_id))
            # Only qualitative "units" are translated - they spell out the two
            # outcomes. Measurement units like ng/mL are international and
            # renaming one would break its statistics.
            if current and QUALITATIVE_SEPARATOR in current:
                self.thesaurus.units[int(raw_id)] = title
        for raw_id, title in (bundled.get("categories") or {}).items():
            self.thesaurus.categories[int(raw_id)] = title
        for raw_id, title in (bundled.get("biomaterials") or {}).items():
            self.thesaurus.biomaterials[int(raw_id)] = title
        for raw_id, title in (bundled.get("biomarkers") or {}).items():
            definition = self.thesaurus.biomarkers.get(int(raw_id))
            if definition is not None:
                definition.title = title

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
                biomaterial=self.thesaurus.biomaterial_title(
                    definition.biomaterial_id if definition else None
                ),
                biomaterial_id=definition.biomaterial_id if definition else None,
                status=item.get("status"),
                synonyms=definition.synonyms if definition else [],
                names={
                    language: names[biomarker_id]
                    for language, names in self.extra_names.items()
                    if biomarker_id in names
                },
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
