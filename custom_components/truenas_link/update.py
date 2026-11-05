"""TrueNAS binary sensor platform."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)

from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .entity import TrueNASEntity, async_add_entities, invalid_state_error
from .update_types import SENSOR_TYPES

# One action at a time per platform. Data comes from the coordinator, but these
# platforms also send actions, which first check the state on TrueNAS and then act:
# this keeps a second action from passing the same check halfway through.
PARALLEL_UPDATES = 1

DEVICE_UPDATE = "device_update"


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up device tracker for TrueNAS component."""
    dispatcher = {
        "TrueNASUpdate": TrueNASUpdate,
        "TrueNASAppUpdate": TrueNASAppUpdate,
    }
    await async_add_entities(config_entry, add_entities, dispatcher, SENSOR_TYPES)


# ---------------------------
#   TrueNASUpdate
# ---------------------------
class TrueNASUpdate(TrueNASEntity, UpdateEntity):
    """Define an TrueNAS Update Sensor."""

    TYPE = DEVICE_UPDATE
    _platform_domain = "update"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Set up device update entity."""
        super().__init__(coordinator, entity_description, uid)

        if not coordinator.read_only:
            self._attr_supported_features = UpdateEntityFeature.INSTALL
            self._attr_supported_features |= UpdateEntityFeature.PROGRESS
        self._attr_title = self.entity_description.title

    @property
    def installed_version(self) -> str:
        """Version installed and in use."""
        return self._data["version"]

    @property
    def latest_version(self) -> str:
        """Latest version available for install."""
        return self._data["update_version"]

    async def options_updated(self) -> None:
        """No action needed."""

    async def async_install(self, version: str, backup: bool, **kwargs: Any) -> None:
        """Install an update."""
        # Since 25.10 update.update only edits the update settings and the
        # download/apply job moved to update.run (same attrs, returns a job id).
        method = (
            "update.run"
            if self.coordinator.version_at_least(25, 10)
            else "update.update"
        )
        job_id = await self._async_call(method, {"reboot": True})
        if job_id is not None:
            self._data["update_jobid"] = job_id

        await self.coordinator.async_refresh()

    @property
    def in_progress(self) -> int:
        """Update installation progress."""
        if self._data["update_state"] != "RUNNING":
            return False

        if self._data["update_progress"] == 0:
            self._data["update_progress"] = 1

        return self._data["update_progress"]


# ---------------------------
#   TrueNASAppUpdate
# ---------------------------
class TrueNASAppUpdate(TrueNASEntity, UpdateEntity):
    """Define an TrueNAS App Update Sensor."""

    TYPE = DEVICE_UPDATE
    _platform_domain = "update"

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Set up device update entity."""
        super().__init__(coordinator, entity_description, uid)

        if not coordinator.read_only:
            self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str:
        """Version installed and in use."""
        return self._data["version"]

    @property
    def latest_version(self) -> str:
        """Latest version available for install."""
        if not self._data.get("running", True):
            # A stopped app cannot be upgraded, do not report a pending update
            return self._data["version"]

        # app.query returns latest_version null when no upgrade is available
        # (25.10) or when it cannot be determined (27.0); report the installed
        # version then instead of an unknown state.
        return self._data["latest_version"] or self._data["version"]

    async def async_install(self, version: str, backup: bool, **kwargs: Any) -> None:
        """Install an update."""
        state = self.coordinator.data["app"][self._data["id"]]["state"]
        if state != "RUNNING":
            # An app must be running to be upgraded
            raise invalid_state_error(self._data["id"], state, "upgrade")

        job_id = await self._async_call("app.upgrade", [self._data["id"]])
        if job_id is not None:
            self._data["update_jobid"] = job_id

        await self.coordinator.async_refresh()

    @property
    def in_progress(self) -> bool:
        """Return if update is in progress."""
        return bool(self._data.get("update_jobid"))

    @property
    def title(self) -> str | None:
        """Return the title of the entity."""
        return self._data["name"]
