"""TrueNAS binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .binary_sensor_types import (
    SENSOR_SERVICES,
    SENSOR_TYPES,
)
from .entity import (
    TrueNASEntity,
    async_add_entities,
    invalid_response_error,
    invalid_state_error,
)

# Seconds a virt instance gets to shut down cleanly (TrueNAS 25.04)
VIRT_STOP_TIMEOUT = 60


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
    await async_add_entities(
        hass, config_entry, dispatcher, SENSOR_TYPES, SENSOR_SERVICES
    )


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
    async def _get_state(self) -> str:
        """Return the current VM state ("RUNNING", "STOPPED", ...)."""
        if self._use_libvirt:
            if not self._data.get("vm_id"):
                # Entry left over from the 25.04 virt.instance API, not yet
                # refreshed by vm.query, so its libvirt id is unknown.
                raise invalid_response_error(self._data["name"])

            tmp_vm = await self._async_call("vm.get_instance", [self._data["vm_id"]])
            status = tmp_vm.get("status") if isinstance(tmp_vm, dict) else None
            state = status.get("state") if isinstance(status, dict) else None
        else:
            tmp_vm = await self._async_call(
                "virt.instance.get_instance", [self._data["id"]]
            )
            state = tmp_vm.get("status") if isinstance(tmp_vm, dict) else None

        if state is None:
            raise invalid_response_error(self._data["name"])

        return state

    async def start(self, overcommit: bool = False):
        """Start a VM."""
        state = await self._get_state()
        if state != "STOPPED":
            raise invalid_state_error(self._data["name"], state, "start")

        if self._use_libvirt:
            await self._async_call(
                "vm.start", [self._data["vm_id"], {"overcommit": overcommit}]
            )
        else:
            await self._async_call("virt.instance.start", [self._data["id"]])

    async def stop(self):
        """Stop a VM."""
        state = await self._get_state()
        if state != "RUNNING":
            raise invalid_state_error(self._data["name"], state, "stop")

        if self._use_libvirt:
            # Graceful ACPI shutdown, powered off if it exceeds shutdown_timeout
            await self._async_call(
                "vm.stop", [self._data["vm_id"], {"force_after_timeout": True}]
            )
        else:
            await self._async_call(
                "virt.instance.stop",
                # Clean shutdown. TrueNAS 25.04 has no fallback to a forced
                # stop: if the timeout passes, the instance keeps running.
                [self._data["id"], {"timeout": VIRT_STOP_TIMEOUT, "force": False}],
            )


# ---------------------------
#   TrueNASContainerBinarySensor
# ---------------------------
class TrueNASContainerBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Container Binary Sensor (TrueNAS 27.0+)."""

    # ---------------------------
    #   _get_state
    # ---------------------------
    async def _get_state(self) -> str:
        """Return the current container state ("RUNNING", "STOPPED", ...)."""
        tmp_container = await self._async_call(
            "container.get_instance", [self._data["container_id"]]
        )
        status = (
            tmp_container.get("status") if isinstance(tmp_container, dict) else None
        )
        state = status.get("state") if isinstance(status, dict) else None
        if state is None:
            raise invalid_response_error(self._data["name"])

        return state

    async def start(self):
        """Start a container."""
        state = await self._get_state()
        if state != "STOPPED":
            raise invalid_state_error(self._data["name"], state, "start")

        await self._async_call("container.start", [self._data["container_id"]])

    async def stop(self):
        """Stop a container."""
        state = await self._get_state()
        if state != "RUNNING":
            raise invalid_state_error(self._data["name"], state, "stop")

        # Clean shutdown, killed if it exceeds the container's shutdown_timeout
        await self._async_call(
            "container.stop",
            [self._data["container_id"], {"force_after_timeout": True}],
        )


# ---------------------------
#   TrueNASServiceBinarySensor
# ---------------------------
class TrueNASServiceBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Service Binary Sensor."""

    async def _get_state(self) -> str:
        """Return the current state of the service."""
        service = await self._async_call("service.get_instance", [self._data["id"]])
        if not isinstance(service, dict) or "state" not in service:
            raise invalid_response_error(self._data["service"])

        return service["state"]

    async def _run(self, action: str) -> None:
        """Run a service.* method, which returns false if it fails."""
        await self._async_call(
            f"service.{action}", [self._data["service"]], false_is_failure=True
        )
        await self.coordinator.async_refresh()

    async def _run_if_not_stopped(self, action: str) -> None:
        """Run a method that only applies to a service that is not stopped."""
        state = await self._get_state()
        if state == "STOPPED":
            raise invalid_state_error(self._data["service"], state, action)

        await self._run(action)

    async def start(self):
        """Start a Service."""
        state = await self._get_state()
        if state != "STOPPED":
            raise invalid_state_error(self._data["service"], state, "start")

        await self._run("start")

    async def stop(self):
        """Stop a Service."""
        await self._run_if_not_stopped("stop")

    async def restart(self):
        """Restart a Service."""
        await self._run_if_not_stopped("restart")

    async def reload(self):
        """Reload a Service."""
        await self._run_if_not_stopped("reload")


# ---------------------------
#   TrueNASAppsBinarySensor
# ---------------------------
class TrueNASAppBinarySensor(TrueNASBinarySensor):
    """Define a TrueNAS Applications Binary Sensor."""

    async def _get_state(self) -> str:
        """Return the current state of the app."""
        app = await self._async_call("app.get_instance", [self._data["id"]])
        if not isinstance(app, dict) or "state" not in app:
            raise invalid_response_error(self._data["name"])

        return app["state"]

    async def start(self):
        """Start an App."""
        state = await self._get_state()
        if state == "RUNNING":
            raise invalid_state_error(self._data["name"], state, "start")

        await self._async_call("app.start", [self._data["id"]])

    async def stop(self):
        """Stop an App."""
        state = await self._get_state()
        if state != "RUNNING":
            raise invalid_state_error(self._data["name"], state, "stop")

        await self._async_call("app.stop", [self._data["id"]])
