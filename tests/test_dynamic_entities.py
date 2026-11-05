"""Tests for items that appear on TrueNAS and disappear from it."""

from __future__ import annotations

import logging

from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest

from custom_components.truenas_link import async_remove_config_entry_device
from custom_components.truenas_link.const import DOMAIN, STALE_AFTER_POLLS

from .conftest import async_add_entry
from .sample_data import _dataset, answers

MEDIA = "sensor.truenas_datasets_tank_media_files"
MEDIA_UNIQUE_ID = "truenas-dataset-tank_media_files"
VM = "binary_sensor.truenas_vms_win11"
DOCKER_APP = "binary_sensor.truenas_apps_plex"
POLLS = 3


async def _setup(hass, server, version="25.10", **overrides):
    """Add an entry on sample answers, with a short wait before a removal."""
    server.results = answers(version)
    entry = await async_add_entry(hass, **overrides)
    entry.runtime_data.stale_after_polls = POLLS
    return entry, entry.runtime_data


async def _poll(hass, coordinator, times=1):
    """Run some successful or failed polls."""
    for _ in range(times):
        await coordinator.async_refresh()
        await hass.async_block_till_done()


def _without(server, method, key, value):
    """Remove an item from what TrueNAS answers."""
    server.results[method] = [
        item for item in server.results[method] if item[key] != value
    ]


def _registered(hass, entity_id):
    """Return the registry entry of an entity, if it has one."""
    return er.async_get(hass).async_get(entity_id)


def test_wait_before_a_removal_is_about_an_hour():
    """Polls come every minute."""
    assert STALE_AFTER_POLLS == 60


def test_new_items_appear_without_a_reload(run_in_hass):
    """A new dataset and a new VM get their entities on the next poll."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        assert hass.states.get("sensor.truenas_datasets_tank_new") is None

        server.results["pool.dataset.query"].append(_dataset("tank/new", 1000))
        vm = {**server.results["vm.query"][0], "id": 8, "name": "fresh"}
        server.results["vm.query"].append(vm)
        await _poll(hass, coordinator)

        assert hass.states.get("sensor.truenas_datasets_tank_new").state is not None
        assert hass.states.get("binary_sensor.truenas_vms_fresh").state == "on"
        registry_entry = _registered(hass, "binary_sensor.truenas_vms_fresh")
        assert registry_entry.unique_id == "truenas-vm-fresh"

    run_in_hass(scenario)


def test_entity_that_exists_is_not_added_twice(run_in_hass):
    """Repeated polls add nothing, and log no duplicate unique id."""

    async def scenario(hass, server):
        entry, coordinator = await _setup(hass, server)
        count = len(
            er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        )

        await _poll(hass, coordinator, 3)

        assert count == len(
            er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        )

    run_in_hass(scenario)


def test_system_value_that_appears_later_gets_its_entity(run_in_hass):
    """alert.list failing at setup only delays its entities."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.errors["alert.list"] = "[EPERM] not allowed"
        entry = await async_add_entry(hass)
        assert hass.states.get("sensor.truenas_system_alerts") is None

        del server.errors["alert.list"]
        await _poll(hass, entry.runtime_data)

        assert hass.states.get("sensor.truenas_system_alerts").state == "1"

    run_in_hass(scenario)


def test_deleted_item_goes_unavailable_then_is_removed(run_in_hass):
    """Its entity stays, unavailable, until enough polls have gone by."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        _without(server, "pool.dataset.query", "name", "tank/Media Files")

        await _poll(hass, coordinator, POLLS - 1)

        assert hass.states.get(MEDIA).state == "unavailable"
        assert _registered(hass, MEDIA) is not None
        assert "tank/Media Files" in coordinator.ds["dataset"]
        # The others are fine
        assert hass.states.get("sensor.truenas_datasets_tank").state != "unavailable"

        await _poll(hass, coordinator)

        assert hass.states.get(MEDIA) is None
        assert _registered(hass, MEDIA) is None
        assert "tank/Media Files" not in coordinator.ds["dataset"]

    run_in_hass(scenario)


def test_item_that_comes_back_in_time_loses_nothing(run_in_hass):
    """The wait starts over, and nothing is removed."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        everything = list(server.results["pool.dataset.query"])
        _without(server, "pool.dataset.query", "name", "tank/Media Files")
        await _poll(hass, coordinator, POLLS - 1)

        server.results["pool.dataset.query"] = everything
        await _poll(hass, coordinator)

        assert hass.states.get(MEDIA).state != "unavailable"

        _without(server, "pool.dataset.query", "name", "tank/Media Files")
        await _poll(hass, coordinator, POLLS - 1)

        assert _registered(hass, MEDIA) is not None

    run_in_hass(scenario)


