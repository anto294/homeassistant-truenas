"""Tests for entity ids and device info built by TrueNASEntity."""

from __future__ import annotations

import pytest
from homeassistant.core import valid_entity_id

from custom_components.truenas.entity import build_entity_id


@pytest.mark.parametrize(
    ("domain", "inst", "group", "name", "expected"),
    [
        # System update entity: empty name, used to end in "_"
        ("update", "TrueNAS", "System", "", "update.truenas_system"),
        # Unchanged ids for regular entities
        ("sensor", "TrueNAS", "System", "Uptime", "sensor.truenas_system_uptime"),
        (
            "sensor",
            "TrueNAS",
            "System",
            "ARC size",
            "sensor.truenas_system_arc_size",
        ),
        ("binary_sensor", "TrueNAS", "VMs", "win11", "binary_sensor.truenas_vms_win11"),
        ("update", "TrueNAS", "Apps", "plex", "update.truenas_apps_plex"),
        # Instance names that are not valid object ids on their own
        ("sensor", "My NAS", "System", "Uptime", "sensor.my_nas_system_uptime"),
        ("sensor", "nas-01", "Disks", "sda", "sensor.nas_01_disks_sda"),
    ],
)
def test_build_entity_id(domain, inst, group, name, expected):
    """Entity ids keep the <inst>_<group>_<name> scheme and are always valid."""
    entity_id = build_entity_id(domain, inst, group, name)

    assert entity_id == expected
    assert valid_entity_id(entity_id)


# Keys of the "primary" device info type in Home Assistant 2024.11, the oldest
# supported release. A device info must fit in one type there, so default_*
# keys (type "secondary") cannot be mixed with name/model/manufacturer.
PRIMARY_DEVICE_INFO_KEYS = {
    "configuration_url",
    "connections",
    "entry_type",
    "hw_version",
    "identifiers",
    "manufacturer",
    "model",
    "model_id",
    "name",
    "serial_number",
    "suggested_area",
    "sw_version",
    "via_device",
}


def _entity(ha_group, data=None):
    """Build a TrueNASEntity with just what device_info reads."""
    from types import SimpleNamespace

    from custom_components.truenas.entity import TrueNASEntity

    entity = TrueNASEntity.__new__(TrueNASEntity)
    entity.entity_description = SimpleNamespace(
        ha_group=ha_group, ha_connection=None, ha_connection_value=None
    )
    entity._inst = "TrueNAS"
    entity._data = data or {}
    entity.coordinator = SimpleNamespace(
        data={
            "system_info": {
                "hostname": "nas",
                "system_product": "TRUENAS-MINI-3.0-XL+",
                "system_manufacturer": "iXsystems",
                "version": "25.10.1",
            }
        },
        config_entry=SimpleNamespace(data={"host": "truenas.lan"}),
    )
    return entity


@pytest.mark.parametrize("ha_group", ["Disks", "VMs", "Apps", "Containers"])
def test_child_device_info_uses_non_deprecated_keys(ha_group):
    """Child devices set name/model/manufacturer, never default_*."""
    info = _entity(ha_group).device_info

    assert not {key for key in info if key.startswith("default_")}
    assert set(info) <= PRIMARY_DEVICE_INFO_KEYS
    assert info["name"] == ha_group
    assert info["model"] == "TRUENAS-MINI-3.0-XL+"
    assert info["manufacturer"] == "iXsystems"
    assert info["connections"] == {("truenas", f"TrueNAS_{ha_group}")}
    assert info["via_device"] == ("truenas", "TrueNAS_nas")


def test_system_device_info_is_unchanged():
    """The System device keeps its identifiers, version and URL."""
    info = _entity("System").device_info

    assert set(info) <= PRIMARY_DEVICE_INFO_KEYS
    assert info["identifiers"] == {("truenas", "TrueNAS_nas")}
    assert info["sw_version"] == "25.10.1"
    assert info["configuration_url"] == "http://truenas.lan"
