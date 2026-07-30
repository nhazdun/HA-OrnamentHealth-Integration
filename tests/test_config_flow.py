"""Tests for the token then profile config flow."""

from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ornament_health.const import (
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_TOKEN,
    DOMAIN,
)

from .conftest import PROFILE_ID, TOKEN


async def test_full_flow(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """The user enters a token, then picks a person."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "profile"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROFILE_ID: PROFILE_ID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Person"
    assert result["data"] == {
        CONF_TOKEN: TOKEN,
        CONF_PROFILE_ID: PROFILE_ID,
        CONF_PROFILE_NAME: "Test Person",
    }


async def test_invalid_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected token keeps the user on the token form."""
    aioclient_mock.get(
        "https://api.ornament.health/accounting-api/public/v1.0/healer/linked-profiles",
        status=401,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A server error is reported as a connection problem."""
    aioclient_mock.get(
        "https://api.ornament.health/accounting-api/public/v1.0/healer/linked-profiles",
        status=500,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "bad"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_profile_aborts(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry
) -> None:
    """Adding the same person twice aborts."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROFILE_ID: PROFILE_ID}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry
) -> None:
    """Reauth swaps the token on the existing entry."""
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "fresh-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "fresh-token"


async def test_options_flow_sets_minutes(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry
) -> None:
    """The poll interval is configurable in minutes."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval_minutes": 30,
            "import_history": True,
            "history_attribute_limit": 20,
            "language": "en",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["scan_interval_minutes"] == 30
    assert config_entry.runtime_data.update_interval == timedelta(minutes=30)


async def test_legacy_hours_option_still_honoured(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """An entry saved with the old hours option keeps its interval."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Person",
        unique_id="legacy",
        data={
            CONF_TOKEN: TOKEN,
            CONF_PROFILE_ID: PROFILE_ID,
            CONF_PROFILE_NAME: "Test Person",
        },
        options={"scan_interval_hours": 6},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(hours=6)
