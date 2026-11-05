"""Tests for a TrueNAS that keeps the connection up but does not answer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import asyncio
from datetime import UTC, datetime, timedelta
import json
import ssl
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.ssl import client_context, get_default_no_verify_context
import pytest
from websockets.asyncio.client import connect as real_connect
from websockets.sync.server import serve

from custom_components.truenas_link.api import (
    RESPONSE_TIMEOUT,
    TrueNASAPI,
    TrueNASConnectionError,
)
from custom_components.truenas_link.const import DOMAIN
from custom_components.truenas_link.entity import TrueNASEntity

from .sample_data import answers
from .conftest import NO_ANSWER, FakeWebSocket, SyncAPI, async_add_entry

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
    return SyncAPI(api), patch(
        "custom_components.truenas_link.api.connect",
        new=AsyncMock(side_effect=list(sockets)),
    )


def test_timeout_is_above_the_longest_call_truenas_makes_wait_for():
    """service.start and friends can take TrueNAS' default of 120 seconds."""
    assert RESPONSE_TIMEOUT > 120


def test_query_without_answer_closes_the_connection(connected_api):
    """query() returns None, leaves nothing open, and gives a known error code."""
    api, ws = connected_api(_answers)

    assert api.query("query.hang") is None

    assert ws.closed
    assert not api.connected()
    assert api.error == "cannot_connect"
    assert not api.real.lock.locked()


def test_call_without_answer_may_have_reached_truenas(connected_api):
    """call() raises, and says that the request went out."""
    api, ws = connected_api(_answers)

    with pytest.raises(TrueNASConnectionError) as err:
        api.call("query.hang")

    assert err.value.request_sent
    assert isinstance(err.value.__cause__, TimeoutError)
    assert ws.closed
    assert not api.connected()
    assert not api.real.lock.locked()


def test_login_without_answer_closes_the_connection():
    """A login that gets no answer is not a wrong key, so no reauthentication."""
    ws = FakeWebSocket(lambda _request: NO_ANSWER)
    api, connect = _api_with(ws)

    with connect:
        assert api.connect() is False

    assert ws.closed
    assert not api.connected()
    assert api.error == "cannot_connect"
    assert not api.real.lock.locked()


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
        coordinator = entry.runtime_data
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
        coordinator = entry.runtime_data
        await coordinator.api.disconnect()
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
def _real_server(
    *hang: str, results: dict | None = None
) -> Iterator[tuple[TrueNASAPI, list]]:
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
                    answer = request["params"][0] == "api-key"
                elif results is not None:
                    answer = results.get(request["method"], [])
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

        server.shutdown()
        thread.join(5)


def test_real_server_that_answers_pings_but_not_the_query():
    """The call times out with the lock free, and the next connection works."""

    async def scenario(api, handlers):
        assert await api.connect()
        assert await api.query("system.info") == "system.info"

        start = time.monotonic()
        with pytest.raises(TrueNASConnectionError) as err:
            await api.call("query.hang")

        assert isinstance(err.value.__cause__, TimeoutError)
        assert err.value.request_sent
        # Closing does not take websockets' close timeout of 10 seconds
        assert SHORT_TIMEOUT <= time.monotonic() - start < 5
        assert not api.connected()
        assert not api.lock.locked()

        # What the next poll does
        assert await api.connect()
        assert await api.query("system.info") == "system.info"
        assert len(handlers) == 2
        await api.disconnect()

    with _real_server("query.hang") as (api, handlers):
        asyncio.run(scenario(api, handlers))


def test_real_server_login_without_answer():
    """A login that gets no answer times out too."""

    async def scenario(api):
        assert await api.connect() is False

        assert api.error == "cannot_connect"
        assert not api.connected()
        assert not api.lock.locked()

    with _real_server("auth.login_with_api_key") as (api, _):
        asyncio.run(scenario(api))


def test_real_server_late_answer_is_not_read_by_the_next_query():
    """The answer that arrives after the timeout does not reach the next query."""

    async def scenario(api, handlers):
        assert await api.connect()
        assert await api.query("query.late") is None

        assert await api.call("system.info") == "system.info"
        await asyncio.sleep(SHORT_TIMEOUT * 2)
        assert await api.call("pool.query") == "pool.query"
        assert len(handlers) == 2
        await api.disconnect()

    with _real_server() as (api, handlers):
        asyncio.run(scenario(api, handlers))


def test_cancelled_call_closes_the_connection():
    """An automation restarting cancels the call. Its answer must not reach the next."""

    async def scenario(api, handlers):
        assert await api.connect()
        task = asyncio.create_task(api.call("query.late"))
        await asyncio.sleep(SHORT_TIMEOUT / 3)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert not api.connected()
        assert not api.lock.locked()
        assert await api.call("system.info") == "system.info"
        assert len(handlers) == 2
        await api.disconnect()

    with _real_server() as (api, handlers):
        asyncio.run(scenario(api, handlers))


