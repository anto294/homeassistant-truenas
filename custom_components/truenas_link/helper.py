"""Helper functions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    ACCESS_LEVEL_READ_ONLY,
    CONF_ACCESS_LEVEL,
    DEFAULT_ACCESS_LEVEL,
    DISCOVERED_ID_PREFIX,
    TO_REDACT,
)


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
def is_read_only(entry_options: Mapping[str, Any]) -> bool:
    """Return whether a config entry's options select the read-only access level.

    Every entry has the option, since the migration to version 2. If it were lost,
    this must not grant more than a new entry gets.
    """
    level = entry_options.get(CONF_ACCESS_LEVEL, DEFAULT_ACCESS_LEVEL)
    return bool(level == ACCESS_LEVEL_READ_ONLY)


# ---------------------------
#   is_system_id
# ---------------------------
def is_system_id(unique_id: str | None) -> bool:
    """Return whether the unique id of a set up entry is the id of its system."""
    return unique_id is not None and not unique_id.startswith(DISCOVERED_ID_PREFIX)


# ---------------------------
#   redact_secrets
# ---------------------------
def redact_secrets(data: Any) -> Any:
    """Return a copy of an API request or response that is safe to log."""
    if isinstance(data, Mapping):
        return {
            key: (
                "**REDACTED**"
                if str(key).lower() in TO_REDACT and value is not None
                else redact_secrets(value)
            )
            for key, value in data.items()
        }

    if isinstance(data, (list, tuple)):
        return [redact_secrets(item) for item in data]

    return data
