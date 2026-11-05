"""Tests for a TrueNAS that keeps the connection up but does not answer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.exceptions import HomeAssistantError
import pytest
from websockets.sync.client import connect as real_connect
from websockets.sync.server import serve

from custom_components.truenas_link.api import (
    RESPONSE_TIMEOUT,
    TrueNASAPI,
    TrueNASConnectionError,
)
from custom_components.truenas_link.const import DOMAIN
from custom_components.truenas_link.entity import TrueNASEntity

from .conftest import NO_ANSWER, FakeWebSocket, async_add_entry

SHORT_TIMEOUT = 0.3


def _answers(request):
    """Answer a login with true, query.hang never, and others with their name."""
    if request["method"] == "auth.login_with_api_key":
        return {"id": request["id"], "result": True}
    if request["method"] == "query.hang":
        return NO_ANSWER
    return {"id": request["id"], "result": request["method"]}


def _api_with(*sockets):
    """Return an API and the patch that makes connect() hand out `sockets`."""
    api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=False)
    return api, patch(
        "custom_components.truenas_link.api.connect", side_effect=list(sockets)
    )


def test_timeout_is_above_the_longest_call_truenas_makes_wait_for():
    """service.start and friends can take TrueNAS' default of 120 seconds."""
    assert RESPONSE_TIMEOUT > 120


def test_every_wait_for_an_answer_has_the_timeout():
    """Both the login and a query use the timeout."""
    ws = FakeWebSocket(_answers)
    api, connect = _api_with(ws)

    with connect:
        assert api.connect()

    assert api.query("system.info") == "system.info"
    assert api.call("system.info") == "system.info"
    assert ws.recv_timeouts == [RESPONSE_TIMEOUT] * 3


def test_query_without_answer_closes_the_connection(connected_api):
    """query() returns None, leaves nothing open, and gives a known error code."""
    api, ws = connected_api(_answers)

    assert api.query("query.hang") is None

    assert ws.closed
    assert not api.connected()
    assert api.error == "cannot_connect"
    assert api.lock.acquire(blocking=False)


def test_call_without_answer_may_have_reached_truenas(connected_api):
    """call() raises, and says that the request went out."""
    api, ws = connected_api(_answers)

    with pytest.raises(TrueNASConnectionError) as err:
        api.call("query.hang")

    assert err.value.request_sent
    assert isinstance(err.value.__cause__, TimeoutError)
    assert ws.closed
    assert not api.connected()
    assert api.lock.acquire(blocking=False)


def test_login_without_answer_closes_the_connection():
    """A login that gets no answer is not a wrong key, so no reauthentication."""
    ws = FakeWebSocket(lambda _request: NO_ANSWER)
    api, connect = _api_with(ws)

    with connect:
        assert api.connect() is False

    assert ws.closed
    assert not api.connected()
    assert api.error == "cannot_connect"
    assert api.lock.acquire(blocking=False)


def test_connection_test_reports_a_query_without_answer():
    """The forms get a code they have a message for."""
    ws = FakeWebSocket(
        lambda request: (
            NO_ANSWER
            if request["method"] == "system.info"
            else {"id": request["id"], "result": True}
        )
    )
    api, connect = _api_with(ws)

    with connect:
        assert api.connection_test() == (False, "cannot_connect")

    assert ws.closed


def test_late_answer_stays_on_the_closed_connection():
    """An answer that is late is never taken for the next request's answer."""
    first = FakeWebSocket(_answers)
    second = FakeWebSocket(_answers)
    api, connect = _api_with(first, second)

    with connect:
        assert api.connect()
        assert api.query("query.hang") is None
        # What a real connection would hold when the late answer arrives
        first._pending.append(json.dumps({"id": 0, "result": "late"}))

        assert api.call("system.info") == "system.info"

    assert first.closed
    assert not second.closed


