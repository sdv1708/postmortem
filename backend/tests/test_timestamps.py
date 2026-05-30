from __future__ import annotations

from datetime import datetime, timezone

from postmortem.timestamps import parse_timestamp


def test_iso_utc_with_z_is_normalized():
    parsed = parse_timestamp("2026-05-09T14:28:31Z api returned 500")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 14, 28, 31, tzinfo=timezone.utc)
    assert parsed.inferred is False
    assert parsed.original_text.startswith("2026-05-09T14:28:31")


def test_space_separated_datetime_assumed_utc():
    parsed = parse_timestamp("2026-05-09 14:28:31 deploy started")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 14, 28, 31, tzinfo=timezone.utc)
    assert parsed.inferred is False


def test_timezone_offset_is_converted_to_utc():
    parsed = parse_timestamp("2026-05-09T16:28:31+02:00 deploy started")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 14, 28, 31, tzinfo=timezone.utc)
    assert parsed.inferred is False


def test_minute_precision_without_seconds():
    parsed = parse_timestamp("2026-05-09 14:28 something happened")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 14, 28, tzinfo=timezone.utc)
    assert parsed.inferred is False


def test_fractional_seconds_with_offset_converts_to_utc():
    # Regression: fractional seconds must not stop the tz offset from applying.
    parsed = parse_timestamp("2026-05-09T14:28:31.250+02:00 deploy started")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 12, 28, 31, tzinfo=timezone.utc)
    assert parsed.inferred is False


def test_fractional_seconds_utc_is_truncated_to_seconds():
    parsed = parse_timestamp("2026-05-09T14:28:31.250Z api 500")
    assert parsed is not None
    assert parsed.normalized == datetime(2026, 5, 9, 14, 28, 31, tzinfo=timezone.utc)


def test_time_only_is_inferred_and_unnormalized():
    parsed = parse_timestamp("14:32 api 500s spike")
    assert parsed is not None
    assert parsed.normalized is None
    assert parsed.inferred is True
    assert parsed.original_text == "14:32"


def test_bracketed_time_only_keeps_brackets_in_original_text():
    # Regression: original_text must include the brackets so a downstream
    # consumer can strip the verbatim prefix from the cited line.
    parsed = parse_timestamp("[14:40] dashboards went red")
    assert parsed is not None
    assert parsed.original_text == "[14:40]"
    assert parsed.inferred is True


def test_relative_phrasing_is_inferred():
    parsed = parse_timestamp("~5 min later the errors cleared")
    assert parsed is not None
    assert parsed.normalized is None
    assert parsed.inferred is True


def test_line_without_timestamp_returns_none():
    assert parse_timestamp("the on-call engineer paged the team") is None
    assert parse_timestamp("") is None
