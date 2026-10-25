# tests for sign-up lists in the store
from datetime import timedelta

import pytest

from store import Receipt, SignupList, Store


def make_list(store, now, title="potluck", slots=None, channel=10, starter=100, post=200, author=1):
    return store.add_list(channel, title, slots, starter, post, author, now)


def test_add_list_then_lookups(tmp_store, now):
    lst = make_list(tmp_store, now, slots=3)
    assert len(lst.id) == 8
    assert lst.status == "open"
    assert lst.entries == []
    assert tmp_store.get_list(lst.id) == lst
    assert tmp_store.find_list_by_starter(100) == lst
    assert tmp_store.find_list_by_post(200) == lst
    assert tmp_store.find_list_by_post(999) is None
    assert tmp_store.get_list("nope") is None


def test_add_entry_numbers_and_item(tmp_store, now):
    lst = make_list(tmp_store, now)
    assert tmp_store.add_entry(lst.id, 1, "bring chips") == {"user_id": 1, "item": "bring chips", "receipt_id": None}
    assert tmp_store.add_entry(lst.id, 2, None) == {"user_id": 2, "item": None, "receipt_id": None}
    assert [e["user_id"] for e in tmp_store.get_list(lst.id).entries] == [1, 2]


def test_duplicate_entry_is_rejected_but_an_item_fills_in(tmp_store, now):
    lst = make_list(tmp_store, now)
    tmp_store.add_entry(lst.id, 1, None)
    assert tmp_store.add_entry(lst.id, 1, None) is None
    assert tmp_store.add_entry(lst.id, 1, "bring chips") == {"user_id": 1, "item": "bring chips", "receipt_id": None}
    assert tmp_store.add_entry(lst.id, 1, "bring dip") is None
    assert len(tmp_store.get_list(lst.id).entries) == 1


def test_slots_cap_entries(tmp_store, now):
    lst = make_list(tmp_store, now, slots=2)
    assert tmp_store.add_entry(lst.id, 1, None)
    assert tmp_store.add_entry(lst.id, 2, None)
    assert tmp_store.add_entry(lst.id, 3, None) is None
    assert tmp_store.list_is_full(lst.id) is True
    assert tmp_store.list_is_full(make_list(tmp_store, now, starter=101, post=201).id) is False


def test_closed_list_takes_no_entries(tmp_store, now):
    lst = make_list(tmp_store, now)
    assert tmp_store.close_list(lst.id).status == "closed"
    assert tmp_store.add_entry(lst.id, 1, None) is None
    assert tmp_store.close_list("nope") is None


def test_set_entry_receipt(tmp_store, now):
    lst = make_list(tmp_store, now)
    tmp_store.add_entry(lst.id, 1, "bring chips")
    r = tmp_store.add(1, "bring chips", None, 10, 101, "l", now, list_id=lst.id)
    assert r.list_id == lst.id
    tmp_store.set_entry_receipt(lst.id, 1, r.id)
    assert tmp_store.get_list(lst.id).entries[0]["receipt_id"] == r.id


def test_open_list_in_channel_within_window(tmp_store, now):
    old = make_list(tmp_store, now - timedelta(minutes=31), starter=100, post=200)
    fresh = make_list(tmp_store, now - timedelta(minutes=5), starter=101, post=201)
    assert tmp_store.open_list_in_channel(10, now, timedelta(minutes=30)) == fresh
    tmp_store.close_list(fresh.id)
    assert tmp_store.open_list_in_channel(10, now, timedelta(minutes=30)) is None
    assert tmp_store.open_list_in_channel(10, now, timedelta(minutes=60)) == old
    assert tmp_store.open_list_in_channel(99, now, timedelta(minutes=60)) is None


def test_lists_in_channel_newest_first(tmp_store, now):
    a = make_list(tmp_store, now - timedelta(hours=1), starter=100, post=200)
    b = make_list(tmp_store, now, starter=101, post=201)
    make_list(tmp_store, now, channel=99, starter=102, post=202)
    assert [l.id for l in tmp_store.lists_in_channel(10)] == [b.id, a.id]


def test_lists_survive_reload(tmp_path, now):
    store = Store(tmp_path / "s.json")
    lst = make_list(store, now, slots=4)
    store.add_entry(lst.id, 1, "bring chips")
    r = store.add(1, "bring chips", None, 10, 101, "l", now, list_id=lst.id)
    store.set_entry_receipt(lst.id, 1, r.id)
    again = Store(tmp_path / "s.json")
    assert again.get_list(lst.id) == store.get_list(lst.id)
    assert again.get(r.id).list_id == lst.id
    assert isinstance(again.get_list(lst.id), SignupList)


def test_forget_drops_entries_and_started_lists(tmp_store, now):
    mine = make_list(tmp_store, now, starter=100, post=200, author=5)
    theirs = make_list(tmp_store, now, starter=101, post=201, author=1)
    tmp_store.add_entry(theirs.id, 5, None)
    tmp_store.add_entry(theirs.id, 2, None)
    tmp_store.forget(5)
    assert tmp_store.get_list(mine.id) is None
    assert [e["user_id"] for e in tmp_store.get_list(theirs.id).entries] == [2]


def test_receipt_dict_round_trip_with_list_id(now):
    r = Receipt("abcd1234", 1, "x", None, "open", 10, 20, "l", now, list_id="ef567890")
    assert Receipt.from_dict(r.to_dict()) == r
    assert Receipt.from_dict({k: v for k, v in r.to_dict().items() if k != "list_id"}).list_id is None
