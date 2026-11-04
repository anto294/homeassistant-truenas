"""TrueNAS Controller."""

from __future__ import annotations

import logging
import re

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)

from .api import TrueNASAPI
from .apiparser import parse_api, utc_from_timestamp
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# First "<major>.<minor>" pair in a TrueNAS version string
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


# ---------------------------
#   TrueNASControllerData
# ---------------------------
class TrueNASCoordinator(DataUpdateCoordinator[None]):
    """TrueNASCoordinator Class."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize TrueNASCoordinator."""
        self.hass = hass
        self.config_entry: ConfigEntry = config_entry

        super().__init__(
            self.hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )

        self.name = config_entry.data[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]

        self.ds = {
            "interface": {},
            "disk": {},
            "pool": {},
            "dataset": {},
            "system_info": {},
            "service": {},
            "vm": {},
            "cloudsync": {},
            "replication": {},
            "snapshottask": {},
            "app": {},
            "container": {},
        }

        self.api = TrueNASAPI(
            config_entry.data[CONF_HOST],
            config_entry.data[CONF_API_KEY],
            config_entry.data[CONF_VERIFY_SSL],
        )

        self._systemstats_errored = []
        self.datasets_hass_device_id = None
        self.last_updatecheck_update = datetime(1970, 1, 1)

        self._is_virtual = False
        self._version_major = 0
        self._version_minor = 0

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected state."""
        return self.api.connected()

    # ---------------------------
    #   _async_update_data
    # ---------------------------
    async def _async_update_data(self):
        """Update TrueNAS data."""
        if not self.api.connected():
            self.api.connect()

        jobs = [
            self.get_systeminfo,
            self.get_systemstats,
            self.get_service,
            self.get_disk,
            self.get_dataset,
            self.get_pool,
            self.get_vm,
            self.get_cloudsync,
            self.get_replication,
            self.get_snapshottask,
            self.get_app,
            self.get_container,
        ]

        for job in jobs:
            if self.api.connected():
                await self.hass.async_add_executor_job(job)

        delta = datetime.now().replace(microsecond=0) - self.last_updatecheck_update
        if self.api.connected() and delta.total_seconds() > 60 * 60 * 12:
            await self.hass.async_add_executor_job(self.get_updatecheck)
            self.last_updatecheck_update = datetime.now().replace(microsecond=0)

        if not self.api.connected():
            raise UpdateFailed("TrueNas Disconnected")

        return self.ds

    # ---------------------------
    #   get_systeminfo
    # ---------------------------
    def get_systeminfo(self) -> None:
        """Get system info from TrueNAS."""
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=self.api.query("system.info"),
            vals=[
                {"name": "version", "default": "unknown"},
                {"name": "hostname", "default": "unknown"},
                {"name": "uptime_seconds", "default": 0},
                {"name": "system_serial", "default": "unknown"},
                {"name": "system_product", "default": "unknown"},
                {"name": "system_manufacturer", "default": "unknown"},
                {"name": "physmem", "default": 0},
            ],
            ensure_vals=[
                {"name": "uptimeEpoch", "default": 0},
                {"name": "cpu_temperature", "default": 0.0},
                {"name": "load_shortterm", "default": 0.0},
                {"name": "load_midterm", "default": 0.0},
                {"name": "load_longterm", "default": 0.0},
                {"name": "cpu_usage", "default": 0.0},
                {"name": "cache_size-arc_value", "default": 0.0},
                {"name": "memory-used_value", "default": 0.0},
                {"name": "memory-free_value", "default": 0.0},
                {"name": "memory-total_value", "default": 0.0},
                {"name": "memory-usage_percent", "default": 0},
                {"name": "update_available", "type": "bool", "default": False},
                {"name": "update_progress", "default": 0},
                {"name": "update_jobid", "default": 0},
                {"name": "update_state", "default": "unknown"},
            ],
        )
        if not self.api.connected():
            return

        if not self.ds["system_info"]["update_available"]:
            self.ds["system_info"]["update_version"] = self.ds["system_info"]["version"]

        if self.ds["system_info"]["update_jobid"]:
            self.ds["system_info"] = parse_api(
                data=self.ds["system_info"],
                source=self.api.query(
                    "core.get_jobs",
                    params=[[["id", "=", self.ds["system_info"]["update_jobid"]]]],
                ),
                vals=[
                    {
                        "name": "update_progress",
                        "source": "progress/percent",
                        "default": 0,
                    },
                    {
                        "name": "update_state",
                        "source": "state",
                        "default": "unknown",
                    },
                ],
            )
            if not self.api.connected():
                return

            if (
                self.ds["system_info"]["update_state"] != "RUNNING"
                or not self.ds["system_info"]["update_available"]
            ):
                self.ds["system_info"]["update_progress"] = 0
                self.ds["system_info"]["update_jobid"] = 0
                self.ds["system_info"]["update_state"] = "unknown"

        self._detect_version(self.ds["system_info"].get("version"))

        self._is_virtual = self.ds["system_info"]["system_manufacturer"] in [
            "QEMU",
            "VMware, Inc.",
            "Microsoft Corporation",
            "Xen",
        ] or self.ds["system_info"]["system_product"] in [
            "VirtualBox",
            "Virtual Machine",
        ]

        if self.ds["system_info"]["uptime_seconds"] > 0:
            now = datetime.now().replace(microsecond=0)
            uptime_tm = datetime.timestamp(
                now - timedelta(seconds=int(self.ds["system_info"]["uptime_seconds"]))
            )
            self.ds["system_info"]["uptimeEpoch"] = utc_from_timestamp(uptime_tm)

        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self.api.query("interface.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "name", "default": "unknown"},
                {"name": "description", "default": "unknown"},
                {"name": "mtu", "default": "unknown"},
                {
                    "name": "link_state",
                    "source": "state/link_state",
                    "default": "unknown",
                },
                {
                    "name": "active_media_type",
                    "source": "state/active_media_type",
                    "default": "unknown",
                },
                {
                    "name": "active_media_subtype",
                    "source": "state/active_media_subtype",
                    "default": "unknown",
                },
                {
                    "name": "link_address",
                    "source": "state/link_address",
                    "default": "unknown",
                },
            ],
            ensure_vals=[
                {"name": "rx", "default": 0},
                {"name": "tx", "default": 0},
            ],
        )

    # ---------------------------
    #   _detect_version
    # ---------------------------
    def _detect_version(self, version: str | None) -> None:
        """Parse the TrueNAS version string into major and minor numbers.

        Accepts every format TrueNAS has used, for example "TrueNAS-SCALE-24.10.2",
        "25.10.1", "25.10-RC.1" or "27.0.0-BETA.1". The version is parsed on every
        refresh so an in-place TrueNAS upgrade switches API code paths without
        reloading the integration.
        """
        match = _VERSION_RE.search(str(version or ""))
        if not match:
            _LOGGER.warning(
                "TrueNAS %s unable to parse version '%s', assuming latest API",
                self.host,
                version,
            )
            return

        major, minor = int(match.group(1)), int(match.group(2))
        if (major, minor) != (self._version_major, self._version_minor):
            _LOGGER.debug(
                "TrueNAS %s detected version %s.%s (%s)",
                self.host,
                major,
                minor,
                version,
            )
            self._version_major = major
            self._version_minor = minor

    # ---------------------------
    #   version_at_least
    # ---------------------------
    def version_at_least(self, major: int, minor: int = 0) -> bool:
        """Return True if the connected TrueNAS is at least major.minor.

        An undetected version (0.0) is treated as the newest release, because
        the API methods of current releases are the most likely to be correct.
        """
        if not self._version_major:
            return True

        return (self._version_major, self._version_minor) >= (major, minor)

    # ---------------------------
    #   get_updatecheck
    # ---------------------------
    def get_updatecheck(self) -> None:
        """Check whether a TrueNAS system update is available."""
        if self.version_at_least(25, 10):
            self._get_updatecheck_status()
        else:
            self._get_updatecheck_legacy()

        if not self.api.connected():
            return

        if (
            self.ds["system_info"]["update_version"] == "unknown"
            and self.ds["system_info"]["version"]
        ):
            self.ds["system_info"]["update_version"] = self.ds["system_info"]["version"]

        self.ds["system_info"]["update_available"] = (
            self.ds["system_info"]["update_status"] == "AVAILABLE"
        )

    # ---------------------------
    #   _get_updatecheck_status
    # ---------------------------
    def _get_updatecheck_status(self) -> None:
        """Check for system updates with update.status (TrueNAS 25.10+).

        update.check_available was removed in 25.10. update.status returns
        {"code": "NORMAL"|"ERROR", "status": {"new_version": {"version": ...}}}
        where new_version is null when the system is up to date.
        """
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=self.api.query("update.status"),
            vals=[
                {"name": "update_code", "source": "code", "default": "unknown"},
                {
                    "name": "update_version",
                    "source": "status/new_version/version",
                    "default": "unknown",
                },
            ],
        )

        if self.ds["system_info"]["update_code"] == "ERROR":
            self.ds["system_info"]["update_status"] = "ERROR"
        elif self.ds["system_info"]["update_version"] != "unknown":
            self.ds["system_info"]["update_status"] = "AVAILABLE"
        else:
            self.ds["system_info"]["update_status"] = "UNAVAILABLE"

    # ---------------------------
    #   _get_updatecheck_legacy
    # ---------------------------
    def _get_updatecheck_legacy(self) -> None:
        """Check for system updates with update.check_available (before 25.10)."""
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=self.api.query("update.check_available"),
            vals=[
                {
                    "name": "update_status",
                    "source": "status",
                    "default": "unknown",
                },
                {
                    "name": "update_version",
                    "source": "version",
                    "default": "unknown",
                },
            ],
        )

    # ---------------------------
    #   get_systemstats
    # ---------------------------
    def get_systemstats(self) -> None:
        """Get system statistics."""
        report_epoch = int(datetime.now().replace(microsecond=0).timestamp())
        tmp_graphs = [
            {"name": "load"},
            {"name": "cputemp"},
            {"name": "cpu"},
            {"name": "arcsize"},
            {"name": "memory"},
        ]

        for uid, vals in self.ds["interface"].items():
            tmp_graphs.append({"name": "interface", "identifier": uid})

        if self._is_virtual:
            tmp_graphs.remove({"name": "cputemp"})

        tmp_graphs = [
            tmp
            for tmp in tmp_graphs
            if self._systemstats_graph_key(tmp) not in self._systemstats_errored
        ]
        if not tmp_graphs:
            return

        # Mean over the 60 seconds that ended 30 seconds ago, so the most
        # recent samples netdata may still be collecting are left out.
        tmp_query = {
            "start": report_epoch - 90,
            "end": report_epoch - 30,
            "aggregate": True,
        }

        reporting_path = "reporting.netdata_get_data"

        tmp_graph = self.api.query(reporting_path, params=[tmp_graphs, tmp_query])

        if not isinstance(tmp_graph, list):
            if not self.api.connected():
                # Connection lost: try again on the next refresh
                return

            # TrueNAS rejected the request. A single graph it cannot serve
            # (cputemp on some hardware, a removed interface) fails the whole
            # call, so query each graph on its own, keep the ones that work
            # and stop requesting the failing ones.
            tmp_graph = []
            tmp_errored = []
            for tmp in tmp_graphs:
                tmp_single = self.api.query(reporting_path, params=[[tmp], tmp_query])
                if isinstance(tmp_single, list):
                    tmp_graph.extend(tmp_single)
                elif not self.api.connected():
                    return
                else:
                    tmp_errored.append(self._systemstats_graph_key(tmp))

            if tmp_errored:
                self._systemstats_errored.extend(tmp_errored)
                _LOGGER.warning(
                    "TrueNAS %s fetching following graphs failed, check your NAS: %s",
                    self.host,
                    ", ".join(
                        f"{name} ({identifier})" if identifier else name
                        for name, identifier in tmp_errored
                    ),
                )

        for i in range(len(tmp_graph)):
            if "name" not in tmp_graph[i]:
                continue

            # CPU temperature
            if tmp_graph[i]["name"] == "cputemp":
                tmp_temps = [
                    v
                    for v in self._systemstats_mean(tmp_graph[i]).values()
                    if v is not None
                ]
                if tmp_temps:
                    self.ds["system_info"]["cpu_temperature"] = round(max(tmp_temps), 2)
                else:
                    self.ds["system_info"]["cpu_temperature"] = 0.0

            # CPU load
            if tmp_graph[i]["name"] == "load":
                # TrueNAS renames load1/load5/load15 to these
                tmp_arr = ("shortterm", "midterm", "longterm")
                self._systemstats_process(tmp_arr, tmp_graph[i], "load")

            # CPU usage
            if tmp_graph[i]["name"] == "cpu":
                # Aggregate "cpu" only, not the per-core "cpu0", "cpu1", ...
                tmp_arr = ("cpu",)
                self._systemstats_process(tmp_arr, tmp_graph[i], "cpu")
                self.ds["system_info"]["cpu_usage"] = round(
                    self.ds["system_info"]["cpu_cpu"], 2
                )

            # Interface
            if tmp_graph[i]["name"] == "interface":
                tmp_etc = tmp_graph[i]["identifier"]
                if tmp_etc in self.ds["interface"]:
                    tmp_arr = ("rx", "tx")
                    tmp_mean = self._systemstats_mean(tmp_graph[i])
                    if tmp_mean:
                        tmp_mean = {
                            k.replace("received", "rx").replace("sent", "tx"): v
                            for k, v in tmp_mean.items()
                        }
                        tmp_legend = [
                            tmp.replace("received", "rx").replace("sent", "tx")
                            for tmp in tmp_graph[i].get("legend") or []
                        ]
                        for tmp_var in tmp_legend:
                            if tmp_var in tmp_arr:
                                tmp_val = tmp_mean.get(tmp_var) or 0.0
                                self.ds["interface"][tmp_etc][tmp_var] = round(
                                    (tmp_val * 0.12207), 2
                                )

                    else:
                        for tmp_load in tmp_arr:
                            self.ds["interface"][tmp_etc][tmp_load] = 0.0

            # memory
            if tmp_graph[i]["name"] == "memory":
                # Legend is "total", "available"; only available is used
                tmp_arr = ("available",)
                self.ds["system_info"]["memory-total_value"] = round(
                    self.ds["system_info"]["physmem"]
                )

                # Without samples free memory would be stored as 0 and usage
                # reported as 100%; keep the last known values instead.
                if not self._systemstats_mean(tmp_graph[i]):
                    continue

                self._systemstats_process(tmp_arr, tmp_graph[i], "memory")
                tmp_total = float(self.ds["system_info"]["memory-total_value"])
                if tmp_total > 0:
                    # Used = total - available, the same figure as the usage %
                    tmp_used = max(
                        tmp_total - float(self.ds["system_info"]["memory-free_value"]),
                        0.0,
                    )
                    self.ds["system_info"]["memory-used_value"] = round(tmp_used)
                    self.ds["system_info"]["memory-usage_percent"] = round(
                        100 * tmp_used / tmp_total
                    )

            # arcsize
            if tmp_graph[i]["name"] == "arcsize":
                # truenas_arcstats.size has a single "size" dimension
                tmp_arr = ("size",)
                self._systemstats_process(tmp_arr, tmp_graph[i], "arcsize")

    # ---------------------------
    #   _systemstats_graph_key
    # ---------------------------
    @staticmethod
    def _systemstats_graph_key(graph: dict) -> tuple:
        """Return the (name, identifier) pair that identifies a requested graph.

        Interfaces share the graph name "interface", so the identifier is
        needed to skip only the interface that failed.
        """
        return graph["name"], graph.get("identifier")

    # ---------------------------
    #   _systemstats_mean
    # ---------------------------
    @staticmethod
    def _systemstats_mean(graph: dict) -> dict:
        """Return the "mean" aggregation of a reporting graph, or {}.

        Since 27.0 reporting.netdata_get_data may return "aggregations": null
        (for example when no samples exist for the requested window), so the
        key being present is not enough.
        """
        tmp_aggregations = graph.get("aggregations")
        if not isinstance(tmp_aggregations, dict):
            return {}

        tmp_mean = tmp_aggregations.get("mean")
        return tmp_mean if isinstance(tmp_mean, dict) else {}

    # ---------------------------
    #   _systemstats_process
    # ---------------------------
    def _systemstats_process(self, arr, graph, t) -> None:
        """Store the mean values of the requested legend entries of a graph.

        `arr` is a tuple of exact legend names. Upstream passed some of them
        as plain strings, which made `in` a substring check ("size" matched
        "arc_size"); a bare string is still wrapped, but it then only
        matches that exact name, so always list the real legend entries.
        """
        if isinstance(arr, str):
            arr = (arr,)

        tmp_mean = self._systemstats_mean(graph)
        if tmp_mean:
            for tmp_var in graph.get("legend") or []:
                if tmp_var in arr:
                    self._systemstats_store(t, tmp_var, tmp_mean.get(tmp_var) or 0.0)
        else:
            # No data for this window: reset to 0 under the same keys
            for tmp_var in arr:
                self._systemstats_store(t, tmp_var, 0.0)

    # ---------------------------
    #   _systemstats_store
    # ---------------------------
    def _systemstats_store(self, t: str, tmp_var: str, tmp_val: float) -> None:
        """Store one reporting value in system_info under its sensor key."""
        if t == "memory":
            if tmp_var == "available":
                self.ds["system_info"]["memory-free_value"] = round(tmp_val)
        elif t == "cpu":
            self.ds["system_info"][f"cpu_{tmp_var}"] = round(tmp_val, 2)
        elif t == "load":
            self.ds["system_info"][f"load_{tmp_var}"] = round(tmp_val, 2)
        elif t == "arcsize":
            self.ds["system_info"]["cache_size-arc_value"] = round(tmp_val, 2)
        else:
            self.ds["system_info"][tmp_var] = round(tmp_val, 2)

    # ---------------------------
    #   get_service
    # ---------------------------
    def get_service(self) -> None:
        """Get service info from TrueNAS."""
        self.ds["service"] = parse_api(
            data=self.ds["service"],
            source=self.api.query("service.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "service", "default": "unknown"},
                {"name": "enable", "type": "bool", "default": False},
                {"name": "state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["service"].items():
            self.ds["service"][uid]["running"] = vals["state"] == "RUNNING"

    # ---------------------------
    #   get_pool
    # ---------------------------
    def get_pool(self) -> None:
        """Get pools from TrueNAS."""
        self.ds["pool"] = parse_api(
            data=self.ds["pool"],
            source=self.api.query("pool.query"),
            key="guid",
            vals=[
                {"name": "guid", "default": 0},
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "path", "default": "unknown"},
                {"name": "status", "default": "unknown"},
                {"name": "healthy", "type": "bool", "default": False},
                {"name": "is_decrypted", "type": "bool", "default": False},
                {
                    "name": "autotrim",
                    "source": "autotrim/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "scan_function",
                    "source": "scan/function",
                    "default": "unknown",
                },
                {"name": "scrub_state", "source": "scan/state", "default": "unknown"},
                {
                    "name": "scrub_start",
                    "source": "scan/start_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_end",
                    "source": "scan/end_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_secs_left",
                    "source": "scan/total_secs_left",
                    "default": 0,
                },
            ],
            ensure_vals=[
                {"name": "available", "default": 0.0},
                {"name": "total", "default": 0.0},
                {"name": "usage", "default": 0.0},
            ],
        )

        self.ds["pool"] = parse_api(
            data=self.ds["pool"],
            source=self.api.query("boot.get_state"),
            key="name",
            vals=[
                {"name": "guid", "default": "boot-pool"},
                {"name": "id", "default": "boot-pool"},
                {"name": "name", "default": "unknown"},
                {"name": "path", "default": "unknown"},
                {"name": "status", "default": "unknown"},
                {"name": "healthy", "type": "bool", "default": False},
                {"name": "is_decrypted", "type": "bool", "default": False},
                {
                    "name": "autotrim",
                    "source": "autotrim/parsed",
                    "type": "bool",
                    "default": False,
                },
                {"name": "root_dataset"},
                {
                    "name": "root_dataset_available",
                    "source": "root_dataset/properties/available/parsed",
                    "default": 0,
                },
                {
                    "name": "root_dataset_used",
                    "source": "root_dataset/properties/used/parsed",
                    "default": 0,
                },
                {
                    "name": "scan_function",
                    "source": "scan/function",
                    "default": "unknown",
                },
                {"name": "scrub_state", "source": "scan/state", "default": "unknown"},
                {
                    "name": "scrub_start",
                    "source": "scan/start_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_end",
                    "source": "scan/end_time/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "scrub_secs_left",
                    "source": "scan/total_secs_left",
                    "default": 0,
                },
                {"name": "allocated", "default": 0},
                {"name": "free", "default": 0},
            ],
            ensure_vals=[
                {"name": "available", "default": 0.0},
                {"name": "total", "default": 0.0},
                {"name": "usage", "default": 0.0},
            ],
        )
        if not self.api.connected():
            return

        # Process pools
        tmp_dataset_available = {}
        tmp_dataset_total = {}
        for uid, vals in self.ds["dataset"].items():
            tmp_dataset_available[self.ds["dataset"][uid]["mountpoint"]] = vals[
                "available"
            ]

            tmp_dataset_total[self.ds["dataset"][uid]["mountpoint"]] = (
                vals["available"] + vals["used"]
            )

        for uid, vals in self.ds["pool"].items():
            if vals["path"] in tmp_dataset_available:
                self.ds["pool"][uid]["available"] = tmp_dataset_available[vals["path"]]

            if vals["path"] in tmp_dataset_total:
                self.ds["pool"][uid]["total"] = tmp_dataset_total[vals["path"]]

            if vals["name"] in ["boot-pool", "freenas-boot"]:
                self.ds["pool"][uid]["available"] = vals["free"]
                self.ds["pool"][uid]["total"] = vals["free"] + vals["allocated"]

                self.ds["pool"][uid].pop("root_dataset")

            if self.ds["pool"][uid]["total"] > 0:
                self.ds["pool"][uid]["usage"] = round(
                    (
                        (
                            self.ds["pool"][uid]["total"]
                            - self.ds["pool"][uid]["available"]
                        )
                        / self.ds["pool"][uid]["total"]
                    )
                    * 100
                )
            else:
                self.ds["pool"][uid]["usage"] = 0

    # ---------------------------
    #   get_dataset
    # ---------------------------
    def get_dataset(self) -> None:
        """Get datasets from TrueNAS."""
        self.ds["dataset"] = parse_api(
            data={},
            source=self.api.query("pool.dataset.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "name", "default": "unknown"},
                {"name": "pool", "default": "unknown"},
                {"name": "mountpoint", "default": "unknown"},
                {"name": "comments", "source": "comments/parsed", "default": ""},
                {
                    "name": "deduplication",
                    "source": "deduplication/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "atime",
                    "source": "atime/parsed",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "casesensitivity",
                    "source": "casesensitivity/parsed",
                    "default": "unknown",
                },
                {"name": "checksum", "source": "checksum/parsed", "default": "unknown"},
                {
                    "name": "exec",
                    "source": "exec/parsed",
                    "type": "bool",
                    "default": False,
                },
                {"name": "sync", "source": "sync/parsed", "default": "unknown"},
                {
                    "name": "compression",
                    "source": "compression/parsed",
                    "default": "unknown",
                },
                {
                    "name": "compressratio",
                    "source": "compressratio/parsed",
                    "default": "unknown",
                },
                {"name": "quota", "source": "quota/parsed", "default": "unknown"},
                {"name": "copies", "source": "copies/parsed", "default": 0},
                {
                    "name": "readonly",
                    "source": "readonly/parsed",
                    "type": "bool",
                    "default": False,
                },
                {"name": "recordsize", "source": "recordsize/parsed", "default": 0},
                {
                    "name": "encryption_algorithm",
                    "source": "encryption_algorithm/parsed",
                    "default": "unknown",
                },
                {"name": "used", "source": "used/parsed", "default": 0},
                {"name": "available", "source": "available/parsed", "default": 0},
            ],
        )

        if len(self.ds["dataset"]) == 0:
            return

        # entities_to_be_removed = []
        # if not self.datasets_hass_device_id:
        #     device_registry = dr.async_get(self.hass)
        #     for device in device_registry.devices.values():
        #         if (
        #             self.config_entry.entry_id in device.config_entries
        #             and device.name.endswith("Datasets")
        #         ):
        #             self.datasets_hass_device_id = device.id
        #             _LOGGER.debug(f"datasets device: {device.name}")
        #
        #     if not self.datasets_hass_device_id:
        #         return
        #
        # _LOGGER.debug(f"datasets_hass_device_id: {self.datasets_hass_device_id}")
        # entity_registry = er.async_get(self.hass)
        # entity_entries = async_entries_for_config_entry(
        #     entity_registry, self.config_entry.entry_id
        # )
        # for entity in entity_entries:
        #     if (
        #         entity.device_id == self.datasets_hass_device_id
        #         and entity.unique_id.removeprefix(f"{self.name.lower()}-dataset-")
        #         not in map(
        #             lambda x: str.replace(x, "/", "_"),
        #             map(str.lower, self.ds["dataset"].keys()),
        #         )
        #     ):
        #         _LOGGER.debug(f"dataset to be removed: {entity.unique_id}")
        #         entities_to_be_removed.append(entity.entity_id)
        #
        # for entity_id in entities_to_be_removed:
        #     entity_registry.async_remove(entity_id)

    # ---------------------------
    #   get_disk
    # ---------------------------
    def get_disk(self) -> None:
        """Get disks from TrueNAS."""
        self.ds["disk"] = parse_api(
            data=self.ds["disk"],
            source=self.api.query("disk.query"),
            key="identifier",
            vals=[
                {"name": "name", "default": "unknown"},
                {"name": "devname", "default": "unknown"},
                {"name": "serial", "default": "unknown"},
                {"name": "size", "default": "unknown"},
                {"name": "hddstandby", "default": "unknown"},
                {"name": "hddstandby_force", "type": "bool", "default": False},
                {"name": "advpowermgmt", "default": "unknown"},
                {"name": "acousticlevel", "default": "unknown"},
                {"name": "togglesmart", "type": "bool", "default": False},
                {"name": "model", "default": "unknown"},
                {"name": "rotationrate", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "zfs_guid", "default": "unknown"},
                {"name": "identifier", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "temperature", "default": 0},
            ],
        )

        # Get disk temperatures
        temps = self.api.query(
            "disk.temperatures",
            params={},
        )

        if temps:
            for uid, vals in self.ds["disk"].items():
                if vals["name"] in temps:  # looks for devname here
                    self.ds["disk"][uid]["temperature"] = temps[vals["name"]]
                    # return devname temp to uid disk
                    # I feel like this will break in the future when TrueNAS updates to a more sensible system. Currently their own long term stats are broken by the changing devnames.

    # ---------------------------
    #   get_vm
    # ---------------------------
    def get_vm(self) -> None:
        """Get VMs from TrueNAS."""
        if self.version_at_least(25, 10):
            self._get_vm_libvirt()
        else:
            self._get_vm_virt()

    # ---------------------------
    #   _get_vm_libvirt
    # ---------------------------
    def _get_vm_libvirt(self) -> None:
        """Get VMs with vm.query (TrueNAS 25.10+).

        25.10 dropped the Incus based virt.instance API and went back to the
        libvirt vm.* API. Entries are keyed by name, like virt.instance used
        to be, so "id" keeps holding the name and entity unique ids stay the
        same. The numeric libvirt id that vm.start/vm.stop expect is stored
        in "vm_id".
        """
        tmp_source = self.api.query("vm.query")
        if not isinstance(tmp_source, list):
            # Query failed: keep the last known entries instead of dropping
            # them (entities would raise KeyError) or converting them twice.
            return

        self.ds["vm"] = parse_api(
            data=self.ds["vm"],
            source=tmp_source,
            key="name",
            vals=[
                {"name": "vm_id", "source": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "description", "default": ""},
                {"name": "vcpus", "default": 1},
                {"name": "cores", "default": 1},
                {"name": "threads", "default": 1},
                {"name": "memory", "default": 0},
                {"name": "autostart", "type": "bool", "default": False},
                {"name": "status", "source": "status/state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["vm"].items():
            vm = self.ds["vm"][uid]
            vm["id"] = uid
            vm["type"] = "VM"
            vm["image"] = "unknown"
            vm["cpu"] = vals["vcpus"] * vals["cores"] * vals["threads"]
            # vm.query reports memory in MiB, the sensor exposes GiB
            vm["memory"] = round(vals["memory"] / 1024, 1)
            vm["running"] = vals["status"] == "RUNNING"

    # ---------------------------
    #   _get_vm_virt
    # ---------------------------
    def _get_vm_virt(self) -> None:
        """Get VMs and containers with virt.instance.query (TrueNAS 25.04)."""
        tmp_source = self.api.query("virt.instance.query")
        if not isinstance(tmp_source, list):
            # Query failed: keep the last known entries instead of dropping
            # them (entities would raise KeyError) or converting them twice.
            return

        self.ds["vm"] = parse_api(
            data=self.ds["vm"],
            source=tmp_source,
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "type", "default": "unknown"},
                {"name": "cpu", "default": 0},
                {"name": "memory", "default": 0},
                {"name": "autostart", "type": "bool", "default": False},
                {"name": "image", "source": "image/description", "default": "unknown"},
                {"name": "status", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["vm"].items():
            self.ds["vm"][uid]["memory"] = round(vals["memory"] / 1024 / 1024 / 1024)
            self.ds["vm"][uid]["running"] = vals["status"] == "RUNNING"

    # ---------------------------
    #   get_container
    # ---------------------------
    def get_container(self) -> None:
        """Get containers with container.query (TrueNAS 27.0+).

        Containers got their own container.* API in 27.0. Older releases have
        no such namespace (25.04 listed containers through virt.instance.*,
        which get_vm already covers), so nothing is queried there.
        Entries are keyed by name, like VMs, and the numeric id that
        container.start/container.stop expect is stored in "container_id".
        """
        if not self.version_at_least(27, 0):
            self.ds["container"] = {}
            return

        tmp_source = self.api.query("container.query")
        if not isinstance(tmp_source, list):
            # Query failed: keep the last known entries instead of dropping
            # them (entities would raise KeyError) or converting them twice.
            return

        self.ds["container"] = parse_api(
            data=self.ds["container"],
            source=tmp_source,
            key="name",
            vals=[
                {"name": "container_id", "source": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "description", "default": ""},
                {"name": "autostart", "type": "bool", "default": False},
                {"name": "cpuset", "default": None},
                {"name": "memory", "default": None},
                {"name": "status", "source": "status/state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["container"].items():
            container = self.ds["container"][uid]
            container["id"] = uid
            # Memory limit in MiB, null means no limit (host memory is shared)
            if isinstance(vals["memory"], int):
                container["memory"] = round(vals["memory"] / 1024, 1)
            container["running"] = vals["status"] == "RUNNING"

    # ---------------------------
    #   get_cloudsync
    # ---------------------------
    def get_cloudsync(self) -> None:
        """Get cloudsync from TrueNAS."""
        self.ds["cloudsync"] = parse_api(
            data=self.ds["cloudsync"],
            source=self.api.query("cloudsync.query"),
            key="id",
            vals=[
                {"name": "id", "default": "unknown"},
                {"name": "description", "default": "unknown"},
                {"name": "direction", "default": "unknown"},
                {"name": "path", "default": "unknown"},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "transfer_mode", "default": "unknown"},
                {"name": "snapshot", "type": "bool", "default": False},
                {"name": "state", "source": "job/state", "default": "unknown"},
                {
                    "name": "time_started",
                    "source": "job/time_started/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "time_finished",
                    "source": "job/time_finished/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {"name": "job_percent", "source": "job/progress/percent", "default": 0},
                {
                    "name": "job_description",
                    "source": "job/progress/description",
                    "default": "unknown",
                },
            ],
        )

    # ---------------------------
    #   get_replication
    # ---------------------------
    def get_replication(self) -> None:
        """Get replication from TrueNAS."""
        self.ds["replication"] = parse_api(
            data=self.ds["replication"],
            source=self.api.query("replication.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "source_datasets", "default": "unknown"},
                {"name": "target_dataset", "default": "unknown"},
                {"name": "recursive", "type": "bool", "default": False},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "direction", "default": "unknown"},
                {"name": "transport", "default": "unknown"},
                {"name": "auto", "type": "bool", "default": False},
                {"name": "retention_policy", "default": "unknown"},
                {"name": "state", "source": "job/state", "default": "unknown"},
                {
                    "name": "time_started",
                    "source": "job/time_started/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {
                    "name": "time_finished",
                    "source": "job/time_finished/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
                {"name": "job_percent", "source": "job/progress/percent", "default": 0},
                {
                    "name": "job_description",
                    "source": "job/progress/description",
                    "default": "unknown",
                },
            ],
        )

    # ---------------------------
    #   get_snapshottask
    # ---------------------------
    def get_snapshottask(self) -> None:
        """Get replication from TrueNAS."""
        self.ds["snapshottask"] = parse_api(
            data=self.ds["snapshottask"],
            source=self.api.query("pool.snapshottask.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "dataset", "default": "unknown"},
                {"name": "recursive", "type": "bool", "default": False},
                {"name": "lifetime_value", "default": 0},
                {"name": "lifetime_unit", "default": "unknown"},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "naming_schema", "default": "unknown"},
                {"name": "allow_empty", "type": "bool", "default": False},
                {"name": "vmware_sync", "type": "bool", "default": False},
                {"name": "state", "source": "state/state", "default": "unknown"},
                {
                    "name": "datetime",
                    "source": "state/datetime/$date",
                    "default": 0,
                    "convert": "utc_from_timestamp",
                },
            ],
        )

    # ---------------------------
    #   get_app
    # ---------------------------
    def get_app(self) -> None:
        """Get Apps from TrueNAS."""
        self.ds["app"] = parse_api(
            data=self.ds["app"],
            source=self.api.query("app.query"),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "name", "default": "unknown"},
                {"name": "human_version", "default": "unknown"},
                {"name": "version", "default": "unknown"},
                {"name": "latest_version", "default": "unknown"},
                {"name": "custom_app", "type": "bool", "default": False},
                {
                    "name": "update_available",
                    "source": "upgrade_available",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "image_updates_available",
                    "type": "bool",
                    "default": False,
                },
                {
                    "name": "portal",
                    "source": "portals/Web UI",
                    "default": "unknown",
                },
                {"name": "state", "default": "unknown"},
            ],
            ensure_vals=[
                {"name": "running", "type": "bool", "default": False},
            ],
        )

        for uid, vals in self.ds["app"].items():
            self.ds["app"][uid]["running"] = vals["state"] == "RUNNING"
