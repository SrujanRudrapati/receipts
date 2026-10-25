# tests for the cubbie skill scripts in receipts-link/. no network: urlopen is swapped for a fake.
import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

SKILL = Path(__file__).parent.parent / "receipts-link"
SCRIPTS = SKILL / "scripts"
TOPIC = "receipts-abcdefghijklmnop"
NOW = 1_800_000_000  # a fixed unix time for the "time" fields

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name):
    # the scripts import receipts_link by name, so every module must share the one in sys.modules
    importlib.import_module("receipts_link")
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def link():
    return importlib.import_module("receipts_link")


@pytest.fixture
def pull():
    return load("pull")


@pytest.fixture
def sos():
    return load("sos")


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SKILL_DATA_DIR", raising=False)
    return tmp_path


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("RECEIPTS_LINK_TOKEN", TOPIC)


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(link, monkeypatch, body="", error=None):
    calls = []

    def urlopen(request, timeout=0):
        calls.append(request)
        if error is not None:
            raise error
        return FakeResponse(body)
    monkeypatch.setattr(link, "urlopen", urlopen)
    return calls


def ndjson(*items):
    return "\n".join(json.dumps(item) for item in items) + "\n"


def caught(receipt_id, what, due="none", channel="cse511", at=NOW, message_id=None):
    return {"id": message_id or f"m-{receipt_id}-c", "time": at, "event": "message",
            "message": f"receipt id={receipt_id} what={what} due={due} channel={channel}"}


def event(receipt_id, name, at=NOW, message_id=None):
    return {"id": message_id or f"m-{receipt_id}-{name}", "time": at, "event": "message",
            "message": f"receipt id={receipt_id} event={name}"}


# ---- the shared bits


def test_parse_receipt_line(link):
    got = link.parse_line("receipt id=ab12cd34 what=intro slides due=2026-10-29T17:00:00-07:00 channel=cse511")
    assert got == {"kind": "caught", "id": "ab12cd34", "what": "intro slides",
                   "due": "2026-10-29T17:00:00-07:00", "channel": "cse511"}


def test_parse_receipt_line_without_due(link):
    got = link.parse_line("receipt id=ab12cd34 what=book a room due=none channel=general")
    assert got["due"] is None and got["what"] == "book a room"


def test_parse_event_line(link):
    assert link.parse_line("receipt id=ab12cd34 event=done") == {"kind": "done", "id": "ab12cd34"}
    assert link.parse_line("receipt id=ab12cd34 event=reassigned") == {"kind": "reassigned", "id": "ab12cd34"}
    assert link.parse_line("receipt id=ab12cd34 event=removed") == {"kind": "removed", "id": "ab12cd34"}


@pytest.mark.parametrize("text", [
    "sos id=ab12cd34 source=cubbie",
    "receipt id=ab12cd34 event=exploded",
    "receipt id=zz12cd34 what=x due=none channel=c",
    "hello",
    "",
])
def test_parse_line_ignores_everything_else(link, text):
    assert link.parse_line(text) is None


def test_topic_from_env_and_missing(link, monkeypatch):
    monkeypatch.setenv("RECEIPTS_LINK_TOKEN", "  " + TOPIC + "\n")
    assert link.topic() == TOPIC
    monkeypatch.setenv("RECEIPTS_LINK_TOKEN", "")
    assert link.topic() is None
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN")
    assert link.topic() is None


def test_state_lives_under_home(link, home):
    assert link.state_path() == home / ".config" / "receipts-link" / "state.json"
    link.save_state({"receipts": {"ab12cd34": {"what": "x"}}})
    assert link.load_state() == {"receipts": {"ab12cd34": {"what": "x"}}}


def test_load_state_when_missing_or_broken(link, home):
    assert link.load_state() == {"receipts": {}}
    link.state_path().parent.mkdir(parents=True)
    link.state_path().write_text("{not json")
    assert link.load_state() == {"receipts": {}}