def test_item_that_comes_back_after_its_removal_gets_the_same_ids(run_in_hass):
    """A new entity, with the old id and unique id."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        everything = list(server.results["pool.dataset.query"])
        _without(server, "pool.dataset.query", "name", "tank/Media Files")
        await _poll(hass, coordinator, POLLS)
        assert _registered(hass, MEDIA) is None

        server.results["pool.dataset.query"] = everything
        await _poll(hass, coordinator)

        assert _registered(hass, MEDIA).unique_id == MEDIA_UNIQUE_ID
        assert hass.states.get(MEDIA).state != "unavailable"

    run_in_hass(scenario)


def test_failed_query_is_not_a_deletion(run_in_hass):
    """Values stay, entities stay available, and no poll counts."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        value = hass.states.get(MEDIA).state
        server.errors["pool.dataset.query"] = "[EBUSY] busy"

        await _poll(hass, coordinator, POLLS * 3)

        assert hass.states.get(MEDIA).state == value
        assert _registered(hass, MEDIA) is not None

    run_in_hass(scenario)


def test_failed_query_does_not_count_towards_the_wait(run_in_hass):
    """Only successful answers without the item count."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        _without(server, "pool.dataset.query", "name", "tank/Media Files")
        await _poll(hass, coordinator, POLLS - 1)

        server.errors["pool.dataset.query"] = "[EBUSY] busy"
        await _poll(hass, coordinator, POLLS * 3)

        assert _registered(hass, MEDIA) is not None

    run_in_hass(scenario)


def test_poll_that_fails_is_not_a_deletion(run_in_hass):
    """Without a connection entities are unavailable, and nothing is removed."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.unanswered = {"system.info"}

        await _poll(hass, coordinator, POLLS * 3)

        assert not coordinator.last_update_success
        assert hass.states.get(MEDIA).state == "unavailable"
        assert _registered(hass, MEDIA) is not None

        server.unanswered = set()
        await _poll(hass, coordinator)

        assert hass.states.get(MEDIA).state != "unavailable"

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("method", "entity_id"),
    [
        ("app.query", DOCKER_APP),
        ("pool.dataset.query", MEDIA),
        ("vm.query", VM),
        ("service.query", "binary_sensor.truenas_services_cifs"),
        ("disk.query", "sensor.truenas_disks_sda"),
        ("cloudsync.query", "sensor.truenas_cloudsync_offsite_backup"),
    ],
)
def test_empty_list_never_removes_a_section(run_in_hass, method, entity_id):
    """Docker restarting or a pool still importing leave a list empty for a while."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        value = hass.states.get(entity_id).state
        server.results[method] = []

        await _poll(hass, coordinator, POLLS * 5)

        assert hass.states.get(entity_id).state == value
        assert _registered(hass, entity_id) is not None

    run_in_hass(scenario)


def test_stopped_apps_are_not_deleted(run_in_hass):
    """A stopped app is still listed: it is off, not gone."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.results["app.query"][0]["state"] = "STOPPED"

        await _poll(hass, coordinator, POLLS * 2)

        assert hass.states.get(DOCKER_APP).state == "off"

    run_in_hass(scenario)


