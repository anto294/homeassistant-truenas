"""Tests for the cron job switches and their removal on read-only entries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.truenas_link import switch as switch_module
from custom_components.truenas_link.coordinator import TrueNASCoordinator
from custom_components.truenas_link.switch import TrueNASCronJobSwitch
from custom_components.truenas_link.switch_types import SENSOR_TYPES

from .test_api import _reply

JOB = {
    "id": 3,
    "description": "Nightly backup",
    "enabled": True,
    "schedule": {"minute": "0", "hour": "3", "dom": "*", "month": "*", "dow": "*"},
}


def _coordinator(api, read_only=False):
    """Build a coordinator around `api` without a Home Assistant instance."""
    coordinator = TrueNASCoordinator.__new__(TrueNASCoordinator)
    coordinator.host = "truenas.lan"
    coordinator.api = api
    coordinator.present = {}
    coordinator.answered = set()
    coordinator.pool_names = set()
    coordinator.read_only = read_only
    coordinator.ds = {"cronjob": {}}
    return coordinator


def test_query_never_asks_for_command_or_user(connected_api):
    """Commands can hold secrets, so they are not even requested."""
    api, ws = connected_api(_reply(result=[JOB]))
    coordinator = _coordinator(api)

    coordinator.get_cronjob()

    request = ws.requests[0]
    assert request["method"] == "cronjob.query"
    assert set(request["params"][1]["select"]) == {
        "id",
        "description",
        "enabled",
        "schedule",
    }
    job = coordinator.ds["cronjob"][3]
    assert job["enabled"] is True
    assert job["cron_name"] == "Nightly backup"
    assert job["schedule"] == "0 3 * * *"
    assert "command" not in job and "user" not in job


def test_job_without_description_gets_a_name(connected_api):
    """A description is optional in TrueNAS."""
    api, _ = connected_api(_reply(result=[{**JOB, "description": ""}]))
    coordinator = _coordinator(api)

    coordinator.get_cronjob()

    assert coordinator.ds["cronjob"][3]["cron_name"] == "Cron job 3"


def test_read_only_entry_does_not_query_cron_jobs(connected_api):
    """Read-only entries have no switches, so nothing is fetched."""
    api, ws = connected_api(_reply(result=[JOB]))
    coordinator = _coordinator(api, read_only=True)

    coordinator.get_cronjob()

    assert ws.requests == []
    assert coordinator.ds["cronjob"] == {}


def test_switch_is_safe_by_default():
    """Off until enabled, and not reachable by voice or area commands."""
    description = SENSOR_TYPES[0]

    assert description.entity_registry_enabled_default is False
    assert description.entity_category is EntityCategory.CONFIG


def _switch(enabled=True):
    """Return a switch with just what turning it on and off reads."""
    switch = TrueNASCronJobSwitch.__new__(TrueNASCronJobSwitch)
    switch._data = {"id": 3, "enabled": enabled}
    switch.coordinator = SimpleNamespace(
        api=SimpleNamespace(call=MagicMock()), async_refresh=AsyncMock()
    )

    async def run_job(func, *args):
        return func(*args)

    switch.hass = SimpleNamespace(async_add_executor_job=run_job)
    return switch


def test_switch_only_sends_enabled():
    """Turning it on or off changes nothing else about the job."""
    switch = _switch()

    asyncio.run(switch.async_turn_off())
    switch.coordinator.api.call.assert_called_once_with(
        "cronjob.update", [3, {"enabled": False}]
    )
    switch.coordinator.async_refresh.assert_awaited_once()

    switch.coordinator.api.call.reset_mock()
    asyncio.run(switch.async_turn_on())
    switch.coordinator.api.call.assert_called_once_with(
        "cronjob.update", [3, {"enabled": True}]
    )


def _entry_for(read_only):
    """Return a stand-in config entry with the given access level."""
    return SimpleNamespace(
        entry_id="entry", runtime_data=SimpleNamespace(read_only=read_only)
    )


def test_read_only_setup_removes_switches_and_adds_none(monkeypatch):
    """Going read-only removes the switches instead of adding them."""
    add = AsyncMock()
    remove = MagicMock()
    monkeypatch.setattr(switch_module, "async_add_entities", add)
    monkeypatch.setattr(switch_module, "async_remove_switches", remove)
    hass = MagicMock()
    entry = _entry_for(True)

    asyncio.run(switch_module.async_setup_entry(hass, entry, None))

    remove.assert_called_once_with(hass, entry)
    add.assert_not_awaited()


def test_administrator_setup_adds_switches(monkeypatch):
    """An Administrator entry sets the switches up as usual."""
    add = AsyncMock()
    remove = MagicMock()
    monkeypatch.setattr(switch_module, "async_add_entities", add)
    monkeypatch.setattr(switch_module, "async_remove_switches", remove)

    asyncio.run(switch_module.async_setup_entry(MagicMock(), _entry_for(False), None))

    add.assert_awaited_once()
    remove.assert_not_called()
