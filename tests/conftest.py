"""Shared fixtures for TrueNAS integration tests."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

from homeassistant import config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    category_registry,
    device_registry,
    entity_registry,
    floor_registry,
    frame,
    issue_registry,
    label_registry,
    translation,
)
import pytest

import custom_components
from custom_components.truenas_link.api import TrueNASAPI
from custom_components.truenas_link.const import DOMAIN

# A responder returns this for a request that TrueNAS never answers
NO_ANSWER = object()


# ---------------------------
#   FakeWebSocket
# ---------------------------
class FakeWebSocket:
    """Stand-in for websockets' ClientConnection that replays canned replies.

    `responder` gets each decoded request and returns the JSON-RPC response
    object to send back, so tests can answer per method. With NO_ANSWER, recv()
    raises the TimeoutError of a real connection right away.
    """

    def __init__(self, responder: Callable[[dict[str, Any]], dict[str, Any]]):
        """Initialize the fake connection."""
        self._responder = responder
        self._pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.recv_timeouts: list[float | None] = []
        self.closed = False

    def send(self, message: str) -> None:
        """Record a request and queue the response for recv()."""
        if self.closed:
            raise ConnectionError("send on a closed connection")

        request = json.loads(message)
        self.requests.append(request)
        response = self._responder(request)
        if response is not NO_ANSWER:
            self._pending.append(
                response if isinstance(response, str) else json.dumps(response)
            )

    def recv(self, timeout: float | None = None) -> str:
        """Return the response queued by the last send()."""
        self.recv_timeouts.append(timeout)
        if not self._pending:
            raise TimeoutError(f"timed out in {timeout}s")

        return self._pending.pop(0)

    def close(self) -> None:
        """Mark the connection as closed."""
        self.closed = True


# ---------------------------
#   connected_api
# ---------------------------
@pytest.fixture
def connected_api() -> Callable[..., tuple[TrueNASAPI, FakeWebSocket]]:
    """Return a factory for a logged-in TrueNASAPI backed by a FakeWebSocket."""

    def _factory(responder):
        api = TrueNASAPI("truenas.lan", "api-key", verify_ssl=False)
        ws = FakeWebSocket(responder)
        api._ws = ws
        api._connected = True
        return api, ws

    return _factory


# ---------------------------
#   FakeTrueNAS
# ---------------------------
class FakeTrueNAS:
    """A TrueNAS that hands out a FakeWebSocket per connection.

    Tests change `valid_keys` to revoke a key, `results` to answer a method
    with something else than an empty list, `errors` to refuse a method, and
    `unanswered` to leave a method without an answer.
    """

    def __init__(self) -> None:
        """Initialize a system that accepts the key "good"."""
        self.valid_keys = {"good"}
        self.results: dict[str, Any] = {
            "system.global.id": "fake-system-id",
            "system.info": {
                "version": "25.10.1",
                "hostname": "nas",
                "uptime_seconds": 5,
                "system_serial": "serial",
                "system_product": "product",
                "system_manufacturer": "manufacturer",
                "physmem": 1,
            },
        }
        self.unanswered: set[str] = set()
        # Methods TrueNAS answers with an error, and its reason
        self.errors: dict[str, str] = {}
        self.sockets: list[FakeWebSocket] = []

    def _respond(self, request: dict[str, Any]) -> Any:
        """Answer one JSON-RPC request."""
        if request["method"] in self.unanswered:
            return NO_ANSWER

        if request["method"] in self.errors:
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"data": {"reason": self.errors[request["method"]]}},
            }

        if request["method"] == "auth.login_with_api_key":
            result = request["params"][0] in self.valid_keys
        else:
            result = self.results.get(request["method"], [])
            params = request["params"]
            options = params[1] if len(params) > 1 else None
            # The query options' select, for top-level fields only
            if isinstance(options, dict) and "select" in options:
                result = [
                    {k: v for k, v in item.items() if k in options["select"]}
                    for item in result
                ]

        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    def connect(self, *_args: Any, **_kwargs: Any) -> FakeWebSocket:
        """Stand in for websockets' connect()."""
        self.sockets.append(FakeWebSocket(self._respond))
        return self.sockets[-1]

    @property
    def open_sockets(self) -> int:
        """Return how many connections were not closed."""
        return sum(not socket.closed for socket in self.sockets)


async def _async_start_hass() -> HomeAssistant:
    """Return a real Home Assistant core that can load this integration."""
    hass = HomeAssistant(tempfile.mkdtemp())
    hass.config.skip_pip = True
    frame.async_setup(hass)
    loader.async_setup(hass)
    translation.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    device_registry.async_setup(hass)
    for registry in (
        area_registry,
        floor_registry,
        label_registry,
        category_registry,
        device_registry,
        entity_registry,
        issue_registry,
    ):
        await registry.async_load(hass)

    hass.data[loader.DATA_CUSTOM_COMPONENTS] = {
        DOMAIN: loader.Integration.resolve_from_root(hass, custom_components, DOMAIN)
    }
    return hass


# ---------------------------
#   run_in_hass
# ---------------------------
@pytest.fixture
def run_in_hass() -> Callable[[Callable[..., Awaitable[None]]], None]:
    """Return a runner for a scenario on a real core and a fake TrueNAS."""

    def _run(scenario: Callable[..., Awaitable[None]]) -> None:
        async def main() -> None:
            hass = await _async_start_hass()
            server = FakeTrueNAS()
            try:
                with patch(
                    "custom_components.truenas_link.api.connect", server.connect
                ):
                    await scenario(hass, server)
            finally:
                await hass.async_stop(force=True)

        asyncio.run(main())

    return _run


async def async_add_entry(hass: HomeAssistant, **overrides: Any):
    """Add an Administrator entry through the setup form and return it."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "TrueNAS",
            "host": "nas",
            "api_key": "good",
            "access_level": "admin",
            "verify_ssl": False,
            **overrides,
        },
    )
    await hass.async_block_till_done()
    # The entry this call added, if another one is already there
    return hass.config_entries.async_entries(DOMAIN)[-1]
