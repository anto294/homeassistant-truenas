"""Tests of what entities tell Home Assistant about themselves."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.truenas_link import binary_sensor_types, sensor_types

from .conftest import async_add_entry
from .sample_data import answers


def _description(descriptions, key):
    """Return the description with a key."""
    return next(item for item in descriptions if item.key == key)


@pytest.mark.parametrize("key", ["vm", "container", "service", "app"])
def test_what_runs_has_the_running_class(key):
    """On still means running, so automations do not change."""
    description = _description(binary_sensor_types.SENSOR_TYPES, key)
    assert description.device_class is BinarySensorDeviceClass.RUNNING


def test_healthy_has_no_class_that_would_invert_it():
    """Problem means on is bad, and here on is good."""
    description = _description(binary_sensor_types.SENSOR_TYPES, "pool_healthy")
    assert description.device_class is None


def test_reboot_required_is_a_diagnostic_problem():
    """It is about the system, and on means something to do."""
    description = _description(
        binary_sensor_types.SENSOR_TYPES, "system_reboot_required"
    )
    assert description.device_class is BinarySensorDeviceClass.PROBLEM
    assert description.entity_category is EntityCategory.DIAGNOSTIC


@pytest.mark.parametrize(
    "key", ["pool_scan", "pool_last_scrub", "pool_errors", "traffic_rx", "traffic_tx"]
)
def test_diagnostic_sensors(key):
    """They describe the system, and do not belong on a default dashboard."""
    description = _description(sensor_types.SENSOR_TYPES, key)
    assert description.entity_category is EntityCategory.DIAGNOSTIC


def test_rarely_used_sensors_start_disabled_on_a_new_entry(run_in_hass):
    """They exist in the registry, and the user can enable them."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        await async_add_entry(hass)
        registry = er.async_get(hass)

        for key in ("load_midterm", "load_longterm"):
            entity = registry.async_get(f"sensor.truenas_system_cpu_{key}")
            assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION

        arc = registry.async_get("sensor.truenas_system_arc_size")
        assert arc.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get("sensor.truenas_system_arc_size") is None

    run_in_hass(scenario)


def test_entity_enabled_before_stays_enabled(run_in_hass):
    """The default only counts when an entity is first registered."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        registry = er.async_get(hass)
        registry.async_update_entity("sensor.truenas_system_arc_size", disabled_by=None)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.truenas_system_arc_size") is not None

    run_in_hass(scenario)
