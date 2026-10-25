# tests for the words around sign-up lists
from datetime import datetime
from types import SimpleNamespace as R

import voice

NAMES = {1: "Yash", 2: "Suraj"}


def entry(uid, item=None):
    return {"user_id": uid, "item": item, "receipt_id": None}


def test_list_text_with_slots():
    text = voice.list_text("potluck friday", [entry(1, "bring chips"), entry(2)], 4, NAMES, closed=False)
    assert text == "\n".join([
        "📋 potluck friday",
        "1. Yash: bring chips",
        "2. Suraj",
        "3. open",
        "4. open",
        "react 🙋 to join",
    ])


def test_list_text_without_slots_or_entries():
    assert voice.list_text("bowling", [], None, NAMES, closed=False) == "📋 bowling\nnobody yet.\nreact 🙋 to join"


def test_list_text_closed():
    text = voice.list_text("bowling", [entry(1)], 3, NAMES, closed=True)
    assert text == "📋 bowling (closed)\n1. Yash"
    assert "open" not in text and "🙋" not in text


def test_list_text_unknown_name():
    assert "1. someone" in voice.list_text("x", [entry(9)], None, NAMES, closed=False)


def test_list_text_is_capped():
    text = voice.list_text("x" * 60, [entry(i, "y" * 100) for i in range(60)], None, NAMES, closed=False)
    assert len(text) <= voice.MAX_BOARD_CHARS


def test_board_marks_list_receipts_and_shows_lists(tz):
    groups = {1: {"open": [R(what="bring chips", due=None, list_id="ab12cd34"), R(what="slides", due=None)],
                  "done": [], "overdue": []}}
    lists = [R(title="potluck friday", entries=[entry(1), entry(2)], slots=4, status="open"),
             R(title="rides", entries=[entry(1)], slots=None, status="closed")]
    text = voice.board_text(groups, NAMES, include_overdue=False, lists=lists)
    assert "• bring chips (due no date, list)" in text
    assert "• slides (due no date)" in text
    assert "lists\npotluck friday: 2 in, 2 open\nrides: 1 in (closed)" in text
    assert text.index("lists") < text.index("Yash")


def test_board_without_lists_is_unchanged(tz):
    groups = {1: {"open": [R(what="slides", due=None)], "done": [], "overdue": []}}
    assert voice.board_text(groups, NAMES, include_overdue=False) == "Yash\n• slides (due no date)"
    assert voice.board_text({}, NAMES, include_overdue=False, lists=[]) == "nothing on the board yet."


def test_close_replies():
    assert voice.list_closed_text("potluck friday", 3) == "closed potluck friday. 3 in."
    assert voice.list_closed_text("potluck friday", 1) == "closed potluck friday. 1 in."
    assert voice.list_none_text() == "no open list here."
    assert voice.list_full_text("potluck friday") == "potluck friday is full."


def test_help_mentions_lists():
    assert "接龙" in voice.help_text() and "/receipts list close" in voice.help_text()


def test_list_words_have_no_at_signs():
    outputs = [voice.list_text("potluck", [entry(1, "chips")], 2, NAMES, closed=False),
               voice.list_closed_text("potluck", 2), voice.list_none_text(), voice.list_full_text("potluck")]
    for out in outputs:
        assert "@" not in out and chr(0x2014) not in out
