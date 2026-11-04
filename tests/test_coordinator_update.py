"""Tests for the TrueNAS system update check on 25.10+."""

from __future__ import annotations

from custom_components.truenas_link.coordinator import TrueNASCoordinator

from .test_api import UPDATE_STATUS_UP_TO_DATE, _reply


def _coordinator(api, version="25.10.1"):
    """Build a coordinator around `api` without a Home Assistant instance."""
    coordinator = TrueNASCoordinator.__new__(TrueNASCoordinator)
    coordinator.host = "truenas.lan"
    coordinator.api = api
    coordinator._version_major = 0
    coordinator._version_minor = 0
    coordinator._detect_version(version)
    coordinator.ds = {"system_info": {"version": version}}
    return coordinator


def test_update_status_up_to_date_is_unavailable(connected_api):
    """update.status with "error": null and no new version -> UNAVAILABLE."""
    api, ws = connected_api(_reply(result=UPDATE_STATUS_UP_TO_DATE))
    coordinator = _coordinator(api)

    coordinator._get_updatecheck_status()

    assert coordinator.ds["system_info"]["update_status"] == "UNAVAILABLE"
    assert api.connected()
    assert not ws.closed


def test_update_check_up_to_date_keeps_connection(connected_api):
    """The full 12-hourly check reports no update and stays connected."""
    api, _ = connected_api(_reply(result=UPDATE_STATUS_UP_TO_DATE))
    coordinator = _coordinator(api)

    coordinator.get_updatecheck()

    system_info = coordinator.ds["system_info"]
    assert system_info["update_available"] is False
    assert system_info["update_version"] == "25.10.1"
    assert api.connected()


def test_update_status_new_version_is_available(connected_api):
    """update.status reporting a new version -> AVAILABLE with that version."""
    api, _ = connected_api(
        _reply(
            result={
                "code": "NORMAL",
                "error": None,
                "status": {"new_version": {"version": "25.10.2"}},
            }
        )
    )
    coordinator = _coordinator(api)

    coordinator.get_updatecheck()

    system_info = coordinator.ds["system_info"]
    assert system_info["update_status"] == "AVAILABLE"
    assert system_info["update_available"] is True
    assert system_info["update_version"] == "25.10.2"