def test_apply_messages_opens_and_closes(link):
    state = {"receipts": {}}
    polled = [
        caught("ab12cd34", "intro slides", due="2026-10-29T17:00:00-07:00", at=NOW - 30),
        caught("9f8e7d6c", "book a room", at=NOW - 20),
        event("9f8e7d6c", "done", at=NOW - 10),
        {"id": "k1", "time": NOW, "event": "keepalive"},
        {"id": "s1", "time": NOW, "event": "message", "message": "sos id=ab12cd34 source=cubbie"},
    ]
    state = link.apply_messages(state, polled)
    assert state["receipts"]["ab12cd34"]["status"] == "open"
    assert state["receipts"]["ab12cd34"]["offered"] is False
    assert state["receipts"]["9f8e7d6c"]["status"] == "done"


def test_apply_messages_uses_time_order_not_list_order(link):
    state = {"receipts": {}}
    polled = [event("ab12cd34", "removed", at=NOW), caught("ab12cd34", "slides", at=NOW - 5)]
    assert link.apply_messages(state, polled)["receipts"]["ab12cd34"]["status"] == "removed"


def test_apply_messages_keeps_offered_and_does_not_mutate(link):
    state = {"receipts": {"ab12cd34": {"what": "slides", "due": None, "channel": "c", "status": "open",
                                       "offered": True, "sos_sent": None, "first_seen": NOW - 100}}}
    before = json.dumps(state)
    after = link.apply_messages(state, [caught("ab12cd34", "slides", at=NOW)])
    assert after["receipts"]["ab12cd34"]["offered"] is True
    assert json.dumps(state) == before


def test_open_receipts_sorted_by_due_then_first_seen(link):
    state = {"receipts": {
        "a1a1a1a1": {"what": "no date", "due": None, "channel": "c", "status": "open", "offered": False, "first_seen": 1},
        "b2b2b2b2": {"what": "later", "due": "2026-10-30T23:59:00-07:00", "channel": "c", "status": "open", "offered": False, "first_seen": 2},
        "c3c3c3c3": {"what": "sooner", "due": "2026-10-28T23:59:00-07:00", "channel": "c", "status": "open", "offered": False, "first_seen": 3},
        "d4d4d4d4": {"what": "done", "due": None, "channel": "c", "status": "done", "offered": False, "first_seen": 4},
    }}
    assert [r["id"] for r in link.open_receipts(state)] == ["c3c3c3c3", "b2b2b2b2", "a1a1a1a1"]


def test_due_label(link):
    now = "2026-10-27T09:00:00-07:00"
    assert link.due_label(None, now) == "no date"
    assert link.due_label("2026-10-27T17:00:00-07:00", now) == "today"
    assert link.due_label("2026-10-28T17:00:00-07:00", now) == "tomorrow"
    assert link.due_label("2026-10-30T17:00:00-07:00", now) == "in 3 days"
    assert link.due_label("2026-10-26T17:00:00-07:00", now) == "overdue"
    assert link.due_label("2026-10-30T17:00:00-07:00", None) == "2026-10-30T17:00:00-07:00"
    assert link.due_label("garbage", now) == "garbage"


# ---- pull.py


def run(module, argv, capsys):
    try:
        code = module.main(argv)
    except SystemExit as stop:
        code = stop.code
    out, err = capsys.readouterr()
    return code, out, err


def test_pull_without_token_exits_3(pull, home, monkeypatch, capsys):
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN", raising=False)
    code, out, err = run(pull, [], capsys)
    assert code == 3
    assert "RECEIPTS_LINK_TOKEN" in err and out == ""


def test_pull_polls_the_topic_and_prints_open_receipts(pull, link, home, token, monkeypatch, capsys):
    body = ndjson(
        caught("ab12cd34", "intro slides", due="2026-10-29T17:00:00-07:00", at=NOW - 30),
        caught("9f8e7d6c", "book a room", at=NOW - 20),
        event("9f8e7d6c", "done", at=NOW - 10),
    )
    calls = fake_urlopen(link, monkeypatch, body=body)
    code, out, err = run(pull, ["--now", "2026-10-27T09:00:00-07:00"], capsys)
    assert code == 0, err
    assert len(calls) == 1
    assert calls[0].full_url == f"https://ntfy.sh/{TOPIC}/json?poll=1&since=24h"
    lines = out.splitlines()
    assert lines[0] == "open 1"
    assert lines[1] == "new ab12cd34 | intro slides | due in 2 days (2026-10-29T17:00:00-07:00) | #cse511"
    assert "book a room" not in out
    assert TOPIC not in out and TOPIC not in err


