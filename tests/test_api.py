"""Tests for TrueNASAPI: JSON-RPC handling of query() and the SSL context."""

from __future__ import annotations

import logging
import ssl

from unittest.mock import patch

from homeassistant.util.ssl import client_context, get_default_no_verify_context

from custom_components.truenas_link.api import TrueNASAPI

from .conftest import FakeWebSocket

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


def test_ssl_context_verifies_with_ca_bundle():
    """Verify SSL uses Home Assistant's context, which loads trusted CAs."""
    api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=True)

    assert api._ssl_context is client_context()
    assert api._ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert api._ssl_context.check_hostname
    assert api._ssl_context.cert_store_stats()["x509_ca"] > 0


def test_ssl_context_without_verification():
    """Without Verify SSL, use Home Assistant's no-verify context."""
    api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=False)

    assert api._ssl_context is get_default_no_verify_context()
    assert api._ssl_context.verify_mode == ssl.CERT_NONE
    assert not api._ssl_context.check_hostname


def _login(result=True):
    """Build a responder that answers a login with `result`, and queries with []."""

    def responder(request):
        if request["method"] == "auth.login_with_api_key":
            return {"id": request["id"], "result": result}
        return {"id": request["id"], "result": []}

    return responder


def _api_with(*sockets):
    """Return an API and the patch that makes connect() hand out `sockets`."""
    api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=False)
    return api, patch(
        "custom_components.truenas_link.api.connect", side_effect=list(sockets)
    )


def test_rejected_login_closes_the_socket():
    """A wrong key leaves no connection open."""
    ws = FakeWebSocket(_login(False))
    api, connect = _api_with(ws)

    with connect:
        assert api.connect() is False

    assert ws.closed
    assert api.error == "invalid_key"
    assert not api.connected()


def test_login_exception_closes_the_socket():
    """A login that raises, here on a reply without a result, leaves nothing open."""
    ws = FakeWebSocket(lambda request: {"id": request["id"]})
    api, connect = _api_with(ws)

    with connect:
        assert api.connect() is False

    assert ws.closed
    assert not api.connected()


def test_connect_closes_a_socket_that_is_still_open():
    """connect() never loses track of a previous connection."""
    first = FakeWebSocket(_login())
    second = FakeWebSocket(_login())
    api, connect = _api_with(first, second)

    with connect:
        assert api.connect()
        assert api.connect()

    assert first.closed
    assert not second.closed
    assert api.connected()


def test_disconnect_survives_a_close_that_fails():
    """disconnect() does not raise, and the API counts as disconnected."""
    ws = FakeWebSocket(_login())
    ws.close = lambda: (_ for _ in ()).throw(OSError("broken pipe"))
    api, connect = _api_with(ws)

    with connect:
        assert api.connect()

    assert api.disconnect() is False
    assert not api.connected()
    # Nothing is left to close
    assert api.disconnect() is False


def test_connection_test_disconnects_and_reports_success():
    """A successful test closes its connection and still reports the outcome."""
    ws = FakeWebSocket(_login())
    api, connect = _api_with(ws)

    with connect:
        assert api.connection_test() == (True, "")

    assert ws.closed
    assert not api.connected()


def test_connection_test_keeps_the_error_code():
    """A failed test closes its connection and reports why it failed."""
    ws = FakeWebSocket(_login(False))
    api, connect = _api_with(ws)

    with connect:
        assert api.connection_test() == (False, "invalid_key")

    assert ws.closed
