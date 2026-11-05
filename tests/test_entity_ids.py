"""Tests that entity ids and unique ids never change.

Users' history, dashboards and automations depend on them, and so does the upgrade
from 1.x, where users add the entry again with the same name. The expected list in
snapshots/entity_ids.json was saved from the code before entity names were
translated. Never regenerate it to make a test pass: a difference is a bug. Only
adding a new entity may extend it. To add one:
TRUENAS_UPDATE_ENTITY_IDS=1 python -m pytest tests/test_entity_ids.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from homeassistant.helpers import entity_registry as er
import pytest

from .conftest import async_add_entry
from .sample_data import answers

SNAPSHOT = Path(__file__).parent / "snapshots" / "entity_ids.json"
CASES = [
    ("TrueNAS", "25.04"),
    ("TrueNAS", "25.10"),
    ("TrueNAS", "27.0"),
    ("My NAS", "27.0"),
]


def _load() -> dict:
    """Return the saved lists."""
    return json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}


@pytest.mark.parametrize("language", ["en", "it"])
@pytest.mark.parametrize(("name", "version"), CASES)
def test_entity_ids_and_unique_ids_do_not_change(run_in_hass, name, version, language):
    """Each entity keeps the id and unique id it was saved with, in any language."""

    async def scenario(hass, server):
        hass.config.language = language
        server.results = answers(version)
        entry = await async_add_entry(hass, name=name)
        registry = er.async_get(hass)
        found = sorted(
            [item.entity_id, item.unique_id]
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        )
        assert found

        key = f"{name} {version}"
        saved = _load()
        if os.environ.get("TRUENAS_UPDATE_ENTITY_IDS"):
            saved[key] = found
            SNAPSHOT.write_text(json.dumps(saved, indent=1) + "\n")

        assert found == saved[key]

    run_in_hass(scenario)
