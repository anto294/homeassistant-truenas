"""Tests for the Administrator and Read-only access levels."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.exceptions import ServiceValidationError
import pytest
import voluptuous as vol

from custom_components.truenas_link import config_flow, entity as entity_module, update
from custom_components.truenas_link.const import (
    ACCESS_LEVEL_ADMIN,
    ACCESS_LEVEL_READ_ONLY,
    CONF_ACCESS_LEVEL,
    DOMAIN,
)
from custom_components.truenas_link.helper import is_read_only
from custom_components.truenas_link.update_types import SENSOR_TYPES

SYSTEM_UPDATE, APP_UPDATE = SENSOR_TYPES
FORM = {
    "name": "TrueNAS",
    "host": "truenas.lan",
    "api_key": "key",
    "verify_ssl": False,
}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, False),  # entries created before the option existed
        ({CONF_ACCESS_LEVEL: ACCESS_LEVEL_ADMIN}, False),
        ({CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}, True),
    ],
)
def test_is_read_only(data, expected):
    """Only an explicit read-only choice restricts the entry."""
    assert is_read_only(data) is expected


def test_setup_form_defaults_to_administrator_and_accepts_read_only():
    """The setup form offers both levels and rejects anything else."""
    schema = config_flow._base_schema({})

    assert schema(FORM)[CONF_ACCESS_LEVEL] == ACCESS_LEVEL_ADMIN
    chosen = {**FORM, CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}
    assert schema(chosen)[CONF_ACCESS_LEVEL] == ACCESS_LEVEL_READ_ONLY
    with pytest.raises(vol.Invalid):
        schema({**FORM, CONF_ACCESS_LEVEL: "root"})


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ({}, ACCESS_LEVEL_ADMIN),
        ({CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}, ACCESS_LEVEL_READ_ONLY),
    ],
)
def test_reconfigure_form_starts_from_the_stored_level(stored, shown):
    """Reconfigure shows the entry's current level."""
    schema = config_flow._reconfigure_schema(stored)
    form = {key: FORM[key] for key in ("host", "api_key", "verify_ssl")}

    assert schema(form)[CONF_ACCESS_LEVEL] == shown


def _flow():
    """Return a config flow whose connection test succeeds."""
    flow = config_flow.TrueNASConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.hass.async_add_executor_job = AsyncMock(
        side_effect=[MagicMock(), (True, "")],
    )
    return flow


def test_setup_stores_the_chosen_level():
    """The level picked in the setup form ends up in the entry data."""
    flow = _flow()
    flow.async_create_entry = MagicMock()
    user_input = {**FORM, CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}

    asyncio.run(flow.async_step_user(user_input))

    flow.async_create_entry.assert_called_once_with(title="TrueNAS", data=user_input)


def test_reconfigure_stores_the_chosen_level():
    """The level picked in Reconfigure replaces the stored one."""
    flow = _flow()
    entry = SimpleNamespace(data={**FORM, CONF_ACCESS_LEVEL: ACCESS_LEVEL_ADMIN})
    flow._get_reconfigure_entry = lambda: entry
    flow.async_update_reload_and_abort = MagicMock()
    user_input = {
        "host": "truenas.lan",
        "api_key": "key",
        "verify_ssl": False,
        CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY,
    }

    asyncio.run(flow.async_step_reconfigure(user_input))

    updates = flow.async_update_reload_and_abort.call_args.kwargs["data_updates"]
    assert updates[CONF_ACCESS_LEVEL] == ACCESS_LEVEL_READ_ONLY


def _coordinator(read_only):
    """Return a stand-in coordinator with one app and the system info."""
    return SimpleNamespace(
        read_only=read_only,
        data={
            "system_info": {"version": "25.10.1"},
            "app": {"plex": {"id": "plex", "name": "Plex"}},
        },
        config_entry=SimpleNamespace(data={"name": "TrueNAS"}),
    )


@pytest.mark.parametrize(
    ("cls", "description", "uid", "admin_features"),
    [
        (
            update.TrueNASUpdate,
            SYSTEM_UPDATE,
            None,
            UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS,
        ),
        (update.TrueNASAppUpdate, APP_UPDATE, "plex", UpdateEntityFeature.INSTALL),
    ],
)
def test_update_entities_only_install_with_administrator_access(
    monkeypatch, cls, description, uid, admin_features
):
    """Read-only update entities still report updates, without the install button."""
    monkeypatch.setattr(
        entity_module.ep,
        "async_get_current_platform",
        lambda: SimpleNamespace(domain="update"),
    )

    admin = cls(_coordinator(False), description, uid)
    read_only = cls(_coordinator(True), description, uid)

    assert admin.supported_features == admin_features
    assert read_only.supported_features == UpdateEntityFeature(0)


def _hass(*access_levels, registered=()):
    """Return a stand-in hass with one config entry per access level."""
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [
        SimpleNamespace(disabled_by=None, data={CONF_ACCESS_LEVEL: level})
        for level in access_levels
    ]
    hass.services.has_service.side_effect = lambda _, name: name in registered
    return hass


SERVICES = [["vm_start", {}, "start"], ["vm_stop", {}, "stop"]]


def test_actions_are_registered_with_an_administrator_entry():
    """One Administrator entry is enough to offer the actions."""
    hass = _hass(ACCESS_LEVEL_READ_ONLY, ACCESS_LEVEL_ADMIN)
    platform = MagicMock()

    entity_module.async_update_services(hass, platform, SERVICES)

    names = [c.args[0] for c in platform.async_register_entity_service.call_args_list]
    assert names == ["vm_start", "vm_stop"]
    hass.services.async_remove.assert_not_called()


def test_actions_are_not_offered_with_only_read_only_entries():
    """Read-only entries register nothing and remove what an earlier setup left."""
    hass = _hass(ACCESS_LEVEL_READ_ONLY, registered={"vm_start"})
    platform = MagicMock()

    entity_module.async_update_services(hass, platform, SERVICES)

    platform.async_register_entity_service.assert_not_called()
    hass.services.async_remove.assert_called_once_with(DOMAIN, "vm_start")


def test_action_runs_the_entity_method_without_targeting_fields():
    """Administrator entities get the action's own fields, not the target."""
    entity = SimpleNamespace(
        coordinator=SimpleNamespace(read_only=False), start=AsyncMock()
    )
    call = SimpleNamespace(data={"entity_id": ["binary_sensor.vm"], "overcommit": True})

    asyncio.run(entity_module.entity_service_handler("start")(entity, call))

    entity.start.assert_awaited_once_with(overcommit=True)


def test_action_on_a_read_only_entity_is_refused():
    """A read-only entity never calls TrueNAS, whatever its API key can do."""
    entity = SimpleNamespace(
        coordinator=SimpleNamespace(read_only=True),
        entity_id="binary_sensor.vm",
        start=AsyncMock(),
    )
    call = SimpleNamespace(data={"entity_id": ["binary_sensor.vm"]})

    with pytest.raises(ServiceValidationError):
        asyncio.run(entity_module.entity_service_handler("start")(entity, call))

    entity.start.assert_not_awaited()
