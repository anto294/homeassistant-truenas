"""Tests for the replication_run action."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.truenas_link.sensor import TrueNASReplicationSensor


def _sensor(task):
    """Return a replication sensor whose task looks like `task`."""
    sensor = TrueNASReplicationSensor.__new__(TrueNASReplicationSensor)
    sensor._data = {"id": 7, "name": "offsite"}
    sensor.coordinator = SimpleNamespace(
        api=SimpleNamespace(query=MagicMock(return_value=task)),
        async_refresh=AsyncMock(),
    )

    async def run_job(func, *args):
        return func(*args)

    sensor.hass = SimpleNamespace(async_add_executor_job=run_job)
    return sensor


@pytest.mark.parametrize("task", [{"job": None}, {"job": {"state": "SUCCESS"}}])
def test_run_starts_an_idle_task(task):
    """A task that never ran or has finished can run."""
    sensor = _sensor(task)

    asyncio.run(sensor.start())

    sensor.coordinator.api.query.assert_called_with("replication.run", [7])


@pytest.mark.parametrize("state", ["WAITING", "RUNNING"])
def test_run_does_not_start_a_running_task(state):
    """A task that is already running is left alone."""
    sensor = _sensor({"job": {"state": state}})

    asyncio.run(sensor.start())

    sensor.coordinator.api.query.assert_called_once_with(
        "replication.get_instance", [7]
    )


def test_run_gives_up_if_the_task_cannot_be_read():
    """A failed query does not start anything."""
    sensor = _sensor(None)

    asyncio.run(sensor.start())

    sensor.coordinator.api.query.assert_called_once_with(
        "replication.get_instance", [7]
    )