def test_datasets_of_a_pool_that_is_gone_do_not_count(run_in_hass):
    """A pool can be exported or still importing: its datasets are not deleted."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        other = {
            **server.results["pool.query"][0],
            "guid": "222",
            "name": "other",
            "path": "/mnt/other",
        }
        server.results["pool.query"] = [other]
        server.results["pool.dataset.query"] = [_dataset("other", 5)]

        await _poll(hass, coordinator, POLLS * 2)

        assert hass.states.get(MEDIA).state != "unavailable"
        assert _registered(hass, MEDIA) is not None

    run_in_hass(scenario)


def test_empty_pool_list_keeps_the_pools_although_the_boot_pool_is_there(run_in_hass):
    """The boot pool is always answered, so it says nothing about the others."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.results["pool.query"] = []

        await _poll(hass, coordinator, POLLS * 2)

        tank = "binary_sensor.truenas_system_tank_healthy"
        assert hass.states.get(tank).state != "unavailable"
        assert _registered(hass, tank) is not None

    run_in_hass(scenario)


def test_boot_query_failing_keeps_the_boot_pool(run_in_hass):
    """Its entities do not count as missing because the query failed."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.errors["boot.get_state"] = "[EBUSY] busy"

        await _poll(hass, coordinator, POLLS * 2)

        boot = "binary_sensor.truenas_system_boot_pool_healthy"
        assert hass.states.get(boot).state != "unavailable"
        assert _registered(hass, boot) is not None

    run_in_hass(scenario)


def test_entity_of_a_removed_item_gets_no_key_error(run_in_hass, caplog):
    """An update after the item is gone writes no exception to the log."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        del coordinator.ds["dataset"]["tank/Media Files"]
        coordinator.present["dataset"] = {"tank"}

        with caplog.at_level(logging.ERROR):
            coordinator.async_update_listeners()
            await hass.async_block_till_done()

        assert "KeyError" not in caplog.text
        assert hass.states.get(MEDIA).state == "unavailable"

    run_in_hass(scenario)


def test_item_disabled_by_the_user_is_not_recreated(run_in_hass):
    """It stays disabled through polls and a reload."""

    async def scenario(hass, server):
        entry, coordinator = await _setup(hass, server)
        registry = er.async_get(hass)
        registry.async_update_entity(MEDIA, disabled_by=er.RegistryEntryDisabler.USER)
        await hass.async_block_till_done()

        await _poll(hass, coordinator, 2)

        assert _registered(hass, MEDIA).disabled
        assert hass.states.get(MEDIA) is None

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await _poll(hass, entry.runtime_data, 2)

        assert _registered(hass, MEDIA).disabled
        assert hass.states.get(MEDIA) is None

    run_in_hass(scenario)


def test_disabled_entity_of_a_deleted_item_is_removed(run_in_hass):
    """Nothing is left behind in the registry."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        registry = er.async_get(hass)
        registry.async_update_entity(MEDIA, disabled_by=er.RegistryEntryDisabler.USER)
        _without(server, "pool.dataset.query", "name", "tank/Media Files")

        await _poll(hass, coordinator, POLLS)

        assert _registered(hass, MEDIA) is None

    run_in_hass(scenario)


def test_read_only_entry_never_gets_switches(run_in_hass):
    """A new cron job adds no switch on a read-only entry."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server, access_level="read_only")
        server.results["cronjob.query"].append(
            {"id": 9, "description": "new", "enabled": True, "schedule": {}}
        )

        await _poll(hass, coordinator, 2)

        registry = er.async_get(hass)
        assert not [
            entry for entry in registry.entities.values() if entry.domain == "switch"
        ]

    run_in_hass(scenario)


def test_administrator_entry_gets_new_cron_jobs_disabled(run_in_hass):
    """A switch that controls TrueNAS starts disabled, also when it appears later."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.results["cronjob.query"].append(
            {"id": 9, "description": "New job", "enabled": True, "schedule": {}}
        )

        await _poll(hass, coordinator)

        assert _registered(hass, "switch.truenas_cron_jobs_new_job").disabled

    run_in_hass(scenario)


def test_entity_left_only_in_the_registry_is_removed(run_in_hass):
    """An item deleted while Home Assistant was off is not in the data at all."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        _without(server, "pool.dataset.query", "name", "tank/Media Files")

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        coordinator.stale_after_polls = POLLS
        assert _registered(hass, MEDIA) is not None

        await _poll(hass, coordinator, POLLS)

        assert _registered(hass, MEDIA) is None

    run_in_hass(scenario)


