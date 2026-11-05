"""Remove what no longer exists on TrueNAS from Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from . import binary_sensor_types, sensor_types, switch_types, update_types
from .coordinator import TrueNASConfigEntry, TrueNASCoordinator

# Per-item descriptions, with the domain of their platform: unique ids are only
# unique within one
_ITEM_DESCRIPTIONS: tuple[tuple[str, Any], ...] = tuple(
    (domain, description)
    for domain, descriptions in (
        ("sensor", sensor_types.SENSOR_TYPES),
        ("binary_sensor", binary_sensor_types.SENSOR_TYPES),
        ("update", update_types.SENSOR_TYPES),
        ("switch", switch_types.SENSOR_TYPES),
    )
    for description in descriptions
    if description.data_reference
)


def _unique_id(coordinator: TrueNASCoordinator, key: str, reference: object) -> str:
    """Return the unique id of an entity of an item, as TrueNASEntity builds it."""
    return f"{coordinator.instance.lower()}-{key}-{slugify(str(reference).lower())}"


def _description_of(coordinator: TrueNASCoordinator, entity: er.RegistryEntry) -> Any:
    """Return the per-item description a registry entry belongs to, if any."""
    prefix = coordinator.instance.lower()
    for domain, description in _ITEM_DESCRIPTIONS:
        if entity.domain == domain and entity.unique_id.startswith(
            f"{prefix}-{description.key}-"
        ):
            return description

    return None


def _dataset_of_absent_pool(coordinator: TrueNASCoordinator, suffix: str) -> bool:
    """Return whether a registry-only dataset may belong to a pool not imported."""
    return not any(
        suffix == slug or suffix.startswith(f"{slug}_")
        for slug in map(slugify, map(str.lower, coordinator.pool_names))
    )


# ---------------------------
#   async_remove_stale_entities
# ---------------------------
@callback
def async_remove_stale_entities(
    hass: HomeAssistant, config_entry: TrueNASConfigEntry
) -> None:
    """Remove entities whose item has been gone for many successful polls.

    Removing an entity loses its customizations, so this only counts sections
    that TrueNAS has just answered with a list that is not empty. It looks at the
    registry and not at the data: after a restart, an item deleted while Home
    Assistant was off is only there.
    """
    coordinator = config_entry.runtime_data
    if not coordinator.last_update_success:
        return

    registry = er.async_get(hass)
    counts = coordinator.stale_entity_polls
    seen = set()
    for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        description = _description_of(coordinator, entity)
        if description is None or description.data_path not in coordinator.answered:
            continue

        section = description.data_path
        reference = description.data_reference
        expected = {
            _unique_id(coordinator, description.key, item.get(reference))
            for uid, item in coordinator.ds[section].items()
            if not coordinator.is_missing(section, uid)
        }
        if entity.unique_id in expected:
            continue

        # An item still in the data but missing, or only in the registry
        suffix = entity.unique_id.removeprefix(
            f"{coordinator.instance.lower()}-{description.key}-"
        )
        if section == "dataset" and _dataset_of_absent_pool(coordinator, suffix):
            continue

        seen.add(entity.entity_id)
        counts[entity.entity_id] = counts.get(entity.entity_id, 0) + 1
        if counts[entity.entity_id] >= coordinator.stale_after_polls:
            registry.async_remove(entity.entity_id)
            seen.discard(entity.entity_id)

    # Items that came back start over
    for entity_id in set(counts) - seen:
        del counts[entity_id]


# ---------------------------
#   async_can_remove_device
# ---------------------------
@callback
def async_can_remove_device(
    hass: HomeAssistant,
    config_entry: TrueNASConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Return whether the user may delete a device, and forget what it held.

    This is the way out for what is never removed automatically: an item that was
    the last of its section, which leaves an empty list. The System device stays,
    and so does a device with anything TrueNAS still reports.
    """
    if device_entry.identifiers:
        return False

    coordinator = config_entry.runtime_data
    sections = set()
    for entity in er.async_entries_for_device(
        er.async_get(hass), device_entry.id, include_disabled_entities=True
    ):
        description = _description_of(coordinator, entity)
        if description is None:
            return False

        section = description.data_path
        present = coordinator.present.get(section)
        if present is None:
            # Unknown so far, so it may well be there
            return False

        for uid in present:
            item = coordinator.ds[section].get(uid, {})
            reference = item.get(description.data_reference)
            if entity.unique_id == _unique_id(coordinator, description.key, reference):
                return False

        sections.add(section)

    for section in sections:
        for uid in set(coordinator.ds[section]) - coordinator.present[section]:
            del coordinator.ds[section][uid]

    # So platforms forget the items, and add them again if they come back
    coordinator.async_update_listeners()
    return True
