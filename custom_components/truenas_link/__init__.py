"""The TrueNAS integration."""

from __future__ import annotations


from homeassistant.const import CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from . import binary_sensor_types, sensor_types
from .const import CONF_ACCESS_LEVEL, DOMAIN, LEGACY_ACCESS_LEVEL, PLATFORMS
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .entity import entity_service_handler, system_device_info
from .stale import async_can_remove_device, async_remove_stale_entities

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Actions by the domain of the entities they target
ACTIONS = (
    ("sensor", sensor_types.SENSOR_SERVICES),
    ("binary_sensor", binary_sensor_types.SENSOR_SERVICES),
)


# ---------------------------
#   async_setup
# ---------------------------
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, once, whatever entries there are or their state.

    So automations using them can be validated even when TrueNAS is unreachable.
    Each action checks the access level and the class of the entity it runs on.
    """
    for entity_domain, actions in ACTIONS:
        for name, schema, method, target in actions:
            async_register_platform_entity_service(
                hass,
                DOMAIN,
                name,
                entity_domain=entity_domain,
                func=entity_service_handler(method, target),
                schema=schema,
            )

    return True


# ---------------------------
#   async_migrate_entry
# ---------------------------
async def async_migrate_entry(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> bool:
    """Move what is not needed to connect from the entry's data to its options.

    The new version is also a safeguard. An older release finds no access level in
    the data and treats that as Administrator, but Home Assistant does not load an
    entry with a version above the integration's: going back gives an error, instead
    of a read-only entry that accepts actions.
    """
    if config_entry.version == 1:
        data = dict(config_entry.data)
        options = {
            **config_entry.options,
            CONF_NAME: data.pop(CONF_NAME),
            CONF_ACCESS_LEVEL: data.pop(CONF_ACCESS_LEVEL, LEGACY_ACCESS_LEVEL),
        }
        hass.config_entries.async_update_entry(
            config_entry, data=data, options=options, version=2
        )

    return True


# ---------------------------
#   _duplicate_issue_id
# ---------------------------
def _duplicate_issue_id(entry_id: str) -> str:
    """Return the id of the repair issue of an entry on a system that has one."""
    return f"duplicate_system_{entry_id}"


# ---------------------------
#   _async_set_missing_unique_id
# ---------------------------
async def _async_set_missing_unique_id(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    coordinator: TrueNASCoordinator,
) -> None:
    """Give an entry made before entries had a unique id its system's id.

    Without the id, or with another entry already holding it, the entry keeps
    working as before. The latter is a repair issue, because only the user can tell
    which entry to keep. It goes away with the entry, or when the id is free.
    """
    issue_id = _duplicate_issue_id(config_entry.entry_id)
    if config_entry.unique_id is not None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    system_id = await coordinator.api.read_system_id()
    if system_id is None:
        return

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.unique_id == system_id:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                config_entry_id=config_entry.entry_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="duplicate_system",
                translation_placeholders={
                    "entry": config_entry.title,
                    "other": other.title,
                },
            )
            return

    ir.async_delete_issue(hass, DOMAIN, issue_id)
    hass.config_entries.async_update_entry(config_entry, unique_id=system_id)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> bool:
    """Set up TrueNAS config entry."""
    coordinator = TrueNASCoordinator(hass, config_entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # A setup retry starts over with a new coordinator and connection
        await coordinator.api.disconnect()
        raise

    async def async_close_connection(_event: Event) -> None:
        """Close the connection when Home Assistant stops, as entries stay loaded."""
        await coordinator.api.disconnect()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_close_connection)
    )

    await _async_set_missing_unique_id(hass, config_entry, coordinator)

    # Register the parent "System" device first, so child devices (Disks,
    # VMs, Apps, ...) can link to its device id whatever platform is set up
    # first.
    system_device = dr.async_get(hass).async_get_or_create_from_info(
        config_entry_id=config_entry.entry_id,
        device_info=system_device_info(coordinator),
    )
    coordinator.system_device_id = system_device.id

    config_entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    @callback
    def async_update_entities() -> None:
        """Remove the entities of what has been gone from TrueNAS for a while."""
        async_remove_stale_entities(hass, config_entry)

    config_entry.async_on_unload(coordinator.async_add_listener(async_update_entities))
    return True


# ---------------------------
#   async_remove_config_entry_device
# ---------------------------
async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Let the user delete a device whose items are no longer on TrueNAS."""
    return async_can_remove_device(hass, config_entry, device_entry)


# ---------------------------
#   async_unload_entry
# ---------------------------
async def async_unload_entry(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> bool:
    """Unload TrueNAS config entry."""

    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        await config_entry.runtime_data.api.disconnect()

    return unload_ok


# ---------------------------
#   async_remove_entry
# ---------------------------
async def async_remove_entry(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> None:
    """Remove the repair issues the removal may have solved.

    That includes those of other entries, which may have been waiting for this one's
    system id. Their next setup raises the issue again if there is still a duplicate.
    """
    entries = [config_entry, *hass.config_entries.async_entries(DOMAIN)]
    for entry in entries:
        ir.async_delete_issue(hass, DOMAIN, _duplicate_issue_id(entry.entry_id))
