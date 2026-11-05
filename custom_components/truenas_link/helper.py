"""Helper functions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import ACCESS_LEVEL_READ_ONLY, CONF_ACCESS_LEVEL, LEGACY_ACCESS_LEVEL


# ---------------------------
#   format_attribute
# ---------------------------
def format_attribute(attr: str) -> str:
    """Format attribute."""
    attr = attr.replace("_", " ")
    attr = attr.replace("-", " ")
    attr = attr.capitalize()
    attr = attr.replace("zfs", "ZFS")
    attr = attr.replace(" gib", " GiB")
    attr = attr.replace("Cpu ", "CPU ")
    attr = attr.replace("Vcpu ", "vCPU ")
    attr = attr.replace("Vmware ", "VMware ")
    attr = attr.replace("Ip4 ", "IP4 ")
    attr = attr.replace("Ip6 ", "IP6 ")
    return attr


# ---------------------------
#   is_read_only
# ---------------------------
def is_read_only(entry_data: Mapping[str, Any]) -> bool:
    """Return whether a config entry's data selects the read-only access level."""
    return (
        entry_data.get(CONF_ACCESS_LEVEL, LEGACY_ACCESS_LEVEL) == ACCESS_LEVEL_READ_ONLY
    )
