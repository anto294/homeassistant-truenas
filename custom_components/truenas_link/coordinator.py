"""TrueNAS Controller."""

from __future__ import annotations

import html
import logging
import re

from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_VERIFY_SSL,
)

from .api import TrueNASAPI
from .apiparser import parse_api
from .const import (
    BOOT_POOL_NAMES,
    DOMAIN,
    LOGIN_INTERVAL,
    STALE_AFTER_POLLS,
    SCAN_IDLE,
    SCAN_PAUSED,
    SCAN_RESILVERING,
    SCAN_SCRUBBING,
)
from .helper import is_read_only

_LOGGER = logging.getLogger(__name__)

# alert.list levels that need attention right away (AlertLevel in middleware)
CRITICAL_ALERT_LEVELS = ("CRITICAL", "ALERT", "EMERGENCY")
# Keeps the attribute well under the recorder's 16 KiB limit
MAX_ALERT_MESSAGES = 20
MAX_ALERT_MESSAGE_LENGTH = 255

# Seconds that a new boot time may differ from the last one and still be the same
# boot. It is worked out from "now" here and an uptime measured earlier on TrueNAS, so
# it moves by a second or two between updates, and more if an answer is slow. Any real
# reboot takes much longer than this, between firmware and importing the pools.
UPTIME_TOLERANCE = 10

# First "<major>.<minor>" pair in a TrueNAS version string
_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


# ---------------------------
#   scan_status
# ---------------------------
def scan_status(pool: dict[str, Any]) -> str:
    """Return what the pool's scan is doing, from its parsed scan values."""
    if pool.get("scrub_state") != "SCANNING":
        return SCAN_IDLE

    if pool.get("scan_function") == "RESILVER":
        return SCAN_RESILVERING

    return SCAN_PAUSED if pool.get("scan_pause") else SCAN_SCRUBBING


# ---------------------------
#   topology_errors
# ---------------------------
def topology_errors(topology: Any) -> dict[str, int]:
    """Return a pool's ZFS error counters, added up over its disks.

    Only leaves count: a mirror or raidz vdev keeps counters of its own that
    do not add up to those of its disks, so adding them would double count.
    """
    errors = {"read_errors": 0, "write_errors": 0, "checksum_errors": 0}

    def add(vdevs: list[Any]) -> None:
        for vdev in vdevs:
            if not isinstance(vdev, dict):
                continue

            if children := vdev.get("children"):
                add(children)
                continue

            stats = vdev.get("stats") or {}
            for name in errors:
                errors[name] += stats.get(name) or 0

    if isinstance(topology, dict):
        for vdevs in topology.values():
            if isinstance(vdevs, list):
                add(vdevs)

    return errors


type TrueNASConfigEntry = ConfigEntry[TrueNASCoordinator]


