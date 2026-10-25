# tests for the weekly awards. real store, real receipts, no mocks.
from datetime import datetime, timedelta

import awards

LINK = "https://discord.com/channels/1/2/3"


def add(store, user, now, due=None, msg=1):
    return store.add(user, "do a thing", due, 2, msg, LINK, now)


def week(now):
    return awards.week_bounds(now)


def test_empty_store_gives_all_none(tmp_store, now):
    start, end = week(now)
    result = awards.compute(tmp_store, start, end)
    assert result == {
        "most_reliable": None,
        "biggest_comeback": None,
        "most_promises": None,
        "the_closer": None,
    }


def test_most_promises_tie_lists_both_sorted(tmp_store, now):
    start, end = week(now)
    add(tmp_store, 20, now, msg=1)
    add(tmp_store, 10, now, msg=2)
    add(tmp_store, 30, now, msg=3)
    add(tmp_store, 30, now, msg=4)
    add(tmp_store, 20, now, msg=5)
    add(tmp_store, 10, now, msg=6)
    result = awards.compute(tmp_store, start, end)["most_promises"]
    assert result == {"user_ids": [10, 20, 30], "value": 2}


def test_receipts_before_week_start_are_ignored(tmp_store, now):
    start, end = week(now)
    add(tmp_store, 10, start - timedelta(days=1))
    result = awards.compute(tmp_store, start, end)
    assert result["most_promises"] is None
    assert result["most_reliable"] is None


def test_most_reliable_uses_done_ratio(tmp_store, now):
    start, end = week(now)
    a1 = add(tmp_store, 10, now, msg=1)
    add(tmp_store, 10, now, msg=2)
    b1 = add(tmp_store, 20, now, msg=3)
    tmp_store.mark_done(a1.id, now)
    tmp_store.mark_done(b1.id, now)
    result = awards.compute(tmp_store, start, end)["most_reliable"]
    assert result == {"user_ids": [20], "value": 1.0}


def test_comeback_picks_closest_to_due(tmp_store, now):
    start, end = week(now)
    far = add(tmp_store, 10, now, due=now + timedelta(hours=5), msg=1)
    close = add(tmp_store, 20, now, due=now + timedelta(minutes=2), msg=2)
    tmp_store.mark_done(far.id, now)
    tmp_store.mark_done(close.id, now)
    result = awards.compute(tmp_store, start, end)["biggest_comeback"]
    assert result == {"user_ids": [20], "value": 120}


def test_comeback_ignores_late_finishes(tmp_store, now):
    start, end = week(now)
    late = add(tmp_store, 10, now, due=now - timedelta(hours=1))
    tmp_store.mark_done(late.id, now)
    assert awards.compute(tmp_store, start, end)["biggest_comeback"] is None


def test_closer_counts_claims(tmp_store, now):
    start, end = week(now)
    r1 = add(tmp_store, 10, now, msg=1)
    r2 = add(tmp_store, 10, now, msg=2)
    r3 = add(tmp_store, 10, now, msg=3)
    tmp_store.reassign(r1.id, 20, now)
    tmp_store.reassign(r2.id, 20, now)
    tmp_store.reassign(r3.id, 30, now)
    result = awards.compute(tmp_store, start, end)["the_closer"]
    assert result == {"user_ids": [20], "value": 2}


def test_week_bounds_midweek(now):
    start, end = week(now)
    assert end == datetime(2026, 10, 23, 17, 0, tzinfo=now.tzinfo)
    assert end - start == timedelta(days=7)


def test_week_bounds_friday_after_five_and_weekend(tz):
    fri = datetime(2026, 10, 23, 17, 30, tzinfo=tz)
    sun = datetime(2026, 10, 25, 9, 0, tzinfo=tz)
    expected = datetime(2026, 10, 30, 17, 0, tzinfo=tz)
    assert week(fri)[1] == expected
    assert week(sun)[1] == expected


def test_week_bounds_friday_before_five(tz):
    fri = datetime(2026, 10, 23, 16, 59, tzinfo=tz)
    assert week(fri)[1] == datetime(2026, 10, 23, 17, 0, tzinfo=tz)


def test_should_post_once_on_friday_hour(tmp_store, tz):
    first = datetime(2026, 10, 23, 17, 30, tzinfo=tz)
    later = datetime(2026, 10, 23, 17, 45, tzinfo=tz)
    assert awards.should_post(first, tmp_store.last_awards_week)
    tmp_store.last_awards_week = awards.week_key(first)
    assert not awards.should_post(later, tmp_store.last_awards_week)


def test_should_post_false_other_times(tz):
    thursday = datetime(2026, 10, 22, 17, 30, tzinfo=tz)
    early = datetime(2026, 10, 23, 16, 30, tzinfo=tz)
    assert not awards.should_post(thursday, None)
    assert not awards.should_post(early, None)


def test_should_post_again_next_week(tz):
    this_week = datetime(2026, 10, 23, 17, 30, tzinfo=tz)
    next_week = datetime(2026, 10, 30, 17, 5, tzinfo=tz)
    key = awards.week_key(this_week)
    assert awards.should_post(next_week, key)
