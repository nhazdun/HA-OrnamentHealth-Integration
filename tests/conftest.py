"""Fixtures for the Ornament Health tests.

The payloads mirror the shape of real Ornament responses but contain invented
ids and values - no real medical data lives in this repository.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ornament_health.const import (
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_TOKEN,
    DOMAIN,
)

PROFILE_ID = "11111111-2222-3333-4444-555555555555"
OTHER_PROFILE_ID = "99999999-8888-7777-6666-555555555555"
TOKEN = "test-token"

# 2022-01-13T02:00:00Z and 2024-06-01T09:00:00Z
DATE_OLD = 1642039200
DATE_NEW = 1717232400

PROFILES_PAYLOAD: list[dict[str, Any]] = [
    {
        "pid": PROFILE_ID,
        "ssoId": "sso-1",
        "createdAt": 1600000000,
        "name": "Test Person",
        "sex": "M",
        "birthday": "1992-01-01",
        "lastSubmissionsUpdate": DATE_NEW,
        "isArchived": False,
        "isDemoPatient": False,
    },
    {
        "pid": OTHER_PROFILE_ID,
        "ssoId": "sso-2",
        "createdAt": 1600000000,
        "name": "Demo Person",
        "sex": "F",
        "birthday": "1983-01-01",
        "lastSubmissionsUpdate": DATE_OLD,
        "isArchived": True,
        "isDemoPatient": True,
    },
]

# Biomarker 187 is stored canonically at 2.4773 per ng/mL, 337 is unitless.
BIOMARKERS_PAYLOAD: dict[str, Any] = {
    "total": 3,
    "biomarkers": [
        {
            "id": 187,
            "categoryId": 60,
            "isUnitless": False,
            "status": "N",
            "entries": [
                {
                    "seid": "e1",
                    "sid": "s1",
                    "value": "61.9325",
                    "originalValue": "25",
                    "date": DATE_OLD,
                    "originalUnitId": 56,
                },
                {
                    "seid": "e2",
                    "sid": "s2",
                    "value": "30.247833",
                    "originalValue": "12.21",
                    "date": DATE_NEW,
                    "originalUnitId": 56,
                },
            ],
        },
        {
            # Same biomarker measured in two different units over time.
            "id": 88,
            "categoryId": 14,
            "isUnitless": False,
            "status": "A",
            "entries": [
                {
                    "seid": "e3",
                    "sid": "s1",
                    "value": "1.0",
                    "originalValue": "1.0",
                    "date": DATE_OLD,
                    "originalUnitId": 34,
                },
                {
                    "seid": "e4",
                    "sid": "s2",
                    "value": "0.4494380",
                    "originalValue": "200",
                    "date": DATE_NEW,
                    "originalUnitId": 56,
                },
            ],
        },
        {
            "id": 337,
            "categoryId": 27,
            "isUnitless": True,
            "status": "N",
            "entries": [
                {
                    "seid": "e5",
                    "sid": "s1",
                    "value": "5.0",
                    "originalValue": "5",
                    "date": DATE_OLD,
                    "originalUnitId": 1,
                }
            ],
        },
    ],
    "refs": {
        # Canonical range 49.55-198.2 is 20-80 ng/mL once divided by 2.4773.
        "187": {"common": [49.55, 198.2], "optimal": [], "paidOptimal": [74.32, 123.9]},
        "88": {"common": [0.08539, 0.8539], "optimal": [], "paidOptimal": []},
        "337": {"common": [5.0, 8.0], "optimal": [], "paidOptimal": []},
    },
}

SUBMISSIONS_PAYLOAD: dict[str, Any] = {
    "total": 1,
    "submissions": [
        {
            "pid": PROFILE_ID,
            "sid": "s2",
            "date": DATE_NEW,
            "hasDate": True,
            "isDeleted": False,
            "laboratory": {"title": "Test Lab"},
            "entries": [{"seid": "e2"}, {"seid": "e4"}],
        }
    ],
}

THESAURUS_PAYLOAD: dict[str, Any] = {
    "needToUpdate": True,
    "digest": "DIGEST-1",
    "biomarkers": [
        {
            "id": 187,
            "title": "Vitamin D, 25-Hydroxy",
            "displayCategoryId": 60,
            "isUnitless": False,
            "unitsFactors": [[56, 2.4773], [34, 1.0]],
        },
        {
            "id": 88,
            "title": "Ferritin",
            "displayCategoryId": 14,
            "isUnitless": False,
            "unitsFactors": [[56, 0.00224719], [34, 1.0]],
        },
        {
            "id": 337,
            "title": "pH, urine",
            "displayCategoryId": 27,
            "isUnitless": True,
            "unitsFactors": [[1, 1.0]],
        },
    ],
}

UNITS_PAYLOAD: list[dict[str, Any]] = [
    {"id": 1, "title": "%", "valueType": 1},
    {"id": 34, "title": "mcg/L", "valueType": 1},
    {"id": 56, "title": "ng/mL", "valueType": 1},
]

CATEGORIES_PAYLOAD: list[dict[str, Any]] = [
    {"id": 14, "title": "Anemia"},
    {"id": 27, "title": "Urine"},
    {"id": 60, "title": "Vitamins"},
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom integrations in every test."""
    return


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock every Ornament endpoint the integration touches."""
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
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.1/measurement-units", json=UNITS_PAYLOAD
    )
    aioclient_mock.get(
        f"{base}/thesaurus-api/public/v1.0/biomarker-categories",
        json=CATEGORIES_PAYLOAD,
    )
    return aioclient_mock


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry for the test profile."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id=PROFILE_ID,
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
    )
    entry.add_to_hass(hass)
    return entry
