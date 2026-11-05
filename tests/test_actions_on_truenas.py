"""Tests for actions through Home Assistant's services, on each TrueNAS release."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.truenas_link.const import DOMAIN

from .conftest import async_add_entry
from .sample_data import answers

WIN11 = "binary_sensor.truenas_vms_win11"
DEBIAN = "binary_sensor.truenas_vms_debian"
ALPINE = "binary_sensor.truenas_vms_alpine"
WEB = "binary_sensor.truenas_containers_web"
DB = "binary_sensor.truenas_containers_db"
CIFS = "binary_sensor.truenas_services_cifs"
SSH = "binary_sensor.truenas_services_ssh"
PLEX = "binary_sensor.truenas_apps_plex"
CUSTOM = "binary_sensor.truenas_apps_custom_app"
OFFSITE = "sensor.truenas_cloudsync_offsite_backup"


async def _setup(hass, server, version):
    """Add an entry on a TrueNAS release, and return a way to see what was sent."""
    server.results = answers(version)
    entry = await async_add_entry(hass)

    def sent(method):
        return [
            request["params"]
            for socket in server.sockets
            for request in socket.requests
            if request["method"] == method
        ]

    return entry, sent


def _call(hass, action, entity_id, **data):
    """Run an action and wait for it."""
    return hass.services.async_call(
        DOMAIN, action, {"entity_id": entity_id, **data}, blocking=True
    )


async def _refused(hass, action, entity_id, key="invalid_state"):
    """Check that an action is refused without reaching TrueNAS."""
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, action, entity_id)
    assert err.value.translation_key == key


async def _failed(hass, action, entity_id, key):
    """Check that an action reports a failure."""
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, action, entity_id)
    assert err.value.translation_key == key


def test_vm_actions_on_25_10(run_in_hass):
    """vm.* takes the numeric id, which the entity keeps apart from its name."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["vm.get_instance"] = {"status": {"state": "STOPPED"}}

        await _call(hass, "vm_start", DEBIAN)
        await _call(hass, "vm_start", DEBIAN, overcommit=True)
        assert sent("vm.start") == [
            [6, {"overcommit": False}],
            [6, {"overcommit": True}],
        ]
        await _refused(hass, "vm_stop", DEBIAN)

        server.results["vm.get_instance"] = {"status": {"state": "RUNNING"}}
        await _call(hass, "vm_stop", WIN11)
        assert sent("vm.stop") == [[5, {"force_after_timeout": True}]]
        await _refused(hass, "vm_start", WIN11)

    run_in_hass(scenario)


@pytest.mark.parametrize(
    "answer", [None, [], {"status": None}, {"status": {}}], ids=str
)
def test_vm_state_that_cannot_be_read_stops_the_action(run_in_hass, answer):
    """Nothing is sent to a VM in an unknown state."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["vm.get_instance"] = answer

        await _failed(hass, "vm_start", DEBIAN, "action_invalid_response")
        assert sent("vm.start") == []

    run_in_hass(scenario)


def test_vm_left_over_from_25_04_has_no_id_to_use(run_in_hass):
    """An upgrade from 25.04 leaves an entry without the numeric id for a moment."""

    async def scenario(hass, server):
        entry, sent = await _setup(hass, server, "25.10")
        entry.runtime_data.ds["vm"]["debian"]["vm_id"] = 0

        await _failed(hass, "vm_start", DEBIAN, "action_invalid_response")
        assert sent("vm.get_instance") == []

    run_in_hass(scenario)


def test_vm_actions_on_25_04(run_in_hass):
    """virt.instance.* takes the name, and stops cleanly."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.04")
        server.results["virt.instance.get_instance"] = {"status": "STOPPED"}

        await _call(hass, "vm_start", ALPINE)
        assert sent("virt.instance.start") == [["alpine"]]
        await _refused(hass, "vm_stop", ALPINE)

        server.results["virt.instance.get_instance"] = {"status": "RUNNING"}
        await _call(hass, "vm_stop", WIN11)
        assert sent("virt.instance.stop") == [
            ["win11", {"timeout": 60, "force": False}]
        ]

        server.results["virt.instance.get_instance"] = None
        await _failed(hass, "vm_start", WIN11, "action_invalid_response")

    run_in_hass(scenario)


