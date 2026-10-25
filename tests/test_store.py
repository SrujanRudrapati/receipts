# tests for the json state store
import os
from datetime import timedelta

import pytest

from store import Receipt, Store


def make(store, now, user=1, what="book the room", due=None, channel=10, msg=100):
    link = f"https://discord.com/channels/1/{channel}/{msg}"
    return store.add(user, what, due, channel, msg, link, now)


def test_add_then_get(tmp_store, now):
    r = make(tmp_store, now)
    assert len(r.id) == 8
    assert r.status == "open"
    assert tmp_store.get(r.id) == r
    assert tmp_store.find_by_message(100) == r
    assert tmp_store.get("nope") is None


def test_what_truncated_to_140(tmp_store, now):
    r = make(tmp_store, now, what="x" * 300)
    assert len(r.what) == 140


def test_mark_done(tmp_store, now):
    r = make(tmp_store, now)
    done = tmp_store.mark_done(r.id, now)
    assert done.status == "done"
    assert done.done_at == now
    assert tmp_store.mark_done("nope", now) is None


def test_remove(tmp_store, now):
    r = make(tmp_store, now)
    assert tmp_store.remove(r.id) is True
    assert tmp_store.remove(r.id) is False
    assert tmp_store.get(r.id) is None


def test_reassign_sets_fields(tmp_store, now):
    r = make(tmp_store, now, user=1)
    out = tmp_store.reassign(r.id, 2, now)
    assert out.previous_user_id == 1
    assert out.user_id == 2
    assert out.claimed_by == 2
    assert out.claimed_at == now
    assert tmp_store.reassign("nope", 2, now) is None


def test_reassign_keeps_nudged(tmp_store, now):
    # the claim DM already says when it is due, so no second nudge right away
    r = make(tmp_store, now, user=1)
    tmp_store.mark_nudged(r.id)
    assert tmp_store.reassign(r.id, 2, now).nudged is True


def test_mark_nudged(tmp_store, now):
    r = make(tmp_store, now)
    tmp_store.mark_nudged(r.id)
    assert tmp_store.get(r.id).nudged is True


def test_board_groups_and_overdue(tmp_store, now):
    late = make(tmp_store, now, due=now - timedelta(days=1), msg=1)
    soon = make(tmp_store, now, due=now + timedelta(days=1), msg=2)
    nodue = make(tmp_store, now, msg=3)
    fin = make(tmp_store, now, msg=4)
    tmp_store.mark_done(fin.id, now)
    make(tmp_store, now, channel=99, msg=5)
    other = make(tmp_store, now, user=2, msg=6)
    board = tmp_store.board(10, now)
    mine = board[1]
    assert set(mine) == {"open", "done", "overdue"}
    assert [r.id for r in mine["overdue"]] == [late.id]
    assert {r.id for r in mine["open"]} == {soon.id, nodue.id}
    assert [r.id for r in mine["done"]] == [fin.id]
    assert [r.id for r in board[2]["open"]] == [other.id]


def test_ask_who_matches_words(tmp_store, now):
    r = make(tmp_store, now, what="I can book a hayden room")
    make(tmp_store, now, what="bring snacks", msg=101)
    out = tmp_store.ask_who(10, "who said they would book the room")
    assert [x.id for x in out] == [r.id]
    assert tmp_store.ask_who(10, "the and for") == []
    assert tmp_store.ask_who(11, "book room") == []


def test_ask_who_best_first(tmp_store, now):
    a = make(tmp_store, now, what="book room", msg=1)
    b = make(tmp_store, now, what="book a hayden room today", msg=2)
    out = tmp_store.ask_who(10, "hayden room book")
    assert [x.id for x in out] == [b.id, a.id]


def test_find_open_limited_to_user(tmp_store, now):
    mine = make(tmp_store, now, user=1, what="book the room", msg=1)
    make(tmp_store, now, user=2, what="book the room", msg=2)
    assert tmp_store.find_open(1, 10, "room").id == mine.id
    assert tmp_store.find_open(3, 10, "room") is None
    tmp_store.mark_done(mine.id, now)
    assert tmp_store.find_open(1, 10, "room") is None


def test_forget_owned_previous_claimed(tmp_store, now):
    a = make(tmp_store, now, user=5, msg=1)
    b = make(tmp_store, now, user=1, msg=2)
    tmp_store.reassign(b.id, 5, now)
    c = make(tmp_store, now, user=1, msg=3)
    tmp_store.reassign(c.id, 7, now)
    tmp_store.reassign(c.id, 1, now)
    keep = make(tmp_store, now, user=9, msg=4)
    tmp_store.link_message(50, "nudge", a.id)
    tmp_store.link_message(51, "help", keep.id)
    assert tmp_store.forget(5) == 2
    assert tmp_store.get(a.id) is None
    assert tmp_store.get(b.id) is None
    assert tmp_store.get(c.id) is not None
    assert tmp_store.lookup_message(50) is None
    assert tmp_store.lookup_message(51) == ("help", keep.id)
    assert tmp_store.forget(7) == 1
    assert tmp_store.forget(5) == 0


