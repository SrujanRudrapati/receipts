# tests for nudges.py. uses a real store, no mocks.
from datetime import timedelta

import pytest

from nudges import demo_now, due_soon, tick, valid_tick_hours, when_label


def add(store, now, due, what="send slides"):
    return store.add(1, what, due, 10, 20, "link", now)


def test_due_in_23h_is_returned(tmp_store, now):
    r = add(tmp_store, now, now + timedelta(hours=23))
    assert due_soon(tmp_store, now) == [r]


def test_nudged_receipt_is_not_returned_again(tmp_store, now):
    r = add(tmp_store, now, now + timedelta(hours=23))
    tmp_store.mark_nudged(r.id)
    assert due_soon(tmp_store, now) == []


def test_done_receipt_is_skipped(tmp_store, now):
    r = add(tmp_store, now, now + timedelta(hours=5))
    tmp_store.mark_done(r.id, now)
    assert due_soon(tmp_store, now) == []


def test_due_in_30h_is_skipped(tmp_store, now):
    add(tmp_store, now, now + timedelta(hours=30))
    assert due_soon(tmp_store, now) == []


def test_no_due_date_is_skipped(tmp_store, now):
    add(tmp_store, now, None)
    assert due_soon(tmp_store, now) == []


def test_overdue_is_skipped(tmp_store, now):
    add(tmp_store, now, now - timedelta(hours=1))
    assert due_soon(tmp_store, now) == []


def test_results_are_sorted_by_due(tmp_store, now):
    late = add(tmp_store, now, now + timedelta(hours=20))
    early = add(tmp_store, now, now + timedelta(hours=2))
    assert due_soon(tmp_store, now) == [early, late]


def test_tick_moves_demo_clock_24h(tmp_store, now):
    tick(tmp_store, 24)
    assert demo_now(tmp_store, now) == now + timedelta(hours=24)


def test_tick_accepts_floats_and_adds_up(tmp_store, now):
    tick(tmp_store, 1.5)
    tick(tmp_store, 0.5)
    assert tmp_store.clock_offset_seconds == 7200


def test_when_label_tomorrow_end_of_day(now, tz):
    due = (now + timedelta(days=1)).replace(hour=23, minute=59)
    assert when_label(due, now) == "tomorrow"


def test_when_label_friday_5pm(now):
    due = (now + timedelta(days=1)).replace(hour=17, minute=0)
    assert when_label(due, now) == "tomorrow at 5pm"
    due = (now + timedelta(days=2)).replace(hour=17, minute=0)
    assert when_label(due, now) == "saturday at 5pm"


def test_when_label_weekday_name(now):
    monday = now + timedelta(days=4)
    assert when_label(monday.replace(hour=23, minute=59), now) == "monday"


def test_when_label_friday_a_week_out(now):
    friday = (now + timedelta(days=8)).replace(hour=17, minute=0)
    assert when_label(friday, now) == "friday at 5pm"


def test_when_label_today_and_minutes(now):
    assert when_label(now.replace(hour=23, minute=59), now) == "today"
    assert when_label(now.replace(hour=17, minute=30), now) == "today at 5:30pm"
    assert when_label(now.replace(hour=9, minute=0), now) == "today at 9am"


@pytest.mark.parametrize("hours", [0.5, 1, 24, 336])
def test_valid_tick_hours_ok(hours):
    assert valid_tick_hours(hours) is True


@pytest.mark.parametrize("hours", [0, -1, 336.5, 1e12, float("inf"), float("-inf"), float("nan")])
def test_valid_tick_hours_rejects(hours):
    assert valid_tick_hours(hours) is False
