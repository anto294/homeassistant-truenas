"""Tests for actions registered in async_setup, and refused on read-only entries."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
import pytest

from custom_components.truenas_link import ACTIONS
from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry
from .sample_data import answers

SERVICES_YAML = (
    Path(__file__).parent.parent / "custom_components/truenas_link/services.yaml"
)
UPTIME = "sensor.truenas_system_uptime"
SNAPSHOT_TARGET = "sensor.truenas_datasets_tank"
TANK_SCAN = "sensor.truenas_system_tank_scan"
OFFSITE = "sensor.truenas_cloudsync_offsite_backup"
BACKUP = "sensor.truenas_replication_tank_to_backup"
WIN11 = "binary_sensor.truenas_vms_win11"
WEB = "binary_sensor.truenas_containers_web"
CIFS = "binary_sensor.truenas_services_cifs"
PLEX = "binary_sensor.truenas_apps_plex"
# Every action, and an entity of the class it is meant for
TARGETS = {
    "system_reboot": UPTIME,
    "system_shutdown": UPTIME,
    "dataset_snapshot": SNAPSHOT_TARGET,
    "pool_scrub_start": TANK_SCAN,
    "pool_scrub_pause": TANK_SCAN,
    "pool_scrub_stop": TANK_SCAN,
    "cloudsync_run": OFFSITE,
    "cloudsync_abort": OFFSITE,
    "replication_run": BACKUP,
    "vm_start": WIN11,
    "vm_stop": WIN11,
    "container_start": WEB,
    "container_stop": WEB,
    "service_start": CIFS,
    "service_stop": CIFS,
    "service_restart": CIFS,
    "service_reload": CIFS,
    "app_start": PLEX,
    "app_stop": PLEX,
}


def _action_names():
    """Return the names of the actions the integration registers."""
    return {action[0] for _, actions in ACTIONS for action in actions}


def _requests(server):
    """Return how many requests TrueNAS has received."""
    return sum(len(socket.requests) for socket in server.sockets)


def test_the_list_of_actions_matches_services_yaml_and_the_targets():
    """An action without a description, or a test, would go unnoticed."""
    assert _action_names() == set(load_yaml(str(SERVICES_YAML)))
    assert _action_names() == set(TARGETS)


def test_actions_exist_without_any_entry(run_in_hass):
    """So automations using them validate even if TrueNAS was never reachable."""

    async def scenario(hass, _server):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()

        assert not hass.config_entries.async_entries(DOMAIN)
        for name in _action_names():
            assert hass.services.has_service(DOMAIN, name), name

    run_in_hass(scenario)


def test_actions_stay_after_the_only_entry_is_removed(run_in_hass):
    """They belong to the integration, not to an entry."""

    async def scenario(hass, server):
        entry = await async_add_entry(hass, access_level="read_only")

        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

        for name in _action_names():
            assert hass.services.has_service(DOMAIN, name), name

    run_in_hass(scenario)


def test_action_on_an_entry_that_is_not_loaded_reaches_nothing(run_in_hass, caplog):
    """Home Assistant finds no entity: it logs that, and raises no error."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        entry = await async_add_entry(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        sent = _requests(server)

        with caplog.at_level(logging.WARNING):
            await hass.services.async_call(
                DOMAIN, "system_reboot", {"entity_id": UPTIME}, blocking=True
            )

        assert _requests(server) == sent
        assert "missing or not currently available" in caplog.text

    run_in_hass(scenario)


@pytest.mark.parametrize("action", sorted(TARGETS))
def test_every_action_is_refused_on_a_read_only_entry(run_in_hass, action):
    """The only protection there is now: it must hold on each platform."""

    async def scenario(hass, server):
        server.results = answers("27.0")
        await async_add_entry(hass, access_level="read_only")
        assert hass.states.get(TARGETS[action]) is not None
        sent = _requests(server)

        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, action, {"entity_id": TARGETS[action]}, blocking=True
            )

        assert err.value.translation_key == "read_only_action"
        assert _requests(server) == sent

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("action", "target"),
    [
        (action, target)
        for action, _ in sorted(TARGETS.items())
        for target in sorted(set(TARGETS.values()))
        if target != TARGETS[action]
        and target.split(".")[0] == TARGETS[action].split(".")[0]
    ],
)
def test_action_is_refused_on_an_entity_of_another_class(run_in_hass, action, target):
    """Methods share names: cloudsync_abort on the uptime sensor would shut down."""

    async def scenario(hass, server):
        server.results = answers("27.0")
        await async_add_entry(hass)
        assert hass.states.get(target) is not None
        sent = _requests(server)

        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, action, {"entity_id": target}, blocking=True
            )

        assert err.value.translation_key == "wrong_action_target"
        assert _requests(server) == sent

    run_in_hass(scenario)


def test_read_only_entry_is_refused_next_to_an_administrator_entry(run_in_hass):
    """Each entity follows its own entry, on the same action."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["system.global.id"] = "system-a"
        await async_add_entry(hass, name="Admin", access_level="admin")
        server.results["system.global.id"] = "system-b"
        await async_add_entry(hass, name="Reader", access_level="read_only")
        sent = _requests(server)

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "system_reboot",
                {"entity_id": "sensor.reader_system_uptime"},
                blocking=True,
            )
        assert _requests(server) == sent

        await hass.services.async_call(
            DOMAIN,
            "system_reboot",
            {"entity_id": "sensor.admin_system_uptime"},
            blocking=True,
        )
        assert _requests(server) > sent

    run_in_hass(scenario)


def test_vm_start_still_receives_overcommit(run_in_hass):
    """Actions get the same arguments as before."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        server.results["vm.get_instance"] = {"status": {"state": "STOPPED"}}
        await async_add_entry(hass)

        await hass.services.async_call(
            DOMAIN,
            "vm_start",
            {"entity_id": "binary_sensor.truenas_vms_debian", "overcommit": True},
            blocking=True,
        )

        assert [
            request["params"]
            for socket in server.sockets
            for request in socket.requests
            if request["method"] == "vm.start"
        ] == [[6, {"overcommit": True}]]

    run_in_hass(scenario)


def test_install_is_not_possible_on_a_read_only_update_entity(run_in_hass):
    """Update entities use Home Assistant's own action, which needs the feature."""

    async def scenario(hass, server):
        server.results = answers("25.10")
        await async_add_entry(hass, access_level="read_only")
        sent = _requests(server)

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "update",
                "install",
                {"entity_id": "update.truenas_apps_plex"},
                blocking=True,
            )

        assert _requests(server) == sent

    run_in_hass(scenario)


def test_integration_cannot_be_set_up_from_yaml():
    """Its configuration is only in config entries."""
    from custom_components import truenas_link

    assert truenas_link.CONFIG_SCHEMA({}) == {}
