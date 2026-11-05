"""TrueNAS HA shared entity model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from logging import getLogger
from typing import Any, Callable

from homeassistant.const import ATTR_ATTRIBUTION, CONF_HOST, CONF_NAME
from homeassistant.core import ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.service import remove_entity_service_fields
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import TrueNASConnectionError, TrueNASRequestError
from .const import (
    ATTRIBUTION,
    DOMAIN,
)
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator
from .helper import format_attribute

_LOGGER = getLogger(__name__)


# ---------------------------
#   system_device_info
# ---------------------------
def system_device_info(coordinator: TrueNASCoordinator) -> DeviceInfo:
    """Return the device info of the TrueNAS "System" device.

    The System device is the parent of every other TrueNAS device. It is
    registered from async_setup_entry, before the platforms, so its device
    id exists when child devices link to it, and by the System entities.
    Both use this function, so they always describe the same device.
    """
    inst = coordinator.config_entry.data[CONF_NAME]
    system_info = coordinator.data["system_info"]
    device_key = (DOMAIN, f"{inst}_{system_info['hostname']}")
    return DeviceInfo(
        connections={device_key},
        identifiers={device_key},
        name="System",
        model=f"{system_info['system_product']}",
        manufacturer=f"{system_info['system_manufacturer']}",
        sw_version=f"{system_info['version']}",
        configuration_url=f"https://{coordinator.config_entry.data[CONF_HOST]}",
    )


# ---------------------------
#   build_entity_id
# ---------------------------
def build_entity_id(domain: str, inst: str, group: Any, name: Any) -> str:
    """Return "<domain>.<inst>_<group>_<name>" as a valid entity id.

    This is the id scheme the integration has always used, so existing
    entities keep their registry ids. Empty parts are skipped: the system
    update entity has an empty name and used to produce the invalid
    "update.truenas_system_" (Home Assistant registered it as
    "update.truenas_system"). Every part is slugified, which also keeps
    instance names with spaces or other characters valid.
    """
    parts = [slugify(str(part).lower()) for part in (inst, group, name)]
    return f"{domain}.{'_'.join(part for part in parts if part)}"


# ---------------------------
#   invalid_state_error
# ---------------------------
def invalid_state_error(name: Any, state: Any, action: str) -> ServiceValidationError:
    """Return the error for an action that does not apply to the current state."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_state",
        translation_placeholders={
            "name": str(name),
            "state": str(state),
            "action": action,
        },
    )


# ---------------------------
#   invalid_response_error
# ---------------------------
def invalid_response_error(name: Any) -> HomeAssistantError:
    """Return the error for an answer an action cannot use."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="action_invalid_response",
        translation_placeholders={"name": str(name)},
    )


# ---------------------------
#   entity_service_handler
# ---------------------------
def entity_service_handler(method: str) -> Callable:
    """Return the handler of an entity service that runs the entity's `method`.

    Actions are registered once for the whole integration, whatever its entries'
    access levels, so this is what stops one from reaching an entity with read-only
    access. The API key of that entity may well be allowed to do it.
    """

    async def handler(entity: TrueNASEntity, call: ServiceCall) -> None:
        """Run the method unless the entity's entry is read-only."""
        if entity.coordinator.read_only:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="read_only_action",
                translation_placeholders={"entity": entity.entity_id},
            )

        await getattr(entity, method)(**remove_entity_service_fields(call))

    return handler


# ---------------------------
#   async_add_entities
# ---------------------------
async def async_add_entities(
    config_entry: TrueNASConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
    dispatcher: dict[str, Callable],
    descriptions: Sequence[Any],
) -> None:
    """Add the platform's entities, now and whenever TrueNAS has new items."""
    coordinator = config_entry.runtime_data
    known: set[tuple[str, Any]] = set()

    @callback
    def async_new_entities() -> list[Entity]:
        """Return an entity for each item not seen before."""
        new: list[Entity] = []
        for description in descriptions:
            data = coordinator.data[description.data_path]
            factory = dispatcher[description.func]
            if not description.data_reference:
                if (
                    data.get(description.data_attribute) is not None
                    and (description.key, None) not in known
                ):
                    known.add((description.key, None))
                    new.append(factory(coordinator, description))

                continue

            # An item that was removed gets an entity again if it comes back
            known.difference_update(
                {
                    item
                    for item in known
                    if item[0] == description.key
                    and item[1] is not None
                    and item[1] not in data
                }
            )
            for uid in data:
                if (description.key, uid) not in known:
                    known.add((description.key, uid))
                    new.append(factory(coordinator, description, uid))

        return new

    @callback
    def async_add_new_entities() -> None:
        """Add what appeared on TrueNAS since the last update."""
        if coordinator.last_update_success and (new := async_new_entities()):
            add_entities(new)

    add_entities(async_new_entities())
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


