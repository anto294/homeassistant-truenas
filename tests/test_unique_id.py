"""Tests for the config entry's unique id: one entry per TrueNAS system."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er, issue_registry as ir
import pytest

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry

FIELDS = {"verify_ssl": False}
SYSTEM_A = "system-a"
SYSTEM_B = "system-b"


async def _start_user_flow(hass, server, **overrides):
    """Submit the setup form and return its result."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "host": "other",
            "api_key": "good",
            "access_level": "admin",
            **FIELDS,
            **overrides,
        },
    )
    await hass.async_block_till_done()
    return result


async def _reconfigure(hass, entry, **overrides):
    """Submit the Reconfigure form and return its result."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"host": "new-host", **FIELDS, **overrides}
    )
    await hass.async_block_till_done()
    return result


async def _reauth(hass, entry, api_key="good"):
    """Submit the reauthentication form and return its result."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"api_key": api_key}
    )
    await hass.async_block_till_done()
    return result


async def _make_legacy(hass, *entries):
    """Turn entries into what an older version left: no unique id, then reload."""
    for entry in entries:
        hass.config_entries.async_update_entry(entry, unique_id=None)
    for entry in entries:
        await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def test_new_entry_gets_the_id_of_its_system(run_in_hass):
    """The setup form stores what system.global.id returns."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A

        entry = await async_add_entry(hass)

        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_same_system_is_refused_whatever_its_address(run_in_hass):
    """A second entry on the same system aborts, and changes nothing."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        await async_add_entry(hass)

        result = await _start_user_flow(hass, server)

        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    run_in_hass(scenario)


def test_other_system_can_be_added(run_in_hass):
    """Another system gets its own entry."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        await async_add_entry(hass)
        server.results["system.global.id"] = SYSTEM_B

        result = await _start_user_flow(hass, server)

        assert result["type"] == "create_entry"
        assert result["result"].unique_id == SYSTEM_B

    run_in_hass(scenario)


@pytest.mark.parametrize("answer", [None, "", [], 123], ids=str)
def test_system_without_an_id_can_still_be_added(run_in_hass, answer):
    """No usable id means no check, not a failure."""

    async def scenario(hass, server):
        server.results["system.global.id"] = answer

        entry = await async_add_entry(hass)

        assert entry.state is ConfigEntryState.LOADED
        assert entry.unique_id is None

    run_in_hass(scenario)


def test_refused_id_query_does_not_stop_the_setup(run_in_hass):
    """TrueNAS refusing the method only means there is no id."""

    async def scenario(hass, server):
        server.errors["system.global.id"] = "[ENOMETHOD] no such method"

        entry = await async_add_entry(hass)

        assert entry.state is ConfigEntryState.LOADED
        assert entry.unique_id is None

    run_in_hass(scenario)


def test_reconfigure_can_change_the_host_of_the_same_system(run_in_hass):
    """A new address for the same system is what Reconfigure is for."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)

        result = await _reconfigure(hass, entry)

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["host"] == "new-host"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reconfigure_refuses_another_system(run_in_hass):
    """Entities would suddenly describe another system."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.results["system.global.id"] = SYSTEM_B

        result = await _reconfigure(hass, entry)

        assert result["type"] == "abort"
        assert result["reason"] == "unique_id_mismatch"
        assert entry.data["host"] == "nas"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reconfigure_of_an_old_entry_has_nothing_to_compare(run_in_hass):
    """Without an id the form works as before, and keeps it unset until setup."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        hass.config_entries.async_update_entry(entry, unique_id=None)
        server.results["system.global.id"] = SYSTEM_B

        result = await _reconfigure(hass, entry)

        assert result["reason"] == "reconfigure_successful"
        assert entry.data["host"] == "new-host"
        # The reload that followed gave it the id of the system it now uses
        assert entry.unique_id == SYSTEM_B

    run_in_hass(scenario)


def test_reconfigure_when_the_system_gives_no_id(run_in_hass):
    """A failed id query does not block the form or lose the stored id."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.results["system.global.id"] = None

        result = await _reconfigure(hass, entry)

        assert result["reason"] == "reconfigure_successful"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reauth_accepts_a_new_key_of_the_same_system(run_in_hass):
    """A new key for the same system is saved."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.valid_keys.add("new")

        result = await _reauth(hass, entry, api_key="new")

        assert result["reason"] == "reauth_successful"
        assert entry.data["api_key"] == "new"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reauth_refuses_a_key_of_another_system(run_in_hass):
    """The address may now lead to another system: the key is not saved."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.valid_keys.add("new")
        server.results["system.global.id"] = SYSTEM_B

        result = await _reauth(hass, entry, api_key="new")

        assert result["type"] == "abort"
        assert result["reason"] == "unique_id_mismatch"
        assert entry.data["api_key"] == "good"

    run_in_hass(scenario)


def test_reauth_of_an_old_entry_works(run_in_hass):
    """An entry without an id can get a new key too."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        hass.config_entries.async_update_entry(entry, unique_id=None)
        server.valid_keys.add("new")

        result = await _reauth(hass, entry, api_key="new")

        assert result["reason"] == "reauth_successful"
        assert entry.data["api_key"] == "new"

    run_in_hass(scenario)


