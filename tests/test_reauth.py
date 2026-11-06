"""Tests for reauthentication, on a real Home Assistant core."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry


def _reauth_flows(hass):
    """Return the reauthentication flows in progress."""
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


async def _lose_connection(hass, entry):
    """Drop the connection, as a restart of TrueNAS or the network would."""
    api = entry.runtime_data.api
    await api.disconnect()


def test_revoked_key_starts_reauthentication(run_in_hass):
    """A rejected login at the next refresh asks for a new key."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        assert not _reauth_flows(hass)
        server.valid_keys.clear()
        await _lose_connection(hass, entry)

        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        flows = _reauth_flows(hass)
        assert len(flows) == 1
        assert flows[0]["step_id"] == "reauth_confirm"
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_revoked_key_during_setup_starts_reauthentication(run_in_hass):
    """A rejected login in setup fails the setup and asks for a new key."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        server.valid_keys.clear()

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert len(_reauth_flows(hass)) == 1
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_other_failures_do_not_start_reauthentication(run_in_hass):
    """An unreachable TrueNAS says nothing about the key."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        await _lose_connection(hass, entry)
        coordinator = entry.runtime_data
        server.valid_keys.clear()

        def refuse(*_args, **_kwargs):
            raise ConnectionRefusedError(111, "Connection refused")

        with patch("aiohttp.ClientSession.ws_connect", refuse):
            await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator.last_update_success
        assert not _reauth_flows(hass)

    run_in_hass(scenario)


def test_reauthentication_with_a_working_key(run_in_hass):
    """The new key is stored and the entry reloads, without a new entry."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        server.valid_keys = {"new"}
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        flow = _reauth_flows(hass)[0]
        form = await hass.config_entries.flow.async_configure(flow["flow_id"])
        assert form["description_placeholders"] == {"name": entry.title}

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"api_key": "new"}
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reauth_successful"
        assert entry.data["api_key"] == "new"
        assert entry.state is ConfigEntryState.LOADED
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        assert not _reauth_flows(hass)
        assert server.open_sockets == 1

    run_in_hass(scenario)


def test_reauthentication_with_a_wrong_key(run_in_hass):
    """A new key that does not work is not stored, and the form asks again."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        server.valid_keys = {"new"}
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        flow = _reauth_flows(hass)[0]
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"api_key": "also-wrong"}
        )
        await hass.async_block_till_done()

        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_key"}
        assert entry.data["api_key"] == "good"
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_rejected_key_raises_a_translated_error_and_starts_reauthentication(
    run_in_hass,
):
    """On a poll, not only at setup, and without fixed text in the code."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        await coordinator.api.disconnect()
        server.valid_keys = set()

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        error = coordinator.last_exception
        assert isinstance(error, ConfigEntryAuthFailed)
        assert error.translation_domain == DOMAIN
        assert error.translation_key == "api_key_rejected"
        assert error.translation_placeholders == {"host": "nas"}
        flows = entry.async_get_active_flows(hass, {SOURCE_REAUTH})
        assert [flow["step_id"] for flow in flows] == ["reauth_confirm"]

    run_in_hass(scenario)


def test_failed_update_raises_a_translated_error(run_in_hass):
    """So the log and the setup retry show it in the language of Home Assistant."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        server.unanswered = {"pool.query"}

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        error = coordinator.last_exception
        assert isinstance(error, UpdateFailed)
        assert error.translation_domain == DOMAIN
        assert error.translation_key == "update_failed"
        assert error.translation_placeholders == {"host": "nas"}
        assert "TrueNas" not in str(error)

    run_in_hass(scenario)
