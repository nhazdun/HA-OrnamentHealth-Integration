"""Config flow for the Ornament Health integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import OrnamentApiError, OrnamentAuthError, OrnamentClient, Profile
from .const import (
    CONF_HISTORY_ATTRIBUTE_LIMIT,
    CONF_IMPORT_HISTORY,
    CONF_LANGUAGE,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_TOKEN,
    DEFAULT_HISTORY_ATTRIBUTE_LIMIT,
    DEFAULT_IMPORT_HISTORY,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SUPPORTED_LANGUAGES,
)

_LOGGER = logging.getLogger(__name__)

TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, multiline=True)
        )
    }
)


def _profile_label(profile: Profile) -> str:
    """Build a human friendly label for the profile picker."""
    label = profile.name
    details = [detail for detail in (profile.birthday, profile.sex) if detail]
    if details:
        label = f"{label} ({', '.join(details)})"
    if profile.is_demo:
        label = f"{label} — demo"
    if profile.is_archived:
        label = f"{label} — archived"
    return label


class OrnamentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for an API token, then let the user pick whose data to track."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._token: str = ""
        self._profiles: list[Profile] = []

    async def _async_validate_token(self, token: str) -> dict[str, str]:
        """Load the profiles behind a token, returning form errors if any."""
        client = OrnamentClient(async_get_clientsession(self.hass), token)
        try:
            self._profiles = await client.async_get_profiles()
        except OrnamentAuthError:
            return {"base": "invalid_auth"}
        except OrnamentApiError as err:
            _LOGGER.debug("Token validation failed: %s", err)
            return {"base": "cannot_connect"}
        if not self._profiles:
            return {"base": "no_profiles"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step one: the API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors = await self._async_validate_token(token)
            if not errors:
                self._token = token
                return await self.async_step_profile()

        return self.async_show_form(
            step_id="user", data_schema=TOKEN_SCHEMA, errors=errors
        )

    async def async_step_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step two: which person's biomarkers to import."""
        if user_input is not None:
            pid = user_input[CONF_PROFILE_ID]
            profile = next((item for item in self._profiles if item.pid == pid), None)
            await self.async_set_unique_id(pid)
            self._abort_if_unique_id_configured()
            name = profile.name if profile else pid
            return self.async_create_entry(
                title=name,
                data={
                    CONF_TOKEN: self._token,
                    CONF_PROFILE_ID: pid,
                    CONF_PROFILE_NAME: name,
                },
            )

        options = [
            SelectOptionDict(value=profile.pid, label=_profile_label(profile))
            for profile in self._profiles
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_PROFILE_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="profile", data_schema=schema)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the flow that replaces an expired token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh token for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors = await self._async_validate_token(token)
            if not errors:
                pid = entry.data[CONF_PROFILE_ID]
                if not any(profile.pid == pid for profile in self._profiles):
                    errors = {"base": "profile_missing"}
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_TOKEN: token}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OrnamentOptionsFlow:
        """Return the options flow."""
        return OrnamentOptionsFlow()


class OrnamentOptionsFlow(OptionsFlow):
    """Tune polling, language and history behaviour."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_HOURS,
                    default=options.get(
                        CONF_SCAN_INTERVAL_HOURS,
                        int(DEFAULT_SCAN_INTERVAL.total_seconds() // 3600),
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=168, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_IMPORT_HISTORY,
                    default=options.get(CONF_IMPORT_HISTORY, DEFAULT_IMPORT_HISTORY),
                ): BooleanSelector(),
                vol.Required(
                    CONF_HISTORY_ATTRIBUTE_LIMIT,
                    default=options.get(
                        CONF_HISTORY_ATTRIBUTE_LIMIT, DEFAULT_HISTORY_ATTRIBUTE_LIMIT
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_LANGUAGE,
                    default=options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=SUPPORTED_LANGUAGES, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
