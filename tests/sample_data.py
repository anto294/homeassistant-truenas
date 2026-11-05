"""Sample TrueNAS API answers, in the shape of the documented responses.

Each version answers with the methods it really has: 25.04 manages VMs and
containers through virt.instance and checks updates with update.check_available,
25.10 moved to vm.* and update.status, and 27.0 added container.*.
"""

from __future__ import annotations

from typing import Any

MS = 1762250000000


def _job(state: str = "SUCCESS", percent: int = 100) -> dict[str, Any]:
    """Return the job object of a task."""
    return {
        "id": 77,
        "state": state,
        "time_started": {"$date": MS - 60000},
        "time_finished": {"$date": MS},
        "progress": {"percent": percent, "description": "done", "extra": None},
    }


def _graph(name: str, legend: list[str], identifier: str | None = None) -> dict:
    """Return a reporting.netdata_get_data graph with one mean per legend entry."""
    return {
        "name": name,
        "identifier": identifier,
        "legend": ["time", *legend],
        "aggregations": {
            "min": {entry: 1.0 for entry in legend},
            "mean": {entry: 2.5 for entry in legend},
            "max": {entry: 4.0 for entry in legend},
        },
    }


def _parsed(value: Any) -> dict[str, Any]:
    """Return a dataset property."""
    return {"parsed": value, "rawvalue": str(value), "value": str(value), "source": ""}


def _dataset(name: str, used: int) -> dict[str, Any]:
    """Return a pool.dataset.query entry."""
    return {
        "id": name,
        "type": "FILESYSTEM",
        "name": name,
        "pool": name.split("/")[0],
        "mountpoint": f"/mnt/{name}",
        "comments": _parsed(""),
        "deduplication": _parsed(False),
        "atime": _parsed(False),
        "casesensitivity": _parsed("SENSITIVE"),
        "checksum": _parsed("ON"),
        "exec": _parsed(True),
        "sync": _parsed("STANDARD"),
        "compression": _parsed("LZ4"),
        "compressratio": _parsed("1.50"),
        "quota": _parsed(None),
        "copies": _parsed(1),
        "readonly": _parsed(False),
        "recordsize": _parsed(131072),
        "encryption_algorithm": _parsed(None),
        "used": _parsed(used),
        "available": _parsed(1000000000000),
    }


def _scan(function: str = "SCRUB", state: str = "FINISHED") -> dict[str, Any]:
    """Return the scan object of a pool."""
    return {
        "function": function,
        "state": state,
        "start_time": {"$date": MS - 3600000},
        "end_time": {"$date": MS},
        "percentage": 100.0,
        "bytes_to_process": 10,
        "bytes_processed": 10,
        "bytes_issued": 10,
        "pause": None,
        "errors": 0,
        "total_secs_left": None,
    }


def _topology() -> dict[str, Any]:
    """Return a mirror of two disks."""
    disk = {
        "type": "DISK",
        "children": [],
        "stats": {"read_errors": 0, "write_errors": 0, "checksum_errors": 0},
    }
    return {
        "data": [{"type": "MIRROR", "children": [disk, disk], "stats": disk["stats"]}]
    }


