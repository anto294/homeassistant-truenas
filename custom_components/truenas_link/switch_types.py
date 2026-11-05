"""Definitions for TrueNAS switch entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.helpers.entity import EntityCategory


@dataclass
class TrueNASSwitchEntityDescription(SwitchEntityDescription):
    """Class describing entities."""

    ha_group: str | None = None
    data_path: str | None = None
    data_attribute: str | None = None
    data_name: str | None = None
    data_uid: str | None = None
    data_reference: str | None = None
    data_attributes_list: List = field(default_factory=lambda: [])
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
