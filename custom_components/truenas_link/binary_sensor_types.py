"""Definitions for TrueNAS binary sensor entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .const import (
    SCHEMA_SERVICE_APP_START,
    SCHEMA_SERVICE_APP_STOP,
    SCHEMA_SERVICE_CONTAINER_START,
    SCHEMA_SERVICE_CONTAINER_STOP,
    SCHEMA_SERVICE_SERVICE_RELOAD,
    SCHEMA_SERVICE_SERVICE_RESTART,
    SCHEMA_SERVICE_SERVICE_START,
    SCHEMA_SERVICE_SERVICE_STOP,
    SCHEMA_SERVICE_VM_START,
    SCHEMA_SERVICE_VM_STOP,
    SERVICE_APP_START,
    SERVICE_APP_STOP,
    SERVICE_CONTAINER_START,
    SERVICE_CONTAINER_STOP,
    SERVICE_SERVICE_RELOAD,
    SERVICE_SERVICE_RESTART,
    SERVICE_SERVICE_START,
    SERVICE_SERVICE_STOP,
    SERVICE_VM_START,
    SERVICE_VM_STOP,
)

DEVICE_ATTRIBUTES_POOL = [
    "path",
    "status",
    "healthy",
    "is_decrypted",
    "autotrim",
    "scrub_state",
    "scrub_start",
    "scrub_end",
    "scrub_secs_left",
    "available",
    "total",
]

DEVICE_ATTRIBUTES_VM = [
    "type",
    "cpu",
    "memory",
    "autostart",
    "image",
]

DEVICE_ATTRIBUTES_CONTAINER = [
    "description",
    "autostart",
    "cpuset",
    "memory",
    "status",
]

DEVICE_ATTRIBUTES_SERVICE = [
    "enable",
    "state",
]

DEVICE_ATTRIBUTES_APP = [
    "name",
    "version",
    "latest_version",
    "human_version",
    "update_available",
    "image_updates_available",
    "custom_app",
    "portal",
]


@dataclass(frozen=True, kw_only=True)
class TrueNASBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class describing entities."""

    ha_group: str = ""
    data_path: str = ""
    # Only for entities without data_reference: created if this value exists
    data_attribute: str = ""
    data_is_on: str = "available"
    data_name: str = ""
    data_uid: str = ""
    data_reference: str = ""
    data_attributes_list: list[str] = field(default_factory=list)
    func: str = "TrueNASBinarySensor"


SENSOR_TYPES: tuple[TrueNASBinarySensorEntityDescription, ...] = (
    TrueNASBinarySensorEntityDescription(
        key="system_alerts_critical",
        translation_key="system_alerts_critical",
        name="Critical alerts",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=None,
        ha_group="System",
        data_path="system_info",
        data_attribute="alerts_critical",
        data_is_on="alerts_critical",
        data_name="",
        data_uid="",
        data_reference="",
        data_attributes_list=["alert_messages"],
    ),
    TrueNASBinarySensorEntityDescription(
        key="system_reboot_required",
        translation_key="system_reboot_required",
        name="Reboot required",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        ha_group="System",
        data_path="system_info",
        data_attribute="reboot_required",
        data_is_on="reboot_required",
        data_name="",
        data_uid="",
        data_reference="",
        data_attributes_list=["reboot_required_reasons"],
    ),
    TrueNASBinarySensorEntityDescription(
        key="pool_healthy",
        translation_key="pool_healthy",
        name="healthy",
        device_class=None,
        entity_category=None,
        ha_group="System",
        data_path="pool",
        data_is_on="healthy",
        data_name="name",
        data_uid="",
        data_reference="guid",
        data_attributes_list=DEVICE_ATTRIBUTES_POOL,
    ),
    TrueNASBinarySensorEntityDescription(
        key="vm",
        translation_key="vm",
        name="",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=None,
        ha_group="VMs",
        data_path="vm",
        data_is_on="running",
        data_name="name",
        data_uid="",
        data_reference="id",
        data_attributes_list=DEVICE_ATTRIBUTES_VM,
        func="TrueNASVMBinarySensor",
    ),
    TrueNASBinarySensorEntityDescription(
        key="container",
        translation_key="container",
        name="",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=None,
        ha_group="Containers",
        data_path="container",
        data_is_on="running",
        data_name="name",
        data_uid="",
        data_reference="id",
        data_attributes_list=DEVICE_ATTRIBUTES_CONTAINER,
        func="TrueNASContainerBinarySensor",
    ),
    TrueNASBinarySensorEntityDescription(
        key="service",
        translation_key="service",
        name="",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=None,
        ha_group="Services",
        data_path="service",
        data_is_on="running",
        data_name="service",
        data_uid="",
        data_reference="id",
        data_attributes_list=DEVICE_ATTRIBUTES_SERVICE,
        func="TrueNASServiceBinarySensor",
    ),
    TrueNASBinarySensorEntityDescription(
        key="app",
        translation_key="app",
        name="",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=None,
        ha_group="Apps",
        data_path="app",
        data_is_on="running",
        data_name="name",
        data_uid="",
        data_reference="id",
        data_attributes_list=DEVICE_ATTRIBUTES_APP,
        func="TrueNASAppBinarySensor",
    ),
)

# Action, its schema, the entity method it runs, and the only entity class it may
# run on: another class can have a method of that name that does something else
SENSOR_SERVICES: list[list[Any]] = [
    [SERVICE_VM_START, SCHEMA_SERVICE_VM_START, "start", "TrueNASVMBinarySensor"],
    [SERVICE_VM_STOP, SCHEMA_SERVICE_VM_STOP, "stop", "TrueNASVMBinarySensor"],
    [
        SERVICE_CONTAINER_START,
        SCHEMA_SERVICE_CONTAINER_START,
        "start",
        "TrueNASContainerBinarySensor",
    ],
    [
        SERVICE_CONTAINER_STOP,
        SCHEMA_SERVICE_CONTAINER_STOP,
        "stop",
        "TrueNASContainerBinarySensor",
    ],
    [
        SERVICE_SERVICE_START,
        SCHEMA_SERVICE_SERVICE_START,
        "start",
        "TrueNASServiceBinarySensor",
    ],
    [
        SERVICE_SERVICE_STOP,
        SCHEMA_SERVICE_SERVICE_STOP,
        "stop",
        "TrueNASServiceBinarySensor",
    ],
    [
        SERVICE_SERVICE_RESTART,
        SCHEMA_SERVICE_SERVICE_RESTART,
        "restart",
        "TrueNASServiceBinarySensor",
    ],
    [
        SERVICE_SERVICE_RELOAD,
        SCHEMA_SERVICE_SERVICE_RELOAD,
        "reload",
        "TrueNASServiceBinarySensor",
    ],
    [SERVICE_APP_START, SCHEMA_SERVICE_APP_START, "start", "TrueNASAppBinarySensor"],
    [SERVICE_APP_STOP, SCHEMA_SERVICE_APP_STOP, "stop", "TrueNASAppBinarySensor"],
]
