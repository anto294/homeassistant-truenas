"""Tests for the API parser."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.truenas_link.apiparser import parse_api, utc_from_timestamp


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
