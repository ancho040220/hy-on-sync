from datetime import datetime, timedelta

from hysync.dates import KST, due_stage, fmt_due, parse_iso, start_date


def test_parse_iso_converts_utc_to_kst():
    dt = parse_iso("2026-12-05T14:59:00Z")
    assert dt == datetime(2026, 12, 5, 23, 59, tzinfo=KST)
    assert dt.utcoffset() == timedelta(hours=9)


def test_parse_iso_handles_notion_millis_and_empty():
    assert parse_iso("2026-12-05T23:59:00.000+09:00") == datetime(2026, 12, 5, 23, 59, tzinfo=KST)
    assert parse_iso(None) is None
    assert parse_iso("") is None


def test_start_date_uses_unlock_when_present():
    due = datetime(2026, 12, 10, 23, 59, tzinfo=KST)
    unlock = datetime(2026, 12, 1, 9, 0, tzinfo=KST)
    assert start_date(unlock, due) == unlock


def test_start_date_falls_back_to_seven_days_before_due():
    due = datetime(2026, 12, 10, 23, 59, tzinfo=KST)
    assert start_date(None, due) == due - timedelta(days=7)
    assert start_date(None, due, offset_days=3) == due - timedelta(days=3)


def test_start_date_never_after_due():
    due = datetime(2026, 12, 10, 23, 59, tzinfo=KST)
    assert start_date(due + timedelta(days=1), due) == due


def test_due_stage_thresholds(now):
    assert due_stage(now + timedelta(hours=73), now) is None
    assert due_stage(now + timedelta(hours=72), now) == "D-3"
    assert due_stage(now + timedelta(hours=25), now) == "D-3"
    assert due_stage(now + timedelta(hours=24), now) == "D-1"
    assert due_stage(now + timedelta(minutes=1), now) == "D-1"
    assert due_stage(now - timedelta(minutes=1), now) is None
    assert due_stage(None, now) is None


def test_fmt_due():
    dt = datetime(2026, 12, 5, 23, 59, tzinfo=KST)
    assert fmt_due(dt) == "12/5(토) 23:59"
    assert fmt_due(dt, all_day=True) == "12/5(토)"
    assert fmt_due(None) == "마감 없음"
