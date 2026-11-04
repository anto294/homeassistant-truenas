"""TrueNAS binary sensor platform."""

from __future__ import annotations
from logging import getLogger

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .binary_sensor_types import (
    SENSOR_SERVICES,
    SENSOR_TYPES,
)
from .entity import TrueNASEntity, async_add_entities

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker for OpenMediaVault component."""
    dispatcher = {
        "TrueNASBinarySensor": TrueNASBinarySensor,
        "TrueNASVMBinarySensor": TrueNASVMBinarySensor,
        "TrueNASContainerBinarySensor": TrueNASContainerBinarySensor,
        "TrueNASServiceBinarySensor": TrueNASServiceBinarySensor,
        "TrueNASAppBinarySensor": TrueNASAppBinarySensor,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   TrueNASBinarySensor
# ---------------------------
class TrueNASBinarySensor(TrueNASEntity, BinarySensorEntity):
    """Define an TrueNAS Binary Sensor."""

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._data[self.entity_description.data_is_on]

    @property
    def icon(self) -> str | None:
        """Return the icon."""
        if self.entity_description.icon_enabled:
            if self._data[self.entity_description.data_is_on]:
                return self.entity_description.icon_enabled
            else:
                return self.entity_description.icon_disabled

        return None


# ---------------------------
#   TrueNASVMBinarySensor
# ---------------------------
class TrueNASVMBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS VM Binary Sensor."""

    @property
    def _use_libvirt(self) -> bool:
        """Return True if VMs are managed through the vm.* API (25.10+)."""
        return self.coordinator.version_at_least(25, 10)

    # ---------------------------
    #   _get_state
    # ---------------------------
    async def _get_state(self) -> str | None:
        """Return the current VM state ("RUNNING", "STOPPED", ...) or None."""
        if self._use_libvirt:
            if not self._data.get("vm_id"):
                # Entry left over from the 25.04 virt.instance API, not yet
                # refreshed by vm.query, so its libvirt id is unknown.
                _LOGGER.error(
                    "VM %s (%s) has no libvirt id yet",
                    self._data["name"],
                    self._data["id"],
                )
                return None

            tmp_vm = await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "vm.get_instance",
                [self._data["vm_id"]],
            )
            status = tmp_vm.get("status") if isinstance(tmp_vm, dict) else None
            state = status.get("state") if isinstance(status, dict) else None
        else:
            tmp_vm = await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "virt.instance.get_instance",
                [self._data["id"]],
            )
            state = tmp_vm.get("status") if isinstance(tmp_vm, dict) else None

        if state is None:
            _LOGGER.error("VM %s (%s) invalid", self._data["name"], self._data["id"])

        return state

    async def start(self, overcommit: bool = False):
        """Start a VM."""
        state = await self._get_state()
        if state is None:
            return

        if state != "STOPPED":
            _LOGGER.warning(
                "VM %s (%s) is not down", self._data["name"], self._data["id"]
            )
            return

        if self._use_libvirt:
            await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "vm.start",
                [self._data["vm_id"], {"overcommit": overcommit}],
            )
        else:
            await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "virt.instance.start",
                [self._data["id"]],
            )

    async def stop(self):
        """Stop a VM."""
        state = await self._get_state()
        if state is None:
            return

        if state != "RUNNING":
            _LOGGER.warning(
                "VM %s (%s) is not up", self._data["name"], self._data["id"]
            )
            return

        if self._use_libvirt:
            # Graceful ACPI shutdown, powered off if it exceeds shutdown_timeout
            await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "vm.stop",
                [self._data["vm_id"], {"force_after_timeout": True}],
            )
        else:
            await self.hass.async_add_executor_job(
                self.coordinator.api.query,
                "virt.instance.stop",
                [self._data["id"], {"timeout": 0, "force": True}],
            )


