"""Tests for setting up and reloading an entry, on a real Home Assistant core."""

from __future__ import annotations

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
