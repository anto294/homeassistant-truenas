"""Tests for TrueNASAPI: JSON-RPC handling of query() and the SSL context."""

from __future__ import annotations

import logging
import ssl

import json
from pathlib import Path
import socket
from unittest.mock import patch

from homeassistant.util.ssl import client_context, get_default_no_verify_context
import pytest

from custom_components.truenas_link.api import (
    TrueNASAPI,
    TrueNASConnectionError,
    TrueNASMalformedResponseError,
    TrueNASRequestError,
)

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


def test_call_returns_a_null_result(connected_api):
    """A successful call that returns null is not an error."""
    api, _ = connected_api(_reply(result=None))

    assert api.call("system.shutdown", ["reason"]) is None


def test_call_raises_when_truenas_refuses(connected_api):
    """A JSON-RPC error raises with TrueNAS' reason, and keeps the connection."""
    api, ws = connected_api(
        _reply(error={"code": -32001, "data": {"reason": "[EBUSY] pool is busy"}})
    )

    with pytest.raises(TrueNASRequestError, match="pool is busy"):
        api.call("pool.scrub.scrub", ["tank", "START"])

    assert api.connected()
    assert not ws.closed


def test_call_raises_on_a_malformed_response(connected_api):
    """A response with neither result nor error raises."""
    api, _ = connected_api(_reply(include_result=False))

    with pytest.raises(TrueNASMalformedResponseError):
        api.call("system.info")


def test_call_raises_when_it_cannot_connect():
    """Without a connection, nothing has been sent."""
    api, connect = _api_with(FakeWebSocket(_login(False)))

    with connect:
        with pytest.raises(TrueNASConnectionError, match="invalid_key") as err:
            api.call("system.reboot", ["reason"])

    assert not err.value.request_sent


def test_call_tells_if_the_connection_broke_before_sending(connected_api):
    """A failed send means TrueNAS has not received the request."""
    api, ws = connected_api(_reply(result=None))
    ws.closed = True

    with pytest.raises(TrueNASConnectionError) as err:
        api.call("system.reboot", ["reason"])

    assert not err.value.request_sent
    assert not api.connected()


def test_call_tells_if_the_connection_broke_after_sending(connected_api):
    """A failed recv means TrueNAS may have acted on the request."""
    api, ws = connected_api(_reply(result=None))
    ws.recv = lambda: (_ for _ in ()).throw(EOFError("connection closed"))

    with pytest.raises(TrueNASConnectionError) as err:
        api.call("system.reboot", ["reason"])

    assert err.value.request_sent
    assert not api.connected()
    assert ws.closed


def test_query_still_returns_none_on_every_failure(connected_api):
    """Polling keeps its behavior: query() never raises."""
    api, ws = connected_api(_reply(result=None))
    ws.recv = lambda: (_ for _ in ()).throw(EOFError("connection closed"))

    assert api.query("system.info") is None
    assert not api.connected()


ERROR_CODES = json.loads(
    (
        Path(__file__).parent.parent
        / "custom_components"
        / "truenas_link"
        / "strings.json"
    ).read_text()
)["config"]["error"]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("timed out during opening handshake"), "handshake_timeout"),
        (TimeoutError(), "handshake_timeout"),
        (socket.timeout("_ssl.c:989: The handshake timed out"), "handshake_timeout"),
        (ConnectionRefusedError(111, "Connection refused"), "connection_refused"),
        (socket.gaierror(-2, "Name or service not known"), "invalid_hostname"),
        (OSError(113, "No route to host"), "invalid_hostname"),
        (
            socket.gaierror(-5, "No address associated with hostname"),
            "unknown_hostname",
        ),
        (
            ssl.SSLCertVerificationError("[SSL: CERTIFICATE_VERIFY_FAILED] failed"),
            "certificate_verify_failed",
        ),
        (Exception("server rejected WebSocket connection: HTTP 404"), "api_not_found"),
        # Not recognized: the fallback, and never the exception's own text
        (OSError("something else entirely"), "cannot_connect"),
        (Exception(""), "cannot_connect"),
    ],
)
def test_connection_failure_gives_a_known_code(error, code):
    """Each connection error maps to a code the forms have a message for."""
    api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=False)

    with patch("custom_components.truenas_link.api.connect", side_effect=error):
        assert api.connection_test() == (False, code)

    assert code in ERROR_CODES


def test_login_exception_gives_a_known_code():
    """A login that raises has a code too, instead of an empty one."""
    api, connect = _api_with(FakeWebSocket(lambda request: {"id": request["id"]}))

    with connect:
        assert api.connection_test() == (False, "cannot_connect")


def test_query_failure_during_the_test_gives_a_known_code():
    """A broken connection never puts the exception's text in the error code."""
    ws = FakeWebSocket(_login())
    original = ws.recv
    replies = iter([original, None])

    def recv():
        reply = next(replies)
        if reply is None:
            raise OSError("connection reset by peer")
        return reply()

    ws.recv = recv
    api, connect = _api_with(ws)

    with connect:
        assert api.connection_test() == (False, "cannot_connect")