def _common(version: str) -> dict[str, Any]:
    """Return the answers of the methods every version has."""
    return {
        "system.global.id": "9f3c1a7e5b2d4c6f8a0e1d2b3c4f5a6b",
        "system.info": {
            "version": version,
            "hostname": "nas",
            "uptime_seconds": 86400,
            "system_serial": "SERIAL1",
            "system_product": "ProLiant",
            "system_manufacturer": "HPE",
            "physmem": 68719476736,
        },
        "interface.query": [
            {
                "id": "eno1",
                "name": "eno1",
                "description": "",
                "mtu": 1500,
                "state": {
                    "link_state": "LINK_STATE_UP",
                    "active_media_type": "Ethernet",
                    "active_media_subtype": "1000baseT",
                    "link_address": "aa:bb:cc:dd:ee:ff",
                },
            }
        ],
        "alert.list": [
            {
                "uuid": "1",
                "level": "WARNING",
                "formatted": "A <b>warning</b>",
                "text": "A warning",
                "dismissed": False,
            }
        ],
        "system.reboot.info": {
            "boot_id": "boot",
            "reboot_required_reasons": [{"code": "FIPS", "reason": "FIPS changed"}],
        },
        "reporting.netdata_get_data": [
            _graph("load", ["shortterm", "midterm", "longterm"]),
            _graph("cputemp", ["cpu0", "cpu1"]),
            _graph("cpu", ["cpu", "cpu0", "cpu1"]),
            _graph("arcsize", ["size"]),
            _graph("memory", ["total", "available"]),
            _graph("interface", ["received", "sent"], "eno1"),
        ],
        "service.query": [
            {
                "id": 1,
                "service": "cifs",
                "enable": True,
                "state": "RUNNING",
                "pids": [],
            },
            {
                "id": 2,
                "service": "ssh",
                "enable": False,
                "state": "STOPPED",
                "pids": [],
            },
        ],
        "disk.query": [
            {
                "identifier": "{serial_lunid}DISK1",
                "name": "sda",
                "devname": "sda",
                "serial": "DISK1",
                "size": 4000787030016,
                "hddstandby": "ALWAYS ON",
                "hddstandby_force": False,
                "advpowermgmt": "DISABLED",
                "acousticlevel": "DISABLED",
                "togglesmart": True,
                "model": "WDC",
                "rotationrate": 7200,
                "type": "HDD",
                "zfs_guid": "111",
            },
            {
                "identifier": "{uuid}abc-DEF",
                "name": "nvme0n1",
                "devname": "nvme0n1",
                "serial": "DISK2",
                "size": 1000204886016,
                "hddstandby": "ALWAYS ON",
                "hddstandby_force": False,
                "advpowermgmt": "DISABLED",
                "acousticlevel": "DISABLED",
                "togglesmart": True,
                "model": "Samsung",
                "rotationrate": None,
                "type": "SSD",
                "zfs_guid": "222",
            },
        ],
        "disk.temperatures": {"sda": 33, "nvme0n1": 41},
        "pool.dataset.query": [
            _dataset("tank", 100000000),
            _dataset("tank/Media Files", 50000000),
            _dataset("tank/ix-apps", 7000000),
        ],
        "pool.query": [
            {
                "guid": "1234567890",
                "id": 1,
                "name": "tank",
                "path": "/mnt/tank",
                "status": "ONLINE",
                "healthy": True,
                "is_decrypted": True,
                "autotrim": {"parsed": False, "value": "off"},
                "scan": _scan(),
                "topology": _topology(),
            }
        ],
        "boot.get_state": {
            "guid": "999",
            "id": "boot-pool",
            "name": "boot-pool",
            "path": "/",
            "status": "ONLINE",
            "healthy": True,
            "is_decrypted": True,
            "autotrim": {"parsed": False, "value": "off"},
            "allocated": 1000000,
            "free": 9000000,
            "root_dataset": {
                "properties": {
                    "available": {"parsed": 9000000},
                    "used": {"parsed": 1000000},
                }
            },
            "scan": _scan(),
            "topology": _topology(),
        },
        "cloudsync.query": [
            {
                "id": 1,
                "description": "Offsite Backup",
                "direction": "PUSH",
                "path": "/mnt/tank/Media Files",
                "enabled": True,
                "transfer_mode": "COPY",
                "snapshot": False,
                "job": _job(),
            },
            {
                "id": 2,
                "description": "Never run",
                "direction": "PULL",
                "path": "/mnt/tank",
                "enabled": False,
                "transfer_mode": "SYNC",
                "snapshot": False,
                "job": None,
            },
        ],
        "replication.query": [
            {
                "id": 1,
                "name": "tank to backup",
                "source_datasets": ["tank/Media Files"],
                "target_dataset": "backup/media",
                "recursive": True,
                "enabled": True,
                "direction": "PUSH",
                "transport": "SSH",
                "auto": True,
                "retention_policy": "SOURCE",
                "job": _job("RUNNING", 40),
            }
        ],
        "pool.snapshottask.query": [
            {
                "id": 1,
                "dataset": "tank/Media Files",
                "recursive": False,
                "lifetime_value": 2,
                "lifetime_unit": "WEEK",
                "enabled": True,
                "naming_schema": "auto-%Y-%m-%d_%H-%M",
                "allow_empty": True,
                "vmware_sync": False,
                "state": {"state": "FINISHED", "datetime": {"$date": MS}},
            }
        ],
        "cronjob.query": [
            {
                "id": 1,
                "description": "Nightly check",
                "enabled": True,
                "schedule": {
                    "minute": "0",
                    "hour": "3",
                    "dom": "*",
                    "month": "*",
                    "dow": "*",
                },
            },
            {
                "id": 3,
                "description": "",
                "enabled": False,
                "schedule": {
                    "minute": "*/5",
                    "hour": "*",
                    "dom": "*",
                    "month": "*",
                    "dow": "*",
                },
            },
        ],
        "app.query": [
            {
                "id": "plex",
                "name": "plex",
                "state": "RUNNING",
                "human_version": "1.40_1.0.0",
                "version": "1.0.0",
                "latest_version": "1.0.1",
                "upgrade_available": True,
                "image_updates_available": False,
                "custom_app": False,
                "portals": {"Web UI": "http://nas:32400/"},
                "notes": "Notes of the app",
            },
            {
                "id": "custom-app",
                "name": "custom-app",
                "state": "STOPPED",
                "human_version": "1.0.0",
                "version": "1.0.0",
                "latest_version": None,
                "upgrade_available": False,
                "image_updates_available": False,
                "custom_app": True,
                "portals": {},
                "notes": None,
            },
        ],
    }


