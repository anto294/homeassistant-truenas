"""TrueNAS API."""

import asyncio
import errno
import re
import socket
import ssl
from logging import DEBUG, getLogger
from typing import Any

import json
from aiohttp import (
    ClientConnectorDNSError,
    ClientConnectorError,
    ClientSession,
    ClientWebSocketResponse,
    WSMsgType,
    WSServerHandshakeError,
)

from .helper import redact_secrets

_LOGGER = getLogger(__name__)


# The errors of a connection, and the codes they stand for. Codes are keys of
# "config.error" in strings.json. These go by type and errno, because the text of an
# error holds the address, and a port such as 8404 is not a 404.
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_REFUSED = "connection_refused"
ERROR_UNREACHABLE = "host_unreachable"
ERROR_TIMEOUT = "handshake_timeout"
CONNECT_ERRNOS = {
    errno.ECONNREFUSED: ERROR_REFUSED,
    errno.EHOSTUNREACH: ERROR_UNREACHABLE,
    errno.ENETUNREACH: ERROR_UNREACHABLE,
    errno.ETIMEDOUT: ERROR_TIMEOUT,
}
# What says most about a host with several addresses: IPv6 being unreachable says
# little if IPv4 answered with a refusal.
AGGREGATE_ERROR_ORDER = (ERROR_REFUSED, ERROR_UNREACHABLE, ERROR_TIMEOUT)
# asyncio's error when all addresses of a host fail with different errors: an OSError
# without an errno, whose text is all that is left of the errors
MULTIPLE_ERRORS_PREFIX = "Multiple exceptions:"
ERRNO_IN_TEXT = re.compile(r"\[Errno (\d+)\]")

# Seconds to wait for the answer to a request. The keepalive pings only show that
# the connection is up, not that TrueNAS will answer. Job methods answer at once,
# but service.start, stop, restart and reload answer when they are done, and
# TrueNAS gives those up to 120 seconds by default, so this has to be above that.
# After a timeout or a cancellation the connection must be closed: every request has
# id 0, so a late answer would otherwise be read as the answer to the next request.
RESPONSE_TIMEOUT = 150
# Seconds to wait for a connection to open
CONNECT_TIMEOUT = 10
# Seconds between pings. A connection is lost when no pong comes in half of this.
HEARTBEAT = 40
# Bytes in one answer, which a system with many datasets can need
MAX_MESSAGE_SIZE = 16777216
URL_FORMAT = "wss://{host}/api/current"


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

    def __init__(self, session: ClientSession, host: str, api_key: str) -> None:
        """Initialize the TrueNAS API.

        The session decides whether certificates are verified. It belongs to Home
        Assistant, so this never closes it.
        """
        self._session = session
        self._host = host
        self._api_key = api_key
        self._url = URL_FORMAT.format(host=host)

        self.lock = asyncio.Lock()
        self._ws: ClientWebSocketResponse | None = None
        # Connections being closed in the background, kept so they are not lost
        self._closing: set[asyncio.Task[None]] = set()
        self._connected = False
        self._error = ""
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
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    self._ws = await self._session.ws_connect(
                        self._url,
                        heartbeat=HEARTBEAT,
                        max_msg_size=MAX_MESSAGE_SIZE,
                    )
            except Exception as e:
                self._error = self._connect_error_code(e)
                # The coordinator logs that TrueNAS went away, and that it is back,
                # and the forms show the code, so this is only for the details
                _LOGGER.debug("TrueNAS %s failed to connect (%s)", self._host, e)
                return False

            try:
                payload = {
                    "method": "auth.login_with_api_key",
                    "jsonrpc": "2.0",
                    "id": 0,
                    "params": [self._api_key],
                }
                await self._ws.send_str(json.dumps(payload))
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
                _LOGGER.debug("TrueNAS %s failed to login (%s)", self._host, e)
                self._error = ERROR_CANNOT_CONNECT
                await self.disconnect()
                return False

            return self._connected

    # ---------------------------
    #   _connect_error_code
    # ---------------------------
    @staticmethod
    def _connect_error_code(error: Exception) -> str:
        """Return the error code for an exception raised while connecting."""
        if isinstance(error, TimeoutError):
            return ERROR_TIMEOUT

        if isinstance(error, (ClientConnectorDNSError, socket.gaierror)):
            return "unknown_hostname"

        if isinstance(error, ClientConnectorError):
            # What failed, without the wrapping of aiohttp
            error = error.os_error

        if isinstance(error, ssl.SSLCertVerificationError):
            return "certificate_verify_failed"

        if isinstance(error, ssl.SSLError):
            if error.reason == "TLSV1_UNRECOGNIZED_NAME":
                return "tls_unrecognized_name"

            return ERROR_CANNOT_CONNECT

        if isinstance(error, WSServerHandshakeError):
            if error.status == 404:
                return "api_not_found"

            # Something answers at this address, but not with a websocket
            return "websocket_not_supported"

        if isinstance(error, OSError):
            if error.errno is not None:
                return CONNECT_ERRNOS.get(error.errno, ERROR_CANNOT_CONNECT)

            if str(error).startswith(MULTIPLE_ERRORS_PREFIX):
                numbers = ERRNO_IN_TEXT.findall(str(error))
                codes = {CONNECT_ERRNOS.get(int(number)) for number in numbers}
                for code in AGGREGATE_ERROR_ORDER:
                    if code in codes:
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
            await self._close(ws)

        return self._connected

    # ---------------------------
    #   _close
    # ---------------------------
    async def _close(self, ws: ClientWebSocketResponse) -> None:
        """Close a connection."""
        try:
            await ws.close()
        except Exception as e:
            # The connection is gone either way
            _LOGGER.debug("TrueNAS %s failed to disconnect (%s)", self._host, e)

    # ---------------------------
    #   _abort
    # ---------------------------
    def _abort(self) -> None:
        """Drop the connection now and close it in the background.

        A cancelled task cannot wait for the close. A late answer can't reach the next
        request either, as that one gets a new connection.
        """
        ws, self._ws = self._ws, None
        self._connected = False
        if ws:
            task = asyncio.create_task(self._close(ws))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    # ---------------------------
    #   _receive
    # ---------------------------
    async def _receive(self) -> str | bytes:
        """Return the next message, or raise TimeoutError if none comes in time."""
        if self._ws is None:
            raise ConnectionError("not connected")

        async with asyncio.timeout(RESPONSE_TIMEOUT):
            message = await self._ws.receive()

        if message.type in (WSMsgType.TEXT, WSMsgType.BINARY):
            data: str | bytes = message.data
            return data

        raise ConnectionError(f"connection closed ({message.type.name})")

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
                # The poll fails because of this, and the coordinator logs that
                _LOGGER.debug(
                    'TrueNAS %s unable to fetch data "%s" (%s)',
                    self._host,
                    service,
                    e,
                )
                await self.disconnect()
                # The reason is in the debug log. This is a code the forms can show.
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
    def _log_failed_method(self, service: str, reason: str) -> None:
        """Log why a polled method failed, unless it was already logged.

        A method that TrueNAS refuses fails on every poll, so this would fill the
        log. A failure with another reason is logged again.
        """
        if self._failed_methods.get(service) == reason:
            _LOGGER.debug(
                "TrueNAS %s query (%s) error: %s", self._host, service, reason
            )
            return

        self._failed_methods[service] = reason
        _LOGGER.error("TrueNAS %s query (%s) error: %s", self._host, service, reason)

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

            await self._ws.send_str(json.dumps(payload))
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
