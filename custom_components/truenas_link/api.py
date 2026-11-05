"""TrueNAS API."""

import asyncio
from logging import DEBUG, ERROR, WARNING, getLogger
from typing import Any

import json
from homeassistant.util.ssl import client_context, get_default_no_verify_context
from websockets.asyncio.client import ClientConnection, connect

from .helper import redact_secrets

_LOGGER = getLogger(__name__)


# Text in a connection error, and the error code it stands for. Codes are keys
# of "config.error" in strings.json. The first match wins.
CONNECT_ERRORS = (
    ("CERTIFICATE_VERIFY_FAILED", "certificate_verify_failed"),
    ("The plain HTTP request was sent to HTTPS port", "http_used"),
    ("TLSV1_UNRECOGNIZED_NAME", "tlsv1_not_supported"),
    ("No WebSocket UPGRADE", "websocket_not_supported"),
    ("No address associated with hostname", "unknown_hostname"),
    ("Connection refused", "connection_refused"),
    ("No route to host", "invalid_hostname"),
    ("Name or service not known", "invalid_hostname"),
    ("404", "api_not_found"),
)
ERROR_CANNOT_CONNECT = "cannot_connect"

# Seconds to wait for the answer to a request. The keepalive pings only show that
# the connection is up, not that TrueNAS will answer. Job methods answer at once,
# but service.start, stop, restart and reload answer when they are done, and
# TrueNAS gives those up to 120 seconds by default, so this has to be above that.
# After a timeout or a cancellation the connection must be closed: every request has
# id 0, so a late answer would otherwise be read as the answer to the next request.
RESPONSE_TIMEOUT = 150


# ---------------------------
#   TrueNASError
# ---------------------------
class TrueNASError(Exception):
    """A call to TrueNAS did not succeed."""


class TrueNASConnectionError(TrueNASError):
    """TrueNAS could not be reached, or the connection broke during a call.

    If request_sent is set, TrueNAS may have received and acted on the request.
    """

    def __init__(self, reason: str, request_sent: bool = False) -> None:
        """Initialize the error."""
        super().__init__(reason)
        self.request_sent = request_sent


class TrueNASRequestError(TrueNASError):
    """TrueNAS answered a call with an error."""


class TrueNASMalformedResponseError(TrueNASRequestError):
    """TrueNAS answered a call with neither a result nor an error."""


