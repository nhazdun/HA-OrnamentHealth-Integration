"""Client for the public Ornament Health API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import ClientResponseError, ClientSession

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=60)

PATH_LINKED_PROFILES = "/accounting-api/public/v1.0/healer/linked-profiles"
PATH_BIOMARKERS = "/medical-data-api/public/v1.0/profile/biomarkers"
PATH_SUBMISSIONS = "/medical-data-api/public/v1.0/profile/submissions"
PATH_THESAURUS_BIOMARKERS = "/thesaurus-api/public/v1.1/biomarkers"
PATH_MEASUREMENT_UNITS = "/thesaurus-api/public/v1.1/measurement-units"
PATH_BIOMARKER_CATEGORIES = "/thesaurus-api/public/v1.0/biomarker-categories"

# Qualitative units spell their outcomes out in the title, e.g. "Negative|Positive".
QUALITATIVE_SEPARATOR = "|"


class OrnamentApiError(Exception):
    """Raised when the Ornament API returns an unexpected response."""


class OrnamentAuthError(OrnamentApiError):
    """Raised when the API token is missing, invalid or expired."""


@dataclass(slots=True)
class Profile:
    """A person whose medical data is available through the account."""

    pid: str
    name: str
    sex: str | None = None
    birthday: str | None = None
    is_demo: bool = False
    is_archived: bool = False
    last_submissions_update: int | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Profile:
        """Build a profile from an API payload."""
        return cls(
            pid=data["pid"],
            name=data.get("name") or data["pid"],
            sex=data.get("sex"),
            birthday=data.get("birthday"),
            is_demo=bool(data.get("isDemoPatient")),
            is_archived=bool(data.get("isArchived")),
            last_submissions_update=data.get("lastSubmissionsUpdate"),
        )


@dataclass(slots=True)
class BiomarkerDefinition:
    """Dictionary metadata describing a biomarker."""

    id: int
    title: str
    category_id: int | None = None
    is_unitless: bool = False
    # unit id -> factor converting an original value into the canonical value
    unit_factors: dict[int, float] = field(default_factory=dict)


@dataclass(slots=True)
class Thesaurus:
    """Static Ornament dictionaries used to make raw ids human readable."""

    biomarkers: dict[int, BiomarkerDefinition] = field(default_factory=dict)
    units: dict[int, str] = field(default_factory=dict)
    categories: dict[int, str] = field(default_factory=dict)
    digest: str | None = None

    def biomarker_title(self, biomarker_id: int) -> str:
        """Return a display title for a biomarker id."""
        definition = self.biomarkers.get(biomarker_id)
        if definition is not None and definition.title:
            return definition.title
        return f"Biomarker {biomarker_id}"

    def unit_title(self, unit_id: int | None) -> str | None:
        """Return the unit symbol for a unit id, or None for qualitative ones."""
        if unit_id is None:
            return None
        title = self.units.get(unit_id)
        if title and QUALITATIVE_SEPARATOR in title:
            # "Undetected|Detected" names the two outcomes, it is not a unit.
            return None
        return title

    def unit_options(self, unit_id: int | None) -> list[str] | None:
        """Return the outcomes of a qualitative unit, in value order.

        Ornament reports qualitative results as 0 or 1 and puts the wording in
        the unit itself, so "Undetected|Detected" means 0 is Undetected and 1 is
        Detected.
        """
        if unit_id is None:
            return None
        title = self.units.get(unit_id)
        if not title or QUALITATIVE_SEPARATOR not in title:
            return None
        options = [part.strip() for part in title.split(QUALITATIVE_SEPARATOR)]
        return [option for option in options if option] or None

    def category_title(self, category_id: int | None) -> str | None:
        """Return the category name for a category id."""
        if category_id is None:
            return None
        return self.categories.get(category_id)


class OrnamentClient:
    """Thin async wrapper around the endpoints this integration needs."""

    def __init__(self, session: ClientSession, token: str) -> None:
        """Initialise the client with a Home Assistant managed session."""
        self._session = session
        self._token = token

    @property
    def token(self) -> str:
        """Return the token currently in use."""
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a request and return the decoded JSON body."""
        url = f"{API_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise OrnamentAuthError(
                        f"Ornament API rejected the token ({response.status})"
                    )
                if response.status == 429:
                    raise OrnamentApiError("Ornament API rate limit reached")
                response.raise_for_status()
                return await response.json(content_type=None)
        except OrnamentApiError:
            raise
        except ClientResponseError as err:
            raise OrnamentApiError(
                f"Ornament API returned {err.status} for {path}"
            ) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise OrnamentApiError(f"Error talking to the Ornament API: {err}") from err

    async def async_get_profiles(self) -> list[Profile]:
        """Return every profile linked to the account behind the token."""
        payload = await self._request("GET", PATH_LINKED_PROFILES)
        if not isinstance(payload, list):
            raise OrnamentApiError("Unexpected linked-profiles payload")
        return [Profile.from_json(item) for item in payload]

    async def async_get_biomarkers(self, pid: str) -> dict[str, Any]:
        """Return every biomarker record ever stored for a profile."""
        payload = await self._request(
            "GET",
            PATH_BIOMARKERS,
            # dateFrom=0 asks for the full history rather than a recent window.
            params={"pid": pid, "dateFrom": 0},
        )
        if not isinstance(payload, dict):
            raise OrnamentApiError("Unexpected biomarkers payload")
        return payload

    async def async_get_submissions(self, pid: str) -> dict[str, Any]:
        """Return lab submissions (test uploads) for a profile."""
        payload = await self._request("GET", PATH_SUBMISSIONS, params={"pid": pid})
        if not isinstance(payload, dict):
            raise OrnamentApiError("Unexpected submissions payload")
        return payload

    async def async_get_thesaurus(
        self, language: str, digest: str | None = None
    ) -> tuple[dict[int, BiomarkerDefinition] | None, str | None]:
        """Return the biomarker dictionary, or None when the digest still matches.

        The dictionary is ~1.6 MB, so the API lets callers pass the digest of the
        copy they already hold and answers with needToUpdate=false instead.
        """
        body: dict[str, Any] = {"lang": language}
        if digest:
            body["digest"] = digest
        payload = await self._request("POST", PATH_THESAURUS_BIOMARKERS, json_body=body)
        if not isinstance(payload, dict):
            raise OrnamentApiError("Unexpected thesaurus payload")

        new_digest = payload.get("digest")
        if not payload.get("needToUpdate", True):
            return None, new_digest

        definitions: dict[int, BiomarkerDefinition] = {}
        for item in payload.get("biomarkers", []):
            try:
                biomarker_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            unit_factors: dict[int, float] = {}
            for pair in item.get("unitsFactors") or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    try:
                        unit_factors[int(pair[0])] = float(pair[1])
                    except (TypeError, ValueError):
                        continue
            definitions[biomarker_id] = BiomarkerDefinition(
                id=biomarker_id,
                title=str(item.get("title") or f"Biomarker {biomarker_id}"),
                category_id=item.get("displayCategoryId"),
                is_unitless=bool(item.get("isUnitless")),
                unit_factors=unit_factors,
            )
        return definitions, new_digest

    async def async_get_units(self, language: str) -> dict[int, str]:
        """Return the measurement unit dictionary."""
        payload = await self._request(
            "GET", PATH_MEASUREMENT_UNITS, params={"lang": language}
        )
        if not isinstance(payload, list):
            raise OrnamentApiError("Unexpected measurement-units payload")
        units: dict[int, str] = {}
        for item in payload:
            try:
                units[int(item["id"])] = str(item["title"])
            except (KeyError, TypeError, ValueError):
                continue
        return units

    async def async_get_categories(self, language: str) -> dict[int, str]:
        """Return the biomarker category dictionary."""
        payload = await self._request(
            "GET", PATH_BIOMARKER_CATEGORIES, params={"lang": language}
        )
        if not isinstance(payload, list):
            raise OrnamentApiError("Unexpected biomarker-categories payload")
        categories: dict[int, str] = {}
        for item in payload:
            try:
                categories[int(item["id"])] = str(item["title"])
            except (KeyError, TypeError, ValueError):
                continue
        return categories
