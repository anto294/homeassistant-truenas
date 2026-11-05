"""Tests for the entry's options: their flow, and the migration to version 2."""

from __future__ import annotations

from types import MappingProxyType

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry
from .sample_data import answers

UPTIME = "sensor.truenas_system_uptime"
CONNECTION = {"host": "nas", "api_key": "good", "verify_ssl": False}


def _old_entry(version=1, data=None, options=None):
    """Return an entry as an earlier version stored it."""
    return config_entries.ConfigEntry(
        version=version,
        minor_version=1,
        domain=DOMAIN,
        title="TrueNAS",
        data=data or {},
        options=options or {},
        source=config_entries.SOURCE_USER,
        unique_id=None,
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )


def test_new_entry_keeps_only_what_connects_in_its_data(run_in_hass):
    """The rest is in the options, whatever the form looked like."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass, access_level="read_only")

        assert entry.version == 2
        assert dict(entry.data) == CONNECTION
        assert dict(entry.options) == {"name": "TrueNAS", "access_level": "read_only"}

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("stored", "level", "read_only"),
    [
        ({"access_level": "read_only"}, "read_only", True),
        ({"access_level": "admin"}, "admin", False),
        # Entries from before the access level existed
        ({}, "admin", False),
    ],
)
def test_migration_moves_the_options_and_keeps_the_entities(
    run_in_hass, stored, level, read_only
):
    """Access level, name and entity ids stay what they were."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = _old_entry(data={"name": "TrueNAS", **CONNECTION, **stored})

        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.version == 2
        assert dict(entry.data) == CONNECTION
        assert dict(entry.options) == {"name": "TrueNAS", "access_level": level}
        assert entry.runtime_data.read_only is read_only
        assert entry.title == "TrueNAS"
        registered = er.async_get(hass).async_get(UPTIME)
        assert registered.unique_id == "truenas-system_uptime"

    run_in_hass(scenario)


def test_entry_of_a_newer_version_is_not_loaded(run_in_hass):
    """What protects a read-only entry when going back to an older release."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = _old_entry(
            version=3,
            data=CONNECTION,
            options={"name": "TrueNAS", "access_level": "read_only"},
        )

        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.MIGRATION_ERROR
        assert hass.states.get(UPTIME) is None
        assert not server.sockets

    run_in_hass(scenario)


def test_configure_changes_the_level_and_reloads(run_in_hass):
    """Actions follow the new level at once, and the name stays."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        assert not coordinator.read_only

        flow = await hass.config_entries.options.async_init(entry.entry_id)
        assert flow["data_schema"]({})["access_level"] == "admin"
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {"access_level": "read_only"}
        )
        await hass.async_block_till_done()

        assert entry.runtime_data is not coordinator
        assert entry.runtime_data.read_only
        assert dict(entry.options) == {"name": "TrueNAS", "access_level": "read_only"}
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, "system_reboot", {"entity_id": UPTIME}, blocking=True
            )
        assert err.value.translation_key == "read_only_action"

    run_in_hass(scenario)


def test_configure_without_a_change_does_not_reload(run_in_hass):
    """Saving the same level must not drop the connection or entities' state."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data

        flow = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {"access_level": "admin"}
        )
        await hass.async_block_till_done()

        assert entry.runtime_data is coordinator

    run_in_hass(scenario)
