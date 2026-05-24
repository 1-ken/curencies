"""Tests for Africa/Nairobi timezone formatting."""
from datetime import datetime, timezone

from app.utils.kenya_time import format_kenya_iso, parse_to_aware_utc, to_kenya


def test_format_kenya_iso_from_utc():
    utc = datetime(2026, 5, 24, 9, 30, 0, tzinfo=timezone.utc)
    kenya = format_kenya_iso(utc)
    assert kenya is not None
    assert "+03:00" in kenya or kenya.endswith("+0300")
    assert "12:30:00" in kenya


def test_parse_kenya_offset_to_utc():
    parsed = parse_to_aware_utc("2026-05-24T12:30:00+03:00")
    assert parsed is not None
    assert parsed.hour == 9
    assert parsed.minute == 30


def test_to_kenya_from_string():
    kenya = to_kenya("2026-05-24T09:30:00+00:00")
    assert kenya is not None
    assert kenya.utcoffset().total_seconds() == 3 * 3600
