"""Shared fixtures for TrueNAS integration tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from custom_components.truenas_link.api import TrueNASAPI


# ---------------------------
#   FakeWebSocket
# ---------------------------
class FakeWebSocket:
    """Stand-in for websockets' ClientConnection that replays canned replies.

    `responder` gets each decoded request and returns the JSON-RPC response
    object to send back, so tests can answer per method.
    """

    def __init__(self, responder: Callable[[dict[str, Any]], dict[str, Any]]):
        """Initialize the fake connection."""
        self._responder = responder
        self._pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def send(self, message: str) -> None:
        """Record a request and queue the response for recv()."""
        request = json.loads(message)
        self.requests.append(request)
        response = self._responder(request)
        self._pending.append(
            response if isinstance(response, str) else json.dumps(response)
        )

    def recv(self) -> str:
        """Return the response queued by the last send()."""
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
