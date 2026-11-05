"""API parser for JSON APIs."""

from datetime import UTC, datetime
from logging import getLogger

from .helper import redact_secrets

_LOGGER = getLogger(__name__)


# ---------------------------
#   utc_from_timestamp
# ---------------------------
def utc_from_timestamp(timestamp: float) -> datetime:
    """Return a UTC time from a timestamp."""
    return datetime.fromtimestamp(timestamp, UTC)


# ---------------------------
#   from_entry
# ---------------------------
def from_entry(entry, param, default="") -> str:
    """Validate and return str value an API dict."""
    if "/" in param:
        for tmp_param in param.split("/"):
            if isinstance(entry, dict) and tmp_param in entry:
                entry = entry[tmp_param]
            else:
                return default

        ret = entry
    elif param in entry:
        ret = entry[param]
    else:
        return default

    if default != "":
        if isinstance(ret, str):
            ret = str(ret)
        elif isinstance(ret, int):
            ret = int(ret)
        elif isinstance(ret, float):
            ret = round(float(ret), 2)

    return ret[:255] if isinstance(ret, str) and len(ret) > 255 else ret


# ---------------------------
#   from_entry_bool
# ---------------------------
def from_entry_bool(entry, param, default=False) -> bool:
    """Validate and return a bool value from an API dict."""
    if "/" in param:
        for tmp_param in param.split("/"):
            if isinstance(entry, dict) and tmp_param in entry:
                entry = entry[tmp_param]
            else:
                return default

        ret = entry
    elif param in entry:
        ret = entry[param]
    else:
        return default

    if isinstance(ret, str):
        if ret in ("on", "On", "ON", "yes", "Yes", "YES", "up", "Up", "UP"):
            ret = True
        elif ret in ("off", "Off", "OFF", "no", "No", "NO", "down", "Down", "DOWN"):
            ret = False

    if not isinstance(ret, bool):
        ret = default

    return ret


# ---------------------------
#   parse_api
# ---------------------------
def parse_api(
    data=None,
    source=None,
    key=None,
    vals=None,
    ensure_vals=None,
) -> dict:
    """Get data from API."""
    debug = _LOGGER.getEffectiveLevel() == 10
    if type(source) == dict:
        tmp = source
        source = [tmp]

    if not source:
        if not key:
            data = fill_defaults(data, vals)
        return data

    if debug:
        _LOGGER.debug("Processing source %s", redact_secrets(source))

    for entry in source:
        uid = None
        if key:
            uid = entry.get(key)
            if not uid:
                continue

            if uid not in data:
                data[uid] = {}

        if debug:
            _LOGGER.debug("Processing entry %s", redact_secrets(entry))

        if vals:
            data = fill_vals(data, entry, uid, vals)

        if ensure_vals:
            data = fill_ensure_vals(data, uid, ensure_vals)

    return data


# ---------------------------
#   fill_defaults
# ---------------------------
def fill_defaults(data, vals) -> dict:
    """Fill defaults if source is not present."""
    for val in vals:
        _name = val["name"]
        _type = val["type"] if "type" in val else "str"
        _source = val["source"] if "source" in val else _name

        if _type == "str":
            _default = val["default"] if "default" in val else ""
            if _name not in data:
                data[_name] = from_entry([], _source, default=_default)

        elif _type == "bool":
            _default = val["default"] if "default" in val else False
            if _name not in data:
                data[_name] = from_entry_bool([], _source, default=_default)

    return data


# ---------------------------
#   fill_vals
# ---------------------------
def fill_vals(data, entry, uid, vals) -> dict:
    """Fill all data."""
    for val in vals:
        _name = val["name"]
        _type = val["type"] if "type" in val else "str"
        _source = val["source"] if "source" in val else _name
        _convert = val["convert"] if "convert" in val else None

        if _type == "str":
            _default = val["default"] if "default" in val else ""
            if uid:
                data[uid][_name] = from_entry(entry, _source, default=_default)
            else:
                data[_name] = from_entry(entry, _source, default=_default)

        elif _type == "bool":
            _default = val["default"] if "default" in val else False

            if uid:
                data[uid][_name] = from_entry_bool(entry, _source, default=_default)
            else:
                data[_name] = from_entry_bool(entry, _source, default=_default)

        if _convert == "utc_from_timestamp":
            if uid:
                if isinstance(data[uid][_name], int) and data[uid][_name] > 0:
                    if data[uid][_name] > 100000000000:
                        data[uid][_name] = data[uid][_name] / 1000

                    data[uid][_name] = utc_from_timestamp(data[uid][_name])
            elif isinstance(data[_name], int) and data[_name] > 0:
                if data[_name] > 100000000000:
                    data[_name] = data[_name] / 1000

                data[_name] = utc_from_timestamp(data[_name])

    return data


# ---------------------------
#   fill_ensure_vals
# ---------------------------
def fill_ensure_vals(data, uid, ensure_vals) -> dict:
    """Add required keys which are not available in data."""
    for val in ensure_vals:
        if uid:
            if val["name"] not in data[uid]:
                _default = val["default"] if "default" in val else ""
                data[uid][val["name"]] = _default

        elif val["name"] not in data:
            _default = val["default"] if "default" in val else ""
            data[val["name"]] = _default

    return data