def test_registry_entity_of_a_pool_that_is_gone_stays(run_in_hass):
    """After a restart without its pool, a dataset's entity is kept."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        server.results["pool.query"] = [
            {**server.results["pool.query"][0], "guid": "222", "name": "other"}
        ]
        server.results["pool.dataset.query"] = [_dataset("other", 5)]

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        coordinator.stale_after_polls = POLLS

        await _poll(hass, coordinator, POLLS * 2)

        assert _registered(hass, MEDIA) is not None

    run_in_hass(scenario)


def _device_of(hass, entity_id):
    """Return the device of an entity."""
    device_id = _registered(hass, entity_id).device_id
    return dr.async_get(hass).async_get(device_id)


def test_system_device_cannot_be_deleted(run_in_hass):
    """It holds the system's own entities."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        device = _device_of(hass, "sensor.truenas_system_uptime")

        assert not await async_remove_config_entry_device(hass, entry, device)

    run_in_hass(scenario)


def test_system_device_left_by_a_rename_can_be_deleted(run_in_hass):
    """Its identifier holds the hostname, so a rename makes a new device."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        devices = dr.async_get(hass)
        old = devices.async_get(entry.runtime_data.system_device_id)
        assert old.identifiers == {(DOMAIN, "TrueNAS_nas")}

        server.results["system.info"]["hostname"] = "renamed"
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        current = devices.async_get(entry.runtime_data.system_device_id)
        assert current.id != old.id
        assert current.identifiers == {(DOMAIN, "TrueNAS_renamed")}
        registry = er.async_get(hass)
        assert not er.async_entries_for_device(registry, old.id, True)
        assert er.async_entries_for_device(registry, current.id, True)

        assert await async_remove_config_entry_device(hass, entry, old)
        assert not await async_remove_config_entry_device(hass, entry, current)

    run_in_hass(scenario)


def test_empty_current_system_device_cannot_be_deleted(run_in_hass):
    """Everything else links to it, whatever it holds right now."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        registry = er.async_get(hass)
        device = dr.async_get(hass).async_get(entry.runtime_data.system_device_id)
        for entity in er.async_entries_for_device(registry, device.id, True):
            registry.async_remove(entity.entity_id)

        assert not await async_remove_config_entry_device(hass, entry, device)

    run_in_hass(scenario)


def test_device_of_an_entry_that_is_not_loaded_cannot_be_deleted(run_in_hass):
    """It has no way to tell what TrueNAS still reports."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        device = dr.async_get(hass).async_get(entry.runtime_data.system_device_id)
        await hass.config_entries.async_unload(entry.entry_id)

        assert not await async_remove_config_entry_device(hass, entry, device)

    run_in_hass(scenario)


def test_device_with_live_items_cannot_be_deleted(run_in_hass):
    """Its entities would only come back."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)

        assert not await async_remove_config_entry_device(
            hass, entry, _device_of(hass, VM)
        )

    run_in_hass(scenario)


def test_device_of_a_section_left_empty_can_be_deleted(run_in_hass):
    """The way out for the last VM, which an empty list never removes."""

    async def scenario(hass, server):
        entry, coordinator = await _setup(hass, server)
        everything = list(server.results["vm.query"])
        server.results["vm.query"] = []
        await _poll(hass, coordinator)
        device = _device_of(hass, VM)

        assert await async_remove_config_entry_device(hass, entry, device)

        assert coordinator.ds["vm"] == {}
        # What Home Assistant does next, when this returns true
        dr.async_get(hass).async_remove_device(device.id)
        await hass.async_block_till_done()
        assert _registered(hass, VM) is None

        # It can come back
        server.results["vm.query"] = everything
        await _poll(hass, coordinator)
        assert _registered(hass, VM) is not None
        assert hass.states.get(VM).state == "on"

    run_in_hass(scenario)


def test_device_is_kept_while_its_section_is_unknown(run_in_hass):
    """Without a first answer it may well be there."""

    async def scenario(hass, server):
        entry, coordinator = await _setup(hass, server)
        device = _device_of(hass, VM)
        del coordinator.present["vm"]

        assert not await async_remove_config_entry_device(hass, entry, device)

    run_in_hass(scenario)