def test_existing_entry_gets_the_id_at_setup(run_in_hass):
    """An entry from an older version gets its id, and keeps its entities."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        registry = er.async_get(hass)
        before = sorted(
            item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        )

        await _make_legacy(hass, entry)

        assert entry.unique_id == SYSTEM_A
        assert entry.state is ConfigEntryState.LOADED
        assert before == sorted(
            item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        )

    run_in_hass(scenario)


def test_two_old_entries_on_one_system_keep_working(run_in_hass):
    """The second stays without an id, with a warning, and loses nothing."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        first = await async_add_entry(hass)
        server.results["system.global.id"] = SYSTEM_B
        second = await async_add_entry(hass, name="Second")
        registry = er.async_get(hass)
        entities = len(er.async_entries_for_config_entry(registry, second.entry_id))
        assert entities
        server.results["system.global.id"] = SYSTEM_A

        await _make_legacy(hass, first, second)

        assert first.unique_id == SYSTEM_A
        assert second.unique_id is None
        assert first.state is ConfigEntryState.LOADED
        assert second.state is ConfigEntryState.LOADED
        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, f"duplicate_system_{second.entry_id}"
        )
        assert issue.translation_key == "duplicate_system"
        assert issue.config_entry_id == second.entry_id
        assert issue.translation_placeholders == {
            "entry": second.title,
            "other": first.title,
        }
        assert (
            len(er.async_entries_for_config_entry(registry, second.entry_id))
            == entities
        )
        states = [state for state in hass.states.async_all()]
        assert all(state.state != "unavailable" for state in states)

    run_in_hass(scenario)


def test_going_back_needs_no_migration(run_in_hass):
    """The id does not change the entry's version or its data."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        data = dict(entry.data)
        version = entry.version

        await _make_legacy(hass, entry)

        assert entry.version == version
        assert dict(entry.data) == data

    run_in_hass(scenario)


async def _configure(hass, flow, data):
    """Submit a form."""
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], data)
    await hass.async_block_till_done()
    return result


def test_setup_recovers_from_an_error(run_in_hass):
    """A wrong key can be corrected in the form, and the entry gets its unique id."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        fields = {"host": "nas", "access_level": "admin", **FIELDS}

        failed = await _configure(hass, flow, {**fields, "api_key": "wrong"})
        assert failed["errors"] == {"host": "invalid_key"}

        result = await _configure(hass, flow, {**fields, "api_key": "good"})
        assert result["type"] == "create_entry"
        assert result["title"] == "TrueNAS"
        assert result["data"]["api_key"] == "good"
        assert result["result"].unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reconfigure_recovers_from_an_error(run_in_hass):
    """A wrong key can be corrected in the form."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.valid_keys.add("new")
        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        fields = {"host": "new-host", **FIELDS}

        failed = await _configure(hass, flow, {**fields, "api_key": "wrong"})
        assert failed["errors"] == {"host": "invalid_key"}
        assert entry.data["host"] == "nas"

        result = await _configure(hass, flow, {**fields, "api_key": "new"})
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["host"] == "new-host"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_reauth_recovers_from_an_error(run_in_hass):
    """A wrong key can be corrected in the form."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        entry = await async_add_entry(hass)
        server.valid_keys.add("new")
        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )

        failed = await _configure(hass, flow, {"api_key": "wrong"})
        assert failed["errors"] == {"base": "invalid_key"}

        result = await _configure(hass, flow, {"api_key": "new"})
        assert result["reason"] == "reauth_successful"
        assert entry.data["api_key"] == "new"
        assert entry.unique_id == SYSTEM_A

    run_in_hass(scenario)


def test_issue_of_two_entries_on_a_system_goes_away_with_one(run_in_hass):
    """Removing either one solves it, and the other then takes the id."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM_A
        first = await async_add_entry(hass)
        second = await async_add_entry(hass, name="Second")
        await _make_legacy(hass, first, second)
        registry = ir.async_get(hass)
        issue_id = f"duplicate_system_{second.entry_id}"
        assert registry.async_get_issue(DOMAIN, issue_id) is not None

        await hass.config_entries.async_remove(first.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get_issue(DOMAIN, issue_id) is None

        await hass.config_entries.async_reload(second.entry_id)
        await hass.async_block_till_done()
        assert second.unique_id == SYSTEM_A
        assert registry.async_get_issue(DOMAIN, issue_id) is None

    run_in_hass(scenario)
