"""Tests for pool scan and error values from pool.query and boot.get_state."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.truenas_link.coordinator import (
    TrueNASCoordinator,
    topology_errors,
)

from .conftest import async_add_entry

END_MS = 1762250000000


def _scan(function="SCRUB", state="FINISHED", pause=None, end=END_MS):
    """Build the scan object the way pool.query returns it."""
    return {
        "function": function,
        "state": state,
        "start_time": {"$date": END_MS - 3600000},
        "end_time": {"$date": end} if end else None,
        "percentage": 100.0,
        "bytes_to_process": 10,
        "bytes_processed": 10,
        "bytes_issued": 10,
        "pause": {"$date": END_MS} if pause else None,
        "errors": 0,
        "total_secs_left": None,
    }


def _disk(read=0, write=0, checksum=0):
    """Build a leaf vdev."""
    return {
        "type": "DISK",
        "children": [],
        "stats": {
            "read_errors": read,
            "write_errors": write,
            "checksum_errors": checksum,
        },
    }


TOPOLOGY = {
    "data": [
        {
            "type": "MIRROR",
            # A vdev's own counters must not be added to those of its disks
            "stats": {"read_errors": 99, "write_errors": 99, "checksum_errors": 99},
            "children": [_disk(read=1), _disk(checksum=2)],
        }
    ],
    "log": [],
    "cache": [_disk(write=3)],
    "spare": [],
    "special": [],
    "dedup": [],
}


def _pool(scan):
    """Build a pool the way pool.query returns it."""
    return {
        "id": 1,
        "guid": "123",
        "name": "tank",
        "path": "/mnt/tank",
        "status": "ONLINE",
        "healthy": True,
        "scan": scan,
        "topology": TOPOLOGY,
    }


BOOT = {
    "name": "boot-pool",
    "path": "/",
    "status": "ONLINE",
    "healthy": True,
    "scan": _scan(),
    "topology": {"data": [_disk(read=5)]},
    "free": 10,
    "allocated": 5,
    "root_dataset": {},
}


def _coordinator(connected_api, pool):
    """Build a coordinator answering pool.query and boot.get_state."""

    def responder(request):
        result = [pool] if request["method"] == "pool.query" else BOOT
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    api, _ = connected_api(responder)
    coordinator = TrueNASCoordinator.__new__(TrueNASCoordinator)
    coordinator.host = "truenas.lan"
    coordinator.api = api
    coordinator.present = {}
    coordinator.answered = set()
    coordinator.pool_names = set()
    coordinator.ds = {"pool": {}, "dataset": {}}
    return coordinator


@pytest.mark.parametrize(
    ("scan", "expected"),
    [
        (None, "idle"),  # no scan yet: scan is null on 27.0
        (_scan(state="FINISHED"), "idle"),
        (_scan(state="CANCELED"), "idle"),
        (_scan(state="SCANNING", end=None), "scrubbing"),
        (_scan(state="SCANNING", end=None, pause=True), "paused"),
        (_scan("RESILVER", "SCANNING", end=None), "resilvering"),
    ],
)
def test_scan_status(connected_api, scan, expected):
    """The scan object maps to one of the sensor's states."""
    coordinator = _coordinator(connected_api, _pool(scan))

    coordinator.get_pool()

    assert coordinator.ds["pool"]["123"]["scan_status"] == expected


def test_last_scrub_only_follows_finished_scrubs(connected_api):
    """A resilver or canceled scrub does not replace the last finished scrub."""
    pool = _pool(_scan())
    coordinator = _coordinator(connected_api, pool)

    coordinator.get_pool()
    last_scrub = coordinator.ds["pool"]["123"]["last_scrub"]
    assert isinstance(last_scrub, datetime)
    assert last_scrub.tzinfo is not None
    assert last_scrub.timestamp() == END_MS / 1000

    pool["scan"] = _scan("RESILVER", "FINISHED", end=END_MS + 5000)
    coordinator.get_pool()
    assert coordinator.ds["pool"]["123"]["last_scrub"] == last_scrub

    pool["scan"] = _scan("SCRUB", "CANCELED", end=END_MS + 5000)
    coordinator.get_pool()
    assert coordinator.ds["pool"]["123"]["last_scrub"] == last_scrub


def test_last_scrub_is_unknown_without_a_finished_scrub(connected_api):
    """No finished scrub means an unknown timestamp, not 1970."""
    coordinator = _coordinator(connected_api, _pool(None))

    coordinator.get_pool()

    assert coordinator.ds["pool"]["123"]["last_scrub"] is None


def test_errors_add_up_the_disks_of_every_vdev(connected_api):
    """Counters come from the disks, with the type of error as attributes."""
    coordinator = _coordinator(connected_api, _pool(_scan()))

    coordinator.get_pool()

    pool = coordinator.ds["pool"]["123"]
    assert pool["pool_errors"] == 6
    assert pool["read_errors"] == 1
    assert pool["write_errors"] == 3
    assert pool["checksum_errors"] == 2
    assert "topology" not in pool


def test_boot_pool_gets_the_same_values(connected_api):
    """boot.get_state has no guid, so the boot pool is keyed by name."""
    coordinator = _coordinator(connected_api, _pool(_scan()))

    coordinator.get_pool()

    boot = coordinator.ds["pool"]["boot-pool"]
    assert boot["pool_errors"] == 5
    assert boot["scan_status"] == "idle"
    assert isinstance(boot["last_scrub"], datetime)


@pytest.mark.parametrize("topology", [None, {}, {"data": None}, {"data": ["x"]}])
def test_topology_errors_tolerates_missing_data(topology):
    """An unexpected topology means no errors, not a failed update."""
    assert sum(topology_errors(topology).values()) == 0


LAST_SCRUB_ENTITY = "sensor.truenas_system_tank_last_scrub"


@pytest.mark.parametrize(
    ("scan", "state"),
    [
        (
            _scan(),
            datetime.fromtimestamp(END_MS / 1000, tz=timezone.utc).isoformat(),
        ),
        # TrueNAS 27 returns null when no scan has ever run
        (None, "unknown"),
        # ZFS only keeps the latest scan
        (_scan(function="RESILVER"), "unknown"),
        (_scan(state="CANCELED"), "unknown"),
        (_scan(state="SCANNING", end=None), "unknown"),
    ],
    ids=["finished", "never", "resilver", "canceled", "running"],
)
def test_last_scrub_entity_on_truenas_27(run_in_hass, scan, state):
    """The sensor shows a finished scrub, and unknown when there is none."""

    async def scenario(hass, server):
        server.results["system.info"] = {
            **server.results["system.info"],
            "version": "27.0.0-RC.1",
        }
        server.results["pool.query"] = [
            {
                "guid": "123",
                "id": 1,
                "name": "tank",
                "path": "/mnt/tank",
                "status": "ONLINE",
                "healthy": True,
                "is_decrypted": True,
                "autotrim": {"parsed": False},
                "scan": scan,
                "topology": {},
            }
        ]

        await async_add_entry(hass)

        assert hass.states.get(LAST_SCRUB_ENTITY).state == state

    run_in_hass(scenario)


def test_boot_pool_query_failing_after_a_good_one_fails_nothing(connected_api):
    """root_dataset is only there after an answer, so removing it may find nothing."""
    coordinator = _coordinator(connected_api, _pool(_scan()))
    coordinator.get_pool()
    query = coordinator.api.query
    coordinator.api.query = lambda method: (
        None if method == "boot.get_state" else query(method)
    )

    coordinator.get_pool()

    assert coordinator.ds["pool"]["boot-pool"]["name"] == "boot-pool"
