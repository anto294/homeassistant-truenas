"""Tests for setting up and reloading an entry, on a real Home Assistant core."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
import pytest
import probatio as vol

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry


def test_reconfigure_reloads_the_entry_once(run_in_hass):
    """Reconfigure reloads through the flow, without an update listener."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
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
                "verify_ssl": False,
            },
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["host"] == "nas2"
        assert entry.state is ConfigEntryState.LOADED
        reloaded = entry.runtime_data
        assert reloaded is not coordinator
        assert not reloaded.read_only
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
                    "host": "nas",
                    "api_key": "good",
                    "access_level": "admin",
                    "verify_ssl": False,
                },
            )

        assert result["errors"] == {"host": "cannot_connect"}

    run_in_hass(scenario)


FORM_KEYS = {"host": "nas", "api_key": "good"}


def _reconfigure_flow(hass, entry):
    """Start Reconfigure for an entry."""
    return hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


def test_new_entries_verify_ssl_by_default(run_in_hass):
    """The setup form starts with verification on."""

    async def scenario(hass, _server):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        data = flow["data_schema"](FORM_KEYS)
        assert data["verify_ssl"] is True

    run_in_hass(scenario)


@pytest.mark.parametrize("stored", [True, False])
def test_reconfigure_shows_the_stored_verify_ssl(run_in_hass, stored):
    """A stored value is shown as it is, and used, without a migration."""

    async def scenario(hass, _server):
        entry = await async_add_entry(hass, verify_ssl=stored)
        assert entry.runtime_data.api._ssl_verify is stored

        flow = await _reconfigure_flow(hass, entry)

        assert flow["data_schema"](FORM_KEYS)["verify_ssl"] is stored
        assert entry.data["verify_ssl"] is stored

    run_in_hass(scenario)


def test_reconfigure_form_keeps_a_stored_false_after_an_error(run_in_hass):
    """The form that comes back after an error still shows it off."""

    async def scenario(hass, _server):
        entry = await async_add_entry(hass, verify_ssl=False)
        flow = await _reconfigure_flow(hass, entry)

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "host": "nas",
                "api_key": "wrong",
                "verify_ssl": False,
            },
        )

        assert result["errors"] == {"host": "invalid_key"}
        assert result["data_schema"](FORM_KEYS)["verify_ssl"] is False

    run_in_hass(scenario)


def test_reconfigure_form_keeps_what_was_entered_after_an_error(run_in_hass):
    """Turning it off and getting an error does not turn it back on."""

    async def scenario(hass, _server):
        entry = await async_add_entry(hass, verify_ssl=True)
        flow = await _reconfigure_flow(hass, entry)

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "host": "other",
                "api_key": "wrong",
                "verify_ssl": False,
            },
        )

        assert result["data_schema"](FORM_KEYS)["verify_ssl"] is False
        assert entry.data["verify_ssl"] is True

    run_in_hass(scenario)


def test_setup_form_keeps_false_after_an_error(run_in_hass):
    """The setup form that comes back after an error still shows it off."""

    async def scenario(hass, _server):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                **FORM_KEYS,
                "api_key": "wrong",
                "access_level": "admin",
                "verify_ssl": False,
            },
        )

        assert result["errors"] == {"host": "invalid_key"}
        data = result["data_schema"](FORM_KEYS)
        assert data["verify_ssl"] is False

    run_in_hass(scenario)


STORED_KEY = "stored-fake-key"
NEW_KEY = "new-fake-key"
RECONFIGURE_FIELDS = {"host": "nas", "verify_ssl": False}


def _form(result):
    """Return what a form's fields tell the browser: type, default and suggestion."""
    fields = {}
    for marker, validator in result["data_schema"].schema.items():
        config = getattr(validator, "config", {})
        fields[str(marker)] = {
            "type": config.get("type"),
            "required": isinstance(marker, vol.Required),
            "default": marker.default() if callable(marker.default) else None,
            "suggested": (marker.description or {}).get("suggested_value"),
        }

    return fields


def _assert_masked(field):
    """Check that the frontend shows a field as a password."""
    assert field["type"] == "password"


def _fake_keys(server):
    """Make the fake TrueNAS accept the keys of these tests."""
    server.valid_keys = {STORED_KEY, NEW_KEY}


def test_setup_form_masks_the_api_key(run_in_hass):
    """The setup form shows the key as a password, also after an error."""

    async def scenario(hass, _server):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        _assert_masked(_form(flow)["api_key"])

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                **FORM_KEYS,
                "api_key": "wrong",
                "access_level": "admin",
                "verify_ssl": False,
            },
        )
        _assert_masked(_form(result)["api_key"])

    run_in_hass(scenario)


