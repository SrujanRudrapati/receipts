# tests for dates.py. "now" is Thursday 2026-10-22 14:00 in Phoenix.
from datetime import datetime

from dates import find_due_text, parse_due, strip_due


def test_weekday_rollover(now, tz):
    assert parse_due("by thursday", now) == datetime(2026, 10, 29, 23, 59, tzinfo=tz)


def test_weekday_next(now, tz):
    assert parse_due("by fri", now) == datetime(2026, 10, 23, 23, 59, tzinfo=tz)


def test_tomorrow(now, tz):
    assert parse_due("tomorrow", now) == datetime(2026, 10, 23, 23, 59, tzinfo=tz)


def test_tonight(now, tz):
    assert parse_due("tonight", now) == datetime(2026, 10, 22, 21, 0, tzinfo=tz)


def test_by_fri_5pm(now, tz):
    assert parse_due("by fri 5pm", now) == datetime(2026, 10, 23, 17, 0, tzinfo=tz)


def test_time_passed_rolls_to_tomorrow(now, tz):
    assert parse_due("by 1pm", now) == datetime(2026, 10, 23, 13, 0, tzinfo=tz)


def test_bare_hour_means_pm(now, tz):
    assert parse_due("by 5", now) == datetime(2026, 10, 22, 17, 0, tzinfo=tz)


def test_today_and_weekend_and_next_week(now, tz):
    assert parse_due("eod", now) == datetime(2026, 10, 22, 17, 0, tzinfo=tz)
    assert parse_due("this weekend", now) == datetime(2026, 10, 24, 23, 59, tzinfo=tz)
    assert parse_due("next week", now) == datetime(2026, 10, 26, 23, 59, tzinfo=tz)


def test_none(now):
    assert parse_due("lol ok", now) is None
    assert find_due_text("lol ok") is None


def test_find_due_text():
    assert find_due_text("do it by thursday please") == "by thursday"


def test_strip_due():
    assert strip_due("do the intro slides by thursday") == "do the intro slides"


def test_result_is_tz_aware(now):
    assert parse_due("tomorrow", now).tzinfo is now.tzinfo