def test_container_actions_on_27_0(run_in_hass):
    """container.* takes the numeric id."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "27.0")
        server.results["container.get_instance"] = {"status": {"state": "STOPPED"}}

        await _call(hass, "container_start", DB)
        assert sent("container.start") == [[10]]
        await _refused(hass, "container_stop", DB)

        server.results["container.get_instance"] = {"status": {"state": "RUNNING"}}
        await _call(hass, "container_stop", WEB)
        assert sent("container.stop") == [[9, {"force_after_timeout": True}]]
        await _refused(hass, "container_start", WEB)

        server.results["container.get_instance"] = {"status": None}
        await _failed(hass, "container_stop", WEB, "action_invalid_response")

    run_in_hass(scenario)


@pytest.mark.parametrize("version", ["25.04", "25.10", "27.0"])
@pytest.mark.parametrize(
    ("action", "method", "entity_id", "state"),
    [
        ("service_start", "service.start", SSH, "STOPPED"),
        ("service_stop", "service.stop", CIFS, "RUNNING"),
        ("service_restart", "service.restart", CIFS, "RUNNING"),
        ("service_reload", "service.reload", CIFS, "RUNNING"),
    ],
)
def test_service_actions(run_in_hass, version, action, method, entity_id, state):
    """Each action reaches its method, and a false answer is an error."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, version)
        server.results["service.get_instance"] = {"state": state}
        server.results[method] = True

        await _call(hass, action, entity_id)
        assert len(sent(method)) == 1

        server.results[method] = False
        await _failed(hass, action, entity_id, "action_failed")

    run_in_hass(scenario)


@pytest.mark.parametrize(
    ("action", "state"),
    [
        ("service_start", "RUNNING"),
        ("service_stop", "STOPPED"),
        ("service_restart", "STOPPED"),
        ("service_reload", "STOPPED"),
    ],
)
def test_service_action_that_does_not_apply(run_in_hass, action, state):
    """It is refused before anything changes."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["service.get_instance"] = {"state": state}

        await _refused(hass, action, CIFS)
        assert sent(f"service.{action.split('_')[1]}") == []

    run_in_hass(scenario)


def test_service_state_that_cannot_be_read(run_in_hass):
    """Nothing is sent."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["service.get_instance"] = {}

        await _failed(hass, "service_stop", CIFS, "action_invalid_response")
        assert sent("service.stop") == []

    run_in_hass(scenario)


def test_app_actions(run_in_hass):
    """Apps are started and stopped by their id."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["app.get_instance"] = {"state": "STOPPED"}

        await _call(hass, "app_start", CUSTOM)
        assert sent("app.start") == [["custom-app"]]
        await _refused(hass, "app_stop", CUSTOM)

        server.results["app.get_instance"] = {"state": "RUNNING"}
        await _call(hass, "app_stop", PLEX)
        assert sent("app.stop") == [["plex"]]
        await _refused(hass, "app_start", PLEX)

        server.results["app.get_instance"] = None
        await _failed(hass, "app_stop", PLEX, "action_invalid_response")

    run_in_hass(scenario)


def test_cloud_sync_state_that_cannot_be_read(run_in_hass):
    """Nothing is started when the answer has no job."""

    async def scenario(hass, server):
        _, sent = await _setup(hass, server, "25.10")
        server.results["cloudsync.get_instance"] = {"id": 1}

        await _failed(hass, "cloudsync_run", OFFSITE, "action_invalid_response")
        assert sent("cloudsync.sync") == []

    run_in_hass(scenario)


DISK = "sensor.truenas_disks_sda"
HEALTHY = "binary_sensor.truenas_system_tank_healthy"


@pytest.mark.parametrize(
    ("action", "entity_id"),
    [
        ("cloudsync_run", DISK),
        ("cloudsync_abort", DISK),
        ("pool_scrub_pause", DISK),
        ("dataset_snapshot", DISK),
        ("system_reboot", DISK),
        ("vm_start", HEALTHY),
        ("vm_stop", HEALTHY),
        ("service_reload", HEALTHY),
    ],
)
def test_action_on_an_entity_it_does_not_apply_to(run_in_hass, action, entity_id):
    """Home Assistant lets any entity of the integration be a target."""

    async def scenario(hass, server):
        await _setup(hass, server, "25.10")

        with pytest.raises(NotImplementedError):
            await _call(hass, action, entity_id)

    run_in_hass(scenario)