def test_pull_remembers_across_runs_and_marks_offered(pull, link, home, token, monkeypatch, capsys):
    fake_urlopen(link, monkeypatch, body=ndjson(caught("ab12cd34", "intro slides", at=NOW - 30)))
    code, out, _ = run(pull, [], capsys)
    assert code == 0 and out.splitlines()[1].startswith("new ab12cd34")
    code, out, _ = run(pull, ["--offered", "ab12cd34"], capsys)
    assert code == 0 and "marked ab12cd34 as offered" in out
    # the topic window is empty now, but the state remembers the receipt
    fake_urlopen(link, monkeypatch, body="")
    code, out, _ = run(pull, [], capsys)
    assert code == 0
    assert out.splitlines()[1].startswith("seen ab12cd34")


def test_pull_offered_unknown_id_exits_2(pull, home, token, capsys):
    code, out, err = run(pull, ["--offered", "deadbeef"], capsys)
    assert code == 2 and "deadbeef" in err


def test_pull_says_when_nothing_is_open(pull, link, home, token, monkeypatch, capsys):
    fake_urlopen(link, monkeypatch, body=ndjson(caught("ab12cd34", "x", at=NOW), event("ab12cd34", "done", at=NOW)))
    code, out, _ = run(pull, [], capsys)
    assert code == 0
    assert out.strip() == "open 0\nno open receipts."


def test_pull_shows_help_asked(pull, link, home, token, monkeypatch, capsys):
    fake_urlopen(link, monkeypatch, body=ndjson(caught("ab12cd34", "slides", at=NOW)))
    run(pull, [], capsys)
    state = link.load_state()
    state["receipts"]["ab12cd34"]["sos_sent"] = NOW
    link.save_state(state)
    code, out, _ = run(pull, [], capsys)
    assert "| help asked" in out.splitlines()[1]


def test_pull_sample_mode_uses_the_asset_and_leaves_state_alone(pull, home, monkeypatch, capsys):
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN", raising=False)
    code, out, err = run(pull, ["--sample", "--now", "2026-10-27T09:00:00-07:00"], capsys)
    assert code == 0, err
    assert out.startswith("open 2\n")
    assert "intro slides" in out and "hayden room" in out
    assert not (home / ".config").exists()


@pytest.mark.parametrize("error, code", [
    (urllib.error.URLError("nope"), 4),
    (urllib.error.HTTPError("https://ntfy.sh/x", 404, "Not Found", {}, io.BytesIO(b"")), 5),
    (urllib.error.HTTPError("https://ntfy.sh/x", 500, "Boom", {}, io.BytesIO(b"")), 6),
    (TimeoutError("slow"), 4),
])
def test_pull_network_errors_map_to_exit_codes(pull, link, home, token, monkeypatch, capsys, error, code):
    fake_urlopen(link, monkeypatch, error=error)
    got, out, err = run(pull, [], capsys)
    assert got == code
    assert err.count("\n") == 1 and TOPIC not in err and out == ""


# ---- sos.py


def seeded_state(link, receipt_id="ab12cd34", status="open"):
    link.save_state({"receipts": {receipt_id: {
        "what": "intro slides", "due": None, "channel": "cse511", "status": status,
        "offered": True, "sos_sent": None, "first_seen": NOW}}})


def test_sos_without_token_exits_3(sos, home, monkeypatch, capsys):
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN", raising=False)
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 3 and "RECEIPTS_LINK_TOKEN" in err


@pytest.mark.parametrize("bad", ["AB12CD34", "ab12cd3", "../../x", "ab12cd34 source=cubbie"])
def test_sos_rejects_bad_ids(sos, home, token, capsys, bad):
    code, out, err = run(sos, ["--id", bad], capsys)
    assert code == 2 and out == ""


