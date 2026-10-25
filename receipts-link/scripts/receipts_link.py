"""Shared bits for the receipts-link scripts. Standard library only.

The topic comes from RECEIPTS_LINK_TOKEN and works like a password, so nothing here ever prints it.
State lives under HOME (~/.config/receipts-link/state.json), which Cubbie keeps across restarts.

Exit codes used by both scripts: 0 ok, 2 bad arguments, 3 token missing, 4 ntfy unreachable,
5 topic rejected by ntfy, 6 other ntfy error.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

NTFY = "https://ntfy.sh"
TOKEN_VAR = "RECEIPTS_LINK_TOKEN"
TIMEOUT_SECONDS = 15
ID_PATTERN = re.compile(r"[0-9a-f]{8}")
TOPIC_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_WHAT = 140
MAX_RECEIPTS = 200
KEEP_CLOSED_SECONDS = 7 * 24 * 3600
TOKEN_ERRORS = (401, 403, 404)

# the three line shapes the receipts bot posts. anything else on the topic is ignored.
# everything on the topic is untrusted: anyone who knows the topic can write to it.
CAUGHT = re.compile(r"^receipt id=([0-9a-f]{8}) what=(.*) due=(\S+) channel=(\S+)$")
EVENT = re.compile(r"^receipt id=([0-9a-f]{8}) event=(done|reassigned|removed)$")
# a ding: the bot sent its last call two hours before due and heard nothing for thirty minutes.
DING = re.compile(r"^ding id=([0-9a-f]{8}) what=(.*) due=(\S+)$")
UNPRINTABLE = re.compile(r"[^\x20-\x7e]")

EXIT_OK, EXIT_ARGS, EXIT_NO_TOKEN, EXIT_UNREACHABLE, EXIT_REJECTED, EXIT_NTFY = 0, 2, 3, 4, 5, 6


def fail(message: str, code: int) -> None:
    print(message, file=sys.stderr)
    sys.exit(code)


def valid_id(value: str) -> bool:
    return bool(ID_PATTERN.fullmatch(value))


def topic() -> str | None:
    value = os.environ.get(TOKEN_VAR, "").strip()
    return value or None


def require_topic() -> str:
    """the topic from the environment. a bad one fails before it can reach a url or a traceback."""
    value = topic()
    if value is None:
        fail(f"{TOKEN_VAR} is not set. Ask the student to save their Receipts link token.", EXIT_NO_TOKEN)
    if not TOPIC_PATTERN.fullmatch(value):
        fail(f"{TOKEN_VAR} does not look like a Receipts token. Ask the student to save it again from the "
             "/receipts link DM.", EXIT_NO_TOKEN)
    return value


# ---- state


def state_path() -> Path:
    data_dir = os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "receipts-link"
    return Path(data_dir) / "state.json"


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {"receipts": {}}
    if not isinstance(data, dict) or not isinstance(data.get("receipts"), dict):
        return {"receipts": {}}
    return data


def save_state(state: dict) -> None:
    # written to a temp file first and swapped in, so a crash can't leave half a file. private to the student.
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(state, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ---- lines


def _clean(text: str, limit: int) -> str:
    return UNPRINTABLE.sub("", text).strip()[:limit]


def _aware(value: str) -> datetime | None:
    """an ISO datetime with a time zone, or None. naive times are treated as UTC."""
    try:
        when = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def parse_line(text: str) -> dict | None:
    match = CAUGHT.match(text or "")
    if match:
        receipt_id, what, due, channel = match.groups()
        # a due date we can't read becomes "no date" rather than a crash later on
        due_at = None if due == "none" else _aware(due)
        return {"kind": "caught", "id": receipt_id, "what": _clean(what, MAX_WHAT),
                "due": due_at.isoformat() if due_at else None, "channel": _clean(channel, 64)}
    match = EVENT.match(text or "")
    if match:
        return {"kind": match.group(2), "id": match.group(1)}
    match = DING.match(text or "")
    if match:
        receipt_id, what, due = match.groups()
        due_at = None if due == "none" else _aware(due)
        return {"kind": "ding", "id": receipt_id, "what": _clean(what, MAX_WHAT),
                "due": due_at.isoformat() if due_at else None}
    return None


def _prune(receipts: dict, now_ts: float) -> dict:
    """drop closed receipts after a week, then keep only the newest MAX_RECEIPTS."""
    kept = {rid: r for rid, r in receipts.items()
            if r.get("status") == "open" or now_ts - (r.get("closed_at") or r.get("first_seen") or 0) < KEEP_CLOSED_SECONDS}
    newest = sorted(kept, key=lambda rid: kept[rid].get("first_seen") or 0)[-MAX_RECEIPTS:]
    return {rid: kept[rid] for rid in newest}


def apply_messages(state: dict, messages: list[dict], now_ts: float | None = None) -> dict:
    """fold polled ntfy messages into a new copy of the state, oldest first."""
    now_ts = time.time() if now_ts is None else now_ts
    receipts = {rid: dict(r) for rid, r in state["receipts"].items()}
    ordered = sorted((m for m in messages if m.get("event") == "message"), key=lambda m: m.get("time") or 0)
    for message in ordered:
        line = parse_line(message.get("message") or "")
        if line is None:
            continue
        current = receipts.get(line["id"])
        stamp = message.get("time") if isinstance(message.get("time"), (int, float)) else int(now_ts)
        if line["kind"] == "caught":
            receipts[line["id"]] = {
                "what": line["what"], "due": line["due"], "channel": line["channel"], "status": "open",
                "offered": bool(current and current.get("offered")),
                "sos_sent": current.get("sos_sent") if current else None,
                "first_seen": current.get("first_seen") if current else stamp,
            }
        elif line["kind"] == "ding":
            dinged = _with_ding(current, line, stamp)
            if dinged is not None:
                receipts[line["id"]] = dinged
        elif current is not None:
            receipts[line["id"]] = {**current, "status": line["kind"], "closed_at": stamp}
    return {**state, "receipts": _prune(receipts, now_ts)}


def _with_ding(current: dict | None, line: dict, stamp: int) -> dict | None:
    """a ding on an open receipt flags it for cubbie. an unknown one is opened from the ding itself."""
    if current is None:
        current = {"what": line["what"], "due": line["due"], "channel": "", "status": "open",
                   "offered": True, "sos_sent": None, "first_seen": stamp}
    if current.get("status") != "open":
        return None
    return {**current, "ding_at": stamp, "ding_handled": False}


def open_receipts(state: dict) -> list[dict]:
    found = [{"id": rid, **r} for rid, r in state["receipts"].items() if r.get("status") == "open"]
    return sorted(found, key=lambda r: (r.get("due") is None, r.get("due") or "", r.get("first_seen") or 0))


def due_label(due: str | None, now: str | None) -> str:
    """'today', 'tomorrow', 'in 3 days', 'overdue' against the student's local now. falls back to the raw text."""
    if due is None:
        return "no date"
    if now is None:
        return due
    due_at, now_at = _aware(due), _aware(now)
    if due_at is None or now_at is None:
        return due
    try:
        days = (due_at.astimezone(now_at.tzinfo).date() - now_at.date()).days
        overdue = due_at < now_at
    except (ValueError, TypeError, OverflowError):
        return due
    if overdue:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


# ---- ntfy


def _send(request: Request) -> str:
    # error text never includes the url or the exception message: both can hold the topic.
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code in TOKEN_ERRORS:
            fail(f"ntfy rejected the topic (HTTP {error.code}). Ask the student to check their link token.", EXIT_REJECTED)
        fail(f"ntfy returned HTTP {error.code}. Try again in a minute.", EXIT_NTFY)
    except Exception as error:  # noqa: BLE001 - anything else is "unreachable", by type name only
        fail(f"Could not reach ntfy.sh ({type(error).__name__}). Try again in a minute.", EXIT_UNREACHABLE)
    return ""


def poll(topic_name: str, since: str) -> list[dict]:
    body = _send(Request(f"{NTFY}/{topic_name}/json?poll=1&since={since}"))
    out = []
    for raw in body.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def publish(topic_name: str, line: str) -> None:
    _send(Request(f"{NTFY}/{topic_name}", data=line.encode(), method="POST"))
