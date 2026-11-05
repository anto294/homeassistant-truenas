"""Tests for how polling handles what real systems return."""

from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest

from custom_components.truenas_link import async_remove_config_entry_device
from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry
from .sample_data import answers

SYSTEM_UPDATE = "update.truenas_system"
PLEX_UPDATE = "update.truenas_apps_plex"


async def _refresh(hass, coordinator):
    """Poll once."""
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def _setup(hass, server, version="25.10", **overrides):
    """Add an entry on sample answers."""
    server.results = answers(version)
    entry = await async_add_entry(hass, **overrides)
    return entry, entry.runtime_data


def test_system_update_is_followed_until_its_job_ends(run_in_hass):
    """update.run returns a job, whose progress shows on the entity."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        coordinator.ds["system_info"]["update_available"] = True
        server.results["update.run"] = 42
        server.results["core.get_jobs"] = [
            {"id": 42, "state": "RUNNING", "progress": {"percent": 0}}
        ]

        await hass.services.async_call(
            "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
        )
        await hass.async_block_till_done()

        # Home Assistant takes 0 for "no progress", so the entity starts from 1
        info = coordinator.ds["system_info"]
        assert info["update_jobid"] == 42
        assert info["update_state"] == "RUNNING"
        assert hass.states.get(SYSTEM_UPDATE).attributes["in_progress"] is not False

        server.results["core.get_jobs"] = [
            {"id": 42, "state": "RUNNING", "progress": {"percent": 30}}
        ]
        await _refresh(hass, coordinator)
        assert info["update_progress"] == 30

        server.results["core.get_jobs"] = [
            {"id": 42, "state": "SUCCESS", "progress": {"percent": 100}}
        ]
        await _refresh(hass, coordinator)
        assert info["update_jobid"] == 0
        assert info["update_state"] == "unknown"

    run_in_hass(scenario)


def test_lost_connection_while_following_a_job_fails_the_poll(run_in_hass):
    """The job stays followed for the next poll."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        coordinator.ds["system_info"]["update_jobid"] = 42
        server.unanswered = {"core.get_jobs"}

        await _refresh(hass, coordinator)

        assert not coordinator.last_update_success
        assert coordinator.ds["system_info"]["update_jobid"] == 42

    run_in_hass(scenario)


def test_app_update_keeps_its_job_id(run_in_hass):
    """app.upgrade returns a job id, which is kept on the app."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        server.results["app.upgrade"] = 55

        await hass.services.async_call(
            "update", "install", {"entity_id": PLEX_UPDATE}, blocking=True
        )
        await hass.async_block_till_done()

        assert entry.runtime_data.ds["app"]["plex"]["update_jobid"] == 55

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("status", "available"),
    [
        ({"code": "NORMAL", "error": None, "status": {"new_version": None}}, False),
        ({"code": "ERROR", "error": {"errname": "ENET"}, "status": None}, False),
        (
            {
                "code": "NORMAL",
                "error": None,
                "status": {"new_version": {"version": "99.0"}},
            },
            True,
        ),
    ],
    ids=["up to date", "error", "available"],
)
def test_update_status_on_25_10(run_in_hass, status, available):
    """update.status says it in three ways."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["update.status"] = status

        entry = await async_add_entry(hass)

        assert entry.runtime_data.ds["system_info"]["update_available"] is available

    run_in_hass(scenario)


def test_update_check_on_25_04(run_in_hass):
    """update.check_available reports a status and a version."""

    async def scenario(hass, server):
        server.results = answers("25.04")
        server.results["update.check_available"] = {
            "status": "AVAILABLE",
            "version": "25.04.3",
        }

        entry = await async_add_entry(hass)

        info = entry.runtime_data.ds["system_info"]
        assert info["update_available"] is True
        assert info["update_version"] == "25.04.3"

    run_in_hass(scenario)


def test_version_that_cannot_be_read_counts_as_the_latest(run_in_hass, caplog):
    """The API of current releases is the most likely to be right."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"]["version"] = "something new"

        with caplog.at_level(logging.WARNING):
            entry = await async_add_entry(hass)

        assert "unable to parse version" in caplog.text
        assert entry.runtime_data.version_at_least(99, 0)

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("method", "section", "version"),
    [
        ("vm.query", "vm", "25.10"),
        ("virt.instance.query", "vm", "25.04"),
        ("container.query", "container", "27.0"),
    ],
)
def test_failed_query_keeps_converted_values(run_in_hass, method, section, version):
    """Memory is converted once, and not again from its last value."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server, version)
        before = {uid: dict(item) for uid, item in coordinator.ds[section].items()}
        server.errors[method] = "[EBUSY] busy"

        await _refresh(hass, coordinator)

        assert coordinator.last_update_success
        assert coordinator.ds[section] == before

    run_in_hass(scenario)


def test_failed_alert_and_reboot_queries_keep_their_values(run_in_hass):
    """Single queries failing only keep what they had."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.errors["alert.list"] = "[EBUSY] busy"
        server.errors["system.reboot.info"] = "[EBUSY] busy"

        await _refresh(hass, coordinator)

        info = coordinator.ds["system_info"]
        assert info["alerts_active"] == 1
        assert info["reboot_required"] is True

    run_in_hass(scenario)


def test_virtual_machine_does_not_ask_for_cpu_temperature(run_in_hass):
    """A virtual TrueNAS has no such graph, which would fail the whole call."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.results["system.info"]["system_manufacturer"] = "QEMU"
        await _refresh(hass, coordinator)
        await _refresh(hass, coordinator)

        last = [
            request["params"]
            for request in server.sockets[-1].requests
            if request["method"] == "reporting.netdata_get_data"
        ][-1]
        assert "cputemp" not in [graph["name"] for graph in last[0]]

    run_in_hass(scenario)