def test_sos_refuses_an_id_that_is_not_an_open_receipt(sos, link, home, token, monkeypatch, capsys):
    calls = fake_urlopen(link, monkeypatch)
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 2 and "pull.py" in err
    seeded_state(link, status="done")
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 2
    assert calls == []


def test_sos_posts_the_exact_line_to_the_topic(sos, link, home, token, monkeypatch, capsys):
    seeded_state(link)
    calls = fake_urlopen(link, monkeypatch, body='{"id":"x1"}')
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 0, err
    assert len(calls) == 1
    assert calls[0].full_url == f"https://ntfy.sh/{TOPIC}"
    assert calls[0].get_method() == "POST"
    assert calls[0].data == b"sos id=ab12cd34 source=cubbie"
    assert "intro slides" in out and TOPIC not in out
    assert link.load_state()["receipts"]["ab12cd34"]["sos_sent"] is not None


def test_sos_sample_mode_prints_without_network_or_state(sos, link, home, monkeypatch, capsys):
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN", raising=False)
    calls = fake_urlopen(link, monkeypatch)
    code, out, err = run(sos, ["--id", "ab12cd34", "--sample"], capsys)
    assert code == 0, err
    assert "sos id=ab12cd34 source=cubbie" in out
    assert calls == [] and not (home / ".config").exists()


def test_sos_network_error_keeps_state_unsent(sos, link, home, token, monkeypatch, capsys):
    seeded_state(link)
    fake_urlopen(link, monkeypatch, error=urllib.error.URLError("down"))
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 4 and TOPIC not in err
    assert link.load_state()["receipts"]["ab12cd34"]["sos_sent"] is None


# ---- the skill file itself


def frontmatter():
    text = (SKILL / "SKILL.md").read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md needs frontmatter"
    return match.group(1), text


def test_skill_md_frontmatter():
    head, text = frontmatter()
    assert re.search(r"^name: receipts-link$", head, re.M)
    description = re.search(r"^description: (.+)$", head, re.M).group(1)
    first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0]
    assert len(first) <= 200 and len(description) <= 1024
    assert "RECEIPTS_LINK_TOKEN" in head
    assert "ntfy.sh" in head
    assert chr(0x2014) not in text
    assert len(text.splitlines()) < 500


def test_skill_md_names_real_files_and_triggers():
    head, text = frontmatter()
    for path in re.findall(r"(?:scripts|assets)/[\w./-]+", text):
        assert (SKILL / path).exists(), path
    for phrase in ("what did I promise", "my receipts", "I can't do", "I need help with"):
        assert phrase in text
    assert 'RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/pull.py' in text
    assert 'RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/sos.py' in text
    assert "I'll only say you need help, not why" in text


# ---- hardening: the topic is untrusted input too


@pytest.mark.parametrize("bad", ["my topic", "receipts-a\nbc", "a/b", "x" * 65, "receipts-ébc"])
def test_malformed_token_fails_without_echoing_it(pull, home, monkeypatch, capsys, bad):
    monkeypatch.setenv("RECEIPTS_LINK_TOKEN", bad)
    code, out, err = run(pull, [], capsys)
    assert code == 3
    assert err.count("\n") == 1 and bad.strip() not in err and "Traceback" not in err


def test_send_never_lets_an_exception_escape(pull, link, home, token, monkeypatch, capsys):
    import http.client
    fake_urlopen(link, monkeypatch, error=http.client.InvalidURL(f"URL can't contain control characters. '/{TOPIC}/json'"))
    code, out, err = run(pull, [], capsys)
    assert code == 4 and TOPIC not in err and "Traceback" not in err
    fake_urlopen(link, monkeypatch, error=ValueError(f"bad {TOPIC}"))
    code, out, err = run(pull, [], capsys)
    assert code == 4 and TOPIC not in err


def test_naive_or_garbage_due_does_not_poison_state(pull, link, home, token, monkeypatch, capsys):
    body = ndjson(
        caught("ab12cd34", "slides", due="2026-10-29T17:00:00", at=NOW),
        caught("9f8e7d6c", "room", due="whenever-ish", at=NOW),
    )
    fake_urlopen(link, monkeypatch, body=body)
    code, out, err = run(pull, ["--now", "2026-10-27T09:00:00-07:00"], capsys)
    assert code == 0, err
    # a naive time is read as UTC and kept. garbage becomes "no date". neither crashes, now or on the next run.
    assert "(2026-10-29T17:00:00+00:00)" in out.splitlines()[1]
    assert "due no date" in out.splitlines()[2]
    code, out, err = run(pull, ["--now", "2026-10-27T09:00:00-07:00"], capsys)
    assert code == 0


