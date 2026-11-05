"""Tests that a lost connection is logged once, and again when it is back."""

from __future__ import annotations

import logging
from unittest.mock import patch

from custom_components.truenas_link import api as api_module

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


def test_unreachable_truenas_is_logged_once_and_when_it_is_back(run_in_hass, caplog):
    """Polls that keep failing to connect add nothing to the log."""

    async def scenario(hass, _server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        async def refused(*_args, **_kwargs):
            raise ConnectionRefusedError("Connection refused")

        with caplog.at_level(logging.INFO, logger=LOGGERS):
            caplog.clear()
            await coordinator.api.disconnect()
            with patch.object(api_module, "connect", refused):
                await _polls(hass, coordinator, 4)

            assert [level for level, _ in _messages(caplog)] == [
                logging.ERROR,
                logging.ERROR,
            ]
            caplog.clear()

            await _polls(hass, coordinator, 2)

        assert [message for _, message in _messages(caplog)] == [
            "Fetching TrueNAS data recovered"
        ]

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

            assert [
                level for level, message in _messages(caplog) if "pool.query" in message
            ] == [logging.WARNING]
            assert not coordinator.last_update_success
            caplog.clear()

            server.unanswered = set()
            await _polls(hass, coordinator, 2)

        messages = [message for _, message in _messages(caplog)]
        assert "TrueNAS nas query (pool.query) works again" in messages
        assert "Fetching TrueNAS data recovered" in messages
        assert len(messages) == 2

    run_in_hass(scenario)
