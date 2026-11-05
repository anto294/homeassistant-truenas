"""Tests for the Administrator and Read-only access levels."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.exceptions import ServiceValidationError
import pytest
import probatio as vol

from custom_components.truenas_link import config_flow, entity as entity_module, update
from custom_components.truenas_link.const import (
    ACCESS_LEVEL_ADMIN,
    ACCESS_LEVEL_READ_ONLY,
    CONF_ACCESS_LEVEL,
)
from custom_components.truenas_link.helper import is_read_only
from custom_components.truenas_link.update_types import SENSOR_TYPES

SYSTEM_UPDATE, APP_UPDATE = SENSOR_TYPES
FORM = {
    "host": "truenas.lan",
    "api_key": "key",
    "verify_ssl": False,
}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, True),  # lost: never more than a new entry gets
        ({CONF_ACCESS_LEVEL: ACCESS_LEVEL_ADMIN}, False),
        ({CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}, True),
    ],
)
def test_is_read_only(data, expected):
    """Only an explicit Administrator choice lifts the restriction."""
    assert is_read_only(data) is expected


def test_setup_form_defaults_to_read_only_and_accepts_administrator():
    """New entries start read-only; the form rejects unknown levels."""
    schema = config_flow._base_schema({})

    assert schema(FORM)[CONF_ACCESS_LEVEL] == ACCESS_LEVEL_READ_ONLY
    chosen = {**FORM, CONF_ACCESS_LEVEL: ACCESS_LEVEL_ADMIN}
    assert schema(chosen)[CONF_ACCESS_LEVEL] == ACCESS_LEVEL_ADMIN
    with pytest.raises(vol.Invalid):
        schema({**FORM, CONF_ACCESS_LEVEL: "root"})


def _flow(monkeypatch):
    """Return a config flow whose connection test succeeds."""
    flow = config_flow.TrueNASConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    api = MagicMock(system_id=None)
    api.connection_test = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(config_flow, "TrueNASAPI", lambda *_: api)
    return flow


def test_setup_stores_the_chosen_level_in_the_options(monkeypatch):
    """Only what is needed to connect goes in the entry data."""
    flow = _flow(monkeypatch)
    flow.async_create_entry = MagicMock()
    user_input = {**FORM, CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY}

    asyncio.run(flow.async_step_user(user_input))

    flow.async_create_entry.assert_called_once_with(
        title="TrueNAS",
        data={"host": "truenas.lan", "api_key": "key", "verify_ssl": False},
        options={"name": "TrueNAS", CONF_ACCESS_LEVEL: ACCESS_LEVEL_READ_ONLY},
    )


def _coordinator(read_only):
    """Return a stand-in coordinator with one app and the system info."""
    return SimpleNamespace(
        read_only=read_only,
        data={
            "system_info": {"version": "25.10.1"},
            "app": {"plex": {"id": "plex", "name": "Plex"}},
        },
        config_entry=SimpleNamespace(options={"name": "TrueNAS"}),
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
    cls, description, uid, admin_features
):
    """Read-only update entities still report updates, without the install button."""
    admin = cls(_coordinator(False), description, uid)
    read_only = cls(_coordinator(True), description, uid)

    assert admin.supported_features == admin_features
    assert read_only.supported_features == UpdateEntityFeature(0)


def test_action_runs_the_entity_method_without_targeting_fields():
    """Administrator entities get the action's own fields, not the target."""
    entity = SimpleNamespace(
        coordinator=SimpleNamespace(read_only=False),
        entity_description=SimpleNamespace(func="TrueNASAppBinarySensor"),
        start=AsyncMock(),
    )
    call = SimpleNamespace(data={"entity_id": ["binary_sensor.vm"], "overcommit": True})

    asyncio.run(
        entity_module.entity_service_handler("start", "TrueNASAppBinarySensor")(
            entity, call
        )
    )

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
        asyncio.run(
            entity_module.entity_service_handler("start", "TrueNASAppBinarySensor")(
                entity, call
            )
        )

    entity.start.assert_not_awaited()