def test_due_label_survives_naive_now(link):
    assert link.due_label("2026-10-30T17:00:00-07:00", "2026-10-27T09:00:00").startswith("in ")
    assert link.due_label("2026-10-30T17:00:00-07:00", "not a time") == "2026-10-30T17:00:00-07:00"


def test_what_and_channel_are_trimmed_and_printable(link):
    line = "receipt id=ab12cd34 what=" + "x" * 200 + "\tzz\x1b[31m due=none channel=chan\x07nel"
    got = link.parse_line(line)
    assert len(got["what"]) <= 140 and "\t" not in got["what"] and "\x1b" not in got["what"]
    assert got["channel"] == "channel"


def test_state_is_pruned(link):
    week = 8 * 24 * 3600
    state = {"receipts": {
        "a1a1a1a1": {"what": "old done", "due": None, "channel": "c", "status": "done", "offered": True,
                     "sos_sent": None, "first_seen": NOW - week * 2, "closed_at": NOW - week},
        "b2b2b2b2": {"what": "fresh done", "due": None, "channel": "c", "status": "done", "offered": True,
                     "sos_sent": None, "first_seen": NOW - 100, "closed_at": NOW - 50},
        "c3c3c3c3": {"what": "old open", "due": None, "channel": "c", "status": "open", "offered": True,
                     "sos_sent": None, "first_seen": NOW - week * 2},
    }}
    pruned = link.apply_messages(state, [], now_ts=NOW)["receipts"]
    assert set(pruned) == {"b2b2b2b2", "c3c3c3c3"}


def test_state_is_capped(link):
    flood = [caught(f"{i:08x}", f"thing {i}", at=NOW - 1000 + i) for i in range(link.MAX_RECEIPTS + 20)]
    receipts = link.apply_messages({"receipts": {}}, flood, now_ts=NOW)["receipts"]
    assert len(receipts) == link.MAX_RECEIPTS
    assert f"{link.MAX_RECEIPTS + 19:08x}" in receipts and "00000000" not in receipts


def test_closing_records_closed_at(link):
    receipts = link.apply_messages({"receipts": {}}, [caught("ab12cd34", "x", at=NOW - 5), event("ab12cd34", "done", at=NOW)])["receipts"]
    assert receipts["ab12cd34"]["closed_at"] == NOW


def test_sos_refuses_a_repeat_unless_asked_again(sos, link, home, token, monkeypatch, capsys):
    seeded_state(link)
    state = link.load_state()
    state["receipts"]["ab12cd34"]["sos_sent"] = NOW
    link.save_state(state)
    calls = fake_urlopen(link, monkeypatch, body="{}")
    code, out, err = run(sos, ["--id", "ab12cd34"], capsys)
    assert code == 2 and "already" in err and calls == []
    code, out, err = run(sos, ["--id", "ab12cd34", "--again"], capsys)
    assert code == 0 and len(calls) == 1


@pytest.mark.parametrize("status, code", [(401, 5), (403, 5), (404, 5), (429, 6), (408, 6)])
def test_only_auth_style_4xx_blame_the_token(pull, link, home, token, monkeypatch, capsys, status, code):
    fake_urlopen(link, monkeypatch, error=urllib.error.HTTPError("https://ntfy.sh/x", status, "x", {}, io.BytesIO(b"")))
    got, out, err = run(pull, [], capsys)
    assert got == code


def test_sample_and_offered_do_not_mix(pull, home, capsys):
    code, out, err = run(pull, ["--sample", "--offered", "ab12cd34"], capsys)
    assert code == 2 and not (home / ".config").exists()


def test_id_pattern_rejects_trailing_newline(link):
    assert link.valid_id("ab12cd34") and not link.valid_id("ab12cd34\n")