def _extra_tasks(before):
    """Return the tasks that started after `before`, other than this one."""
    return asyncio.all_tasks() - before - {asyncio.current_task()}


@pytest.mark.parametrize("key", ["api-key", "wrong-key"], ids=["accepted", "rejected"])
def test_no_task_or_connection_is_left_behind(key):
    """A rejected login, a connection test and a disconnect leave nothing running."""

    async def scenario(api, handlers):
        api._api_key = key
        before = asyncio.all_tasks()

        for _ in range(5):
            await api.connection_test()
            await asyncio.sleep(0)

        await asyncio.sleep(0.05)
        assert not _extra_tasks(before)
        assert len(handlers) == 5
        for websocket in handlers:
            assert websocket.protocol.state.name in ("CLOSING", "CLOSED")

    with _real_server() as (api, handlers):
        asyncio.run(scenario(api, handlers))


def _open_connections(handlers):
    """Return how many connections the server still has open."""
    return sum(websocket.protocol.state.name == "OPEN" for websocket in handlers)


def _connection_tasks():
    """Return the tasks that real client connections keep running."""
    return [
        task
        for task in asyncio.all_tasks()
        if "Connection." in task.get_coro().__qualname__
        and "ServerConnection" not in task.get_coro().__qualname__
    ]


async def _settled(hass):
    """Let closing connections finish, on both sides."""
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)


def test_setup_failure_unload_and_reload_leave_nothing_behind(run_in_hass):
    """On a real core, through a real connection: each path closes what it opened."""

    with _real_server(results=answers("25.10")) as (api, handlers):

        def connect(_url, **kwargs):
            kwargs.pop("ssl", None)
            return real_connect(api._url, **kwargs)

        async def scenario(hass, server):
            with patch("custom_components.truenas_link.api.connect", connect):
                # The form's connection test, then the entry's own connection
                entry = await async_add_entry(hass, api_key="api-key")
                await _settled(hass)
                assert _open_connections(handlers) == 1
                assert len(handlers) == 2
                assert len(_connection_tasks()) > 0

                # Reload: the old connection goes, and there is one again
                await hass.config_entries.async_reload(entry.entry_id)
                await _settled(hass)
                assert _open_connections(handlers) == 1

                # Unload
                await hass.config_entries.async_unload(entry.entry_id)
                await _settled(hass)
                assert _open_connections(handlers) == 0
                assert not _connection_tasks()

                # A setup that fails, because the key was revoked
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "api_key": "wrong"}
                )
                await hass.config_entries.async_setup(entry.entry_id)
                await _settled(hass)
                assert entry.state is ConfigEntryState.SETUP_ERROR
                assert _open_connections(handlers) == 0
                assert not _connection_tasks()

        run_in_hass(scenario)


def test_stopping_home_assistant_closes_the_connection(run_in_hass):
    """Entries stay loaded at shutdown, so the connection needs its own close."""

    async def scenario(hass, server):
        await async_add_entry(hass)
        assert server.open_sockets == 1

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()

        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_nothing_runs_in_an_executor(run_in_hass):
    """The client is asynchronous, so polling needs no thread of its own."""

    async def scenario(hass, server):
        server.results = answers("27.0")
        entry = await async_add_entry(hass)

        with patch.object(hass, "async_add_executor_job", side_effect=AssertionError):
            await entry.runtime_data.async_refresh()
            await hass.async_block_till_done()

        assert entry.runtime_data.last_update_success

    run_in_hass(scenario)


def _tls_server(tmp_path):
    """Return a server with a self-signed certificate, as TrueNAS has by default."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "server.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        + certificate.public_bytes(serialization.Encoding.PEM)
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(path)

    def handler(websocket):
        for message in websocket:
            request = json.loads(message)
            websocket.send(json.dumps({"id": request["id"], "result": True}))

    return serve(handler, "127.0.0.1", 0, ssl=context)


@pytest.mark.parametrize(
    ("verify_ssl", "expected"),
    [(False, (True, "")), (True, (False, "certificate_verify_failed"))],
    ids=["verification off", "verification on"],
)
def test_real_tls_server_with_a_self_signed_certificate(tmp_path, verify_ssl, expected):
    """Home Assistant's contexts reach the connection, with the same error code."""
    with _tls_server(tmp_path) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.socket.getsockname()[1]
        api = TrueNASAPI(f"127.0.0.1:{port}", "api-key", verify_ssl=verify_ssl)

        assert asyncio.run(api.connection_test()) == expected
        assert not api.connected()

        server.shutdown()
        thread.join(5)


def test_getting_the_ssl_context_does_not_touch_the_disk():
    """Creating the client runs on the event loop, so it must not load certificates."""
    with patch("ssl.SSLContext.load_verify_locations", side_effect=AssertionError):
        assert (
            TrueNASAPI("nas", "key", verify_ssl=True)._ssl_context is client_context()
        )
        assert (
            TrueNASAPI("nas", "key", verify_ssl=False)._ssl_context
            is get_default_no_verify_context()
        )