# ---------------------------
#   TrueNASContainerBinarySensor
# ---------------------------
class TrueNASContainerBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Container Binary Sensor (TrueNAS 27.0+)."""

    # ---------------------------
    #   _get_state
    # ---------------------------
    async def _get_state(self) -> str | None:
        """Return the current container state ("RUNNING", "STOPPED", ...) or None."""
        tmp_container = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "container.get_instance",
            [self._data["container_id"]],
        )
        status = (
            tmp_container.get("status") if isinstance(tmp_container, dict) else None
        )
        state = status.get("state") if isinstance(status, dict) else None
        if state is None:
            _LOGGER.error(
                "Container %s (%s) invalid", self._data["name"], self._data["id"]
            )

        return state

    async def start(self):
        """Start a container."""
        state = await self._get_state()
        if state is None:
            return

        if state != "STOPPED":
            _LOGGER.warning(
                "Container %s (%s) is not down", self._data["name"], self._data["id"]
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "container.start",
            [self._data["container_id"]],
        )

    async def stop(self):
        """Stop a container."""
        state = await self._get_state()
        if state is None:
            return

        if state != "RUNNING":
            _LOGGER.warning(
                "Container %s (%s) is not up", self._data["name"], self._data["id"]
            )
            return

        # Clean shutdown, killed if it exceeds the container's shutdown_timeout
        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "container.stop",
            [self._data["container_id"], {"force_after_timeout": True}],
        )


# ---------------------------
#   TrueNASServiceBinarySensor
# ---------------------------
class TrueNASServiceBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Service Binary Sensor."""

    async def start(self):
        """Start a Service."""
        tmp_service = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.get_instance",
            [self._data["id"]],
        )

        if "state" not in tmp_service:
            _LOGGER.error(
                "Service %s (%s) invalid", self._data["service"], self._data["id"]
            )
            return

        if tmp_service["state"] != "STOPPED":
            _LOGGER.warning(
                "Service %s (%s) is not stopped",
                self._data["service"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.start",
            [self._data["service"]],
        )

        await self.coordinator.async_refresh()

    async def stop(self):
        """Stop a Service."""
        tmp_service = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.get_instance",
            [self._data["id"]],
        )

        if "state" not in tmp_service:
            _LOGGER.error(
                "Service %s (%s) invalid", self._data["service"], self._data["id"]
            )
            return

        if tmp_service["state"] == "STOPPED":
            _LOGGER.warning(
                "Service %s (%s) is not running",
                self._data["service"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.stop",
            [self._data["service"]],
        )
        await self.coordinator.async_refresh()

    async def restart(self):
        """Restart a Service."""
        tmp_service = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.get_instance",
            [self._data["id"]],
        )

        if "state" not in tmp_service:
            _LOGGER.error(
                "Service %s (%s) invalid", self._data["service"], self._data["id"]
            )
            return

        if tmp_service["state"] == "STOPPED":
            _LOGGER.warning(
                "Service %s (%s) is not running",
                self._data["service"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.restart",
            [self._data["service"]],
        )

        await self.coordinator.async_refresh()

    async def reload(self):
        """Reload a Service."""
        tmp_service = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.get_instance",
            [self._data["id"]],
        )

        if "state" not in tmp_service:
            _LOGGER.error(
                "Service %s (%s) invalid", self._data["service"], self._data["id"]
            )
            return

        if tmp_service["state"] == "STOPPED":
            _LOGGER.warning(
                "Service %s (%s) is not running",
                self._data["service"],
                self._data["id"],
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "service.reload",
            [self._data["service"]],
        )

        await self.coordinator.async_refresh()


# ---------------------------
#   TrueNASAppsBinarySensor
# ---------------------------
class TrueNASAppBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Applications Binary Sensor."""

    async def start(self):
        """Start an App."""
        tmp_app = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "app.get_instance",
            [self._data["id"]],
        )

        if tmp_app is None or "state" not in tmp_app:
            _LOGGER.error("App %s (%s) invalid", self._data["name"], self._data["id"])
            return

        if tmp_app["state"] == "RUNNING":
            _LOGGER.warning(
                "App %s (%s) is not down", self._data["name"], self._data["id"]
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "app.start",
            [self._data["id"]],
        )

    async def stop(self):
        """Stop an App."""
        tmp_app = await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "app.get_instance",
            [self._data["id"]],
        )

        if tmp_app is None or "state" not in tmp_app:
            _LOGGER.error("App %s (%s) invalid", self._data["name"], self._data["id"])
            return

        if tmp_app["state"] != "RUNNING":
            _LOGGER.warning(
                "App %s (%s) is not up", self._data["name"], self._data["id"]
            )
            return

        await self.hass.async_add_executor_job(
            self.coordinator.api.query,
            "app.stop",
            [self._data["id"]],
        )
