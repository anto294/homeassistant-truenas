"""Tests that the uptime sensor only changes on a real reboot."""

from __future__ import annotations

import pytest

from .conftest import async_add_entry
from .sample_data import answers

UPTIME = "sensor.truenas_system_uptime"


async def _state_with_uptime(hass, server, entry, seconds):
    """Return the sensor's state after an update that reports this uptime."""
    server.results["system.info"]["uptime_seconds"] = seconds
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    return hass.states.get(UPTIME).state


@pytest.mark.parametrize(
    "seconds",
    [100000, 100001, 99999, 100003, 99997, 100000.75, 100001.2, 99999.9],
)
def test_small_differences_do_not_change_the_state(run_in_hass, seconds):
    """Also with the decimals that TrueNAS can report."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"]["uptime_seconds"] = 100000
        entry = await async_add_entry(hass)
        before = hass.states.get(UPTIME).state

        assert await _state_with_uptime(hass, server, entry, seconds) == before

    run_in_hass(scenario)


@pytest.mark.parametrize("seconds", [30, 30.5, 99000, 101000])
def test_real_reboot_changes_the_state(run_in_hass, seconds):
    """A much lower uptime, or a clock that really moved."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"]["uptime_seconds"] = 100000
        entry = await async_add_entry(hass)
        before = hass.states.get(UPTIME).state

        after = await _state_with_uptime(hass, server, entry, seconds)

        assert after != before

    run_in_hass(scenario)


def test_small_differences_do_not_add_up(run_in_hass):
    """Each update is compared with the value kept, not with the one before it."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.info"]["uptime_seconds"] = 100000
        entry = await async_add_entry(hass)
        before = hass.states.get(UPTIME).state

        for seconds in (100002, 100004, 100006, 100008):
            assert await _state_with_uptime(hass, server, entry, seconds) == before

        # 20 seconds from the value kept: the clock really moved, once
        after = await _state_with_uptime(hass, server, entry, 100020)
        assert after != before
        assert await _state_with_uptime(hass, server, entry, 100021) == after

    run_in_hass(scenario)


def test_first_reading_sets_the_state(run_in_hass):
    """There is nothing to compare it with."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        await async_add_entry(hass)

        assert hass.states.get(UPTIME).state != "unknown"

    run_in_hass(scenario)
