"""Tests for entity ids and device info built by TrueNASEntity."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import valid_entity_id
from homeassistant.helpers import device_registry as dr

from custom_components.truenas_link import entity as entity_module
from custom_components.truenas_link.entity import build_entity_id


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


SYSTEM_DEVICE_ID = "0123456789abcdef0123456789abcdef"


def _allowed_device_info_keys() -> set[str]:
    """Return the DeviceInfo keys the installed Home Assistant accepts.

    Up to 2026.x a device info had to fit one of DEVICE_INFO_TYPES; later
    releases only accept the keys of the DeviceInfo TypedDict.
    """
    keys = set(dr.DeviceInfo.__required_keys__ | dr.DeviceInfo.__optional_keys__)
    if types := getattr(dr, "DEVICE_INFO_TYPES", None):
        keys &= types["primary"]
    return keys


def _deprecated_device_info_keys() -> set[str]:
    """Return the async_get_or_create parameters the installed HA deprecates."""
    return set(getattr(dr, "_DEPRECATED_DEVICE_INFO_PARAMETERS", {}))


def _entity(ha_group, data=None):
    """Build a TrueNASEntity with just what device_info reads."""
    from types import SimpleNamespace

    from custom_components.truenas_link.entity import TrueNASEntity

    entity = TrueNASEntity.__new__(TrueNASEntity)
    entity.entity_description = SimpleNamespace(ha_group=ha_group)
    entity._inst = "TrueNAS"
    entity._data = data or {}
    entity.coordinator = _coordinator()
    return entity


def _coordinator():
    """Return a stand-in coordinator with system info after the first refresh."""
    from types import SimpleNamespace

    return SimpleNamespace(
        data={
            "system_info": {
                "hostname": "nas",
                "system_product": "TRUENAS-MINI-3.0-XL+",
                "system_manufacturer": "iXsystems",
                "version": "25.10.1",
            }
        },
        config_entry=SimpleNamespace(
            entry_id="entry",
            data={"host": "truenas.lan"},
            options={"name": "TrueNAS"},
        ),
        system_device_id=SYSTEM_DEVICE_ID,
    )


@pytest.mark.parametrize("ha_group", ["Disks", "VMs", "Apps", "Containers"])
def test_child_device_info_is_valid_for_installed_ha(ha_group):
    """Child device info only uses keys the installed HA accepts, none deprecated."""
    info = _entity(ha_group).device_info

    assert set(info.keys()) <= _allowed_device_info_keys()
    assert not set(info.keys()) & _deprecated_device_info_keys()
    assert not {key for key in info.keys() if key.startswith("default_")}
    assert info.name == ha_group
    assert info.model == "TRUENAS-MINI-3.0-XL+"
    assert info.manufacturer == "iXsystems"
    assert info.connections == {("truenas_link", f"TrueNAS_{ha_group}")}


def test_child_links_its_parent_by_device_id():
    """via_device_id is the parent's device registry id."""
    info = _entity("VMs").device_info

    assert info.via_device_id == SYSTEM_DEVICE_ID
    assert "via_device" not in info


def test_system_device_info_is_unchanged():
    """The System device keeps its identifiers, version and URL."""
    info = _entity("System").device_info

    assert set(info.keys()) <= _allowed_device_info_keys()
    assert info == entity_module.system_device_info(_coordinator())
    assert info.identifiers == {("truenas_link", "TrueNAS_nas")}
    assert info.connections == {("truenas_link", "TrueNAS_nas")}
    assert info.name == "System"
    assert info.sw_version == "25.10.1"
    assert info.configuration_url == "https://truenas.lan"
    assert "via_device" not in info and "via_device_id" not in info


def test_setup_registers_system_device_before_platforms(monkeypatch):
    """async_setup_entry creates the parent device, then forwards platforms."""
    from unittest.mock import AsyncMock, MagicMock

    import custom_components.truenas_link as integration

    calls = []
    coordinator = _coordinator()
    coordinator.system_device_id = None
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_add_listener = MagicMock()

    registry = MagicMock()

    def get_or_create(**kwargs):
        calls.append(("device", kwargs))
        return MagicMock(id=SYSTEM_DEVICE_ID)

    registry.async_get_or_create_from_info.side_effect = get_or_create

    async def forward(entry, platforms):
        calls.append(("platforms", coordinator.system_device_id))

    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = forward
    config_entry = MagicMock(entry_id="entry")

    monkeypatch.setattr(integration, "TrueNASCoordinator", lambda *_: coordinator)
    monkeypatch.setattr(integration.dr, "async_get", lambda _: registry)

    assert asyncio.run(integration.async_setup_entry(hass, config_entry))

    assert [call[0] for call in calls] == ["device", "platforms"]
    assert calls[0][1] == {
        "config_entry_id": "entry",
        "device_info": entity_module.system_device_info(coordinator),
    }
    # Platforms already see the parent's device id
    assert calls[1][1] == SYSTEM_DEVICE_ID


def test_devices_in_the_registry_stay_the_same(run_in_hass):
    """Every field of the System device and of a device linked to it."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    from custom_components.truenas_link.const import DOMAIN

    from .conftest import async_add_entry
    from .sample_data import answers

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        devices = dr.async_get(hass)

        system = devices.async_get(entry.runtime_data.system_device_id)
        key = (DOMAIN, "TrueNAS_nas")
        assert system.identifiers == {key}
        assert system.connections == {key}
        assert system.name == "System"
        assert system.configuration_url == "https://nas"
        assert system.sw_version == server.results["system.info"]["version"]
        assert system.model == server.results["system.info"]["system_product"]
        info = server.results["system.info"]
        assert system.manufacturer == info["system_manufacturer"]
        assert system.via_device_id is None

        entities = er.async_get(hass)
        disks = devices.async_get(
            entities.async_get("sensor.truenas_disks_sda").device_id
        )
        assert disks.connections == {(DOMAIN, "TrueNAS_Disks")}
        assert disks.name == "Disks"
        assert disks.identifiers == set()
        assert disks.model == info["system_product"]
        assert disks.manufacturer == info["system_manufacturer"]
        assert disks.via_device_id == system.id

    run_in_hass(scenario)
