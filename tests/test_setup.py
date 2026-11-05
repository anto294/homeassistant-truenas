"""Tests for setting up and reloading an entry, on a real Home Assistant core."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry


def test_reconfigure_reloads_the_entry_once(run_in_hass):
    """Reconfigure reloads through the flow, without an update listener."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert entry.state is ConfigEntryState.LOADED
        assert not entry.update_listeners
        connections = len(server.sockets)

        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "host": "nas2",
                "api_key": "good",
                "access_level": "read_only",
                "verify_ssl": False,
            },
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["host"] == "nas2"
        assert entry.state is ConfigEntryState.LOADED
        reloaded = hass.data[DOMAIN][entry.entry_id]
        assert reloaded is not coordinator
        assert reloaded.read_only
        # One connection for the flow's test and one for a single reload
        assert len(server.sockets) == connections + 2

    run_in_hass(scenario)


def test_unload_closes_the_connection(run_in_hass):
    """Nothing stays connected to TrueNAS after an unload."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        assert server.open_sockets == 1

        assert await hass.config_entries.async_unload(entry.entry_id)

        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_reload_leaves_one_connection(run_in_hass):
    """A reload replaces the connection."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)

        assert await hass.config_entries.async_reload(entry.entry_id)

        assert server.open_sockets == 1

    run_in_hass(scenario)


def test_failed_setup_closes_the_connection(run_in_hass):
    """Setup retries do not pile up connections if the first refresh breaks."""

    async def scenario(hass, server):
        with patch(
            "custom_components.truenas_link.coordinator.TrueNASCoordinator.get_disk",
            side_effect=ValueError("unexpected payload"),
        ):
            entry = await async_add_entry(hass)

        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_wrong_key_during_setup_leaves_no_connection(run_in_hass):
    """A login that is rejected in setup closes its connection."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        server.valid_keys.clear()

        assert not await hass.config_entries.async_setup(entry.entry_id)

        assert server.open_sockets == 0

    run_in_hass(scenario)


def test_form_shows_a_known_error_for_an_unknown_failure(run_in_hass):
    """The form gets a code with a message, not the exception's text."""

    async def scenario(hass, server):
        def fail(*_args, **_kwargs):
            raise OSError("unexpected <failure>")

        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with patch("custom_components.truenas_link.api.connect", fail):
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {
                    "name": "TrueNAS",
                    "host": "nas",
                    "api_key": "good",
                    "access_level": "admin",
                    "verify_ssl": False,
                },
            )

        assert result["errors"] == {"host": "cannot_connect"}

    run_in_hass(scenario)
