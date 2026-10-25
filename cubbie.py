# the cubbie link. each linked user has a private ntfy topic that works like a password.
# we post one line per receipt event to it, and read "sos" lines back from it.
# this file is pure: the lines we write, the lines we accept, and what counts as fresh.
# the network part lives in relay.py.
import re
import secrets
from collections import deque
from dataclasses import dataclass, field

TOPIC_PREFIX = "receipts-"
TOPIC_BYTES = 12  # token_urlsafe(12) is exactly 16 url-safe characters
MAX_AGE_SECONDS = 10 * 60
MAX_SEEN = 500
EVENTS = ("done", "reassigned", "removed")

# only this exact shape, with the 8 hex chars our receipt ids use. anything else is ignored.
SOS_PATTERN = re.compile(r"^\s*sos id=([0-9a-f]{8})\s+source=cubbie\s*$")
_SPACE = re.compile(r"\s+")


def new_topic() -> str:
    return TOPIC_PREFIX + secrets.token_urlsafe(TOPIC_BYTES)


def _one_line(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def receipt_line(receipt, channel_name: str) -> str:
    due = receipt.due.isoformat() if receipt.due is not None else "none"
    # channel is the last token, so it gets no spaces at all. discord names never have any anyway.
    channel = _SPACE.sub("", channel_name)
    return f"receipt id={receipt.id} what={_one_line(receipt.what)} due={due} channel={channel}"


def ding_line(receipt) -> str:
    """the escalation line. a summary and a time, never a reason."""
    due = receipt.due.isoformat() if receipt.due is not None else "none"
    return f"ding id={receipt.id} what={_one_line(receipt.what)} due={due}"


def update_line(receipt_id: str, event: str) -> str:
    if event not in EVENTS:
        raise ValueError(f"unknown cubbie event: {event}")
    return f"receipt id={receipt_id} event={event}"


def parse_sos(text: str) -> str | None:
    match = SOS_PATTERN.match(text)
    return match.group(1) if match else None


@dataclass
class Cursor:
    """where we are in one topic: the last ntfy id we saw, and recent ids so repeats are dropped."""
    since: str | None = None
    seen: deque = field(default_factory=lambda: deque(maxlen=MAX_SEEN))


def _fresh(message: dict, now_ts: float) -> bool:
    stamp = message.get("time")
    return isinstance(stamp, (int, float)) and now_ts - stamp <= MAX_AGE_SECONDS


def sos_ids(messages, now_ts: float, cursor: Cursor) -> list[str]:
    """receipt ids from the sos lines in one poll. moves the cursor past everything it saw."""
    found = []
    for message in messages:
        message_id = message.get("id")
        if not message_id:
            continue
        cursor.since = message_id
        if message_id in cursor.seen:
            continue
        cursor.seen.append(message_id)
        if message.get("event") != "message" or not _fresh(message, now_ts):
            continue
        receipt_id = parse_sos(message.get("message") or "")
        if receipt_id is not None:
            found.append(receipt_id)
    return found
