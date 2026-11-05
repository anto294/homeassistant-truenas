"""Tests for the API parser."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.truenas_link.apiparser import parse_api, utc_from_timestamp

CONVERT = "utc_from_timestamp"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (0, datetime(1970, 1, 1, tzinfo=UTC)),
        (1762250000, datetime(2025, 11, 4, 9, 53, 20, tzinfo=UTC)),
        (1762250000.123, datetime(2025, 11, 4, 9, 53, 20, 123000, tzinfo=UTC)),
    ],
)
def test_utc_from_timestamp(timestamp, expected):
    """A timestamp gives the same instant, shown the same way, in UTC."""
    result = utc_from_timestamp(timestamp)

    assert result == expected
    assert result.utcoffset() == timedelta(0)
    assert result.isoformat() == expected.isoformat()


def test_timestamp_in_milliseconds_is_converted():
    """TrueNAS sends {"$date": milliseconds}, which becomes an aware datetime."""
    result = parse_api(
        data={},
        source={"end": {"$date": 1762250000123}},
        vals=[
            {
                "name": "end",
                "source": "end/$date",
                "default": 0,
                "convert": "utc_from_timestamp",
            }
        ],
    )

    assert result["end"] == datetime(2025, 11, 4, 9, 53, 20, 123000, tzinfo=UTC)


DATASET_VALS = [
    {"name": "name", "default": "unknown"},
    {"name": "atime", "source": "atime/parsed", "type": "bool", "default": False},
    {"name": "copies", "source": "copies/parsed", "default": 0},
    {"name": "quota", "source": "quota/parsed", "default": "unknown"},
]


def test_nested_values_of_an_item_are_read_by_path():
    """pool.dataset.query keeps each property's value under "parsed"."""
    data = parse_api(
        data={},
        source=[
            {
                "id": "tank",
                "name": "tank",
                "atime": {"parsed": True},
                "copies": {"parsed": 2},
                "quota": {"parsed": None},
            }
        ],
        key="id",
        vals=DATASET_VALS,
    )

    assert data["tank"] == {"name": "tank", "atime": True, "copies": 2, "quota": None}


def test_missing_paths_get_the_defaults():
    """A property that is not there, or a parent that is null, gives the default."""
    data = parse_api(
        data={},
        source=[{"id": "tank", "atime": None, "copies": "oops"}],
        key="id",
        vals=DATASET_VALS,
    )

    assert data["tank"] == {
        "name": "unknown",
        "atime": False,
        "copies": 0,
        "quota": "unknown",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("on", True),
        ("YES", True),
        ("Up", True),
        ("off", False),
        ("No", False),
        ("DOWN", False),
        ("maybe", False),
        (None, False),
        (1, False),
    ],
)
def test_bool_values(value, expected):
    """TrueNAS spells booleans in several ways. Anything else gives the default."""
    data = parse_api(
        data={},
        source={"state": value},
        vals=[{"name": "state", "type": "bool", "default": False}],
    )

    assert data["state"] is expected


def test_bool_default_for_a_field_that_is_not_there():
    """Top-level and nested."""
    data = parse_api(
        data={},
        source={"other": 1},
        vals=[
            {"name": "a", "type": "bool", "default": True},
            {"name": "b", "source": "x/y", "type": "bool"},
        ],
    )

    assert data == {"a": True, "b": False}


def test_values_keep_their_type_and_floats_are_rounded():
    """With a default, numbers stay numbers. Long texts are cut."""
    data = parse_api(
        data={},
        source={"mtu": 1500, "ratio": 1.23456, "text": "x" * 300, "raw": 1.23456},
        vals=[
            {"name": "mtu", "default": 0},
            {"name": "ratio", "default": 0},
            {"name": "text", "default": "unknown"},
            {"name": "raw"},
        ],
    )

    assert data["mtu"] == 1500
    assert data["ratio"] == 1.23
    assert len(data["text"]) == 255
    assert data["raw"] == 1.23456


def test_failed_query_gives_defaults_only_to_a_single_object():
    """system.info failing must leave the sensors' keys in place."""
    vals = [
        {"name": "version", "default": "unknown"},
        {"name": "hostname"},
        {"name": "ok", "type": "bool", "default": True},
        {"name": "off", "type": "bool"},
    ]

    assert parse_api(data={}, source=None, vals=vals) == {
        "version": "unknown",
        "hostname": "",
        "ok": True,
        "off": False,
    }
    assert parse_api(data={"version": "25.10"}, source=None, vals=vals)["version"] == (
        "25.10"
    )


def test_failed_query_keeps_the_items_of_a_list():
    """Values stay when a single query fails."""
    items = {"a": {"name": "a"}}

    assert parse_api(data=items, source=None, key="id", vals=[]) == items
    assert parse_api(data=items, source=[], key="id", vals=[]) == items


def test_entries_without_a_key_are_skipped():
    """They cannot be told apart. An id of 0 is not valid either."""
    data = parse_api(
        data={},
        source=[{"name": "no key"}, {"id": 0, "name": "zero"}, {"id": 7, "name": "ok"}],
        key="id",
        vals=[{"name": "name"}],
    )

    assert data == {7: {"name": "ok"}}


def test_ensure_vals_only_fill_what_is_missing():
    """A value from the last poll stays, for an item and for a single object."""
    ensure = [{"name": "temperature", "default": 0}, {"name": "label"}]

    data = parse_api(
        data={"a": {"temperature": 33}},
        source=[{"id": "a"}],
        key="id",
        ensure_vals=ensure,
    )
    assert data["a"] == {"temperature": 33, "label": ""}

    single = parse_api(data={"temperature": 33}, source={"x": 1}, ensure_vals=ensure)
    assert single == {"temperature": 33, "label": ""}


def test_dates_of_items_are_converted_from_seconds_and_milliseconds():
    """A job's time is in milliseconds, and a missing time stays 0."""
    vals = [
        {"name": "start", "source": "s/$date", "default": 0, "convert": CONVERT},
        {"name": "end", "source": "e/$date", "default": 0, "convert": CONVERT},
    ]
    source = [{"id": "a", "s": {"$date": 1762250000000}, "e": None}]

    item = parse_api(data={}, source=source, key="id", vals=vals)["a"]
    assert item["start"] == datetime(2025, 11, 4, 9, 53, 20, tzinfo=UTC)
    assert item["end"] == 0

    single = parse_api(
        data={},
        source={"s": {"$date": 1762250000}, "e": None},
        vals=vals,
    )
    assert single["start"] == datetime(2025, 11, 4, 9, 53, 20, tzinfo=UTC)
    assert single["end"] == 0
