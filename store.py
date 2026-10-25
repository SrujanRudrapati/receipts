# json backed state for the bot. one file, saved after every change.
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MAX_WHAT = 140
MIN_WORD = 3
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "who",
    "said", "they", "would", "doing", "going", "gonna",
}
DATE_FIELDS = ("due", "created_at", "done_at", "claimed_at")


@dataclass
class Receipt:
    id: str
    user_id: int
    what: str
    due: datetime | None
    status: str
    channel_id: int
    message_id: int
    message_link: str
    created_at: datetime
    done_at: datetime | None = None
    nudged: bool = False
    previous_user_id: int | None = None
    claimed_by: int | None = None
    claimed_at: datetime | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in DATE_FIELDS:
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Receipt":
        data = dict(data)
        for key in DATE_FIELDS:
            if data.get(key) is not None:
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


def words(text: str) -> set[str]:
    found = re.split(r"[^a-z]+", text.lower())
    return {w for w in found if len(w) >= MIN_WORD and w not in STOPWORDS}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self._receipts: dict[str, Receipt] = {}
        self._channels: set[int] = set()
        self._links: dict[int, tuple[str, str]] = {}
        self._offset = 0
        self._awards_week: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        for raw in data.get("receipts", []):
            r = Receipt.from_dict(raw)
            self._receipts[r.id] = r
        self._channels = set(data.get("tracked_channels", []))
        self._links = {int(k): tuple(v) for k, v in data.get("links", {}).items()}
        self._offset = data.get("clock_offset_seconds", 0)
        self._awards_week = data.get("last_awards_week")

    def save(self) -> None:
        data = {
            "receipts": [r.to_dict() for r in self._receipts.values()],
            "tracked_channels": sorted(self._channels),
            "links": {str(k): list(v) for k, v in self._links.items()},
            "clock_offset_seconds": self._offset,
            "last_awards_week": self._awards_week,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

    # receipts

    def add(self, user_id, what, due, channel_id, message_id, message_link, now) -> Receipt:
        r = Receipt(
            id=uuid.uuid4().hex[:8],
            user_id=user_id,
            what=what[:MAX_WHAT],
            due=due,
            status="open",
            channel_id=channel_id,
            message_id=message_id,
            message_link=message_link,
            created_at=now,
        )
        self._receipts[r.id] = r
        self.save()
        return r

    def get(self, receipt_id: str) -> Receipt | None:
        return self._receipts.get(receipt_id)

    def find_by_message(self, message_id: int) -> Receipt | None:
        for r in self._receipts.values():
            if r.message_id == message_id:
                return r
        return None

    def all_receipts(self) -> list[Receipt]:
        return list(self._receipts.values())

    def mark_done(self, receipt_id, now) -> Receipt | None:
        r = self.get(receipt_id)
        if r is None:
            return None
        r.status = "done"
        r.done_at = now
        self.save()
        return r

    def remove(self, receipt_id) -> bool:
        if self._receipts.pop(receipt_id, None) is None:
            return False
        self.save()
        return True

    def reassign(self, receipt_id, new_user_id, now) -> Receipt | None:
        r = self.get(receipt_id)
        if r is None:
            return None
        r.previous_user_id = r.user_id
        r.user_id = new_user_id
        r.claimed_by = new_user_id
        r.claimed_at = now
        self.save()
        return r

    def mark_nudged(self, receipt_id) -> None:
        r = self.get(receipt_id)
        if r is not None:
            r.nudged = True
            self.save()

    # views

    def board(self, channel_id, now) -> dict[int, dict[str, list[Receipt]]]:
        out: dict[int, dict[str, list[Receipt]]] = {}
        for r in self._receipts.values():
            if r.channel_id != channel_id:
                continue
            groups = out.setdefault(r.user_id, {"open": [], "done": [], "overdue": []})
            groups[self._bucket(r, now)].append(r)
        return out

    @staticmethod
    def _bucket(r: Receipt, now) -> str:
        if r.status == "done":
            return "done"
        if r.due is not None and r.due < now:
            return "overdue"
        return "open"

    def _matches(self, candidates, query: str) -> list[Receipt]:
        wanted = words(query)
        scored = [(len(wanted & words(r.what)), r) for r in candidates]
        scored = [pair for pair in scored if pair[0] > 0]
        scored.sort(key=lambda pair: -pair[0])
        return [r for _, r in scored]

    def _open_in(self, channel_id: int):
        return [
            r for r in self._receipts.values()
            if r.status == "open" and r.channel_id == channel_id
        ]

    def ask_who(self, channel_id, query) -> list[Receipt]:
        return self._matches(self._open_in(channel_id), query)

    def find_open(self, user_id, channel_id, query) -> Receipt | None:
        mine = [r for r in self._open_in(channel_id) if r.user_id == user_id]
        found = self._matches(mine, query)
        return found[0] if found else None

    # privacy

    def forget(self, user_id) -> int:
        gone = [
            r.id for r in self._receipts.values()
            if user_id in (r.user_id, r.previous_user_id, r.claimed_by)
        ]
        for rid in gone:
            del self._receipts[rid]
        self._links = {m: v for m, v in self._links.items() if v[1] not in gone}
        self.save()
        return len(gone)

    # channels and message links

    def set_channel(self, channel_id: int, on: bool) -> None:
        if on:
            self._channels.add(channel_id)
        else:
            self._channels.discard(channel_id)
        self.save()

    def is_tracked(self, channel_id: int) -> bool:
        return channel_id in self._channels

    def tracked_channels(self) -> list[int]:
        return sorted(self._channels)

    def link_message(self, message_id: int, kind: str, receipt_id: str) -> None:
        self._links[message_id] = (kind, receipt_id)
        self.save()

    def lookup_message(self, message_id: int) -> tuple[str, str] | None:
        return self._links.get(message_id)

    def unlink_message(self, message_id: int) -> None:
        if self._links.pop(message_id, None) is not None:
            self.save()

    # settings

    @property
    def clock_offset_seconds(self) -> int:
        return self._offset

    @clock_offset_seconds.setter
    def clock_offset_seconds(self, value: int) -> None:
        self._offset = value
        self.save()

    @property
    def last_awards_week(self) -> str | None:
        return self._awards_week

    @last_awards_week.setter
    def last_awards_week(self, value: str | None) -> None:
        self._awards_week = value
        self.save()
