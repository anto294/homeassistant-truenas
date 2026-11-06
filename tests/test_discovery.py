"""Tests that a TrueNAS system announcing itself is offered, and no more than that."""

from __future__ import annotations

from ipaddress import ip_address
import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry

HOST = "192.168.1.42"
SYSTEM = "fake-system-id"


def _announcement(address=HOST, hostname="truenas.local."):
    """Return what a TrueNAS system announces over mDNS."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(address),
        ip_addresses=[ip_address(address)],
        port=80,
        hostname=hostname,
        type="_http._tcp.local.",
        name="truenas._http._tcp.local.",
        properties={},
    )


async def _discover(hass, info=None):
    """Start the flow of an announcement."""
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=info or _announcement(),
    )


def _fields(key="good", host=HOST):
    """Return what the user submits in the form."""
    return {
        "host": host,
        "api_key": key,
        "access_level": "read_only",
        "verify_ssl": False,
    }


def test_manifest_announces_the_match():
    """Home Assistant starts the flow from this."""
    manifest = json.loads(
        (
            Path(__file__).parent.parent
            / "custom_components/truenas_link/manifest.json"
        ).read_text()
    )
    assert manifest["zeroconf"] == [{"type": "_http._tcp.local.", "name": "truenas*"}]


def test_announcement_shows_the_form_with_the_address_and_contacts_nobody(run_in_hass):
    """The user confirms, and nothing was sent to the host before that."""

    async def scenario(hass, server):
        result = await _discover(hass)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        schema = {str(key): key for key in result["data_schema"].schema}
        assert schema["host"].default() == HOST
        assert server.sockets == []
        flow = hass.config_entries.flow.async_get(result["flow_id"])
        assert flow["context"]["title_placeholders"] == {
            "name": "truenas",
            "host": HOST,
        }

    run_in_hass(scenario)


def test_confirming_makes_an_entry_with_the_id_of_the_system(run_in_hass):
    """It is an ordinary read-only entry, whose id replaces that of the flow."""

    async def scenario(hass, server):
        server.results["system.global.id"] = SYSTEM
        result = await _discover(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _fields()
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == SYSTEM
        assert result["result"].data["host"] == HOST
        assert result["result"].options["access_level"] == "read_only"

    run_in_hass(scenario)


def test_wrong_key_stays_in_the_form(run_in_hass):
    """As in the form the user opens."""

    async def scenario(hass, server):
        result = await _discover(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _fields("wrong")
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"host": "invalid_key"}

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("configured", "announcement"),
    [
        (HOST, _announcement()),
        (f"{HOST}:8443", _announcement()),
        ("truenas.local", _announcement()),
    ],
    ids=["address", "address and port", "hostname"],
)
def test_configured_system_is_not_offered(run_in_hass, configured, announcement):
    """By its address or the name it announces."""

    async def scenario(hass, server):
        await async_add_entry(hass, host=configured)

        result = await _discover(hass, announcement)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    run_in_hass(scenario)


def test_announcement_never_changes_the_address_of_an_entry(run_in_hass):
    """Otherwise anyone could announce the name and be sent the entry's key."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass, host="192.168.1.7")
        sockets = len(server.sockets)

        result = await _discover(hass, _announcement(hostname="nas.local."))

        assert result["type"] is FlowResultType.FORM
        assert entry.data["host"] == "192.168.1.7"
        assert len(server.sockets) == sockets

    run_in_hass(scenario)


def test_same_address_is_offered_once(run_in_hass):
    """Announcements repeat, and the form may still be open."""

    async def scenario(hass, server):
        await _discover(hass)

        result = await _discover(hass)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_in_progress"

    run_in_hass(scenario)


def test_ignored_address_is_not_offered_again(run_in_hass):
    """Ignoring is how to get rid of a system added by another name."""

    async def scenario(hass, server):
        result = await _discover(hass)
        flow = hass.config_entries.flow.async_get(result["flow_id"])
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IGNORE},
            data={"unique_id": flow["context"]["unique_id"], "title": "TrueNAS"},
        )
        await hass.async_block_till_done()

        result = await _discover(hass)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    run_in_hass(scenario)


def test_ipv6_address_is_not_offered(run_in_hass):
    """The form and the connection expect a host without brackets."""

    async def scenario(hass, server):
        result = await _discover(hass, _announcement("fd00::42"))

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "not_ipv4_address"

    run_in_hass(scenario)
