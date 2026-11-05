"""Definitions for TrueNAS update entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.update import UpdateEntityDescription


@dataclass(frozen=True, kw_only=True)
class TrueNASUpdateEntityDescription(UpdateEntityDescription):
    """Class describing entities."""

    ha_group: str = ""
    title: str | None = None
    data_path: str = ""
    data_attribute: str = "available"
    data_name: str = ""
    data_uid: str = ""
    data_reference: str = ""
    data_attributes_list: list[str] = field(default_factory=list)
    func: str | None = None


SENSOR_TYPES: tuple[TrueNASUpdateEntityDescription, ...] = (
    TrueNASUpdateEntityDescription(
        key="system_update",
        name="",
        ha_group="System",
        title="TrueNAS",
        data_path="system_info",
        data_attribute="update_available",
        data_name="",
        data_uid="",
        data_reference="",
        func="TrueNASUpdate",
    ),
    TrueNASUpdateEntityDescription(
        key="app_update",
        name="",
        ha_group="Apps",
        data_path="app",
        data_attribute="update_available",
        data_name="name",
        data_uid="id",
        data_reference="id",
        func="TrueNASAppUpdate",
    ),
)
