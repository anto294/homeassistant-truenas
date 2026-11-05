"""Tests that secrets stay out of Home Assistant, its logs and diagnostics."""

from __future__ import annotations

import json
import logging

import pytest

from custom_components.truenas_link.const import TO_REDACT
from custom_components.truenas_link.apiparser import parse_api
from custom_components.truenas_link.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.truenas_link.helper import redact_secrets

from .conftest import async_add_entry

API_LOGGER = "custom_components.truenas_link.api"
PARSER_LOGGER = "custom_components.truenas_link.apiparser"
FAKE_SECRET = "finto-valore-test"
APP = {
    "id": "scrutiny",
    "name": "scrutiny",
    "state": "RUNNING",
    "human_version": "1.0",
    "version": "1.0",
    "latest_version": "1.0",
    "upgrade_available": False,
    "image_updates_available": False,
    "custom_app": False,
    "portals": {},
    "notes": f"Default Credentials\nPassword: {FAKE_SECRET}",
}
JOB = {
    "state": "RUNNING",
    "time_started": {"$date": 1000},
    "time_finished": None,
    "progress": {"percent": 40, "description": "copying"},
}
CLOUDSYNC = {
    "id": 1,
    "description": "offsite",
    "direction": "PUSH",
    "path": "/mnt/tank",
    "enabled": True,
    "transfer_mode": "COPY",
    "snapshot": False,
    "job": JOB,
    "encryption_password": "cloud-secret-1",
    "credentials": {
        "id": 1,
        "provider": {
            "type": "S3",
            "access_key_id": "cloud-secret-2",
            "secret_access_key": "cloud-secret-3",
        },
    },
}
REPLICATION = {
    "id": 2,
    "name": "backup",
    "source_datasets": ["tank/data"],
    "target_dataset": "backup/data",
    "recursive": True,
    "enabled": True,
    "direction": "PUSH",
    "transport": "SSH",
    "auto": True,
    "retention_policy": "SOURCE",
    "job": JOB,
    "encryption_key": "replication-secret-1",
    "ssh_credentials": {
        "id": 1,
        "attributes": {"private_key": "replication-secret-2"},
    },
}


def test_task_secrets_are_not_requested_and_every_field_still_arrives(
    run_in_hass, caplog
):
    """select keeps secrets out, and what the sensors read in."""

    async def scenario(hass, server):
        server.results["cloudsync.query"] = [CLOUDSYNC]
        server.results["replication.query"] = [REPLICATION]

        with caplog.at_level(logging.DEBUG):
            entry = await async_add_entry(hass)

        ds = entry.runtime_data.ds
        task = next(iter(ds["cloudsync"].values()))
        assert task["description"] == "offsite"
        assert task["transfer_mode"] == "COPY"
        assert task["state"] == "RUNNING"
        assert task["job_percent"] == 40
        replication = next(iter(ds["replication"].values()))
        assert replication["name"] == "backup"
        assert replication["retention_policy"] == "SOURCE"
        assert replication["state"] == "RUNNING"
        assert "secret" not in json.dumps(ds, default=str)
        assert "cloud-secret" not in caplog.text
        assert "replication-secret" not in caplog.text

    run_in_hass(scenario)


def test_log_redacts_a_response_that_was_not_filtered(connected_api, caplog):
    """Secrets are hidden at any depth, and the caller still gets the real data."""
    response = {
        "name": "visible-name",
        "items": [{"attributes": {"Token": "secret-1", "pass": "secret-2"}}],
        "private_key": "secret-3",
        "client_secret": "secret-4",
        "encryption_key": None,
    }
    api, _ = connected_api(lambda request: {"id": 0, "result": response})

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        assert api.query("cloudsync.get_instance", [1]) == response

    assert "visible-name" in caplog.text
    assert "secret-" not in caplog.text


def test_log_redacts_a_list_response(connected_api, caplog):
    """A list of objects is redacted too."""
    api, _ = connected_api(
        lambda request: {"id": 0, "result": [{"secret_access_key": "secret-1"}]}
    )

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        api.query("cloudsync.query")

    assert "secret-1" not in caplog.text


def test_log_redacts_the_request(connected_api, caplog):
    """What goes out is hidden as well."""
    api, _ = connected_api(lambda request: {"id": 0, "result": None})

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        api.query("some.method", [{"password": "secret-1"}])

    assert "secret-1" not in caplog.text


def test_log_leaves_out_a_response_that_is_not_json(connected_api, caplog):
    """Plain text cannot be redacted key by key, so only its size is logged."""
    api, _ = connected_api(lambda request: "token=secret-1")

    with caplog.at_level(logging.DEBUG, logger=API_LOGGER):
        assert api.query("some.method") == "token=secret-1"

    assert "secret-1" not in caplog.text
    assert "<14 characters>" in caplog.text


def test_redact_keeps_empty_values_and_does_not_change_the_input():
    """None tells that nothing is set, and the data in use stays untouched."""
    data = {"token": None, "key": "secret"}

    assert redact_secrets(data) == {"token": None, "key": "**REDACTED**"}
    assert data["key"] == "secret"


