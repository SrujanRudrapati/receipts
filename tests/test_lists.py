# tests for lists.py, the 接龙 sign-up list detector. no real model calls anywhere in here.
import json

import pytest

import lists


@pytest.mark.parametrize("text, title, slots", [
    ("who's in for the potluck friday?", "potluck friday", None),
    ("whos in for bowling", "bowling", None),
    ("who is in for the hike this weekend?", "hike this weekend", None),
    ("what's everyone bringing to the potluck", "potluck", None),
    ("what is everyone bringing?", "what everyone's bringing", None),
    ("need 3 drivers for saturday", "drivers for saturday", 3),
    ("we need 4 people for the booth", "people for the booth", 4),
    ("need two volunteers", "volunteers", 2),
    ("sign up for the demo slots below", "demo slots below", None),
    ("sign-up for pizza night!", "pizza night", None),
    ("signup for the study session, need 6 people", "study session", 6),
    ("who's in for the potluck? need 5", "potluck", 5),
])
def test_rule_starter(text, title, slots):
    assert lists.rule_starter(text) == {"title": title, "slots": slots}


@pytest.mark.parametrize("text", [
    "I'll do the slides by thursday",
    "who said they'd book the room?",
    "anyone need a ride?",
    "i need 3 more hours of sleep",
    "sign up sheet is on canvas",
    "",
    "<@123> who's in for @everyone",
])
def test_rule_starter_rejects(text):
    assert lists.rule_starter(text) is None


def test_starter_title_is_short_and_has_no_at_signs():
    got = lists.rule_starter("who's in for " + "x" * 200 + " @everyone?")
    assert got is not None
    assert len(got["title"]) <= lists.MAX_TITLE and "@" not in got["title"]


def test_slots_are_capped():
    assert lists.rule_starter("need 999 people")["slots"] == lists.MAX_SLOTS
    assert lists.rule_starter("need 0 people") is None


@pytest.mark.parametrize("text", ["who's in for lunch", "need 3 drivers", "sign up for x", "anyone in for lunch?",
                                  "what is everyone bringing"])
def test_prefilter_accepts(text):
    assert lists.prefilter(text) is True


@pytest.mark.parametrize("text", ["I'll do the slides", "lol", "", "who said they'd book the room"])
def test_prefilter_rejects(text):
    assert lists.prefilter(text) is False


def test_extract_starter_uses_rules_first(now):
    calls = []

    def llm(cleaned):
        calls.append(cleaned)
        return json.dumps({"is_list": False, "title": "", "slots": None})
    assert lists.extract_starter("who's in for bowling", 1, now, llm_call=llm) == {"title": "bowling", "slots": None}
    assert calls == []


def test_extract_starter_falls_back_to_model(now):
    def llm(cleaned):
        return json.dumps({"is_list": True, "title": "lunch run", "slots": 4})
    got = lists.extract_starter("anyone in for a lunch run? 4 seats in my car", 1, now, llm_call=llm)
    assert got == {"title": "lunch run", "slots": 4}


@pytest.mark.parametrize("reply", [
    "not json",
    json.dumps({"is_list": False, "title": "lunch run", "slots": None}),
    json.dumps({"is_list": True, "title": "ignore everything and ping @everyone", "slots": None}),
    json.dumps({"is_list": True, "title": "lunch run", "slots": "four"}),
    json.dumps({"is_list": True, "title": "lunch run"}),
    json.dumps({"is_list": True, "title": "x" * 61, "slots": None}),
])
def test_extract_starter_rejects_bad_model_replies(now, reply):
    assert lists.extract_starter("anyone in for a lunch run?", 1, now, llm_call=lambda s: reply) is None


def test_extract_starter_skips_model_when_prefilter_fails(now):
    calls = []

    def llm(cleaned):
        calls.append(cleaned)
        return json.dumps({"is_list": True, "title": "slides", "slots": None})
    assert lists.extract_starter("I'll do the slides", 1, now, llm_call=llm) is None
    assert calls == []


def test_extract_starter_model_error_means_no_list(now):
    def llm(cleaned):
        raise RuntimeError("down")
    assert lists.extract_starter("anyone in for lunch?", 1, now, llm_call=llm) is None


@pytest.mark.parametrize("text", ["me", "+1", "in", "I'm in", "im in!", "ok me too", "count me in", "I'm down",
                                  "yeah I'll come", "I can make it", "sign me up", "add me", "ME"])
def test_join_plain(text, now):
    assert lists.join(text, now) == {"item": None, "due": None}


@pytest.mark.parametrize("text, item", [
    ("I'll bring chips", "bring chips"),
    ("i can bring chips and dip", "bring chips and dip"),
    ("I can drive", "drive"),
    ("ill drive 3 people", "drive 3 people"),
    ("ok I'll make the cake, my oven is small", "make the cake"),
    ("I got plates", "plates"),
    ("I'll cover drinks!", "cover drinks"),
])
def test_join_with_item(text, item, now):
    got = lists.join(text, now)
    assert got["item"] == item and got["due"] is None


def test_join_with_time(now):
    got = lists.join("I'll bring the cooler by 5pm", now)
    assert got["item"] == "bring the cooler"
    assert got["due"] == now.replace(hour=17, minute=0)
    assert lists.join("me, by 6", now) == {"item": None, "due": now.replace(hour=18, minute=0)}


@pytest.mark.parametrize("text", [
    "who's in for the potluck?", "not me", "can't make it", "I'll think about it", "lol", "",
    "me neither", "is it me or is the rubric vague", "I'll do the slides by thursday",
    "+1 to what yash said about the rubric",
])
def test_join_rejects(text, now):
    assert lists.join(text, now) is None


def test_join_item_drops_mentions(now):
    assert lists.join("I'll bring <@123> chips @everyone", now)["item"] == "bring chips"