# ---------------------------
#   TrueNASControllerData
# ---------------------------
class TrueNASCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """TrueNASCoordinator Class."""

    def __init__(self, hass: HomeAssistant, config_entry: TrueNASConfigEntry):
        """Initialize TrueNASCoordinator."""
        self.hass = hass
        self.config_entry: TrueNASConfigEntry = config_entry

        super().__init__(
            self.hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )

        self.name = config_entry.options[CONF_NAME]
        self.instance = config_entry.options[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]
        self.read_only = is_read_only(config_entry.options)

        self.ds: dict[str, dict[Any, Any]] = {
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
            "cronjob": {},
        }

        self.api = TrueNASAPI(
            config_entry.data[CONF_HOST],
            config_entry.data[CONF_API_KEY],
            config_entry.data[CONF_VERIFY_SSL],
        )

        # Per section: the uids in TrueNAS' last answer, which may be empty.
        # A failed query leaves this as it was.
        self.present: dict[str, set[Any]] = {}
        # Sections whose answer in the current poll was a list with something in it
        self.answered: set[str] = set()
        # Names of the pools in TrueNAS' last answer
        self.pool_names: set[str] = set()
        self.stale_after_polls = STALE_AFTER_POLLS
        # Successful polls without an item, per section, and per registry entity
        self._stale_item_polls: dict[str, dict[Any, int]] = {}
        self.stale_entity_polls: dict[str, int] = {}

        self._systemstats_errored: list[tuple[str, str | None]] = []
        # Device registry id of the "System" device, set by async_setup_entry
        self.system_device_id: str | None = None
        self.last_login = 0.0
        # The entry is about to reload, so nothing new should be added to it
        self.reload_scheduled = False
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
    async def _async_update_data(self) -> dict[str, Any]:
        """Update TrueNAS data."""
        self.answered = set()
        if not self.api.connected() or monotonic() - self.last_login >= LOGIN_INTERVAL:
            await self.api.connect()
            self.last_login = monotonic()
            # Check it here: the next query() clears the error code
            if self.api.error == "invalid_key":
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="api_key_rejected",
                    translation_placeholders={"host": self.host},
                )

        jobs = [
            self.get_systeminfo,
            self.get_systemstats,
            self.get_alerts,
            self.get_rebootinfo,
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
            self.get_cronjob,
        ]

        for job in jobs:
            if self.api.connected():
                await job()

        delta = datetime.now().replace(microsecond=0) - self.last_updatecheck_update
        if self.api.connected() and delta.total_seconds() > 60 * 60 * 12:
            await self.get_updatecheck()
            self.last_updatecheck_update = datetime.now().replace(microsecond=0)

        if not self.api.connected():
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"host": self.host},
            )

        self._forget_stale_items()
        return self.ds

    # ---------------------------
    #   _seen
    # ---------------------------
    def _seen(self, section: str, key: str, source: Any) -> Any:
        """Note which items a query returned, and return its answer.

        None means that the query failed, which says nothing about the items.
        """
        if isinstance(source, list):
            uids = {
                item[key] for item in source if isinstance(item, dict) and item.get(key)
            }
            self.present[section] = uids
            if uids:
                self.answered.add(section)

        return source

    # ---------------------------
    #   is_missing
    # ---------------------------
    def is_missing(self, section: str, uid: Any) -> bool:
        """Return whether TrueNAS no longer lists an item it knows the section of.

        An empty list does not count: Docker restarting empties the apps, and a
        pool that is not imported yet empties its datasets. For the same reason a
        dataset does not count while its pool is not there.
        """
        present = self.present.get(section)
        if not present or uid in present:
            return False

        if section == "dataset":
            item = self.ds["dataset"].get(uid) or {}
            return item.get("pool") in self.pool_names

        return True

    # ---------------------------
    #   _forget_stale_items
    # ---------------------------
    def _forget_stale_items(self) -> None:
        """Drop items from the data after many successful polls without them."""
        for section in self.answered:
            polls = self._stale_item_polls.setdefault(section, {})
            missing = {uid for uid in self.ds[section] if self.is_missing(section, uid)}
            for uid in set(polls) - missing:
                del polls[uid]

            for uid in missing:
                polls[uid] = polls.get(uid, 0) + 1
                if polls[uid] >= self.stale_after_polls:
                    del self.ds[section][uid]
                    del polls[uid]

    # ---------------------------
    #   get_systeminfo
    # ---------------------------
    async def get_systeminfo(self) -> None:
        """Get system info from TrueNAS."""
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=await self.api.query("system.info"),
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
                # None: the entity exists, and its state is unknown until TrueNAS
                # reports a value. A default of 0 would show as a real reading.
                {"name": "uptimeEpoch", "default": None},
                {"name": "cpu_temperature", "default": None},
                {"name": "load_shortterm", "default": None},
                {"name": "load_midterm", "default": None},
                {"name": "load_longterm", "default": None},
                {"name": "cpu_usage", "default": None},
                {"name": "cache_size-arc_value", "default": None},
                {"name": "memory-used_value", "default": None},
                {"name": "memory-free_value", "default": None},
                {"name": "memory-total_value", "default": None},
                {"name": "memory-usage_percent", "default": None},
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
                source=await self.api.query(
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
            boot_time = dt_util.utcnow().replace(microsecond=0) - timedelta(
                seconds=int(self.ds["system_info"]["uptime_seconds"])
            )
            last_boot_time = self.ds["system_info"]["uptimeEpoch"]
            if (
                last_boot_time is None
                or abs((boot_time - last_boot_time).total_seconds()) > UPTIME_TOLERANCE
            ):
                self.ds["system_info"]["uptimeEpoch"] = boot_time

        self.ds["interface"] = parse_api(
            data=self.ds["interface"],
            source=self._seen(
                "interface", "id", await self.api.query("interface.query")
            ),
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
                {"name": "rx", "default": None},
                {"name": "tx", "default": None},
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
    async def get_updatecheck(self) -> None:
        """Check whether a TrueNAS system update is available."""
        if self.version_at_least(25, 10):
            await self._get_updatecheck_status()
        else:
            await self._get_updatecheck_legacy()

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
    async def _get_updatecheck_status(self) -> None:
        """Check for system updates with update.status (TrueNAS 25.10+).

        update.check_available was removed in 25.10. update.status returns
        {"code": "NORMAL"|"ERROR", "status": {"new_version": {"version": ...}}}
        where new_version is null when the system is up to date.
        """
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=await self.api.query("update.status"),
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
    async def _get_updatecheck_legacy(self) -> None:
        """Check for system updates with update.check_available (before 25.10)."""
        self.ds["system_info"] = parse_api(
            data=self.ds["system_info"],
            source=await self.api.query("update.check_available"),
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
    #   get_alerts
    # ---------------------------
    async def get_alerts(self) -> None:
        """Get the active (not dismissed) TrueNAS alerts."""
        alerts = await self.api.query("alert.list")
        if not isinstance(alerts, list):
            # Keep the last values. Without any, the entities are not created.
            return

        active = [alert for alert in alerts if not alert.get("dismissed")]
        messages = []
        for alert in active[:MAX_ALERT_MESSAGES]:
            # "text" is a template with placeholders, "formatted" may have HTML
            text = alert.get("formatted") or alert.get("text") or ""
            text = html.unescape(re.sub(r"<[^>]+>", "", text))
            messages.append(
                f"{alert.get('level', 'UNKNOWN')}: {text}"[:MAX_ALERT_MESSAGE_LENGTH]
            )

        system_info = self.ds["system_info"]
        system_info["alerts_active"] = len(active)
        system_info["alerts_critical"] = any(
            alert.get("level") in CRITICAL_ALERT_LEVELS for alert in active
        )
        system_info["alert_messages"] = messages

    # ---------------------------
    #   get_rebootinfo
    # ---------------------------
    async def get_rebootinfo(self) -> None:
        """Get whether TrueNAS needs a reboot, and why."""
        info = await self.api.query("system.reboot.info")
        if not isinstance(info, dict):
            # Keep the last values. Without any, the entity is not created.
            return

        reasons = [
            reason.get("reason", "unknown")
            for reason in info.get("reboot_required_reasons") or []
        ]
        self.ds["system_info"]["reboot_required"] = bool(reasons)
        self.ds["system_info"]["reboot_required_reasons"] = reasons

    # ---------------------------
    #   get_systemstats
    # ---------------------------
    async def get_systemstats(self) -> None:
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

        tmp_graph = await self.api.query(reporting_path, params=[tmp_graphs, tmp_query])

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
                tmp_single = await self.api.query(
                    reporting_path, params=[[tmp], tmp_query]
                )
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
                self.ds["system_info"]["cpu_temperature"] = (
                    round(max(tmp_temps), 2) if tmp_temps else None
                )

            # CPU load
            if tmp_graph[i]["name"] == "load":
                # TrueNAS renames load1/load5/load15 to these
                tmp_arr: tuple[str, ...] = ("shortterm", "midterm", "longterm")
                self._systemstats_process(tmp_arr, tmp_graph[i], "load")

            # CPU usage
            if tmp_graph[i]["name"] == "cpu":
                # Aggregate "cpu" only, not the per-core "cpu0", "cpu1", ...
                tmp_arr = ("cpu",)
                self._systemstats_process(tmp_arr, tmp_graph[i], "cpu")
                self.ds["system_info"]["cpu_usage"] = self.ds["system_info"]["cpu_cpu"]

            # Interface
            if tmp_graph[i]["name"] == "interface":
                tmp_etc = tmp_graph[i]["identifier"]
                if tmp_etc in self.ds["interface"]:
                    tmp_mean = {
                        k.replace("received", "rx").replace("sent", "tx"): v
                        for k, v in self._systemstats_mean(tmp_graph[i]).items()
                    }
                    for tmp_var in ("rx", "tx"):
                        tmp_val = tmp_mean.get(tmp_var)
                        self.ds["interface"][tmp_etc][tmp_var] = (
                            None if tmp_val is None else round(tmp_val * 0.12207, 2)
                        )

            # memory
            if tmp_graph[i]["name"] == "memory":
                # Legend is "total", "available"; only available is used
                tmp_arr = ("available",)
                tmp_physmem = self.ds["system_info"]["physmem"]
                self.ds["system_info"]["memory-total_value"] = (
                    round(tmp_physmem) if tmp_physmem else None
                )

                # A moment without samples says nothing about the memory in use,
                # so keep the last known values, or unknown if there are none yet.
                if self._systemstats_mean(tmp_graph[i]).get("available") is None:
                    continue

                self._systemstats_process(tmp_arr, tmp_graph[i], "memory")
                tmp_total = float(self.ds["system_info"]["memory-total_value"] or 0)
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
    def _systemstats_graph_key(graph: dict[str, Any]) -> tuple[str, str | None]:
        """Return the (name, identifier) pair that identifies a requested graph.

        Interfaces share the graph name "interface", so the identifier is
        needed to skip only the interface that failed.
        """
        return graph["name"], graph.get("identifier")

    # ---------------------------
    #   _systemstats_mean
    # ---------------------------
    @staticmethod
    def _systemstats_mean(graph: dict[str, Any]) -> dict[str, Any]:
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
    def _systemstats_process(
        self, arr: tuple[str, ...], graph: dict[str, Any], t: str
    ) -> None:
        """Store the mean values of the requested legend entries of a graph.

        `arr` is a tuple of exact legend names.
        """
        tmp_mean = self._systemstats_mean(graph)
        for tmp_var in arr:
            # None if this window has no data: 0 would be a false reading
            self._systemstats_store(t, tmp_var, tmp_mean.get(tmp_var))

    # ---------------------------
    #   _systemstats_store
    # ---------------------------
    def _systemstats_store(self, t: str, tmp_var: str, tmp_val: float | None) -> None:
        """Store one reporting value in system_info under its sensor key."""
        tmp_round = None if tmp_val is None else round(tmp_val, 2)
        if t == "memory":
            # The caller only gets here with a value
            self.ds["system_info"]["memory-free_value"] = round(tmp_val or 0)
        elif t == "cpu":
            self.ds["system_info"][f"cpu_{tmp_var}"] = tmp_round
        elif t == "load":
            self.ds["system_info"][f"load_{tmp_var}"] = tmp_round
        elif t == "arcsize":
            self.ds["system_info"]["cache_size-arc_value"] = tmp_round

    # ---------------------------
    #   get_service
    # ---------------------------
    async def get_service(self) -> None:
        """Get service info from TrueNAS."""
        self.ds["service"] = parse_api(
            data=self.ds["service"],
            source=self._seen("service", "id", await self.api.query("service.query")),
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
    async def get_pool(self) -> None:
        """Get pools from TrueNAS."""
        tmp_pools = await self.api.query("pool.query")
        self.ds["pool"] = parse_api(
            data=self.ds["pool"],
            source=tmp_pools,
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
                {"name": "scan_pause", "source": "scan/pause", "default": 0},
                {"name": "scan_percentage", "source": "scan/percentage", "default": 0},
                {"name": "scan_errors", "source": "scan/errors", "default": 0},
            ],
            ensure_vals=[
                {"name": "available", "default": 0.0},
                {"name": "total", "default": 0.0},
                {"name": "usage", "default": 0.0},
            ],
        )

        tmp_boot = await self.api.query("boot.get_state")
        self._seen_pools(tmp_pools, tmp_boot)
        self.ds["pool"] = parse_api(
            data=self.ds["pool"],
            source=tmp_boot,
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
                {"name": "scan_pause", "source": "scan/pause", "default": 0},
                {"name": "scan_percentage", "source": "scan/percentage", "default": 0},
                {"name": "scan_errors", "source": "scan/errors", "default": 0},
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

        # ZFS error counters, from the topology that is not kept in ds
        raw_pools = {pool.get("guid"): pool for pool in tmp_pools or []}
        if isinstance(tmp_boot, dict):
            raw_pools[tmp_boot.get("name")] = tmp_boot

        for uid, raw_pool in raw_pools.items():
            if uid in self.ds["pool"]:
                errors = topology_errors(raw_pool.get("topology"))
                self.ds["pool"][uid].update(errors)
                self.ds["pool"][uid]["pool_errors"] = sum(errors.values())

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
            vals["scan_status"] = scan_status(vals)
            # pool.query only has the latest scan, which may be a resilver or
            # a canceled scrub, so remember the last scrub that finished
            vals.setdefault("last_scrub", None)
            if (
                vals["scan_function"] == "SCRUB"
                and vals["scrub_state"] == "FINISHED"
                and isinstance(vals["scrub_end"], datetime)
            ):
                vals["last_scrub"] = vals["scrub_end"]

            if vals["path"] in tmp_dataset_available:
                self.ds["pool"][uid]["available"] = tmp_dataset_available[vals["path"]]

            if vals["path"] in tmp_dataset_total:
                self.ds["pool"][uid]["total"] = tmp_dataset_total[vals["path"]]

            if vals["name"] in BOOT_POOL_NAMES:
                self.ds["pool"][uid]["available"] = vals["free"]
                self.ds["pool"][uid]["total"] = vals["free"] + vals["allocated"]

                # Only there after an answer: the query may have failed this time
                self.ds["pool"][uid].pop("root_dataset", None)

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
    #   _seen_pools
    # ---------------------------
    def _seen_pools(self, pools: Any, boot: Any) -> None:
        """Note the pools that exist, from the answers of both pool queries.

        The boot pool is always there, so it cannot tell whether the list of the
        others is empty, and pools only count if both queries worked.
        """
        if not isinstance(pools, list) or not isinstance(boot, dict):
            return

        names = {pool["name"] for pool in pools if pool.get("name")}
        self.pool_names = names | {str(boot.get("name"))}
        if pools:
            self.present["pool"] = {pool["guid"] for pool in pools if pool.get("guid")}
            self.present["pool"].add(boot.get("name"))
            self.answered.add("pool")

    # ---------------------------
    #   get_dataset
    # ---------------------------
    async def get_dataset(self) -> None:
        """Get datasets from TrueNAS."""
        self.ds["dataset"] = parse_api(
            data=self.ds["dataset"],
            source=self._seen(
                "dataset", "id", await self.api.query("pool.dataset.query")
            ),
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

    # ---------------------------
    #   get_disk
    # ---------------------------
    async def get_disk(self) -> None:
        """Get disks from TrueNAS."""
        disks = await self.api.query("disk.query")
        self._async_follow_new_identifiers(disks)
        self.ds["disk"] = parse_api(
            data=self.ds["disk"],
            source=self._seen("disk", "identifier", disks),
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
                {"name": "temperature", "default": None},
            ],
        )

        # Get disk temperatures
        temps = await self.api.query(
            "disk.temperatures",
            params={},
        )

        # None: the query failed, so keep the last values. If TrueNAS answers without
        # a disk, it has no temperature to report for it now.
        if isinstance(temps, dict):
            for uid, vals in self.ds["disk"].items():
                self.ds["disk"][uid]["temperature"] = temps.get(vals["name"])
                # looks for devname here, and returns devname temp to uid disk
                # I feel like this will break in the future when TrueNAS updates to a more sensible system. Currently their own long term stats are broken by the changing devnames.

    # ---------------------------
    #   _async_follow_new_identifiers
    # ---------------------------
    @callback
    def _async_follow_new_identifiers(self, disks: Any) -> None:
        """Keep the entity of a disk whose identifier changed, then reload.

        Without a serial, a disk's identifier holds its name until TrueNAS partitions
        it, and then a partition's uuid. Its entity's unique id holds the identifier,
        so the disk would get a second entity with another entity id. A disk with a
        new serial or size is another disk, whatever its name.
        """
        if not isinstance(disks, list):
            return

        listed = {disk.get("identifier") for disk in disks}
        registry = er.async_get(self.hass)
        fields = ("name", "serial", "size")
        for disk in disks:
            new = disk.get("identifier")
            if new in self.ds["disk"]:
                continue

            for old, known in self.ds["disk"].items():
                if old in listed or any(known.get(f) != disk.get(f) for f in fields):
                    continue

                entity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, self._disk_unique_id(old)
                )
                new_unique_id = self._disk_unique_id(new)
                if (
                    entity_id is None
                    or registry.async_get_entity_id("sensor", DOMAIN, new_unique_id)
                    is not None
                ):
                    continue

                registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
                self.reload_scheduled = True

        if self.reload_scheduled:
            # Entities hold their item's identifier, so they have to be made again
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    def _disk_unique_id(self, identifier: Any) -> str:
        """Return the unique id of a disk's entity, as TrueNASEntity builds it."""
        return f"{self.instance.lower()}-disk-{slugify(str(identifier).lower())}"

    # ---------------------------
    #   get_vm
    # ---------------------------
    async def get_vm(self) -> None:
        """Get VMs from TrueNAS."""
        if self.version_at_least(25, 10):
            await self._get_vm_libvirt()
        else:
            await self._get_vm_virt()

    # ---------------------------
    #   _get_vm_libvirt
    # ---------------------------
    async def _get_vm_libvirt(self) -> None:
        """Get VMs with vm.query (TrueNAS 25.10+).

        25.10 dropped the Incus based virt.instance API and went back to the
        libvirt vm.* API. Entries are keyed by name, like virt.instance used
        to be, so "id" keeps holding the name and entity unique ids stay the
        same. The numeric libvirt id that vm.start/vm.stop expect is stored
        in "vm_id".
        """
        tmp_source = self._seen("vm", "name", await self.api.query("vm.query"))
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
    async def _get_vm_virt(self) -> None:
        """Get VMs and containers with virt.instance.query (TrueNAS 25.04)."""
        tmp_source = self._seen("vm", "id", await self.api.query("virt.instance.query"))
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
    async def get_container(self) -> None:
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

        tmp_source = self._seen(
            "container", "name", await self.api.query("container.query")
        )
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
    async def get_cloudsync(self) -> None:
        """Get cloudsync from TrueNAS.

        The fields are selected so the credentials and the encryption password,
        which the task also holds, never reach Home Assistant.
        """
        self.ds["cloudsync"] = parse_api(
            data=self.ds["cloudsync"],
            source=self._seen(
                "cloudsync",
                "id",
                await self.api.query(
                    "cloudsync.query",
                    params=[
                        [],
                        {
                            "select": [
                                "id",
                                "description",
                                "direction",
                                "path",
                                "enabled",
                                "transfer_mode",
                                "snapshot",
                                "job",
                            ]
                        },
                    ],
                ),
            ),
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
    async def get_replication(self) -> None:
        """Get replication from TrueNAS.

        The fields are selected so the encryption key and the SSH credentials,
        which the task also holds, never reach Home Assistant.
        """
        self.ds["replication"] = parse_api(
            data=self.ds["replication"],
            source=self._seen(
                "replication",
                "id",
                await self.api.query(
                    "replication.query",
                    params=[
                        [],
                        {
                            "select": [
                                "id",
                                "name",
                                "source_datasets",
                                "target_dataset",
                                "recursive",
                                "enabled",
                                "direction",
                                "transport",
                                "auto",
                                "retention_policy",
                                "job",
                            ]
                        },
                    ],
                ),
            ),
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
    async def get_snapshottask(self) -> None:
        """Get replication from TrueNAS."""
        self.ds["snapshottask"] = parse_api(
            data=self.ds["snapshottask"],
            source=self._seen(
                "snapshottask", "id", await self.api.query("pool.snapshottask.query")
            ),
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
    #   get_cronjob
    # ---------------------------
    async def get_cronjob(self) -> None:
        """Get cron jobs from TrueNAS, for the switches that enable them.

        Read-only entries have no use for them. The fields are selected so
        the command and user, which can hold secrets, never reach Home
        Assistant, not even its debug log.
        """
        if self.read_only:
            return

        self.ds["cronjob"] = parse_api(
            data=self.ds["cronjob"],
            source=self._seen(
                "cronjob",
                "id",
                await self.api.query(
                    "cronjob.query",
                    params=[
                        [],
                        {"select": ["id", "description", "enabled", "schedule"]},
                    ],
                ),
            ),
            key="id",
            vals=[
                {"name": "id", "default": 0},
                {"name": "description", "default": ""},
                {"name": "enabled", "type": "bool", "default": False},
                {"name": "minute", "source": "schedule/minute", "default": "*"},
                {"name": "hour", "source": "schedule/hour", "default": "*"},
                {"name": "dom", "source": "schedule/dom", "default": "*"},
                {"name": "month", "source": "schedule/month", "default": "*"},
                {"name": "dow", "source": "schedule/dow", "default": "*"},
            ],
        )
        for uid, vals in self.ds["cronjob"].items():
            vals["cron_name"] = vals["description"] or f"Cron job {uid}"
            vals["schedule"] = " ".join(
                str(vals[field]) for field in ("minute", "hour", "dom", "month", "dow")
            )

    # ---------------------------
    #   get_app
    # ---------------------------
    async def get_app(self) -> None:
        """Get Apps from TrueNAS."""
        self.ds["app"] = parse_api(
            data=self.ds["app"],
            source=self._seen("app", "id", await self.api.query("app.query")),
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