def test_lost_connection_while_querying_graphs_one_by_one(run_in_hass):
    """No graph counts as failed because the connection dropped."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        calls = []
        real_query = coordinator.api.query

        def query(method, params={}):
            if method != "reporting.netdata_get_data":
                return real_query(method, params)

            calls.append(params)
            if len(calls) == 1:
                coordinator.api._failed_methods[method] = "x"
                return None

            coordinator.api.disconnect()
            return None

        coordinator.api.query = query
        await coordinator.hass.async_add_executor_job(coordinator.get_systemstats)

        assert coordinator._systemstats_errored == []

    run_in_hass(scenario)


def test_stats_with_nothing_left_to_ask_for(run_in_hass):
    """Every graph failed before: no call is made."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        coordinator._systemstats_errored = [
            ("load", None),
            ("cputemp", None),
            ("cpu", None),
            ("arcsize", None),
            ("memory", None),
            ("interface", "eno1"),
        ]
        before = len(server.sockets[-1].requests)

        await coordinator.hass.async_add_executor_job(coordinator.get_systemstats)

        assert len(server.sockets[-1].requests) == before

    run_in_hass(scenario)


def test_graphs_without_samples_or_a_name(run_in_hass):
    """27.0 may return null aggregations for a window without samples."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        info = coordinator.ds["system_info"]
        free = info["memory-free_value"]
        empty = {"aggregations": None, "legend": []}
        server.results["reporting.netdata_get_data"] = [
            {"legend": []},
            {**empty, "name": "cputemp", "identifier": None},
            {**empty, "name": "memory", "identifier": None},
            {**empty, "name": "interface", "identifier": "eno1"},
            {**empty, "name": "interface", "identifier": "gone"},
            {
                "name": "cputemp",
                "identifier": None,
                "legend": ["cpu0"],
                "aggregations": {"mean": {"cpu0": None}},
            },
        ]

        await _refresh(hass, coordinator)

        assert info["cpu_temperature"] == 0.0
        # Kept, because 0 free would mean 100% used
        assert info["memory-free_value"] == free
        assert coordinator.ds["interface"]["eno1"]["rx"] == 0.0
        assert coordinator.ds["interface"]["eno1"]["tx"] == 0.0

    run_in_hass(scenario)


def test_graph_values(run_in_hass):
    """The sample answer ends up in the sensors, in the units they declare."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        await _refresh(hass, coordinator)

        info = coordinator.ds["system_info"]
        assert info["load_shortterm"] == 2.5
        assert info["cpu_usage"] == 2.5
        assert info["cpu_temperature"] == 2.5
        assert info["cache_size-arc_value"] == 2.5
        assert coordinator.ds["interface"]["eno1"]["rx"] == round(2.5 * 0.12207, 2)

    run_in_hass(scenario)


def test_going_read_only_removes_switches_and_their_device(run_in_hass):
    """Nothing is left of the cron jobs, not even a disabled entity."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        registry = er.async_get(hass)
        switch = registry.async_get("switch.truenas_cron_jobs_nightly_check")
        device_id = switch.device_id
        assert device_id

        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {"host": "nas", "access_level": "read_only", "verify_ssl": False},
        )
        await hass.async_block_till_done()

        assert registry.async_get("switch.truenas_cron_jobs_nightly_check") is None
        assert dr.async_get(hass).async_get(device_id) is None

    run_in_hass(scenario)


def test_enabled_cron_switch_shows_and_changes_the_job(run_in_hass):
    """Once the user enables the entity, it works."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        entity_id = "switch.truenas_cron_jobs_nightly_check"
        er.async_get(hass).async_update_entity(entity_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get(entity_id).state == "on"

        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )

        sent = [
            request["params"]
            for socket in server.sockets
            for request in socket.requests
            if request["method"] == "cronjob.update"
        ]
        assert sent == [[1, {"enabled": False}]]

    run_in_hass(scenario)


def test_device_with_an_entity_that_is_not_an_item_is_kept(run_in_hass):
    """An entity from before, of unknown form, is not ours to remove."""

    async def scenario(hass, server):
        entry, _ = await _setup(hass, server)
        registry = er.async_get(hass)
        vm = registry.async_get("binary_sensor.truenas_vms_win11")
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            "not-a-known-form",
            config_entry=entry,
            device_id=vm.device_id,
        )
        device = dr.async_get(hass).async_get(vm.device_id)

        assert not await async_remove_config_entry_device(hass, entry, device)

    run_in_hass(scenario)


def test_action_error_keeps_the_entity_working(run_in_hass):
    """A refusal is reported, and leaves the connection for the next poll."""

    async def scenario(hass, server):
        _, coordinator = await _setup(hass, server)
        server.errors["system.reboot"] = "[EPERM] not allowed"

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN,
                "system_reboot",
                {"entity_id": "sensor.truenas_system_uptime"},
                blocking=True,
            )

        assert coordinator.connected()

    run_in_hass(scenario)
