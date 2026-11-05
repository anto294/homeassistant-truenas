"""TrueNAS sensor platform."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BOOT_POOL_NAMES, DOMAIN, SCAN_IDLE, SCAN_PAUSED, SCAN_SCRUBBING
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .entity import (
    TrueNASEntity,
    async_add_entities,
    invalid_response_error,
    invalid_state_error,
)
from .sensor_types import (
    SENSOR_SERVICES,
    SENSOR_TYPES,
)

# Job states in which a task is already running
JOB_ACTIVE_STATES = ("WAITING", "RUNNING")


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry for TrueNAS component."""
    dispatcher = {
        "TrueNASSensor": TrueNASSensor,
        "TrueNASUptimeSensor": TrueNASUptimeSensor,
        "TrueNASClousyncSensor": TrueNASClousyncSensor,
        "TrueNASDatasetSensor": TrueNASDatasetSensor,
        "TrueNASPoolScanSensor": TrueNASPoolScanSensor,
        "TrueNASReplicationSensor": TrueNASReplicationSensor,
    }
    await async_add_entities(
        hass, config_entry, dispatcher, SENSOR_TYPES, SENSOR_SERVICES
    )


# ---------------------------
#   TrueNASSensor
# ---------------------------
class TrueNASSensor(TrueNASEntity, SensorEntity):
    """Define an TrueNAS sensor."""

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, entity_description, uid)
        self._attr_suggested_unit_of_measurement = (
            self.entity_description.suggested_unit_of_measurement
        )

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        return self._data[self.entity_description.data_attribute]

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        if self.entity_description.native_unit_of_measurement:
            if self.entity_description.native_unit_of_measurement.startswith("data__"):
                uom = self.entity_description.native_unit_of_measurement[6:]
                if uom in self._data:
                    return self._data[uom]

            return self.entity_description.native_unit_of_measurement

        return None


# ---------------------------
#   TrueNASUptimeSensor
# ---------------------------
class TrueNASUptimeSensor(TrueNASSensor):
    """Define an TrueNAS Uptime sensor."""

    async def restart(self) -> None:
        """Restart TrueNAS system."""
        await self._async_call(
            "system.reboot", ["Home Assistant Integration"], may_disconnect=True
        )

    async def stop(self) -> None:
        """Shutdown TrueNAS system."""
        await self._async_call(
            "system.shutdown", ["Home Assistant Integration"], may_disconnect=True
        )


# ---------------------------
#   TrueNASPoolScanSensor
# ---------------------------
class TrueNASPoolScanSensor(TrueNASSensor):
    """Define a TrueNAS pool scan sensor, the target of the scrub actions."""

    async def _scrub(
        self, allowed: tuple[str, ...], action: str, legacy_action: str
    ) -> None:
        """Send a scrub action, if the pool's scan state allows it.

        This also keeps a resilver out of reach, which must never be stopped
        from here, and a second scrub from being started.
        """
        name = self._data["name"]
        if name in BOOT_POOL_NAMES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scrub_boot_pool",
                translation_placeholders={"name": name},
            )

        if self._data["scan_status"] not in allowed:
            raise invalid_state_error(
                name, self._data["scan_status"], f"{action.lower()} scrub"
            )

        if self.coordinator.version_at_least(27, 0):
            # Without a threshold of 0, START does nothing and reports no
            # error if the last scrub is less than 35 days old
            method = "zpool.scrub.run"
            params = [{"pool_name": name, "action": action, "threshold": 0}]
        else:
            method = "pool.scrub.scrub"
            params = [name, legacy_action]

        await self._async_call(method, params)
        await self.coordinator.async_refresh()

    async def start(self) -> None:
        """Start a scrub, or resume a paused one."""
        await self._scrub((SCAN_IDLE, SCAN_PAUSED), "START", "START")

    async def pause(self) -> None:
        """Pause a running scrub."""
        await self._scrub((SCAN_SCRUBBING,), "PAUSE", "PAUSE")

    async def stop(self) -> None:
        """Stop a running or paused scrub."""
        await self._scrub((SCAN_SCRUBBING, SCAN_PAUSED), "CANCEL", "STOP")


# ---------------------------
#   TrueNASReplicationSensor
# ---------------------------
class TrueNASReplicationSensor(TrueNASSensor):
    """Define a TrueNAS replication sensor."""

    async def start(self) -> None:
        """Run the replication task, unless it is already running."""
        task = await self._async_call("replication.get_instance", [self._data["id"]])
        if not isinstance(task, dict):
            raise invalid_response_error(self._data["name"])

        # job is null if the task has never run
        state = (task.get("job") or {}).get("state")
        if state in JOB_ACTIVE_STATES:
            raise invalid_state_error(self._data["name"], state, "replication.run")

        await self._async_call("replication.run", [self._data["id"]])
        await self.coordinator.async_refresh()


# ---------------------------
#   TrueNASDatasetSensor
# ---------------------------
class TrueNASDatasetSensor(TrueNASSensor):
    """Define an TrueNAS Dataset sensor."""

    async def snapshot(self) -> None:
        """Create dataset snapshot."""
        ts = datetime.now().isoformat(sep="_", timespec="microseconds")
        # zfs.snapshot.create was replaced by pool.snapshot.create in 25.10
        method = (
            "pool.snapshot.create"
            if self.coordinator.version_at_least(25, 10)
            else "zfs.snapshot.create"
        )
        await self._async_call(
            method, {"dataset": f"{self._data['name']}", "name": f"custom-{ts}"}
        )


# ---------------------------
#   TrueNASClousyncSensor
# ---------------------------
class TrueNASClousyncSensor(TrueNASSensor):
    """Define an TrueNAS Cloudsync sensor."""

    async def _job_state(self) -> str | None:
        """Return the state of the task's job, None if the task has never run."""
        task = await self._async_call("cloudsync.get_instance", [self._data["id"]])
        if not isinstance(task, dict) or "job" not in task:
            raise invalid_response_error(self._data["description"])

        return (task["job"] or {}).get("state")

    async def start(self) -> None:
        """Run cloudsync job."""
        state = await self._job_state()
        if state in JOB_ACTIVE_STATES:
            raise invalid_state_error(
                self._data["description"], state, "cloudsync.sync"
            )

        await self._async_call("cloudsync.sync", [self._data["id"]])

    async def stop(self) -> None:
        """Abort cloudsync job."""
        state = await self._job_state()
        if state not in JOB_ACTIVE_STATES:
            raise invalid_state_error(
                self._data["description"], state or "idle", "cloudsync.abort"
            )

        await self._async_call(
            "cloudsync.abort", [self._data["id"]], false_is_failure=True
        )
