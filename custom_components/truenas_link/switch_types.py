"""Definitions for TrueNAS switch entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory


@dataclass(frozen=True, kw_only=True)
class TrueNASSwitchEntityDescription(SwitchEntityDescription):
    """Class describing entities."""

    ha_group: str = ""
    data_path: str = ""
    data_attribute: str = ""
    data_name: str = ""
    data_uid: str = ""
    data_reference: str = ""
    data_attributes_list: list[str] = field(default_factory=list)
    func: str = "TrueNASCronJobSwitch"


SENSOR_TYPES: tuple[TrueNASSwitchEntityDescription, ...] = (
    TrueNASSwitchEntityDescription(
        key="cronjob",
        translation_key="cronjob",
        name="",
        # Off until the user turns the entity on. As a config entity it is
        # not exposed to voice assistants or switched by area and device
        # targets, such as "turn off the living room".
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
        ha_group="Cron jobs",
        data_path="cronjob",
        data_attribute="enabled",
        data_name="cron_name",
        data_uid="",
        data_reference="id",
        data_attributes_list=["schedule"],
    ),
)
