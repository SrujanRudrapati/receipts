from datetime import datetime
from types import SimpleNamespace as R

import pytest

import voice

NAMES = {1: "Yash", 2: "Suraj"}


def rec(what, due, status="open", uid=1):
    return R(what=what, due=due, status=status, message_link="https://x/1", user_id=uid)


@pytest.fixture
def groups(tz):
    due = datetime(2026, 10, 29, 17, 0, tzinfo=tz)
    eod = datetime(2026, 11, 3, 23, 59, tzinfo=tz)
    return {
        1: {
            "open": [rec("intro slides", due), rec("references", None)],
            "done": [rec("outline", eod, "done")],
            "overdue": [rec("late survey", eod, "overdue")],
        },
        2: {"open": [rec("demo video", eod, uid=2)], "done": [], "overdue": []},
    }


def all_outputs(groups):
    awards = {
        "most_reliable": {"user_ids": [1, 2], "value": 3},
        "biggest_comeback": {"user_ids": [2], "value": 2},
        "most_promises": {"user_ids": [1], "value": 5},
        "the_closer": {"user_ids": [1], "value": 1},
    }
    return [
        voice.nudge_dm("slides", "thu 5pm"), voice.got_it(),
        voice.help_wanted("Yash", "slides"), voice.claimed_channel("Suraj", "slides"),
        voice.claimed_dm_old("Suraj", "slides"), voice.claimed_dm_new("slides", "fri"),
        voice.who_answer("Yash", "slides", "https://x/1"), voice.who_none(),
        voice.board_text(groups, NAMES, True), voice.board_text(groups, NAMES, False),
        voice.overdue_text(groups, NAMES), voice.overdue_text({}, NAMES),
        voice.awards_text(awards, NAMES), voice.help_text(), voice.on_text(),
        voice.off_text(), voice.forgot_text(3), voice.undo_text(),
        voice.done_text("slides"), voice.not_found_text(), voice.demo_banner(),
        voice.tick_text(24, "thu 5pm"), voice.tick_bad_text(), voice.demo_denied_text(),
    ]


def test_no_at_signs_or_dashes(groups):
    for out in all_outputs(groups):
        assert isinstance(out, str) and out
        assert "@" not in out and "<@&" not in out
        assert chr(0x2014) not in out


def test_fixed_strings():
    assert voice.nudge_dm("slides", "thu 5pm") == "slides due thu 5pm. still on it?"
    assert voice.got_it() == "got it."
    assert voice.help_wanted("Yash", "slides") == "Yash could use a hand with slides. anyone?"


def test_board_formats_dates(groups):
    text = voice.board_text(groups, NAMES, True)
    assert "• intro slides (due thu oct 29 5pm)" in text
    assert "• references (due no date)" in text
    assert "• demo video (due tue nov 3)" in text
    assert "late survey" in text
    assert "Yash" in text and "Suraj" in text


def test_board_hides_overdue(groups):
    assert "late survey" not in voice.board_text(groups, NAMES, False)


def test_board_unknown_name(groups):
    assert "someone" in voice.board_text(groups, {}, True)


def test_overdue_text(groups):
    text = voice.overdue_text(groups, NAMES)
    assert "late survey" in text and "intro slides" not in text
    assert voice.overdue_text({}, NAMES) == "nothing overdue."


def test_awards_quiet():
    empty = {k: None for k in ("most_reliable", "biggest_comeback", "most_promises", "the_closer")}
    assert voice.awards_text(empty, NAMES) == "quiet week. no awards yet."


def test_awards_ties_and_skips():
    res = {
        "most_reliable": {"user_ids": [1, 2], "value": 3},
        "biggest_comeback": None,
        "most_promises": {"user_ids": [9], "value": 5},
        "the_closer": None,
    }
    text = voice.awards_text(res, NAMES)
    assert "Yash and Suraj" in text
    assert "someone" in text
    assert len(text.splitlines()) == 2
    assert "overdue" not in text.lower()


def test_help_mentions_commands():
    h = voice.help_text()
    for s in ("/receipts on", "/done", "/receipts board", "/awards", "/forgetme", "/receipts off", "not a promise"):
        assert s in h


def test_demo_banner():
    assert "demo" in voice.demo_banner() and "CSE 511" in voice.demo_banner()


def test_validate_polish():
    assert voice.validate_polish("slides due in 3 days", {"3"}, set())
    assert not voice.validate_polish("slides due in 4 days", {"3"}, set())
    assert not voice.validate_polish("hey @everyone", set(), set())
    assert not voice.validate_polish("hey <@123>", set(), set())
    assert not voice.validate_polish("a" * 121, set(), set())
    assert voice.validate_polish("a" * 120, set(), set())


def test_validate_names_and_weekdays():
    assert voice.validate_polish("Slides due Thursday in october", set(), set())
    assert voice.validate_polish("ok so Thursday works", set(), set())
    assert not voice.validate_polish("ok so Bob works", set(), set())
    assert voice.validate_polish("ok so Bob works", set(), {"Bob"})
    assert voice.validate_polish("ok. Fine then", set(), set())


def test_polish():
    def boom(_):
        raise RuntimeError("down")

    assert voice.polish("t", set(), set()) == "t"
    assert voice.polish("t", set(), set(), boom) == "t"
    assert voice.polish("t", set(), set(), lambda s: "nicer") == "nicer"
    assert voice.polish("t", set(), set(), lambda s: "@everyone") == "t"


HOSTILE = ["@everyone", "@here", "<@&1>", "@everyone <@&1> @here pizza"]


@pytest.mark.parametrize("bad", HOSTILE)
def test_hostile_model_what_never_reaches_voice(now, bad):
    import detect

    reply = '{"is_promise": true, "what": "' + bad + ' pizza", "due_text": null}'
    got = detect.extract("I'll get the pizza", 1, now, llm_call=lambda s: reply)
    for out in (voice.help_wanted("Yash", got["what"]), voice.who_answer("Yash", got["what"], "l"),
                voice.claimed_channel("Suraj", got["what"]), voice.done_text(got["what"])):
        assert "@" not in out and "<@" not in out


@pytest.mark.parametrize("bad", HOSTILE)
def test_hostile_chat_text_never_reaches_voice(now, bad):
    import detect

    got = detect.extract(f"I'll bring {bad} chips", 1, now, llm_call=lambda s: "no")
    assert "@" not in voice.help_wanted("Yash", got["what"])
    assert "<@" not in voice.done_text(got["what"])


def test_board_is_capped(tz):
    due = datetime(2026, 10, 29, 17, 0, tzinfo=tz)
    many = {1: {"open": [rec(f"task number {i} with some words", due) for i in range(200)],
                "done": [], "overdue": []}}
    text = voice.board_text(many, NAMES, False)
    assert len(text) <= 1900
    assert text.endswith("...and more. use /done to clear some.")
    assert "• task number 0 " in text


def test_short_board_not_cut(groups):
    assert "and more" not in voice.board_text(groups, NAMES, True)


def test_closer_line_matches_claims():
    res = {"the_closer": {"user_ids": [1], "value": 2}}
    assert voice.awards_text(res, NAMES) == "the closer: Yash. jumped in when someone needed a hand."


def test_tick_bad_text():
    assert voice.tick_bad_text() == "give me a number of hours between 0 and 336."


def test_demo_denied_text():
    assert voice.demo_denied_text() == "only demo runners can do this."
