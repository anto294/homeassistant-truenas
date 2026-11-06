"""Config flow to configure TrueNAS."""

from __future__ import annotations

from collections.abc import Mapping
from logging import getLogger
from typing import Any

import probatio as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
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
    DISCOVERED_ID_PREFIX,
    DOMAIN,
)
from .api import TrueNASAPI
from .helper import is_system_id

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


def _host_without_port(host: str) -> str:
    """Return a host as a system announces it, which is without its port."""
    return host.rsplit(":", 1)[0]


def _api_key_selector() -> TextSelector:
    """Return the field for an API key, which masks what it shows."""
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _base_schema(truenas_config: Mapping[str, Any]) -> vol.Schema:
    """Generate base schema."""
    base_schema = {
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
            CONF_VERIFY_SSL,
            # Not "or": a stored False has to stay False
            default=truenas_config.get(CONF_VERIFY_SSL, DEFAULT_SSL_VERIFY),
        ): bool,
    }

    return vol.Schema(base_schema)


# ---------------------------
#   new_entry_name
# ---------------------------
@callback
def new_entry_name(hass: HomeAssistant, hostname: str | None) -> str:
    """Return the name of a new entry, which its entity ids are built from.

    The first entry gets the default name, so someone who adds an entry with that
    name again gets the same entity ids. Later ones get the name of their system. The
    comparison uses slugs, as entity ids do, so two names cannot give the same ids.
    """
    taken = {
        slugify(str(entry.options[CONF_NAME]))
        for entry in hass.config_entries.async_entries(DOMAIN)
        if CONF_NAME in entry.options
    }
    short_hostname = hostname.split(".")[0] if hostname else ""
    if slugify(DEFAULT_DEVICE_NAME) not in taken:
        return DEFAULT_DEVICE_NAME

    base = short_hostname if slugify(short_hostname) else DEFAULT_DEVICE_NAME
    name = base
    number = 1
    while slugify(name) in taken:
        number += 1
        name = f"{base} {number}"

    return name


# ---------------------------
#   TrueNASConfigFlow
# ---------------------------
class TrueNASConfigFlow(ConfigFlow, domain=DOMAIN):
    """TrueNASConfigFlow class."""

    # 2: what is not needed to connect moved from data to options
    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TrueNASOptionsFlow:
        """Return the flow behind the entry's Configure button."""
        return TrueNASOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.truenas_config: dict[str, Any] = {}
        # From the last connection test, None if TrueNAS did not give them
        self._system_id: str | None = None
        self._hostname: str | None = None

    async def _async_connection_error(
        self, host: str, api_key: str, verify_ssl: bool
    ) -> str | None:
        """Return the error code of a connection test, None if it worked."""
        api = TrueNASAPI(async_get_clientsession(self.hass, verify_ssl), host, api_key)
        conn, errorcode = await api.connection_test()
        if conn:
            self._system_id = api.system_id
            self._hostname = api.hostname
            return None

        # The form shows this as a message
        _LOGGER.debug("TrueNAS connection error (%s)", errorcode)
        return errorcode

    async def _async_abort_if_other_system(self, entry: ConfigEntry) -> None:
        """Stop a form from pointing an entry to another TrueNAS system.

        A new address for the same system is fine. An entry without the id of its
        system has nothing to compare with, and neither has a system that gives no id.
        """
        if not is_system_id(entry.unique_id) or self._system_id is None:
            return

        await self.async_set_unique_id(self._system_id, raise_on_progress=False)
        self._abort_if_unique_id_mismatch()

    @callback
    def _async_close_offers(self, host: str) -> None:
        """Close the discovery flows of a host that now has an entry.

        Their unique id is not the system's, so Home Assistant does not close them.
        A host entered as a name cannot be matched with an announced address.
        """
        unique_id = f"{DISCOVERED_ID_PREFIX}{_host_without_port(host)}"
        for flow in self._async_in_progress(
            include_uninitialized=True, match_context={"unique_id": unique_id}
        ):
            self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Offer a TrueNAS system that announces itself, with its address filled in.

        Nothing is sent to it until the user has entered a key and confirmed. An
        announcement proves nothing, so it never changes the address of an entry: that
        would send the entry's key to whoever announces that name. An announcement has
        no id of the system either, so this flow's unique id only stops the same
        address from being offered twice, or again after the user ignored it. The form
        replaces it with the system's id.
        """
        host = discovery_info.host
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")

        hostname = discovery_info.hostname.rstrip(".")
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            configured = _host_without_port(str(entry.data.get(CONF_HOST, "")))
            if configured in (host, hostname):
                return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(f"{DISCOVERED_ID_PREFIX}{host}")
        self._abort_if_unique_id_configured()

        self.truenas_config[CONF_HOST] = host
        # Only the name: a reauthentication flow has no other placeholder, and the
        # translations share one title
        self.context["title_placeholders"] = {
            "name": f"{hostname.split('.')[0]} ({host})",
        }
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        truenas_config = self.truenas_config
        errors = {}

        if user_input is not None:
            truenas_config.update(user_input)

            # Test connection
            errorcode = await self._async_connection_error(
                truenas_config[CONF_HOST],
                truenas_config[CONF_API_KEY],
                truenas_config[CONF_VERIFY_SSL],
            )
            if errorcode is not None:
                errors[CONF_HOST] = errorcode
            elif self._system_id is not None:
                await self.async_set_unique_id(self._system_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
            else:
                # The id of a discovery flow must not stay on the entry
                await self.async_set_unique_id(None)

            # Save instance
            if not errors:
                self._async_close_offers(truenas_config[CONF_HOST])
                name = new_entry_name(self.hass, self._hostname)
                return self.async_create_entry(
                    title=name,
                    data={
                        key: value
                        for key, value in truenas_config.items()
                        if key != CONF_ACCESS_LEVEL
                    },
                    options={
                        CONF_NAME: name,
                        CONF_ACCESS_LEVEL: truenas_config[CONF_ACCESS_LEVEL],
                    },
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
            else:
                await self._async_abort_if_other_system(reconfigure_entry)

            # Save instance
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
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
                await self._async_abort_if_other_system(reauth_entry)
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


# ---------------------------
#   TrueNASOptionsFlow
# ---------------------------
class TrueNASOptionsFlow(OptionsFlowWithReload):
    """Change the access level, reloading the entry if it changed.

    The name is an option too, because it is not needed to connect, but entity ids
    are built from it, so this flow keeps it as it is.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the access level."""
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(data={**options, **user_input})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCESS_LEVEL,
                        default=options.get(CONF_ACCESS_LEVEL, DEFAULT_ACCESS_LEVEL),
                    ): _access_level_selector()
                }
            ),
        )