# ---------------------------
#   TrueNASAPI
# ---------------------------
class TrueNASAPI(object):
    """Handle all communication with TrueNAS."""

    def __init__(
        self,
        host: str,
        api_key: str,
        verify_ssl: bool = True,
    ) -> None:
        """Initialize the TrueNAS API."""
        self._host = host
        self._api_key = api_key
        self._ssl_verify = verify_ssl
        self._url = f"wss://{self._host}/api/current"
        # Home Assistant's shared contexts, created when it starts, so getting one
        # does not block. They are shared, so never modify them.
        self._ssl_context = (
            client_context() if verify_ssl else get_default_no_verify_context()
        )

        self.lock = asyncio.Lock()
        self._ws: ClientConnection | None = None
        self._connected = False
        self._error = ""
        self._error_logged = False
        # What each method last failed with, to log a repeated failure once
        self._failed_methods: dict[str, str] = {}
        # Set by connection_test
        self.system_id: str | None = None
        self.hostname: str | None = None

    # ---------------------------
    #   connect
    # ---------------------------
    async def connect(self) -> bool:
        """Return connected boolean."""
        async with self.lock:
            # Each connection has tasks of its own, so never lose track of one by
            # overwriting it
            await self.disconnect()
            self._error = ""
            try:
                self._ws = await connect(
                    self._url,
                    ssl=self._ssl_context,
                    max_size=16777216,
                    ping_interval=20,
                )
            except Exception as e:
                self._error = self._connect_error_code(e)

                if not self._error_logged:
                    _LOGGER.error("TrueNAS %s failed to connect (%s)", self._host, e)

                self._error_logged = True
                return False

            try:
                payload = {
                    "method": "auth.login_with_api_key",
                    "jsonrpc": "2.0",
                    "id": 0,
                    "params": [self._api_key],
                }
                await self._ws.send(json.dumps(payload))
                message = await self._receive()
                data = json.loads(message)
                self._connected = data["result"]
                if not self._connected:
                    self._error = "invalid_key"
                    await self.disconnect()

            except asyncio.CancelledError:
                self._abort()
                raise
            except Exception as e:
                if not self._error_logged:
                    _LOGGER.error("TrueNAS %s failed to login (%s)", self._host, e)

                self._error = ERROR_CANNOT_CONNECT
                await self.disconnect()
                self._error_logged = True
                return False

            self._error_logged = False
            return self._connected

    # ---------------------------
    #   _connect_error_code
    # ---------------------------
    @staticmethod
    def _connect_error_code(error: Exception) -> str:
        """Return the error code for an exception raised while connecting."""
        # Its text depends on the websockets release and the step that timed out
        if isinstance(error, TimeoutError):
            return "handshake_timeout"

        text = str(error)
        for marker, code in CONNECT_ERRORS:
            if marker in text:
                return code

        return ERROR_CANNOT_CONNECT

    # ---------------------------
    #   disconnect
    # ---------------------------
    async def disconnect(self) -> bool:
        """Close the connection, if any, and return connected boolean.

        It does not take the lock, so an unload does not have to wait for a request
        that hangs: closing is what ends it.
        """
        ws, self._ws = self._ws, None
        self._connected = False
        if ws:
            try:
                await ws.close()
            except Exception as e:
                # The connection is gone either way
                _LOGGER.debug("TrueNAS %s failed to disconnect (%s)", self._host, e)

        return self._connected

    # ---------------------------
    #   _abort
    # ---------------------------
    def _abort(self) -> None:
        """Drop the connection at once, for a cancelled task that cannot wait."""
        ws, self._ws = self._ws, None
        self._connected = False
        if ws:
            ws.transport.abort()

    # ---------------------------
    #   _receive
    # ---------------------------
    async def _receive(self) -> str | bytes:
        """Return the next message, or raise TimeoutError if none comes in time."""
        if self._ws is None:
            raise ConnectionError("not connected")

        async with asyncio.timeout(RESPONSE_TIMEOUT):
            return await self._ws.recv()

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected boolean."""
        return self._connected

    # ---------------------------
    #   connection_test
    # ---------------------------
    async def connection_test(self) -> tuple[bool, str]:
        """Return whether a connection and a query work, and the error code."""
        try:
            await self.connect()
            if self.connected():
                self.system_id = await self.read_system_id()
                # Last, because each query replaces the error code
                info = await self.query("system.info")
                hostname = info.get("hostname") if isinstance(info, dict) else None
                self.hostname = hostname if isinstance(hostname, str) else None

            return self._connected, self._error
        finally:
            await self.disconnect()

    # ---------------------------
    #   read_system_id
    # ---------------------------
    async def read_system_id(self) -> str | None:
        """Return the UUID that identifies this TrueNAS system, None if unknown.

        system.global.id is a value of the system's configuration, so it stays the
        same when the address changes, and it is not tied to the hardware, unlike
        a serial number, which can be empty or repeated on virtual machines. It
        needs READONLY_ADMIN, and both controllers of an HA system share it.
        """
        system_id = await self.query("system.global.id")
        return system_id if isinstance(system_id, str) and system_id else None

    # ---------------------------
    #   query
    # ---------------------------
    async def query(self, service: str, params: Any = {}) -> Any:
        """Retrieve data from TrueNAS, returning None if that fails.

        A successful call can also return None, so code that needs to know
        whether a call worked uses call() instead.

        It never reconnects: a poll connects once, at its start. A query that
        reconnected after the connection was lost would end the poll connected,
        and hide that it failed. The poll has to fail so entities show it.
        """
        if not self.connected():
            return None

        async with self.lock:
            self._error = ""
            try:
                result = await self._exchange(service, params)
            except TrueNASMalformedResponseError as e:
                self._log_failed_method(service, str(e))
                self._error = "malformed_result"
            except TrueNASRequestError as e:
                self._log_failed_method(service, str(e))
            except TrueNASConnectionError as e:
                self._log_failed_method(service, str(e), WARNING)
                await self.disconnect()
                # The reason is in the log. This is a code the forms can show.
                self._error = ERROR_CANNOT_CONNECT
            else:
                if self._failed_methods.pop(service, None) is not None:
                    _LOGGER.info(
                        "TrueNAS %s query (%s) works again", self._host, service
                    )

                return result

            return None

    # ---------------------------
    #   _log_failed_method
    # ---------------------------
    def _log_failed_method(self, service: str, reason: str, level: int = ERROR) -> None:
        """Log why a polled method failed, unless it was already logged.

        A method that TrueNAS refuses or leaves without an answer fails on every
        poll, so this would fill the log. A failure with another reason is logged
        again, and query() logs when the method works again.
        """
        if self._failed_methods.get(service) == reason:
            _LOGGER.debug(
                "TrueNAS %s query (%s) error: %s", self._host, service, reason
            )
            return

        self._failed_methods[service] = reason
        _LOGGER.log(
            level, "TrueNAS %s query (%s) error: %s", self._host, service, reason
        )

    # ---------------------------
    #   call
    # ---------------------------
    async def call(self, service: str, params: Any = {}) -> Any:
        """Return the result of a call, raising a TrueNASError if it fails."""
        if not self.connected():
            await self.connect()

        if not self.connected():
            raise TrueNASConnectionError(self._error or ERROR_CANNOT_CONNECT)

        async with self.lock:
            try:
                return await self._exchange(service, params)
            except TrueNASConnectionError:
                await self.disconnect()
                raise

    # ---------------------------
    #   _exchange
    # ---------------------------
    async def _exchange(self, service: str, params: Any) -> Any:
        """Send a request and return the result, raising a TrueNASError if it fails."""
        debug = _LOGGER.isEnabledFor(DEBUG)
        if debug:
            _LOGGER.debug(
                "TrueNAS %s query: %s, %s", self._host, service, redact_secrets(params)
            )

        payload = {
            "method": service,
            "jsonrpc": "2.0",
            "id": 0,
            "params": [],
        }
        if params != {}:
            if type(params) is not list:
                params = [params]
            payload["params"] = params

        try:
            if self._ws is None:
                raise ConnectionError("not connected")

            await self._ws.send(json.dumps(payload))
        except asyncio.CancelledError:
            self._abort()
            raise
        except Exception as e:
            raise TrueNASConnectionError(str(e)) from e

        try:
            message = await self._receive()
            if not isinstance(message, str):
                raise TypeError("TrueNAS sent binary data")

            is_object = message.startswith("{")
            response: Any = json.loads(message) if is_object else None
        except asyncio.CancelledError:
            self._abort()
            raise
        except TimeoutError as e:
            reason = f"no answer in {RESPONSE_TIMEOUT} seconds"
            raise TrueNASConnectionError(reason, request_sent=True) from e
        except Exception as e:
            raise TrueNASConnectionError(str(e), request_sent=True) from e

        if not is_object:
            data = message
        # JSON-RPC 2.0: a failed call carries a top-level "error" object and no
        # "result". Keys inside "result" belong to the method's own return
        # value (update.status, for example, always returns "error": null) and
        # must not be read as a protocol error.
        elif response.get("error") is not None:
            raise TrueNASRequestError(self._rpc_error_reason(response["error"]))
        elif "result" not in response:
            raise TrueNASMalformedResponseError("returned neither result nor error")
        else:
            data = response["result"]

        if debug:
            # Text that is not JSON cannot be redacted key by key
            logged = (
                redact_secrets(data) if is_object else f"<{len(message)} characters>"
            )
            _LOGGER.debug(
                "TrueNAS %s query (%s) response: %s", self._host, service, logged
            )

        return data

    # ---------------------------
    #   _rpc_error_reason
    # ---------------------------
    @staticmethod
    def _rpc_error_reason(error: Any) -> str:
        """Return a JSON-RPC error's text, preferring TrueNAS' detailed reason."""
        reason = None
        if isinstance(error, dict):
            details = error.get("data")
            if isinstance(details, dict):
                reason = details.get("reason")

            if not reason:
                reason = error.get("message")

        return str(reason or redact_secrets(error))

    @property
    def error(self) -> str:
        """Return error."""
        return self._error