def test_channels(tmp_store):
    assert not tmp_store.is_tracked(10)
    tmp_store.set_channel(10, True)
    tmp_store.set_channel(11, True)
    tmp_store.set_channel(11, False)
    assert tmp_store.is_tracked(10)
    assert tmp_store.tracked_channels() == [10]


def test_links(tmp_store, now):
    r = make(tmp_store, now)
    tmp_store.link_message(7, "nudge", r.id)
    assert tmp_store.lookup_message(7) == ("nudge", r.id)
    tmp_store.unlink_message(7)
    assert tmp_store.lookup_message(7) is None
    tmp_store.unlink_message(7)


def test_settings_defaults_and_setters(tmp_store):
    assert tmp_store.clock_offset_seconds == 0
    assert tmp_store.last_awards_week is None
    tmp_store.clock_offset_seconds = 90
    tmp_store.last_awards_week = "2026-W43"
    assert tmp_store.clock_offset_seconds == 90
    assert tmp_store.last_awards_week == "2026-W43"


def test_reload_round_trips_everything(tmp_path, now):
    path = tmp_path / "state.json"
    s = Store(path)
    r = make(s, now, due=now + timedelta(hours=3))
    s.reassign(r.id, 2, now)
    s.mark_done(r.id, now)
    s.mark_nudged(r.id)
    s.set_channel(10, True)
    s.link_message(8, "help", r.id)
    s.clock_offset_seconds = 30
    s.last_awards_week = "2026-W43"
    s2 = Store(path)
    back = s2.get(r.id)
    assert back == s.get(r.id)
    assert back.due.tzinfo is not None
    assert back.created_at.utcoffset() == now.utcoffset()
    assert back.done_at == now
    assert s2.is_tracked(10)
    assert s2.lookup_message(8) == ("help", r.id)
    assert s2.clock_offset_seconds == 30
    assert s2.last_awards_week == "2026-W43"


def test_receipt_dict_round_trip(now):
    r = Receipt("abcd1234", 1, "x", None, "open", 2, 3, "l", now)
    assert Receipt.from_dict(r.to_dict()) == r


def test_atomic_save_survives_crash(tmp_path, now, monkeypatch):
    path = tmp_path / "state.json"
    s = Store(path)
    good = make(s, now)

    def boom(src, dst):
        raise OSError("disk died")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        make(s, now, what="second one", msg=200)
    monkeypatch.undo()
    fresh = Store(path)
    assert [r.id for r in fresh.all_receipts()] == [good.id]


def test_save_fsyncs_before_replace(tmp_path, now, monkeypatch):
    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(os, "replace", lambda a, b: calls.append("replace") or real_replace(a, b))
    s = Store(tmp_path / "state.json")
    make(s, now)
    assert calls == ["fsync", "replace"]
    assert Store(tmp_path / "state.json").all_receipts()


# cubbie link topics


def test_cubbie_topic_link_and_unlink(tmp_store):
    assert tmp_store.cubbie_topic(1) is None
    tmp_store.link_cubbie(1, "receipts-abcdefghijklmnop")
    assert tmp_store.cubbie_topic(1) == "receipts-abcdefghijklmnop"
    assert tmp_store.cubbie_links() == {1: "receipts-abcdefghijklmnop"}
    assert tmp_store.unlink_cubbie(1) is True
    assert tmp_store.unlink_cubbie(1) is False
    assert tmp_store.cubbie_topic(1) is None
    assert tmp_store.cubbie_links() == {}


def test_cubbie_topic_survives_reload(tmp_store):
    tmp_store.link_cubbie(1, "receipts-abcdefghijklmnop")
    again = Store(tmp_store.path)
    assert again.cubbie_topic(1) == "receipts-abcdefghijklmnop"
    assert again.cubbie_links() == {1: "receipts-abcdefghijklmnop"}


def test_cubbie_link_replaces_old_topic(tmp_store):
    tmp_store.link_cubbie(1, "receipts-old")
    tmp_store.link_cubbie(1, "receipts-new")
    assert tmp_store.cubbie_topic(1) == "receipts-new"


def test_forget_drops_cubbie_topic(tmp_store, now):
    tmp_store.link_cubbie(5, "receipts-abcdefghijklmnop")
    tmp_store.link_cubbie(6, "receipts-someoneelse")
    tmp_store.forget(5)
    assert tmp_store.cubbie_topic(5) is None
    assert tmp_store.cubbie_topic(6) == "receipts-someoneelse"
