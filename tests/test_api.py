"""Tests for TrueNASAPI: JSON-RPC handling of query() and the SSL context."""

from __future__ import annotations

import logging

import json
from pathlib import Path
import errno
import ssl
from unittest.mock import AsyncMock, patch

from homeassistant.util.ssl import client_context, get_default_no_verify_context
import pytest

from custom_components.truenas_link.api import (
    TrueNASAPI,
    TrueNASConnectionError,
    TrueNASMalformedResponseError,
    TrueNASRequestError,
)

from .conftest import FakeWebSocket, SyncAPI

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
    return SyncAPI(api), patch(
        "custom_components.truenas_link.api.connect",
        new=AsyncMock(side_effect=list(sockets)),
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
    ws.recv = lambda: (_ for _ in ()).throw(EOFError("closed"))

    with pytest.raises(TrueNASConnectionError) as err:
        api.call("system.reboot", ["reason"])

    assert err.value.request_sent
    assert not api.connected()
    assert ws.closed


def test_query_still_returns_none_on_every_failure(connected_api):
    """Polling keeps its behavior: query() never raises."""
    api, ws = connected_api(_reply(result=None))
    ws.recv = lambda: (_ for _ in ()).throw(EOFError("closed"))

    assert api.query("system.info") is None
    assert not api.connected()


def test_query_does_not_reconnect(connected_api):
    """Only the start of a poll connects: see the test on a lost connection."""
    api, ws = connected_api(_reply(result=[]))
    api.disconnect()

    with patch("custom_components.truenas_link.api.connect") as connect:
        assert api.query("pool.query") is None

    connect.assert_not_called()
    assert len(ws.requests) == 0
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
        # What asyncio raises, for what cannot be made to happen on a local socket.
        # tests/test_connection_errors.py gets the others from real connections.
        (
            OSError(errno.EHOSTUNREACH, "Connect call failed ('10.0.0.1', 443)"),
            "host_unreachable",
        ),
        (
            OSError(errno.ENETUNREACH, "Connect call failed ('10.0.0.1', 443)"),
            "host_unreachable",
        ),
        (
            OSError(errno.ETIMEDOUT, "Connect call failed ('10.0.0.1', 443)"),
            "handshake_timeout",
        ),
        (
            OSError(
                "Multiple exceptions: [Errno 101] Connect call failed ('::1', 443), "
                "[Errno 111] Connect call failed ('10.0.0.1', 443)"
            ),
            "connection_refused",
        ),
        (
            OSError(
                "Multiple exceptions: [Errno 110] Connect call failed ('::1', 443), "
                "[Errno 113] Connect call failed ('10.0.0.1', 443)"
            ),
            "host_unreachable",
        ),
        (
            OSError(
                "Multiple exceptions: [Errno 104] Connect call failed ('::1', 443), "
                "[Errno 110] Connect call failed ('10.0.0.1', 443)"
            ),
            "handshake_timeout",
        ),
        # Numbers in an address or a text are not errors
        (
            ConnectionRefusedError(111, "Connect call failed ('::1', 8404)"),
            "connection_refused",
        ),
        (OSError("Multiple exceptions: 404, [Errno 1] no"), "cannot_connect"),
        (
            OSError(errno.EPERM, "Connect call failed ('10.0.0.1', 404)"),
            "cannot_connect",
        ),
        (OSError("something with 404 in it"), "cannot_connect"),
        (Exception("server rejected WebSocket connection: HTTP 404"), "cannot_connect"),
        # Not recognized: the fallback, and never the exception's own text
        (OSError("something else entirely"), "cannot_connect"),
        (Exception(""), "cannot_connect"),
    ],
)
def test_connection_failure_gives_a_known_code(error, code):
    """Each connection error maps to a code the forms have a message for."""
    api = SyncAPI(TrueNASAPI("truenas.lan", "api-key", verify_ssl=False))

    with patch(
        "custom_components.truenas_link.api.connect", new=AsyncMock(side_effect=error)
    ):
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


def _errors(caplog):
    """Return the messages logged as errors."""
    return [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]


def test_repeated_rpc_error_is_logged_once(connected_api, caplog):
    """A method that keeps failing the same way does not fill the log."""
    api, _ = connected_api(_reply(error={"data": {"reason": "[EBUSY] busy"}}))

    with caplog.at_level(logging.INFO, logger="custom_components.truenas_link.api"):
        for _ in range(3):
            assert api.query("pool.query") is None

    assert len(_errors(caplog)) == 1
    assert "[EBUSY] busy" in caplog.text


def test_other_rpc_error_of_the_same_method_is_logged(connected_api, caplog):
    """A different failure says something new."""
    replies = iter(["[EBUSY] busy", "[EBUSY] busy", "[EIO] broken", "[EIO] broken"])
    api, _ = connected_api(
        lambda request: {"id": 0, "error": {"data": {"reason": next(replies)}}}
    )

    with caplog.at_level(logging.INFO, logger="custom_components.truenas_link.api"):
        for _ in range(4):
            api.query("pool.query")

    assert len(_errors(caplog)) == 2
    assert "[EIO] broken" in _errors(caplog)[1]


def test_each_method_logs_its_own_error(connected_api, caplog):
    """One method's failure does not hide another's."""
    api, _ = connected_api(_reply(error={"data": {"reason": "[EBUSY] busy"}}))

    with caplog.at_level(logging.INFO, logger="custom_components.truenas_link.api"):
        api.query("pool.query")
        api.query("disk.query")

    assert len(_errors(caplog)) == 2


def test_method_that_works_again_says_so_and_can_fail_again(connected_api, caplog):
    """Recovery is logged once, and a later failure counts as new."""
    replies = iter(
        [
            {"id": 0, "error": {"data": {"reason": "[EBUSY] busy"}}},
            {"id": 0, "result": []},
            {"id": 0, "result": []},
            {"id": 0, "error": {"data": {"reason": "[EBUSY] busy"}}},
        ]
    )
    api, _ = connected_api(lambda request: next(replies))

    with caplog.at_level(logging.INFO, logger="custom_components.truenas_link.api"):
        for _ in range(4):
            api.query("pool.query")

    assert len(_errors(caplog)) == 2
    assert caplog.text.count("works again") == 1


def test_malformed_response_is_logged_once_and_keeps_its_code(connected_api, caplog):
    """The error code stays on every poll, even when nothing new is logged."""
    api, _ = connected_api(_reply(include_result=False))

    with caplog.at_level(logging.INFO, logger="custom_components.truenas_link.api"):
        api.query("system.info")
        api.query("system.info")

    assert len(_errors(caplog)) == 1
    assert api.error == "malformed_result"
