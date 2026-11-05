"""Tests for the scrub actions on the pool scan sensor."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.truenas_link.sensor import TrueNASPoolScanSensor


def _sensor(status="idle", name="tank", version=(25, 10)):
    """Return a scan sensor with just what the actions read."""
    sensor = TrueNASPoolScanSensor.__new__(TrueNASPoolScanSensor)
    sensor._data = {"name": name, "scan_status": status}
    sensor.coordinator = SimpleNamespace(
        api=SimpleNamespace(call=AsyncMock()),
        version_at_least=lambda major, minor=0: version >= (major, minor),
        async_refresh=AsyncMock(),
    )

    return sensor


@pytest.mark.parametrize(
    ("status", "method", "legacy", "current"),
    [
        ("idle", "start", "START", "START"),
        ("paused", "start", "START", "START"),
        ("scrubbing", "pause", "PAUSE", "PAUSE"),
        ("scrubbing", "stop", "STOP", "CANCEL"),
        ("paused", "stop", "STOP", "CANCEL"),
    ],
)
@pytest.mark.parametrize("version", [(25, 4), (25, 10), (27, 0)])
def test_action_uses_the_method_of_the_running_version(
    status, method, legacy, current, version
):
    """pool.scrub.scrub until 25.10, zpool.scrub.run from 27.0."""
    sensor = _sensor(status, version=version)

    asyncio.run(getattr(sensor, method)())

    if version >= (27, 0):
        expected = (
            "zpool.scrub.run",
            [{"pool_name": "tank", "action": current, "threshold": 0}],
        )
    else:
        expected = ("pool.scrub.scrub", ["tank", legacy])
    sensor.coordinator.api.call.assert_called_once_with(*expected)
    sensor.coordinator.async_refresh.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "method"),
    [
        ("scrubbing", "start"),
        ("idle", "pause"),
        ("paused", "pause"),
        ("idle", "stop"),
        # A resilver must stay out of reach of every action
        ("resilvering", "start"),
        ("resilvering", "pause"),
        ("resilvering", "stop"),
    ],
)
def test_action_is_refused_in_the_wrong_state(status, method):
    """Nothing is sent to TrueNAS if the action does not apply."""
    sensor = _sensor(status)

    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(getattr(sensor, method)())

    assert err.value.translation_key == "invalid_state"
    sensor.coordinator.api.call.assert_not_called()


@pytest.mark.parametrize("name", ["boot-pool", "freenas-boot"])
def test_boot_pool_is_refused(name):
    """The boot pool has no scrub actions."""
    sensor = _sensor(name=name)

    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(sensor.start())

    assert err.value.translation_key == "scrub_boot_pool"
    sensor.coordinator.api.call.assert_not_called()
