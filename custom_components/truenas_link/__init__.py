"""The TrueNAS integration."""

from __future__ import annotations


from logging import getLogger

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from . import binary_sensor_types, sensor_types
from .const import DOMAIN, PLATFORMS
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .entity import entity_service_handler, system_device_info
from .stale import async_can_remove_device, async_remove_stale_entities

_LOGGER = getLogger(__name__)

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
    Each action checks the access level of the entity it runs on.
    """
    for entity_domain, actions in ACTIONS:
        for name, schema, method in actions:
            async_register_platform_entity_service(
                hass,
                DOMAIN,
                name,
                entity_domain=entity_domain,
                func=entity_service_handler(method),
                schema=schema,
            )

    return True


# ---------------------------
#   _async_set_missing_unique_id
# ---------------------------
async def _async_set_missing_unique_id(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    coordinator: TrueNASCoordinator,
) -> None:
    """Give an entry made before entries had a unique id its system's id.

    This needs no migration, so going back to an older version still works: an
    older version ignores the id. Without the id, or with another entry already
    holding it, the entry keeps working as before.
    """
    if config_entry.unique_id is not None:
        return

    system_id = await hass.async_add_executor_job(coordinator.api.read_system_id)
    if system_id is None:
        return

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.unique_id == system_id:
            _LOGGER.warning(
                'The TrueNAS entries "%s" and "%s" connect to the same system. '
                "Both keep working, but they poll it twice: remove one if you do "
                "not need it",
                config_entry.title,
                other.title,
            )
            return

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
        await hass.async_add_executor_job(coordinator.api.disconnect)
        raise

    await _async_set_missing_unique_id(hass, config_entry, coordinator)

    # Register the parent "System" device first, so child devices (Disks,
    # VMs, Apps, ...) can link to its device id whatever platform is set up
    # first.
    system_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        **system_device_info(coordinator),
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
        await hass.async_add_executor_job(config_entry.runtime_data.api.disconnect)

    return unload_ok
