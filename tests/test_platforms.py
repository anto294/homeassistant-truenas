"""Tests for the platforms' hand-off to entity.async_add_entities."""

from __future__ import annotations

import asyncio
import importlib

import pytest


@pytest.mark.parametrize(
    ("platform", "types_module"),
    [
        ("sensor", "sensor_types"),
        ("binary_sensor", "binary_sensor_types"),
        ("update", "update_types"),
    ],
)
def test_platform_passes_its_own_descriptions_and_services(
    monkeypatch, platform, types_module
):
    """Each platform hands its SENSOR_TYPES and SENSOR_SERVICES over."""
    module = importlib.import_module(f"custom_components.truenas_link.{platform}")
    types = importlib.import_module(f"custom_components.truenas_link.{types_module}")
    received = {}

    async def fake_add_entities(hass, config_entry, dispatcher, descriptions, services):
        received.update(
            dispatcher=dispatcher, descriptions=descriptions, services=services
        )

    monkeypatch.setattr(module, "async_add_entities", fake_add_entities)

    asyncio.run(module.async_setup_entry(object(), object(), None))

    assert received["descriptions"] is types.SENSOR_TYPES
    assert received["services"] is types.SENSOR_SERVICES
    # Every description's entity class is in the platform's dispatcher
    assert {d.func for d in types.SENSOR_TYPES} <= set(received["dispatcher"])
