"""Tests for the JSON-RPC handling of TrueNASAPI.query()."""

from __future__ import annotations

import logging

# update.status on TrueNAS 25.10 for a system that is up to date. The
# "error": null key is part of the method's own result, not a JSON-RPC error.
UPDATE_STATUS_UP_TO_DATE = {
    "code": "NORMAL",
    "error": None,
    "status": {"new_version": None},
}


def _reply(result=None, error=None, include_result=True):
    """Build a responder that answers every request the same way."""

    def responder(request):
        response = {"jsonrpc": "2.0", "id": request["id"]}
        if error is not None:
            response["error"] = error
        elif include_result:
            response["result"] = result
        return response

    return responder


def test_result_containing_null_error_key_is_returned(connected_api):
    """A result with "error": null is data, not a failure (TrueNAS 25.10)."""
    api, ws = connected_api(_reply(result=UPDATE_STATUS_UP_TO_DATE))

    assert api.query("update.status") == UPDATE_STATUS_UP_TO_DATE
    assert api.connected()
    assert not ws.closed
    assert api.error == ""
    assert ws.requests[0]["method"] == "update.status"


def test_rpc_error_logs_reason_and_keeps_connection(connected_api, caplog):
    """A top-level JSON-RPC error returns None without disconnecting."""
    api, ws = connected_api(
        _reply(
            error={
                "code": -32001,
                "message": "Method call error",
                "data": {"reason": "[ENOENT] VM 7 does not exist"},
            }
        )
    )

    with caplog.at_level(logging.ERROR, logger="custom_components.truenas_link.api"):
        assert api.query("vm.get_instance", [7]) is None

    assert api.connected()
    assert not ws.closed
    assert "[ENOENT] VM 7 does not exist" in caplog.text


def test_rpc_error_without_data_logs_message(connected_api, caplog):
    """Errors without data/reason (e.g. data: null) fall back to message."""
    api, _ = connected_api(
        _reply(error={"code": -32601, "message": "Method not found", "data": None})
    )

    with caplog.at_level(logging.ERROR, logger="custom_components.truenas_link.api"):
        assert api.query("update.check_available") is None

    assert api.connected()
    assert "Method not found" in caplog.text


def test_response_without_result_or_error_is_malformed(connected_api):
    """A response with neither result nor error sets malformed_result."""
    api, _ = connected_api(_reply(include_result=False))

    assert api.query("system.info") is None
    assert api.error == "malformed_result"
    assert api.connected()


def test_list_result_is_returned(connected_api):
    """Query methods returning lists are passed through unchanged."""
    pools = [{"name": "tank", "healthy": True}]
    api, _ = connected_api(_reply(result=pools))

    assert api.query("pool.query") == pools
