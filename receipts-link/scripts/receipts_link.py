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
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

NTFY = "https://ntfy.sh"
TOKEN_VAR = "RECEIPTS_LINK_TOKEN"
TIMEOUT_SECONDS = 15
ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")

# the two line shapes the receipts bot posts. anything else on the topic is ignored.
CAUGHT = re.compile(r"^receipt id=([0-9a-f]{8}) what=(.*) due=(\S+) channel=(\S+)$")
EVENT = re.compile(r"^receipt id=([0-9a-f]{8}) event=(done|reassigned|removed)$")

EXIT_OK, EXIT_ARGS, EXIT_NO_TOKEN, EXIT_UNREACHABLE, EXIT_REJECTED, EXIT_NTFY = 0, 2, 3, 4, 5, 6


def fail(message: str, code: int) -> None:
    print(message, file=sys.stderr)
    sys.exit(code)


def topic() -> str | None:
    value = os.environ.get(TOKEN_VAR, "").strip()
    return value or None


def require_topic() -> str:
    value = topic()
    if value is None:
        fail(f"{TOKEN_VAR} is not set. Ask the student to save their Receipts link token.", EXIT_NO_TOKEN)
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
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ---- lines


def parse_line(text: str) -> dict | None:
    match = CAUGHT.match(text or "")
    if match:
        receipt_id, what, due, channel = match.groups()
        return {"kind": "caught", "id": receipt_id, "what": what.strip(),
                "due": None if due == "none" else due, "channel": channel}
    match = EVENT.match(text or "")
    if match:
        return {"kind": match.group(2), "id": match.group(1)}
    return None


def apply_messages(state: dict, messages: list[dict]) -> dict:
    """fold polled ntfy messages into a new copy of the state, oldest first."""
    receipts = {rid: dict(r) for rid, r in state["receipts"].items()}
    ordered = sorted((m for m in messages if m.get("event") == "message"), key=lambda m: m.get("time") or 0)
    for message in ordered:
        line = parse_line(message.get("message") or "")
        if line is None:
            continue
        current = receipts.get(line["id"])
        if line["kind"] == "caught":
            receipts[line["id"]] = {
                "what": line["what"], "due": line["due"], "channel": line["channel"], "status": "open",
                "offered": bool(current and current.get("offered")),
                "sos_sent": current.get("sos_sent") if current else None,
                "first_seen": current.get("first_seen") if current else message.get("time") or int(time.time()),
            }
        elif current is not None:
            receipts[line["id"]] = {**current, "status": line["kind"]}
    return {**state, "receipts": receipts}


def open_receipts(state: dict) -> list[dict]:
    found = [{"id": rid, **r} for rid, r in state["receipts"].items() if r.get("status") == "open"]
    return sorted(found, key=lambda r: (r.get("due") is None, r.get("due") or "", r.get("first_seen") or 0))


def due_label(due: str | None, now: str | None) -> str:
    """'today', 'tomorrow', 'in 3 days', 'overdue' against the student's local now. falls back to the raw text."""
    if due is None:
        return "no date"
    if now is None:
        return due
    try:
        due_at = datetime.fromisoformat(due)
        now_at = datetime.fromisoformat(now)
        days = (due_at.astimezone(now_at.tzinfo).date() - now_at.date()).days
    except (ValueError, TypeError):
        return due
    if due_at < now_at:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


# ---- ntfy


def _send(request: Request) -> str:
    # error text never includes the url: the url is the topic.
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            fail(f"ntfy rejected the topic (HTTP {error.code}). Ask the student to check their link token.", EXIT_REJECTED)
        fail(f"ntfy returned HTTP {error.code}. Try again in a minute.", EXIT_NTFY)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
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
