"""TrueNAS switch platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import TrueNASConfigEntry
from .entity import TrueNASEntity, async_add_entities
from .switch_types import SENSOR_SERVICES, SENSOR_TYPES


# ---------------------------
#   async_remove_switches
# ---------------------------
@callback
def async_remove_switches(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> None:
    """Remove this entry's switches, and the devices left without entities.

    Switches cannot work on a read-only entry. Without this, those from when
    the entry had Administrator access would stay as unavailable entities.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device_ids = set()
    for entity in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        if entity.domain == "switch":
            device_ids.add(entity.device_id)
            entity_registry.async_remove(entity.entity_id)

    for device_id in device_ids - {None}:
        if not er.async_entries_for_device(
            entity_registry, device_id, include_disabled_entities=True
        ):
            device_registry.async_remove_device(device_id)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for TrueNAS component."""
    if config_entry.runtime_data.read_only:
        async_remove_switches(hass, config_entry)
        return

    dispatcher = {
        "TrueNASCronJobSwitch": TrueNASCronJobSwitch,
    }
    await async_add_entities(
        hass, config_entry, dispatcher, SENSOR_TYPES, SENSOR_SERVICES
    )


# ---------------------------
#   TrueNASCronJobSwitch
# ---------------------------
class TrueNASCronJobSwitch(TrueNASEntity, SwitchEntity):
    """Enable or disable a TrueNAS cron job.

    It only ever sends "enabled": it cannot run a job, or change its command
    or user.
    """

    @property
    def is_on(self) -> bool:
        """Return true if the cron job is enabled."""
        return self._data["enabled"]

    async def _set_enabled(self, enabled: bool) -> None:
        """Enable or disable the cron job."""
        await self._async_call(
            "cronjob.update", [self._data["id"], {"enabled": enabled}]
        )
        await self.coordinator.async_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the cron job."""
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the cron job."""
        await self._set_enabled(False)