def test_parser_keeps_redacted_values_in_its_result(caplog):
    """TO_REDACT only affects parse_api's debug log, not the data."""
    source = {"hostname": "my-nas", "link_address": "aa:bb"}

    with caplog.at_level(
        logging.DEBUG, logger="custom_components.truenas_link.apiparser"
    ):
        result = parse_api(
            data={},
            source=source,
            vals=[
                {"name": "hostname", "default": "unknown"},
                {"name": "link_address", "default": "unknown"},
            ],
        )

    assert result == source
    assert "my-nas" not in caplog.text
    assert "aa:bb" not in caplog.text


def test_new_keys_are_lower_case():
    """The log comparison lowers the key, so TO_REDACT has to be lower case."""
    assert all(key == key.lower() for key in TO_REDACT)


def test_diagnostics_hide_what_identifies_the_system(run_in_hass):
    """Diagnostics are made to be shared, so they carry no identifying data."""

    async def scenario(hass, server):
        server.results["system.info"] = {
            **server.results["system.info"],
            "hostname": "my-nas",
            "system_serial": "my-serial",
        }
        server.results["interface.query"] = [
            {
                "id": "eth0",
                "name": "eth0",
                "state": {"link_address": "aa:bb:cc:dd:ee:ff"},
            }
        ]
        entry = await async_add_entry(hass, host="my-host", api_key="good")

        result = await async_get_config_entry_diagnostics(hass, entry)
        text = json.dumps(result, default=str)

        for secret in ("my-nas", "my-serial", "aa:bb:cc:dd:ee:ff", "my-host", "good"):
            assert secret not in text
        assert result["entry"]["data"]["name"] == "TrueNAS"
        assert result["data"]["system_info"]["version"] == "25.10.1"
        assert result["data"]["interface"]["eth0"]["name"] == "eth0"
        # The data in use keeps its values
        ds = entry.runtime_data.ds
        assert ds["system_info"]["hostname"] == "my-nas"

    run_in_hass(scenario)


def test_app_notes_stay_out_of_logs_entities_and_diagnostics(run_in_hass, caplog):
    """App notes can list credentials, so they appear nowhere, and the app works."""

    async def scenario(hass, server):
        server.results["app.query"] = [APP]

        with caplog.at_level(logging.DEBUG):
            entry = await async_add_entry(hass)

        # Both loggers did log this response, without its notes
        logged = [
            record.getMessage()
            for record in caplog.records
            if record.name in (API_LOGGER, PARSER_LOGGER)
            and "scrutiny" in record.getMessage()
        ]
        assert {API_LOGGER, PARSER_LOGGER} <= {
            record.name
            for record in caplog.records
            if "scrutiny" in record.getMessage()
        }
        assert logged
        assert FAKE_SECRET not in caplog.text

        ds = entry.runtime_data.ds
        assert ds["app"]["scrutiny"]["name"] == "scrutiny"
        assert "notes" not in ds["app"]["scrutiny"]
        assert FAKE_SECRET not in json.dumps(ds, default=str)

        states = hass.states.async_all()
        assert any("scrutiny" in state.entity_id for state in states)
        for state in states:
            assert FAKE_SECRET not in str(state.state)
            assert FAKE_SECRET not in str(state.attributes)

        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert FAKE_SECRET not in json.dumps(diagnostics, default=str)

    run_in_hass(scenario)


@pytest.mark.parametrize(
    "field",
    [
        "notes",
        "Notes",
        "comments",
        "description",
        "user_properties",
        "command",
        "command_line_args",
        "environment",
        "initenv",
        "vnc_password",
        "credentials",
        "arguments",
        "logs_excerpt",
        "exception",
        "args",
        "formatted",
        "text",
    ],
)
@pytest.mark.parametrize(
    "value", [FAKE_SECRET, {"nested": FAKE_SECRET}, [FAKE_SECRET]], ids=str
)
def test_free_text_fields_stay_out_of_both_debug_logs(
    connected_api, caplog, field, value
):
    """A field is hidden as a whole, at any depth, and the data stays complete."""
    response = {"name": "visible-name", "details": [{field: value}]}
    api, _ = connected_api(lambda request: {"id": 0, "result": response})

    with caplog.at_level(logging.DEBUG):
        result = api.query("some.query")
        parse_api(data={}, source=result, key="name", vals=[{"name": "name"}])

    assert result == response
    assert {API_LOGGER, PARSER_LOGGER} <= {record.name for record in caplog.records}
    assert "visible-name" in caplog.text
    assert FAKE_SECRET not in caplog.text


def test_diagnostics_hide_a_cron_jobs_description_and_its_copy(run_in_hass):
    """cron_name repeats a description, which can hold anything."""

    async def scenario(hass, server):
        server.results["cronjob.query"] = [
            {
                "id": 1,
                "description": FAKE_SECRET,
                "enabled": True,
                "schedule": {"minute": "0"},
            }
        ]
        entry = await async_add_entry(hass)

        ds = entry.runtime_data.ds
        assert ds["cronjob"][1]["cron_name"] == FAKE_SECRET
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert FAKE_SECRET not in json.dumps(diagnostics, default=str)

    run_in_hass(scenario)
