"""Tests for the platforms' hand-off to entity.async_add_entities."""

from __future__ import annotations

import asyncio
import importlib

import pytest

from custom_components.truenas_link.const import PLATFORMS


@pytest.mark.parametrize(
    ("platform", "types_module"),
    [
        ("sensor", "sensor_types"),
        ("binary_sensor", "binary_sensor_types"),
        ("update", "update_types"),
    ],
)
def test_platform_passes_its_own_descriptions(monkeypatch, platform, types_module):
    """Each platform hands its SENSOR_TYPES over."""
    module = importlib.import_module(f"custom_components.truenas_link.{platform}")
    types = importlib.import_module(f"custom_components.truenas_link.{types_module}")
    received = {}

    async def fake_add_entities(config_entry, add_entities, dispatcher, descriptions):
        received.update(dispatcher=dispatcher, descriptions=descriptions)

    monkeypatch.setattr(module, "async_add_entities", fake_add_entities)

    asyncio.run(module.async_setup_entry(object(), object(), None))

    assert received["descriptions"] is types.SENSOR_TYPES
    # Every description's entity class is in the platform's dispatcher
    assert {d.func for d in types.SENSOR_TYPES} <= set(received["dispatcher"])


@pytest.mark.parametrize("platform", [platform.value for platform in PLATFORMS])
def test_platform_sets_parallel_updates(platform):
    """Every platform says how many actions it runs at a time."""
    module = importlib.import_module(f"custom_components.truenas_link.{platform}")

    assert module.PARALLEL_UPDATES == 1
