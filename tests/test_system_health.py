"""Tests for TrueNAS alerts and the reboot required state."""

from __future__ import annotations

import asyncio

from custom_components.truenas_link.binary_sensor_types import SENSOR_TYPES
from custom_components.truenas_link.coordinator import TrueNASCoordinator

from .test_api import _reply


def _coordinator(api):
    """Build a coordinator around `api` without a Home Assistant instance."""
    coordinator = TrueNASCoordinator.__new__(TrueNASCoordinator)
    coordinator.host = "truenas.lan"
    coordinator.api = api.real
    coordinator.ds = {"system_info": {"hostname": "nas"}}
    return coordinator


def _alert(level, text="Pool %(volume)s is sick", formatted="Pool tank is sick", **kw):
    """Build one alert the way alert.list returns it."""
    return {
        "uuid": "1",
        "source": "",
        "klass": "VolumeStatus",
        "args": {},
        "node": "Controller A",
        "key": "[]",
        "dismissed": False,
        "mail": None,
        "text": text,
        "id": "1",
        "level": level,
        "formatted": formatted,
        "one_shot": False,
        **kw,
    }


def test_alerts_count_only_active_ones(connected_api):
    """Dismissed alerts are not counted, and a warning is not critical."""
    alerts = [_alert("WARNING"), _alert("CRITICAL", dismissed=True)]
    api, ws = connected_api(_reply(result=alerts))
    coordinator = _coordinator(api)

    asyncio.run(coordinator.get_alerts())

    assert ws.requests[0]["method"] == "alert.list"
    system_info = coordinator.ds["system_info"]
    assert system_info["alerts_active"] == 1
    assert system_info["alerts_critical"] is False
    assert system_info["alert_messages"] == ["WARNING: Pool tank is sick"]


def test_critical_levels_turn_the_problem_sensor_on(connected_api):
    """CRITICAL and above need attention."""
    for level in ("CRITICAL", "ALERT", "EMERGENCY"):
        api, _ = connected_api(_reply(result=[_alert(level)]))
        coordinator = _coordinator(api)

        asyncio.run(coordinator.get_alerts())

        assert coordinator.ds["system_info"]["alerts_critical"] is True


def test_alert_messages_are_plain_text_and_bounded(connected_api):
    """HTML goes away, and many long alerts cannot overflow the attribute."""
    alerts = [
        _alert("INFO", formatted='<a href="/x">Tom &amp; Jerry</a>'),
        _alert("INFO", formatted=None, text="Fallback text"),
        *[_alert("INFO", formatted="x" * 1000) for _ in range(40)],
    ]
    api, _ = connected_api(_reply(result=alerts))
    coordinator = _coordinator(api)

    asyncio.run(coordinator.get_alerts())

    system_info = coordinator.ds["system_info"]
    assert system_info["alerts_active"] == 42
    messages = system_info["alert_messages"]
    assert messages[0] == "INFO: Tom & Jerry"
    assert messages[1] == "INFO: Fallback text"
    assert len(messages) == 20
    assert all(len(message) <= 255 for message in messages)


def test_failed_alert_query_keeps_values_and_creates_no_entity(connected_api):
    """A refused query leaves the values, so no entity shows a false zero."""

    def refused(request):
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": 13, "message": "Not authorized"},
        }

    api, _ = connected_api(refused)
    coordinator = _coordinator(api)

    asyncio.run(coordinator.get_alerts())

    assert "alerts_active" not in coordinator.ds["system_info"]
    assert api.connected()


def test_reboot_required_reports_the_reasons(connected_api):
    """Pending reasons turn the sensor on and are kept as text."""
    info = {
        "boot_id": "abc",
        "reboot_required_reasons": [{"code": "FIPS", "reason": "FIPS changed"}],
    }
    api, ws = connected_api(_reply(result=info))
    coordinator = _coordinator(api)

    asyncio.run(coordinator.get_rebootinfo())

    assert ws.requests[0]["method"] == "system.reboot.info"
    assert coordinator.ds["system_info"]["reboot_required"] is True
    assert coordinator.ds["system_info"]["reboot_required_reasons"] == ["FIPS changed"]


def test_no_reboot_reasons_means_no_reboot_required(connected_api):
    """An empty list means no reboot is required."""
    api, _ = connected_api(
        _reply(result={"boot_id": "abc", "reboot_required_reasons": []})
    )
    coordinator = _coordinator(api)

    asyncio.run(coordinator.get_rebootinfo())

    assert coordinator.ds["system_info"]["reboot_required"] is False


def test_system_level_binary_sensors_can_be_created():
    """async_add_entities reads data_attribute when there is no data_reference."""
    for description in SENSOR_TYPES:
        if not description.data_reference:
            assert description.data_attribute == description.data_is_on
