"""Tests for translated entity names and icons."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.truenas_link import (
    binary_sensor_types,
    sensor_types,
    switch_types,
)

from .conftest import async_add_entry
from .sample_data import answers

COMPONENT = Path(__file__).parent.parent / "custom_components" / "truenas_link"
ICONS = json.loads((COMPONENT / "icons.json").read_text())["entity"]
STRINGS = json.loads((COMPONENT / "strings.json").read_text())["entity"]
DESCRIPTIONS = {
    "sensor": sensor_types.SENSOR_TYPES,
    "binary_sensor": binary_sensor_types.SENSOR_TYPES,
    "switch": switch_types.SENSOR_TYPES,
}
ALL = [
    (domain, description)
    for domain, descriptions in DESCRIPTIONS.items()
    for description in descriptions
]


def _ids(pairs):
    """Name each test after its description."""
    return [f"{domain}-{description.key}" for domain, description in pairs]


@pytest.mark.parametrize(("domain", "description"), ALL, ids=_ids(ALL))
def test_no_icon_stays_in_the_code(domain, description):
    """Icons live in icons.json."""
    assert description.icon is None
    assert not hasattr(description, "icon_enabled")


@pytest.mark.parametrize(
    ("domain", "description"),
    [pair for pair in ALL if pair[1].translation_key],
    ids=_ids([pair for pair in ALL if pair[1].translation_key]),
)
def test_translation_key_has_an_icon(domain, description):
    """A key without an icon loses the one it had in the code."""
    if description.key not in ("system_alerts_critical",):
        assert ICONS[domain][description.translation_key]["default"].startswith("mdi:")


@pytest.mark.parametrize(
    "key",
    ["system_reboot_required", "pool_healthy", "vm", "container", "service", "app"],
)
def test_binary_sensors_show_their_state_in_the_icon(key):
    """icon_enabled and icon_disabled became the on and off icons."""
    icon = ICONS["binary_sensor"][key]

    assert icon["default"] != icon["state"]["off"]


@pytest.mark.parametrize(("domain", "description"), ALL, ids=_ids(ALL))
def test_english_translation_matches_the_name_in_the_description(domain, description):
    """English users see the same names as before, also for entity ids."""
    if not description.name:
        assert description.key not in STRINGS.get(domain, {})
        return

    assert description.translation_key == description.key
    expected = description.name
    if description.data_reference:
        expected = f"{{name}} {description.name}"

    assert STRINGS[domain][description.key]["name"] == expected


def _friendly(hass, entity_id):
    """Return the name an entity shows."""
    return hass.states.get(entity_id).attributes["friendly_name"]


def test_names_in_english_do_not_change(run_in_hass):
    """Device name, item and description, as before."""

    async def scenario(hass, server):
        server.results = answers("27.0")
        await async_add_entry(hass)

        assert _friendly(hass, "sensor.truenas_system_uptime") == "System Uptime"
        assert _friendly(hass, "sensor.truenas_system_tank_free") == "System tank free"
        assert _friendly(hass, "sensor.truenas_datasets_tank") == "Datasets tank"
        assert _friendly(hass, "binary_sensor.truenas_vms_win11") == "VMs win11"
        # Home Assistant 2024.11 keeps a space after the device name
        assert _friendly(hass, "update.truenas_system").strip() == "System"

    run_in_hass(scenario)


def test_names_in_italian_with_the_same_entity_ids(run_in_hass):
    """Names follow the language. Items keep their names, and ids stay English."""

    async def scenario(hass, server):
        hass.config.language = "it"
        server.results = answers("27.0")
        await async_add_entry(hass)

        assert (
            _friendly(hass, "sensor.truenas_system_uptime")
            == "System Tempo di attività"
        )
        assert (
            _friendly(hass, "sensor.truenas_system_tank_free")
            == "System tank spazio libero"
        )
        assert (
            _friendly(hass, "binary_sensor.truenas_system_reboot_required")
            == "System Riavvio richiesto"
        )
        assert _friendly(hass, "binary_sensor.truenas_vms_win11") == "VMs win11"

    run_in_hass(scenario)


def test_entity_of_an_item_follows_its_new_name(run_in_hass):
    """A task renamed on TrueNAS shows the new name, and keeps its entity id."""

    async def scenario(hass, server):
        server.results = answers("27.0")
        entry = await async_add_entry(hass)
        entity_id = "sensor.truenas_cloudsync_offsite_backup"

        server.results["cloudsync.query"][0]["description"] = "Renamed"
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert _friendly(hass, entity_id) == "Cloudsync Renamed"

    run_in_hass(scenario)


def test_scan_states_are_translated():
    """Each option of the scan sensor has a text."""
    states = STRINGS["sensor"]["pool_scan"]["state"]
    options = next(d.options for d in sensor_types.SENSOR_TYPES if d.key == "pool_scan")

    assert set(states) == set(options)