def test_save_state_is_atomic_and_private(link, home):
    link.save_state({"receipts": {}})
    path = link.state_path()
    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


# ---- ding: the bot heard nothing after its last call, so cubbie steps in


def ding(receipt_id, what="intro slides", due="2026-10-29T17:00:00-07:00", at=NOW, message_id=None):
    return {"id": message_id or f"m-{receipt_id}-ding", "time": at, "event": "message",
            "message": f"ding id={receipt_id} what={what} due={due}"}


def test_parse_ding_line(link):
    got = link.parse_line("ding id=ab12cd34 what=intro slides due=2026-10-29T17:00:00-07:00")
    assert got == {"kind": "ding", "id": "ab12cd34", "what": "intro slides", "due": "2026-10-29T17:00:00-07:00"}
    assert link.parse_line("ding id=ab12cd34 what=x due=none")["due"] is None
    assert link.parse_line("ding id=zz12cd34 what=x due=none") is None


def test_apply_ding_flags_a_known_receipt(link):
    state = link.apply_messages({"receipts": {}}, [caught("ab12cd34", "intro slides", at=NOW - 60), ding("ab12cd34")])
    r = state["receipts"]["ab12cd34"]
    assert r["status"] == "open" and r["ding_at"] == NOW and r["ding_handled"] is False


def test_apply_ding_for_an_unknown_receipt_opens_it(link):
    state = link.apply_messages({"receipts": {}}, [ding("ab12cd34", what="book a room", due="none")])
    r = state["receipts"]["ab12cd34"]
    assert r["status"] == "open" and r["what"] == "book a room" and r["due"] is None
    assert r["ding_at"] == NOW and r["ding_handled"] is False


def test_apply_ding_ignores_closed_receipts(link):
    polled = [caught("ab12cd34", "x", at=NOW - 60), event("ab12cd34", "done", at=NOW - 30), ding("ab12cd34")]
    r = link.apply_messages({"receipts": {}}, polled)["receipts"]["ab12cd34"]
    assert r["status"] == "done" and "ding_at" not in r


def test_pull_prints_ding_lines_and_dinged_marks_them_handled(pull, link, home, token, monkeypatch, capsys):
    body = ndjson(caught("ab12cd34", "intro slides", due="2026-10-29T17:00:00-07:00", at=NOW - 60),
                  caught("9f8e7d6c", "book a room", at=NOW - 50), ding("ab12cd34"))
    fake_urlopen(link, monkeypatch, body=body)
    code, out, err = run(pull, ["--now", "2026-10-29T15:30:00-07:00"], capsys)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == "open 2"
    assert lines[1] == "ding ab12cd34 | intro slides | due today (2026-10-29T17:00:00-07:00) | #cse511"
    assert lines[2].startswith("new 9f8e7d6c")
    code, out, _ = run(pull, ["--dinged", "ab12cd34"], capsys)
    assert code == 0 and "marked ab12cd34 as handled" in out
    fake_urlopen(link, monkeypatch, body="")
    code, out, _ = run(pull, ["--now", "2026-10-29T15:30:00-07:00"], capsys)
    assert out.splitlines()[1].startswith("new ab12cd34")


def test_pull_dinged_unknown_id_exits_2(pull, home, token, capsys):
    code, out, err = run(pull, ["--dinged", "deadbeef"], capsys)
    assert code == 2 and "deadbeef" in err


def test_sample_has_a_ding(pull, home, monkeypatch, capsys):
    monkeypatch.delenv("RECEIPTS_LINK_TOKEN", raising=False)
    code, out, err = run(pull, ["--sample", "--now", "2026-10-29T15:30:00-07:00"], capsys)
    assert code == 0, err
    assert any(line.startswith("ding ") for line in out.splitlines())


def test_skill_md_covers_the_ding():
    head, text = frontmatter()
    assert "## Flow 4: a ding" in text
    assert "ding" in re.search(r"^description: (.+)$", head, re.M).group(1)
    assert "30-minute" in text or "30 minute" in text
    assert "--dinged <id>" in text
    assert "only after the student says yes" in text or "Ask before" in text
    assert "phone" in text.lower()
