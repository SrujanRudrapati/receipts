# tests for the cubbie link: topic names, the lines we post, and the sos lines we accept.
import re
from datetime import datetime
from types import SimpleNamespace as NS

import pytest

import cubbie

TEN_MINUTES = 600


def receipt(**overrides):
    base = dict(id="ab12cd34", what="intro slides", due=None, user_id=1, status="open")
    base.update(overrides)
    return NS(**base)


# topics


def test_new_topic_shape():
    topic = cubbie.new_topic()
    assert re.fullmatch(r"receipts-[A-Za-z0-9_-]{16}", topic), topic


def test_new_topic_is_random():
    assert len({cubbie.new_topic() for _ in range(50)}) == 50


# lines we post


def test_receipt_line_with_due(tz):
    due = datetime(2026, 10, 29, 17, 0, tzinfo=tz)
    line = cubbie.receipt_line(receipt(due=due), "cse511-group")
    assert line == "receipt id=ab12cd34 what=intro slides due=2026-10-29T17:00:00-07:00 channel=cse511-group"


def test_receipt_line_without_due():
    line = cubbie.receipt_line(receipt(), "general")
    assert line == "receipt id=ab12cd34 what=intro slides due=none channel=general"


def test_receipt_line_is_one_line():
    line = cubbie.receipt_line(receipt(what="intro\nslides\r\n  for  thursday"), "gen\neral")
    assert "\n" not in line and "\r" not in line
    assert "what=intro slides for thursday" in line
    assert line.endswith("channel=general")


@pytest.mark.parametrize("event", ["done", "reassigned", "removed"])
def test_update_line(event):
    assert cubbie.update_line("ab12cd34", event) == f"receipt id=ab12cd34 event={event}"


def test_update_line_rejects_unknown_event():
    with pytest.raises(ValueError):
        cubbie.update_line("ab12cd34", "exploded")


# sos lines we accept


def test_parse_sos_exact():
    assert cubbie.parse_sos("sos id=ab12cd34 source=cubbie") == "ab12cd34"


def test_parse_sos_allows_surrounding_whitespace():
    assert cubbie.parse_sos("  sos id=ab12cd34  source=cubbie \n") == "ab12cd34"


@pytest.mark.parametrize("text", [
    "sos id=ab12cd34",
    "sos id=ab12cd34 source=someone",
    "sos source=cubbie id=ab12cd34",
    "SOS id=ab12cd34 source=cubbie",
    "sos id=ab12cd34 source=cubbie extra=1",
    "sos id=../../etc source=cubbie",
    "sos id=AB12CD34 source=cubbie",
    "sos id=ab12cd345 source=cubbie",
    "receipt id=ab12cd34 what=slides due=none channel=x",
    "please sos id=ab12cd34 source=cubbie",
    "",
])
def test_parse_sos_rejects_everything_else(text):
    assert cubbie.parse_sos(text) is None


# which polled messages count


def msg(message_id="m1", text="sos id=ab12cd34 source=cubbie", age=0, now_ts=1_000_000):
    return {"id": message_id, "time": now_ts - age, "event": "message", "message": text}


def test_sos_ids_picks_fresh_sos_lines():
    cursor = cubbie.Cursor()
    found = cubbie.sos_ids([msg()], now_ts=1_000_000, cursor=cursor)
    assert found == ["ab12cd34"]
    assert cursor.since == "m1"


def test_sos_ids_skips_old_messages():
    cursor = cubbie.Cursor()
    old = msg(age=TEN_MINUTES + 1)
    edge = msg(message_id="m2", age=TEN_MINUTES)
    assert cubbie.sos_ids([old, edge], now_ts=1_000_000, cursor=cursor) == ["ab12cd34"]
    assert cursor.since == "m2"


def test_sos_ids_skips_duplicates_across_polls():
    cursor = cubbie.Cursor()
    assert cubbie.sos_ids([msg()], now_ts=1_000_000, cursor=cursor) == ["ab12cd34"]
    assert cubbie.sos_ids([msg()], now_ts=1_000_000, cursor=cursor) == []
    assert cubbie.sos_ids([msg(), msg()], now_ts=1_000_000, cursor=cursor) == []


def test_sos_ids_skips_non_sos_and_keepalives():
    cursor = cubbie.Cursor()
    polled = [
        {"id": "k1", "time": 1_000_000, "event": "keepalive"},
        msg(message_id="m2", text="receipt id=ab12cd34 what=slides due=none channel=x"),
        {"id": "m3", "time": 1_000_000, "event": "message"},
        {"id": "m4", "time": "soon", "event": "message", "message": "sos id=ab12cd34 source=cubbie"},
        msg(message_id="m5", text="sos id=ffffffff source=cubbie"),
    ]
    assert cubbie.sos_ids(polled, now_ts=1_000_000, cursor=cursor) == ["ffffffff"]
    assert cursor.since == "m5"


def test_cursor_seen_is_bounded():
    cursor = cubbie.Cursor()
    many = [msg(message_id=f"m{i}") for i in range(cubbie.MAX_SEEN + 50)]
    cubbie.sos_ids(many, now_ts=1_000_000, cursor=cursor)
    assert len(cursor.seen) <= cubbie.MAX_SEEN
