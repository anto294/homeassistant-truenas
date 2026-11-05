"""Config flow to configure TrueNAS."""

from __future__ import annotations

from collections.abc import Mapping
from logging import getLogger
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_POLL,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ACCESS_LEVEL_ADMIN,
    ACCESS_LEVEL_READ_ONLY,
    CONF_ACCESS_LEVEL,
    DEFAULT_ACCESS_LEVEL,
    DEFAULT_DEVICE_NAME,
    DEFAULT_HOST,
    DEFAULT_SSL_VERIFY,
    DOMAIN,
    LEGACY_ACCESS_LEVEL,
)
from .api import TrueNASAPI

_LOGGER = getLogger(__name__)


def _access_level_selector() -> SelectSelector:
    """Return the selector for the level of access the API key is used with."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[ACCESS_LEVEL_ADMIN, ACCESS_LEVEL_READ_ONLY],
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_ACCESS_LEVEL,
        )
    )


def _api_key_selector() -> TextSelector:
    """Return the field for an API key, which masks what it shows."""
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _base_schema(truenas_config: Mapping[str, Any]) -> vol.Schema:
    """Generate base schema."""
    base_schema = {
        vol.Required(
            CONF_NAME, default=truenas_config.get(CONF_NAME) or DEFAULT_DEVICE_NAME
        ): str,
        vol.Required(
            CONF_HOST, default=truenas_config.get(CONF_HOST) or DEFAULT_HOST
        ): str,
        vol.Required(
            CONF_API_KEY, default=truenas_config.get(CONF_API_KEY) or ""
        ): _api_key_selector(),
        vol.Required(
            CONF_ACCESS_LEVEL,
            default=truenas_config.get(CONF_ACCESS_LEVEL) or DEFAULT_ACCESS_LEVEL,
        ): _access_level_selector(),
        vol.Required(
            CONF_VERIFY_SSL,
            # Not "or": a stored False has to stay False
            default=truenas_config.get(CONF_VERIFY_SSL, DEFAULT_SSL_VERIFY),
        ): bool,
    }

    return vol.Schema(base_schema)


def _reconfigure_schema(
    truenas_config: Mapping[str, Any], entered_api_key: str | None = None
) -> vol.Schema:
    """Generate the Reconfigure schema.

    The form never gets the stored API key, because a schema's values are sent to
    the browser even if the field masks them. It only gets entered_api_key: what
    the user typed before an error. An empty field keeps the stored key.
    """
    base_schema = {
        vol.Required(
            CONF_HOST, default=truenas_config.get(CONF_HOST) or DEFAULT_HOST
        ): str,
        vol.Optional(
            CONF_API_KEY, description={"suggested_value": entered_api_key}
        ): _api_key_selector(),
        vol.Required(
            CONF_ACCESS_LEVEL,
            default=truenas_config.get(CONF_ACCESS_LEVEL) or LEGACY_ACCESS_LEVEL,
        ): _access_level_selector(),
        vol.Required(
            CONF_VERIFY_SSL,
            # Not "or": a stored False has to stay False
            default=truenas_config.get(CONF_VERIFY_SSL, DEFAULT_SSL_VERIFY),
        ): bool,
    }

    return vol.Schema(base_schema)


# ---------------------------
#   configured_instances
# ---------------------------
@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return {
        entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)
    }


# ---------------------------
#   TrueNASConfigFlow
# ---------------------------
class TrueNASConfigFlow(ConfigFlow, domain=DOMAIN):
    """TrueNASConfigFlow class."""

    VERSION = 1
    CONNECTION_CLASS = CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.truenas_config: dict[str, Any] = {}

    async def _async_connection_error(
        self, host: str, api_key: str, verify_ssl: bool
    ) -> str | None:
        """Return the error code of a connection test, None if it worked."""
        api = await self.hass.async_add_executor_job(
            TrueNASAPI, host, api_key, verify_ssl
        )
        conn, errorcode = await self.hass.async_add_executor_job(api.connection_test)
        if conn:
            return None

        _LOGGER.error("TrueNAS connection error (%s)", errorcode)
        return errorcode

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        truenas_config = self.truenas_config
        errors = {}

        if user_input is not None:
            truenas_config.update(user_input)

            # Check if instance with this name already exists
            if truenas_config[CONF_NAME] in configured_instances(self.hass):
                errors["base"] = "name_exists"

            # Test connection
            errorcode = await self._async_connection_error(
                truenas_config[CONF_HOST],
                truenas_config[CONF_API_KEY],
                truenas_config[CONF_VERIFY_SSL],
            )
            if errorcode is not None:
                errors[CONF_HOST] = errorcode

            # Save instance
            if not errors:
                return self.async_create_entry(
                    title=truenas_config[CONF_NAME], data=truenas_config
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(truenas_config),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        reconfigure_entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            # Only this submission counts: a key that was typed before an error
            # and then cleared must not come back
            self.truenas_config = dict(user_input)
            if not self.truenas_config.get(CONF_API_KEY):
                self.truenas_config.pop(CONF_API_KEY, None)

        truenas_config = self.truenas_config

        if user_input is not None:
            # Test connection
            errorcode = await self._async_connection_error(
                truenas_config[CONF_HOST],
                truenas_config.get(CONF_API_KEY, reconfigure_entry.data[CONF_API_KEY]),
                truenas_config[CONF_VERIFY_SSL],
            )
            if errorcode is not None:
                errors[CONF_HOST] = errorcode

            # Save instance
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    title=reconfigure_entry.data[CONF_NAME],
                    data_updates=truenas_config,
                )

        return self.async_show_form(
            step_id="reconfigure",
            # After an error, keep what was entered
            data_schema=_reconfigure_schema(
                {**reconfigure_entry.data, **truenas_config},
                truenas_config.get(CONF_API_KEY),
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start over with a new API key, because TrueNAS rejected the stored one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key, and store it if it works."""
        reauth_entry = self._get_reauth_entry()
        errors = {}

        if user_input is not None:
            errorcode = await self._async_connection_error(
                reauth_entry.data[CONF_HOST],
                user_input[CONF_API_KEY],
                reauth_entry.data[CONF_VERIFY_SSL],
            )
            if errorcode is None:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )

            errors["base"] = errorcode

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _api_key_selector()}),
            description_placeholders={"name": reauth_entry.title},
            errors=errors,
        )
