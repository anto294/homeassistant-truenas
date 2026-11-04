"""Tests for system statistics parsed from reporting.netdata_get_data."""

from __future__ import annotations

from custom_components.truenas.coordinator import TrueNASCoordinator

from .test_api import _reply

GIB = 1024**3


def _graph(name, legend, mean, identifier=None):
    """Build one graph the way reporting.netdata_get_data returns it.

    The legend starts with "time" and aggregations hold min/mean/max per
    legend entry, as on TrueNAS 25.04, 25.10 and 27.0.
    """
    return {
        "name": name,
        "identifier": identifier,
        "data": [],
        "aggregations": {"min": dict(mean), "mean": dict(mean), "max": dict(mean)},
        "start": 1762250000,
        "end": 1762250060,
        "legend": ["time", *legend],
    }


# Legend names as produced by the TrueNAS netdata plugins (truenas_arcstats,
# truenas_cpu_usage, truenas_meminfo, system.load) and the middleware graph
# classes that rename them.
REPORTING_GRAPHS = [
    _graph(
        "load",
        ["shortterm", "midterm", "longterm"],
        {"shortterm": 0.52, "midterm": 0.61, "longterm": 0.7},
    ),
    _graph("cputemp", ["0", "1"], {"0": 41.5, "1": 44.25}),
    _graph(
        "cpu",
        ["cpu", "cpu0", "cpu1"],
        {"cpu": 12.345, "cpu0": 30.0, "cpu1": 5.0},
    ),
    _graph("arcsize", ["size"], {"size": 8.5 * GIB}),
    _graph("memory", ["available"], {"available": 12 * GIB}),
    _graph(
        "interface",
        ["received", "sent"],
        {"received": 100.0, "sent": 50.0},
        identifier="eno1",
    ),
]


def _coordinator(api):
    """Build a coordinator around `api` without a Home Assistant instance."""
    coordinator = TrueNASCoordinator.__new__(TrueNASCoordinator)
    coordinator.host = "truenas.lan"
    coordinator.api = api
    coordinator._is_virtual = False
    coordinator._systemstats_errored = []
    coordinator.ds = {
        "system_info": {"physmem": 16 * GIB},
        "interface": {"eno1": {"rx": 0, "tx": 0}},
    }
    return coordinator


def test_systemstats_populates_every_sensor(connected_api):
    """Each graph's real legend names reach their sensor keys."""
    api, ws = connected_api(_reply(result=REPORTING_GRAPHS))
    coordinator = _coordinator(api)

    coordinator.get_systemstats()

    system_info = coordinator.ds["system_info"]
    assert ws.requests[0]["method"] == "reporting.netdata_get_data"
    # ARC size: legend "size" (upstream matched it as a substring of "arc_size")
    assert system_info["cache_size-arc_value"] == round(8.5 * GIB, 2)
    # CPU: only the aggregate "cpu" entry, not the per-core values
    assert system_info["cpu_usage"] == 12.35
    assert "cpu_cpu0" not in system_info
    assert system_info["cpu_temperature"] == 44.25
    assert system_info["load_shortterm"] == 0.52
    assert system_info["load_midterm"] == 0.61
    assert system_info["load_longterm"] == 0.7
    assert system_info["memory-free_value"] == 12 * GIB
    assert system_info["memory-usage_percent"] == 25
    assert coordinator.ds["interface"]["eno1"] == {"rx": 12.21, "tx": 6.1}


def test_arcsize_without_samples_reports_zero(connected_api):
    """A null aggregation (27.0) resets ARC size to 0 instead of failing."""
    graph = _graph("arcsize", ["size"], {})
    graph["aggregations"] = None
    api, _ = connected_api(_reply(result=[graph]))
    coordinator = _coordinator(api)
    coordinator.ds["system_info"]["cache_size-arc_value"] = 123.0

    coordinator.get_systemstats()

    assert coordinator.ds["system_info"]["cache_size-arc_value"] == 0.0


def _graphs_by_request(request):
    """Return the canned graphs matching the graphs a request asks for."""
    wanted = {(g["name"], g.get("identifier")) for g in request["params"][0]}
    return [g for g in REPORTING_GRAPHS if (g["name"], g["identifier"]) in wanted]


def test_request_parameters(connected_api):
    """Graphs and a valid query (start before end, boolean aggregate) are sent."""
    api, ws = connected_api(_reply(result=REPORTING_GRAPHS))
    coordinator = _coordinator(api)

    coordinator.get_systemstats()

    graphs, query = ws.requests[0]["params"]
    assert {"name": "interface", "identifier": "eno1"} in graphs
    assert {"name": "arcsize"} in graphs
    assert query["start"] < query["end"]
    assert query["end"] - query["start"] == 60
    assert query["aggregate"] is True


def test_failing_graph_is_isolated_and_skipped(connected_api, caplog):
    """One graph TrueNAS rejects no longer drops all system statistics."""

    def responder(request):
        names = [g["name"] for g in request["params"][0]]
        if "cputemp" in names:
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32001, "message": "Method call error"},
            }
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": _graphs_by_request(request),
        }

    api, ws = connected_api(responder)
    coordinator = _coordinator(api)

    coordinator.get_systemstats()

    # Batch, then one request per graph, each shaped [[graph], query]
    assert len(ws.requests) == 1 + 6
    for request in ws.requests[1:]:
        graphs, query = request["params"]
        assert len(graphs) == 1 and query["aggregate"] is True
    assert coordinator._systemstats_errored == [("cputemp", None)]
    assert "cputemp" in caplog.text
    assert api.connected()
    system_info = coordinator.ds["system_info"]
    assert system_info["cache_size-arc_value"] == round(8.5 * GIB, 2)
    assert system_info["cpu_usage"] == 12.35
    assert coordinator.ds["interface"]["eno1"] == {"rx": 12.21, "tx": 6.1}

    # Next refresh: one batch request without the failing graph
    ws.requests.clear()
    coordinator.get_systemstats()
    assert len(ws.requests) == 1
    assert {"name": "cputemp"} not in ws.requests[0]["params"][0]


def test_connection_loss_does_not_mark_graphs_as_failed(connected_api):
    """A dropped connection is retried later, not treated as a bad graph."""

    def responder(request):
        raise ConnectionError("connection reset")

    api, ws = connected_api(responder)
    coordinator = _coordinator(api)

    coordinator.get_systemstats()

    assert len(ws.requests) == 1
    assert coordinator._systemstats_errored == []
    assert not api.connected()
