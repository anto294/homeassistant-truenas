"""Tests of the error codes, from real failures of real connections."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from http import HTTPStatus
import socket
import ssl
import threading

import pytest

from custom_components.truenas_link.api import TrueNASAPI

from .test_timeout import _tls_server


def _test(host, verify_ssl=False):
    """Return the result of a connection test."""
    return asyncio.run(TrueNASAPI(host, "api-key", verify_ssl).connection_test())


def _closed_port():
    """Return a port that nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _running(server):
    """Return the port of a server that runs for this block."""
    with server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server.socket.getsockname()[1]
        server.shutdown()
        thread.join(5)


def test_closed_port_is_a_refusal():
    """asyncio's text is "Connect call failed", not "Connection refused"."""
    assert _test(f"127.0.0.1:{_closed_port()}") == (False, "connection_refused")


def test_closed_port_with_404_in_it_is_a_refusal():
    """This used to give api_not_found, because the text holds the port."""
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 8404))
        except OSError:
            pytest.skip("port 8404 is in use")

    assert _test("127.0.0.1:8404") == (False, "connection_refused")


def test_host_with_several_addresses_is_a_refusal():
    """A name for IPv6 and IPv4 fails with a text that combines both errors."""
    assert _test(f"localhost:{_closed_port()}") == (False, "connection_refused")


def test_name_that_does_not_resolve():
    """The .invalid domain never resolves."""
    assert _test("truenas.invalid") == (False, "unknown_hostname")


def test_invalid_certificate(tmp_path):
    """A self-signed certificate, with verification on."""
    with _running(_tls_server(tmp_path)) as port:
        result = _test(f"127.0.0.1:{port}", verify_ssl=True)

    assert result == (False, "certificate_verify_failed")


def _respond(status):
    """Return a process_request that answers with an HTTP status."""
    return lambda connection, _request: connection.respond(status, "not this\n")


def test_http_404_is_a_missing_api(tmp_path):
    """TrueNAS older than the versioned API, or another server."""
    server = _tls_server(tmp_path, process_request=_respond(HTTPStatus.NOT_FOUND))
    with _running(server) as port:
        assert _test(f"127.0.0.1:{port}") == (False, "api_not_found")


@pytest.mark.parametrize("status", [HTTPStatus.OK, HTTPStatus.BAD_GATEWAY])
def test_other_http_answer_is_no_websocket(tmp_path, status):
    """A reverse proxy that does not pass websockets on, for one."""
    server = _tls_server(tmp_path, process_request=_respond(status))
    with _running(server) as port:
        assert _test(f"127.0.0.1:{port}") == (False, "websocket_not_supported")


def test_server_that_does_not_recognize_the_hostname(tmp_path):
    """The name is sent only for a hostname, not for an address."""
    server = _tls_server(
        tmp_path,
        sni_callback=lambda *_: ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME,
    )
    with _running(server) as port:
        assert _test(f"localhost:{port}") == (False, "tls_unrecognized_name")


def test_plain_http_port():
    """Any other TLS failure, here a port that does not speak TLS, has a code too."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def answer():
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")

        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        port = listener.getsockname()[1]

        assert _test(f"127.0.0.1:{port}") == (False, "cannot_connect")
        thread.join(5)
