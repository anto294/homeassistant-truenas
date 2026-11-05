"""The TrueNAS integration."""

from __future__ import annotations


from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import PLATFORMS
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .entity import system_device_info


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
    return True


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
