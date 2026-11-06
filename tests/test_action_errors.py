"""Tests for how actions report failures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.truenas_link import binary_sensor, sensor, switch, update
from custom_components.truenas_link.api import (
    TrueNASConnectionError,
    TrueNASRequestError,
)

COMPONENT = Path(__file__).parent.parent / "custom_components" / "truenas_link"
# Answers to the reads actions make before they change anything
READS = {
    "cloudsync.get_instance": {"job": {"state": "RUNNING"}},
    "replication.get_instance": {"job": None},
    "vm.get_instance": {"status": {"state": "STOPPED"}},
    "container.get_instance": {"status": {"state": "STOPPED"}},
    "service.get_instance": {"state": "RUNNING"},
    "app.get_instance": {"state": "RUNNING"},
}


def _entity(cls, data, answer, app_state="RUNNING"):
    """Return an entity with just what its actions read, answering with `answer`."""

    def call(method, _params):
        if method in READS and answer is not READ_FAILS:
            return READS[method]

        if isinstance(answer, Exception):
            raise answer
        if answer is READ_FAILS:
            raise TrueNASRequestError("refused")

        return answer

    entity = cls.__new__(cls)
    entity._data = data
    entity.coordinator = SimpleNamespace(
        api=SimpleNamespace(call=AsyncMock(side_effect=call)),
        version_at_least=lambda *_: True,
        async_refresh=AsyncMock(),
        data={"app": {"plex": {"state": app_state}}},
    )

    return entity


READ_FAILS = object()
VM = {"id": "vm", "vm_id": 1, "name": "vm"}
CONTAINER = {"id": "box", "container_id": 2, "name": "box"}
SERVICE = {"id": 3, "service": "ssh"}
APP = {"id": "plex", "name": "plex"}
TASK = {"id": 4, "name": "task", "description": "task"}
POOL = {"name": "tank", "scan_status": "idle"}
# Every action, set up so that it gets as far as changing something
ACTIONS = [
    (sensor.TrueNASUptimeSensor, {}, "restart", ()),
    (sensor.TrueNASUptimeSensor, {}, "stop", ()),
    (sensor.TrueNASPoolScanSensor, POOL, "start", ()),
    (sensor.TrueNASReplicationSensor, TASK, "start", ()),
    (sensor.TrueNASDatasetSensor, {"name": "tank/data"}, "snapshot", ()),
    (sensor.TrueNASClousyncSensor, TASK, "stop", ()),
    (binary_sensor.TrueNASVMBinarySensor, VM, "start", ()),
    (binary_sensor.TrueNASContainerBinarySensor, CONTAINER, "start", ()),
    (binary_sensor.TrueNASServiceBinarySensor, SERVICE, "stop", ()),
    (binary_sensor.TrueNASServiceBinarySensor, SERVICE, "restart", ()),
    (binary_sensor.TrueNASServiceBinarySensor, SERVICE, "reload", ()),
    (binary_sensor.TrueNASAppBinarySensor, APP, "stop", ()),
    (update.TrueNASUpdate, {}, "async_install", ("1", False)),
    (update.TrueNASAppUpdate, {"id": "plex"}, "async_install", ("1", False)),
    (switch.TrueNASCronJobSwitch, {"id": 5}, "async_turn_on", ()),
]


@pytest.mark.parametrize(("cls", "data", "method", "args"), ACTIONS)
def test_refusal_raises_a_translated_error(cls, data, method, args):
    """When TrueNAS refuses, the action fails and the reason reaches the user."""
    entity = _entity(cls, dict(data), TrueNASRequestError("[EBUSY] busy"))

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(getattr(entity, method)(*args))

    assert err.value.translation_key == "action_rejected"
    assert err.value.translation_placeholders["reason"] == "[EBUSY] busy"
    assert "update_jobid" not in entity._data


@pytest.mark.parametrize(("cls", "data", "method", "args"), ACTIONS)
def test_unreachable_truenas_raises_a_translated_error(cls, data, method, args):
    """When TrueNAS cannot be reached, the action fails."""
    entity = _entity(cls, dict(data), TrueNASConnectionError("no route"))

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(getattr(entity, method)(*args))

    assert err.value.translation_key == "action_unreachable"


@pytest.mark.parametrize("method", ["restart", "stop"])
def test_power_action_succeeds_if_the_connection_drops_after_sending(method):
    """A NAS going down can close the connection before it answers."""
    error = TrueNASConnectionError("connection closed", request_sent=True)
    entity = _entity(sensor.TrueNASUptimeSensor, {}, error)

    asyncio.run(getattr(entity, method)())

    entity.coordinator.api.call.assert_called_once()


def test_only_power_actions_accept_a_dropped_connection():
    """Elsewhere a dropped connection means the outcome is unknown: report it."""
    error = TrueNASConnectionError("connection closed", request_sent=True)
    entity = _entity(sensor.TrueNASDatasetSensor, {"name": "tank/data"}, error)

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.snapshot())


@pytest.mark.parametrize("method", ["restart", "stop"])
def test_power_action_that_succeeds_with_null(method):
    """system.reboot and system.shutdown can answer null on success."""
    entity = _entity(sensor.TrueNASUptimeSensor, {}, None)

    asyncio.run(getattr(entity, method)())


@pytest.mark.parametrize("method", ["stop", "restart", "reload"])
def test_service_method_that_returns_false_fails(method):
    """service.* returns false instead of raising if the operation fails."""
    entity = _entity(binary_sensor.TrueNASServiceBinarySensor, SERVICE, False)

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(getattr(entity, method)())

    assert err.value.translation_key == "action_failed"
    entity.coordinator.async_refresh.assert_not_awaited()


def test_cloudsync_abort_that_returns_false_fails():
    """cloudsync.abort returns false if it could not abort."""
    entity = _entity(sensor.TrueNASClousyncSensor, TASK, False)

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(entity.stop())

    assert err.value.translation_key == "action_failed"


@pytest.mark.parametrize("method", ["start", "stop"])
def test_cloudsync_survives_a_failed_read(method):
    """These two raised a TypeError on None when the read failed."""
    entity = _entity(sensor.TrueNASClousyncSensor, TASK, READ_FAILS)

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(getattr(entity, method)())

    assert err.value.translation_key == "action_rejected"


def test_cloudsync_task_that_never_ran_can_start(monkeypatch):
    """job is null for a task that has never run."""
    monkeypatch.setitem(READS, "cloudsync.get_instance", {"job": None})
    entity = _entity(sensor.TrueNASClousyncSensor, TASK, None)

    asyncio.run(entity.start())

    entity.coordinator.api.call.assert_called_with("cloudsync.sync", [4])


def test_cloudsync_task_that_never_ran_cannot_be_aborted(monkeypatch):
    """There is nothing to abort."""
    monkeypatch.setitem(READS, "cloudsync.get_instance", {"job": None})
    entity = _entity(sensor.TrueNASClousyncSensor, TASK, None)

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.stop())


def test_running_cloudsync_task_is_not_started_again():
    """A second run is refused without calling TrueNAS."""
    entity = _entity(sensor.TrueNASClousyncSensor, TASK, None)

    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(entity.start())

    assert err.value.translation_key == "invalid_state"
    entity.coordinator.api.call.assert_called_once()


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (binary_sensor.TrueNASVMBinarySensor, VM),
        (binary_sensor.TrueNASContainerBinarySensor, CONTAINER),
    ],
)
def test_vm_and_container_in_the_wrong_state_are_refused(cls, data):
    """Stopping what is stopped is a validation error."""
    entity = _entity(cls, data, None)

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.stop())

    entity.coordinator.api.call.assert_called_once()


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (binary_sensor.TrueNASServiceBinarySensor, SERVICE),
        (binary_sensor.TrueNASAppBinarySensor, APP),
    ],
)
def test_service_and_app_in_the_wrong_state_are_refused(cls, data):
    """Starting what runs is a validation error."""
    entity = _entity(cls, data, None)

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.start())

    entity.coordinator.api.call.assert_called_once()


def test_stopped_app_cannot_be_upgraded():
    """An app has to run to be upgraded."""
    entity = _entity(update.TrueNASAppUpdate, {"id": "plex"}, 9, app_state="STOPPED")

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_install("1", False))

    entity.coordinator.api.call.assert_not_called()


@pytest.mark.parametrize("cls", [update.TrueNASUpdate, update.TrueNASAppUpdate])
def test_install_keeps_the_job_id(cls):
    """The job id tells that the update is in progress."""
    entity = _entity(cls, {"id": "plex"}, 9)

    asyncio.run(entity.async_install("1", False))

    assert entity._data["update_jobid"] == 9


@pytest.mark.parametrize("cls", [update.TrueNASUpdate, update.TrueNASAppUpdate])
def test_install_does_not_store_a_null_job_id(cls):
    """A null result is no job id."""
    entity = _entity(cls, {"id": "plex"}, None)

    asyncio.run(entity.async_install("1", False))

    assert "update_jobid" not in entity._data


@pytest.mark.parametrize(
    "path", ["strings.json", "translations/en.json", "translations/it.json"]
)
def test_every_exception_key_is_translated(path):
    """Each translation_key the code raises has a message in each language."""
    used = set()
    for source in COMPONENT.glob("*.py"):
        # There, translation_key names an entity
        if source.name.endswith("_types.py"):
            continue

        used |= set(re.findall(r'translation_key="(\w+)"', source.read_text()))

    assert used
    translations = json.loads((COMPONENT / path).read_text())
    assert used <= {*translations["exceptions"], *translations["issues"]}
