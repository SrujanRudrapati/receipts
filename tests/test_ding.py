# tests for the pure side of ding: store flags, timing in nudges.py, the cubbie line, the words.
from datetime import timedelta

import pytest

import cubbie
import nudges
import voice
from store import Receipt


def make(store, now, user=1, due=None, msg=100):
    return store.add(user, "intro slides", due, 10, msg, "l", now)


def armed(store, user=1):
    store.link_cubbie(user, "receipts-topic")
    store.set_ding(user, True)


# ---- store


def test_ding_flag_defaults_off_and_round_trips(tmp_path):
    from store import Store
    store = Store(tmp_path / "s.json")
    assert store.ding_on(1) is False
    store.set_ding(1, True)
    assert Store(tmp_path / "s.json").ding_on(1) is True
    store.set_ding(1, False)
    assert store.ding_on(1) is False


def test_forget_drops_ding_flag(tmp_store):
    tmp_store.set_ding(5, True)
    tmp_store.forget(5)
    assert tmp_store.ding_on(5) is False


def test_receipt_ding_fields(tmp_store, now):
    r = make(tmp_store, now)
    assert (r.acked, r.ding_sent_at, r.dinged) == (False, None, False)
    tmp_store.mark_acked(r.id)
    tmp_store.mark_ding_sent(r.id, now)
    tmp_store.mark_dinged(r.id)
    again = tmp_store.get(r.id)
    assert (again.acked, again.ding_sent_at, again.dinged) == (True, now, True)
    assert Receipt.from_dict(again.to_dict()) == again
    assert Receipt.from_dict({k: v for k, v in again.to_dict().items()
                              if k not in ("acked", "ding_sent_at", "dinged")}).dinged is False


# ---- timing


def test_ding_due_within_two_hours_for_armed_users_only(tmp_store, now):
    armed(tmp_store, 1)
    tmp_store.link_cubbie(2, "receipts-other")      # linked, ding off
    tmp_store.set_ding(3, True)                      # ding on, not linked
    soon = make(tmp_store, now, user=1, due=now + timedelta(hours=1, minutes=59), msg=1)
    make(tmp_store, now, user=1, due=now + timedelta(hours=2, minutes=1), msg=2)
    make(tmp_store, now, user=1, due=now - timedelta(minutes=1), msg=3)
    make(tmp_store, now, user=1, due=None, msg=4)
    make(tmp_store, now, user=2, due=now + timedelta(hours=1), msg=5)
    make(tmp_store, now, user=3, due=now + timedelta(hours=1), msg=6)
    assert [r.id for r in nudges.ding_due(tmp_store, now)] == [soon.id]


def test_ding_due_skips_acked_done_and_already_sent(tmp_store, now):
    armed(tmp_store)
    due = now + timedelta(hours=1)
    acked = make(tmp_store, now, due=due, msg=1)
    tmp_store.mark_acked(acked.id)
    done = make(tmp_store, now, due=due, msg=2)
    tmp_store.mark_done(done.id, now)
    sent = make(tmp_store, now, due=due, msg=3)
    tmp_store.mark_ding_sent(sent.id, now)
    fresh = make(tmp_store, now, due=due, msg=4)
    assert [r.id for r in nudges.ding_due(tmp_store, now)] == [fresh.id]


def test_ding_escalate_after_thirty_quiet_minutes(tmp_store, now):
    armed(tmp_store)
    due = now + timedelta(hours=1)
    quiet = make(tmp_store, now, due=due, msg=1)
    tmp_store.mark_ding_sent(quiet.id, now - timedelta(minutes=30))
    recent = make(tmp_store, now, due=due, msg=2)
    tmp_store.mark_ding_sent(recent.id, now - timedelta(minutes=29))
    answered = make(tmp_store, now, due=due, msg=3)
    tmp_store.mark_ding_sent(answered.id, now - timedelta(hours=1))
    tmp_store.mark_acked(answered.id)
    already = make(tmp_store, now, due=due, msg=4)
    tmp_store.mark_ding_sent(already.id, now - timedelta(hours=1))
    tmp_store.mark_dinged(already.id)
    never = make(tmp_store, now, due=due, msg=5)
    assert [r.id for r in nudges.ding_escalate(tmp_store, now)] == [quiet.id]


def test_ding_escalate_needs_link_and_opt_in(tmp_store, now):
    r = make(tmp_store, now, due=now + timedelta(hours=1))
    tmp_store.mark_ding_sent(r.id, now - timedelta(hours=1))
    assert nudges.ding_escalate(tmp_store, now) == []
    tmp_store.set_ding(1, True)
    assert nudges.ding_escalate(tmp_store, now) == []
    tmp_store.link_cubbie(1, "receipts-topic")
    assert [x.id for x in nudges.ding_escalate(tmp_store, now)] == [r.id]


def test_tick_steps_walk_the_clock_in_half_hours():
    assert nudges.tick_steps(1) == [0.5, 0.5]
    assert nudges.tick_steps(1.25) == [0.5, 0.5, 0.25]
    assert nudges.tick_steps(0.2) == [0.2]
    assert sum(nudges.tick_steps(24)) == 24
    assert len(nudges.tick_steps(nudges.MAX_TICK_HOURS)) == nudges.MAX_TICK_HOURS * 2


# ---- the line to cubbie and the words


def test_ding_line(now):
    r = Receipt("ab12cd34", 1, "intro  slides", now, "open", 10, 20, "l", now)
    assert cubbie.ding_line(r) == f"ding id=ab12cd34 what=intro slides due={now.isoformat()}"


def test_ding_words():
    assert voice.ding_dm("intro slides", "today at 5pm") == "last call: intro slides due today at 5pm. still on it?"
    assert voice.reminded_text() == "🔔 reminded"
    assert voice.ding_on_text() == "ok, ding is on. if you go quiet before something is due, cubbie hears about it."
    assert voice.ding_off_text() == "ok, ding is off."
    assert voice.ding_needs_link_text() == "link cubbie first with /receipts link."
    for out in (voice.ding_dm("x", "y"), voice.reminded_text(), voice.ding_on_text(), voice.ding_off_text(),
                voice.ding_needs_link_text()):
        assert "@" not in out and chr(0x2014) not in out
    assert "/receipts ding" in voice.help_text()
