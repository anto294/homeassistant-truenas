"""Tests that the uptime sensor only changes on a real reboot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util
import pytest

from custom_components.truenas_link import coordinator

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


def test_change_of_the_clock_does_not_change_the_state(run_in_hass, monkeypatch):
    """Going off summer time leaves the moment TrueNAS booted where it was."""
    # The hour before and the hour after clocks go back in Rome, on 25 October 2026.
    # The system's clock is what datetime.now() and timestamp() use.
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    rome = ZoneInfo("Europe/Rome")
    moment = [datetime(2026, 10, 25, 0, 30, tzinfo=UTC)]

    class LocalClock(datetime):
        """The local clock at the moment of the test."""

        @classmethod
        def now(cls, tz=None):
            return moment[0].astimezone(tz or rome).replace(tzinfo=tz)

    monkeypatch.setattr(coordinator, "datetime", LocalClock)
    monkeypatch.setattr(dt_util, "utcnow", lambda: moment[0])

    async def scenario(hass, server):
        server.results = answers("25.10")
        # Booted before the change, so the local time then had another offset
        server.results["system.info"]["uptime_seconds"] = 100000
        entry = await async_add_entry(hass)
        before = hass.states.get(UPTIME).state

        moment[0] += timedelta(hours=2)
        after = await _state_with_uptime(hass, server, entry, 100000 + 7200)

        assert after == before

    try:
        run_in_hass(scenario)
    finally:
        monkeypatch.undo()
        time.tzset()