def test_reauth_form_masks_the_api_key(run_in_hass):
    """The reauthentication form shows the key as a password, and starts empty."""

    async def scenario(hass, server):
        _fake_keys(server)
        entry = await async_add_entry(hass, api_key=STORED_KEY)

        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )

        assert flow["step_id"] == "reauth_confirm"
        _assert_masked(_form(flow)["api_key"])
        assert STORED_KEY not in str(_form(flow))

    run_in_hass(scenario)


def test_reconfigure_form_never_gets_the_stored_key(run_in_hass):
    """The stored key is not sent to the browser, even masked."""

    async def scenario(hass, server):
        _fake_keys(server)
        entry = await async_add_entry(hass, api_key=STORED_KEY)

        flow = await _reconfigure_flow(hass, entry)

        field = _form(flow)["api_key"]
        _assert_masked(field)
        assert not field["required"]
        assert STORED_KEY not in str(_form(flow))

        # Nor after an error that has nothing to do with the key
        server.valid_keys = set()
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], RECONFIGURE_FIELDS
        )
        assert result["errors"] == {"host": "invalid_key"}
        assert STORED_KEY not in str(_form(result))

    run_in_hass(scenario)


@pytest.mark.parametrize("empty", [{}, {"api_key": ""}], ids=["missing", "blank"])
def test_reconfigure_with_an_empty_key_keeps_the_stored_one(run_in_hass, empty):
    """The connection test uses the stored key, and the entry keeps it."""

    async def scenario(hass, server):
        _fake_keys(server)
        entry = await async_add_entry(hass, api_key=STORED_KEY)
        flow = await _reconfigure_flow(hass, entry)
        # Only the stored key can pass the test
        server.valid_keys = {STORED_KEY}

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {**RECONFIGURE_FIELDS, **empty, "host": "nas2"}
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["api_key"] == STORED_KEY
        assert entry.data["host"] == "nas2"

    run_in_hass(scenario)


def test_reconfigure_with_a_new_key_replaces_the_stored_one(run_in_hass):
    """A key that was entered is tested and saved."""

    async def scenario(hass, server):
        _fake_keys(server)
        entry = await async_add_entry(hass, api_key=STORED_KEY)
        flow = await _reconfigure_flow(hass, entry)
        # Only the new key can pass the test
        server.valid_keys = {NEW_KEY}

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {**RECONFIGURE_FIELDS, "api_key": NEW_KEY}
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["api_key"] == NEW_KEY

    run_in_hass(scenario)


def test_reconfigure_keeps_an_entered_key_only_until_it_is_cleared(run_in_hass):
    """After an error the typed key stays in the form, and clearing it counts."""

    async def scenario(hass, server):
        _fake_keys(server)
        entry = await async_add_entry(hass, api_key=STORED_KEY)
        flow = await _reconfigure_flow(hass, entry)
        server.valid_keys = {STORED_KEY}

        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {**RECONFIGURE_FIELDS, "api_key": NEW_KEY}
        )
        assert result["errors"] == {"host": "invalid_key"}
        field = _form(result)["api_key"]
        _assert_masked(field)
        assert field["suggested"] == NEW_KEY
        assert entry.data["api_key"] == STORED_KEY

        # Without it, the stored key is the one to test and to keep
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], RECONFIGURE_FIELDS
        )
        await hass.async_block_till_done()

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["api_key"] == STORED_KEY

    run_in_hass(scenario)


def test_connection_lost_during_a_poll_fails_the_poll(run_in_hass):
    """Entities go unavailable, even if a later query of the poll could reconnect.

    get_pool makes a second query after pool.query, so a query that reconnects
    would end the poll connected, and hide that its data is old.
    """

    async def scenario(hass, server):
        entry = await async_add_entry(hass)
        coordinator = entry.runtime_data
        states = [state.entity_id for state in hass.states.async_all()]
        assert states
        connections = len(server.sockets)

        server.unanswered = {"pool.query"}
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert not coordinator.last_update_success
        assert not coordinator.connected()
        assert len(server.sockets) == connections
        assert server.open_sockets == 0
        assert all(hass.states.get(state).state == "unavailable" for state in states)

        server.unanswered = set()
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert coordinator.last_update_success
        assert coordinator.connected()
        assert all(hass.states.get(state).state != "unavailable" for state in states)

    run_in_hass(scenario)