def _libvirt_vms() -> list[dict[str, Any]]:
    """Return a vm.query answer (25.10 and later)."""
    return [
        {
            "id": 5,
            "name": "win11",
            "description": "Desktop",
            "vcpus": 2,
            "cores": 2,
            "threads": 1,
            "memory": 8192,
            "autostart": True,
            "status": {"state": "RUNNING", "pid": 100, "domain_state": "RUNNING"},
        },
        {
            "id": 6,
            "name": "debian",
            "description": "",
            "vcpus": 1,
            "cores": 1,
            "threads": 1,
            "memory": 2048,
            "autostart": False,
            "status": {"state": "STOPPED", "pid": None, "domain_state": "SHUTOFF"},
        },
    ]


def answers(version: str) -> dict[str, Any]:
    """Return the answers of a TrueNAS release, "25.04", "25.10" or "27.0"."""
    full_version = {"25.04": "25.04.2", "25.10": "25.10.1", "27.0": "27.0.0-RC.1"}
    result = _common(full_version[version])
    if version == "25.04":
        result["update.check_available"] = {"status": "UNAVAILABLE", "version": None}
        result["virt.instance.query"] = [
            {
                "id": "win11",
                "name": "win11",
                "type": "VM",
                "status": "RUNNING",
                "cpu": "4",
                "memory": 8589934592,
                "autostart": True,
                "image": {"description": "Windows 11"},
            },
            {
                "id": "alpine",
                "name": "alpine",
                "type": "CONTAINER",
                "status": "STOPPED",
                "cpu": None,
                "memory": 2147483648,
                "autostart": False,
                "image": {"description": "Alpine"},
            },
        ]
        return result

    result["update.status"] = {
        "code": "NORMAL",
        "error": None,
        "status": {"current_version": {}, "new_version": {"version": "99.0"}},
    }
    result["vm.query"] = _libvirt_vms()
    if version == "27.0":
        result["container.query"] = [
            {
                "id": 9,
                "name": "web",
                "description": "Web server",
                "autostart": True,
                "cpuset": "0-1",
                "memory": 2048,
                "status": {"state": "RUNNING", "pid": 200, "domain_state": None},
            },
            {
                "id": 10,
                "name": "db",
                "description": "",
                "autostart": False,
                "cpuset": None,
                "memory": None,
                "status": {"state": "STOPPED", "pid": None, "domain_state": None},
            },
        ]

    return result
