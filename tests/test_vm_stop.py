"""Tests for how VMs are stopped."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.truenas_link.binary_sensor import TrueNASVMBinarySensor


def test_virt_instance_stop_is_a_clean_shutdown():
    """On TrueNAS 25.04 a VM gets time to shut down and is never forced off."""
    sensor = TrueNASVMBinarySensor.__new__(TrueNASVMBinarySensor)
    sensor._data = {"id": "win11", "name": "win11"}

    query = MagicMock(return_value={"status": "RUNNING"})
    sensor.coordinator = SimpleNamespace(
        api=SimpleNamespace(query=query), version_at_least=lambda *_: False
    )

    async def run_job(func, *args):
        return func(*args)

    sensor.hass = SimpleNamespace(async_add_executor_job=run_job)

    async def running():
        return "RUNNING"

    sensor._get_state = running

    asyncio.run(sensor.stop())

    query.assert_called_once_with(
        "virt.instance.stop", ["win11", {"timeout": 60, "force": False}]
    )