def test_action_without_answer_is_an_error_unless_it_stops_truenas(run_in_hass):
    """A timeout after sending counts as success only for reboot and shutdown."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = hass.data[DOMAIN][entry.entry_id]
        entity = SimpleNamespace(hass=hass, coordinator=coordinator)
        server.unanswered = {"cronjob.update", "system.reboot"}

        with pytest.raises(HomeAssistantError) as err:
            await TrueNASEntity._async_call(entity, "cronjob.update", [1, {}])
        assert err.value.translation_key == "action_unreachable"
        assert server.open_sockets == 0

        uptime = next(
            state.entity_id
            for state in hass.states.async_all()
            if "uptime" in state.entity_id
        )
        await hass.services.async_call(
            DOMAIN, "system_reboot", {"entity_id": uptime}, blocking=True
        )
        assert server.sockets[-1].requests[-1]["method"] == "system.reboot"
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_login_without_answer_does_not_ask_for_a_new_key(run_in_hass):
    """The next poll fails, without starting a reauthentication."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.api.disconnect()
        server.unanswered = {"auth.login_with_api_key"}

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator.last_update_success
        assert not list(entry.async_get_active_flows(hass, {"reauth"}))
        assert server.open_sockets == 0

    run_in_hass(scenario)


# ---------------------------
#   Real websocket server
# ---------------------------
@contextmanager
def _real_server(*hang: str) -> Iterator[tuple[TrueNASAPI, list]]:
    """Run a server that answers pings, but not the requests for `hang` methods.

    websockets answers pings by itself, whatever the handler is doing.
    query.late gets its answer after the client has stopped waiting.
    """
    handlers = []

    def handler(websocket):
        handlers.append(websocket)
        try:
            for message in websocket:
                request = json.loads(message)
                if request["method"] in hang:
                    continue
                if request["method"] == "query.late":
                    time.sleep(SHORT_TIMEOUT * 2)
                    answer = "late"
                elif request["method"] == "auth.login_with_api_key":
                    answer = True
                else:
                    answer = request["method"]
                websocket.send(json.dumps({"id": request["id"], "result": answer}))
        except Exception:  # The client closed while a late answer was on its way
            pass

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.socket.getsockname()[1]
        api = TrueNASAPI(f"127.0.0.1:{port}", "api-key", verify_ssl=False)
        api._url = f"ws://127.0.0.1:{port}/api/current"
        api._ssl_context = None

        def connect(url, **kwargs):
            # Pings well within the timeout: a server that did not answer them
            # would end in a closed connection, not in a timeout
            kwargs.update(ping_interval=0.05, ping_timeout=SHORT_TIMEOUT / 2)
            return real_connect(url, **kwargs)

        with (
            patch("custom_components.truenas_link.api.RESPONSE_TIMEOUT", SHORT_TIMEOUT),
            patch("custom_components.truenas_link.api.connect", connect),
        ):
            yield api, handlers

        api.disconnect()
        server.shutdown()
        thread.join(5)


def test_real_server_that_answers_pings_but_not_the_query():
    """The call times out with the lock free, and the next connection works."""
    with _real_server("query.hang") as (api, handlers):
        assert api.connect()
        assert api.query("system.info") == "system.info"

        start = time.monotonic()
        with pytest.raises(TrueNASConnectionError) as err:
            api.call("query.hang")

        assert isinstance(err.value.__cause__, TimeoutError)
        assert err.value.request_sent
        # Closing does not take websockets' close timeout of 10 seconds
        assert SHORT_TIMEOUT <= time.monotonic() - start < 5
        assert not api.connected()
        assert api.lock.acquire(blocking=False)
        api.lock.release()

        # What the next poll does
        assert api.connect()
        assert api.query("system.info") == "system.info"
        assert len(handlers) == 2


def test_real_server_login_without_answer():
    """A login that gets no answer times out too."""
    with _real_server("auth.login_with_api_key") as (api, _):
        assert api.connect() is False

        assert api.error == "cannot_connect"
        assert not api.connected()
        assert api.lock.acquire(blocking=False)


def test_real_server_late_answer_is_not_read_by_the_next_query():
    """The answer that arrives after the timeout does not reach the next query."""
    with _real_server() as (api, handlers):
        assert api.connect()
        assert api.query("query.late") is None

        assert api.call("system.info") == "system.info"
        time.sleep(SHORT_TIMEOUT * 2)
        assert api.call("pool.query") == "pool.query"
        assert len(handlers) == 2