# ---------------------------
#   TrueNASEntity
# ---------------------------
class TrueNASEntity(CoordinatorEntity[TrueNASCoordinator], Entity):
    """Define entity."""

    _attr_has_entity_name = True
    # The domain of the platform, set by each platform's base class
    _platform_domain: str

    async def _async_call(
        self,
        method: str,
        params: Any = {},
        *,
        false_is_failure: bool = False,
        may_disconnect: bool = False,
    ) -> Any:
        """Return the result of an action's call to TrueNAS.

        Raise a translated HomeAssistantError if TrueNAS cannot be reached or
        refuses. false_is_failure is for methods that report a failure by
        returning false. may_disconnect is for methods that stop TrueNAS, which
        can drop the connection before answering: once the request has gone
        out, that counts as success.
        """
        try:
            result = await self.hass.async_add_executor_job(
                self.coordinator.api.call, method, params
            )
        except TrueNASConnectionError as err:
            if may_disconnect and err.request_sent:
                _LOGGER.debug("Connection closed while running %s (%s)", method, err)
                return None

            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_unreachable",
                translation_placeholders={"method": method},
            ) from err
        except TrueNASRequestError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_rejected",
                translation_placeholders={"method": method, "reason": str(err)},
            ) from err

        if false_is_failure and result is False:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"method": method},
            )

        return result

    def __init__(
        self,
        coordinator: TrueNASCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Initialize entity."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._inst = coordinator.config_entry.data[CONF_NAME]
        self._config_entry = self.coordinator.config_entry
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._uid = uid
        if self._uid:
            self._data = coordinator.data[self.entity_description.data_path][self._uid]
        else:
            self._data = coordinator.data[self.entity_description.data_path]

        # From the English names in the descriptions, never the translated name
        # that the entity shows: entity ids must not depend on the language
        self.entity_id = build_entity_id(
            self._platform_domain,
            self._inst,
            self.entity_description.ha_group,
            self._english_name(),
        )
        self._update_name()

    @callback
    def _handle_coordinator_update(self) -> None:
        section = self.coordinator.data[self.entity_description.data_path]
        if not self._uid:
            self._data = section
        elif self._uid in section:
            self._data = section[self._uid]
            self._update_name()

        # Otherwise the item is gone: keep its last values for the entity's name,
        # until its removal. available says that they are out of date.
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return false while the item is gone from TrueNAS."""
        if not super().available:
            return False

        if not self._uid:
            return True

        path = self.entity_description.data_path
        return self._uid in self.coordinator.data[
            path
        ] and not self.coordinator.is_missing(path, self._uid)

    def _english_name(self) -> str:
        """Return the name that entity ids are built from."""
        suffix = self.entity_description.name
        if not self._uid:
            return f"{suffix}"

        item = self._data[self.entity_description.data_name]
        return f"{item} {suffix}" if suffix else f"{item}"

    def _update_name(self) -> None:
        """Set the name of an item's entity, which holds the item's own name.

        Those with a name of their own in the description get it translated, with
        the item as a placeholder. A pool or interface cannot be renamed, so that
        is set once. Other items are named as they are on TrueNAS, which can change.
        """
        if not self._uid:
            return

        item = str(self._data[self.entity_description.data_name])
        if not self.entity_description.name:
            self._attr_name = item
        elif not hasattr(self, "_attr_translation_placeholders"):
            self._attr_translation_placeholders = {"name": item}

    @property
    def unique_id(self) -> str:
        """Return a unique id for this entity."""
        if self._uid:
            return f"{self._inst.lower()}-{self.entity_description.key}-{slugify(str(self._data[self.entity_description.data_reference]).lower())}"
        else:
            return f"{self._inst.lower()}-{self.entity_description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return a description for device registry."""
        if self.entity_description.ha_group == "System":
            return system_device_info(self.coordinator)

        info = DeviceInfo(
            connections={(DOMAIN, f"{self._inst}_{self.entity_description.ha_group}")},
            name=self.entity_description.ha_group,
            model=f"{self.coordinator.data['system_info']['system_product']}",
            manufacturer=f"{self.coordinator.data['system_info']['system_manufacturer']}",
        )
        # Registered in async_setup_entry before any platform is set up
        if self.coordinator.system_device_id:
            info["via_device_id"] = self.coordinator.system_device_id

        return info

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes
        for variable in self.entity_description.data_attributes_list:
            if variable in self._data:
                attributes[format_attribute(variable)] = self._data[variable]

        return attributes

    async def start(self):
        """Run function."""
        raise NotImplementedError()

    async def stop(self):
        """Stop function."""
        raise NotImplementedError()

    async def pause(self):
        """Pause function."""
        raise NotImplementedError()

    async def restart(self):
        """Restart function."""
        raise NotImplementedError()

    async def reload(self):
        """Reload function."""
        raise NotImplementedError()

    async def snapshot(self):
        """Snapshot function."""
        raise NotImplementedError()
