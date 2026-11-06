"""Tests that a lost connection is logged once, and again when it is back."""

from __future__ import annotations

import logging
from unittest.mock import patch

from homeassistant import config_entries

from custom_components.truenas_link.const import DOMAIN, LOGIN_INTERVAL

from .conftest import async_add_entry

LOGGERS = "custom_components.truenas_link"


def _messages(caplog):
    """Return what the integration logged, by level, without the debug messages."""
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name.startswith(LOGGERS) and record.levelno >= logging.INFO
    ]


async def _polls(hass, coordinator, count):
    """Update the data a number of times."""
    for _ in range(count):
        await coordinator.async_refresh()
        await hass.async_block_till_done()


COORDINATOR_DOWN = (
    logging.ERROR,
    "Error fetching TrueNAS data: "
    "Could not get data from TrueNAS nas: the connection failed",
)
COORDINATOR_BACK = (logging.INFO, "Fetching TrueNAS data recovered")


def test_unreachable_truenas_is_logged_once_and_when_it_is_back(run_in_hass, caplog):
    """One message when it goes away, and one when it is back, whatever is between."""

    async def scenario(hass, _server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        async def refused(*_args, **_kwargs):
            raise ConnectionRefusedError("Connection refused")

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            await coordinator.api.disconnect()
            with patch("aiohttp.ClientSession.ws_connect", refused):
                await _polls(hass, coordinator, 4)

            assert _messages(caplog) == [COORDINATOR_DOWN]
            caplog.clear()

            await _polls(hass, coordinator, 2)

        assert _messages(caplog) == [COORDINATOR_BACK]

    run_in_hass(scenario)


def test_query_without_an_answer_is_logged_once_and_when_it_works(run_in_hass, caplog):
    """The connection opens on every poll, and the same query hangs every time."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            server.unanswered = {"pool.query"}
            await _polls(hass, coordinator, 3)

            assert _messages(caplog) == [COORDINATOR_DOWN]
            assert not coordinator.last_update_success
            caplog.clear()

            server.unanswered = set()
            await _polls(hass, coordinator, 2)

        assert _messages(caplog) == [COORDINATOR_BACK]

    run_in_hass(scenario)


def test_failed_login_is_logged_once_and_when_it_is_back(run_in_hass, caplog):
    """A login that gets no answer is not a wrong key, and fails like the rest."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            await coordinator.api.disconnect()
            server.unanswered = {"auth.login_with_api_key"}
            await _polls(hass, coordinator, 3)

            assert _messages(caplog) == [COORDINATOR_DOWN]
            caplog.clear()

            server.unanswered = set()
            await _polls(hass, coordinator, 2)

        assert _messages(caplog) == [COORDINATOR_BACK]

    run_in_hass(scenario)


def test_the_cause_stays_in_the_debug_log(run_in_hass, caplog):
    """Nothing about why it failed is lost, for those who turn on debug logging."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        async def refused(*_args, **_kwargs):
            raise ConnectionRefusedError("the refused cause")

        with caplog.at_level(logging.DEBUG, logger=LOGGERS):
            caplog.clear()
            await coordinator.api.disconnect()
            with patch("aiohttp.ClientSession.ws_connect", refused):
                await _polls(hass, coordinator, 1)

            assert "failed to connect (the refused cause)" in caplog.text
            caplog.clear()

            server.unanswered = {"pool.query"}
            await _polls(hass, coordinator, 1)

        assert 'unable to fetch data "pool.query"' in caplog.text

    run_in_hass(scenario)


def test_form_with_a_connection_error_logs_nothing_above_debug(run_in_hass, caplog):
    """The form already shows the error, and the user may be typing a host."""

    async def scenario(hass, _server):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {
                    "host": "nas",
                    "api_key": "wrong",
                    "access_level": "admin",
                    "verify_ssl": False,
                },
            )

        assert result["errors"] == {"host": "invalid_key"}
        assert _messages(caplog) == []

    run_in_hass(scenario)


def test_method_that_truenas_refuses_is_still_logged_once(run_in_hass, caplog):
    """This is not about the connection, and nothing else reports it."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            server.errors["alert.list"] = "[EPERM] not allowed"
            await _polls(hass, coordinator, 3)

        assert [
            level for level, message in _messages(caplog) if "alert.list" in message
        ] == [logging.ERROR]

    run_in_hass(scenario)


def test_revoked_key_is_noticed_at_the_next_login(run_in_hass):
    """TrueNAS keeps an open connection going, so polls alone do not tell."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        server.valid_keys = set()

        await coordinator.async_refresh()
        assert coordinator.last_update_success

        coordinator.last_login -= LOGIN_INTERVAL
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator.last_update_success
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert [flow["context"]["source"] for flow in flows] == ["reauth"]
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_new_login_leaves_a_single_connection(run_in_hass):
    """A login replaces the connection, and only once per interval."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        sockets = len(server.sockets)

        await coordinator.async_refresh()
        assert len(server.sockets) == sockets

        coordinator.last_login -= LOGIN_INTERVAL
        await coordinator.async_refresh()
        await coordinator.async_refresh()

        assert coordinator.last_update_success
        assert len(server.sockets) == sockets + 1
        assert server.open_sockets == 1

    run_in_hass(scenario)
