"""Tests that a value TrueNAS does not report is unknown, and not a false 0."""

from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN

from homeassistant.helpers import entity_registry as er

from .conftest import async_add_entry
from .sample_data import answers

CPU_TEMPERATURE = "sensor.truenas_system_temperature"
CPU_USAGE = "sensor.truenas_system_cpu_usage"
LOAD = "sensor.truenas_system_cpu_load_shortterm"
ARC = "sensor.truenas_system_arc_size"
MEMORY = "sensor.truenas_system_memory_usage"
RX = "sensor.truenas_system_eno1_rx"
UPTIME = "sensor.truenas_system_uptime"
DISK = "sensor.truenas_disks_sda"
OTHER_DISK = "sensor.truenas_disks_nvme0n1"
GRAPHS = "reporting.netdata_get_data"
FROM_GRAPHS = (CPU_TEMPERATURE, CPU_USAGE, LOAD, ARC, MEMORY, RX)


def _without_samples(server):
    """Make every graph answer without samples, as 27.0 can."""
    server.results[GRAPHS] = [
        {**graph, "aggregations": None} for graph in server.results[GRAPHS]
    ]


def _with_mean(server, value):
    """Make every graph report the same value."""
    server.results[GRAPHS] = [
        {
            **graph,
            "aggregations": {
                "mean": {entry: value for entry in graph["legend"] if entry != "time"},
            },
        }
        for graph in server.results[GRAPHS]
    ]


def _state(hass, entity_id):
    """Return the state of an entity, which must exist."""
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def _refresh(hass, entry):
    """Poll once."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def _add_entry(hass, **overrides):
    """Add an entry, with ARC size enabled as these tests look at it."""
    entry = await async_add_entry(hass, **overrides)
    er.async_get(hass).async_update_entity(ARC, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_graphs_without_samples_at_first_still_create_the_sensors(run_in_hass):
    """The sensors exist from the start, with the same ids, and are unknown."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        _without_samples(server)

        await _add_entry(hass)

        for entity_id in FROM_GRAPHS:
            assert _state(hass, entity_id) == STATE_UNKNOWN, entity_id

    run_in_hass(scenario)


def test_graphs_that_lose_their_samples_become_unknown(run_in_hass):
    """Except memory, because a moment without samples says nothing about it."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await _add_entry(hass)
        assert _state(hass, CPU_USAGE) == "2.5"
        memory = _state(hass, MEMORY)

        _without_samples(server)
        await _refresh(hass, entry)

        for entity_id in (CPU_TEMPERATURE, CPU_USAGE, LOAD, ARC, RX):
            assert _state(hass, entity_id) == STATE_UNKNOWN, entity_id
        assert _state(hass, MEMORY) == memory

    run_in_hass(scenario)


def test_a_mean_of_null_is_unknown_and_a_real_zero_stays_zero(run_in_hass):
    """The two look the same to a check for a true value."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await _add_entry(hass)

        _with_mean(server, None)
        await _refresh(hass, entry)
        for entity_id in (CPU_TEMPERATURE, CPU_USAGE, LOAD, ARC, RX):
            assert _state(hass, entity_id) == STATE_UNKNOWN, entity_id

        _with_mean(server, 0.0)
        await _refresh(hass, entry)
        for entity_id in (CPU_TEMPERATURE, CPU_USAGE, LOAD, ARC, RX):
            assert float(_state(hass, entity_id)) == 0.0, entity_id
        # Nothing available means all of it is in use
        assert _state(hass, MEMORY) == "100"

    run_in_hass(scenario)


def test_failed_graphs_keep_the_last_values(run_in_hass):
    """A query that fails says nothing about the values."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await _add_entry(hass)

        server.errors[GRAPHS] = "[EBUSY] busy"
        await _refresh(hass, entry)

        for entity_id in FROM_GRAPHS:
            assert _state(hass, entity_id) != STATE_UNKNOWN, entity_id

    run_in_hass(scenario)


def test_virtual_truenas_keeps_its_cpu_temperature_sensor_unknown(run_in_hass):
    """It is never asked for, so it would otherwise not exist after this change."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"]["system_manufacturer"] = "QEMU"
        # TrueNAS answers with the graphs it is asked for, and this one is not
        server.results[GRAPHS] = [
            graph for graph in server.results[GRAPHS] if graph["name"] != "cputemp"
        ]
        entry = await _add_entry(hass)
        await _refresh(hass, entry)

        assert _state(hass, CPU_TEMPERATURE) == STATE_UNKNOWN

    run_in_hass(scenario)


def test_entity_of_a_value_never_read_is_still_not_created(run_in_hass):
    """Unknown is for a value without a reading, not for one that could not be read."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.errors["alert.list"] = "[EPERM] not allowed"

        await _add_entry(hass)

        assert hass.states.get("sensor.truenas_system_alerts") is None

    run_in_hass(scenario)


def test_disk_temperatures(run_in_hass):
    """A reported 0 stays, a disk left out is unknown, and a failure keeps the rest."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await _add_entry(hass)
        assert _state(hass, DISK) == "33"

        server.results["disk.temperatures"] = {"sda": 0, "nvme0n1": None}
        await _refresh(hass, entry)
        assert _state(hass, DISK) == "0"
        assert _state(hass, OTHER_DISK) == STATE_UNKNOWN

        server.results["disk.temperatures"] = {"sda": 35}
        await _refresh(hass, entry)
        assert _state(hass, DISK) == "35"
        assert _state(hass, OTHER_DISK) == STATE_UNKNOWN

        server.errors["disk.temperatures"] = "[EBUSY] busy"
        await _refresh(hass, entry)
        assert _state(hass, DISK) == "35"

    run_in_hass(scenario)


def test_disk_without_temperature_from_the_start_is_unknown(run_in_hass):
    """The entity exists, as every disk has one."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["disk.temperatures"] = {}

        await _add_entry(hass)

        assert _state(hass, DISK) == STATE_UNKNOWN

    run_in_hass(scenario)


def test_uptime_without_a_reading_is_unknown(run_in_hass):
    """A timestamp sensor cannot show 0 at all."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"] = {
            key: value
            for key, value in server.results["system.info"].items()
            if key != "uptime_seconds"
        }

        await _add_entry(hass)

        assert _state(hass, UPTIME) == STATE_UNKNOWN

    run_in_hass(scenario)
