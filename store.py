# json backed state for the bot. one file, saved after every change.
# with background=True the write happens on one worker thread, in order, so the
# event loop never waits on fsync. the in-memory change is always immediate.
import asyncio
import json
import logging
import os
import re
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("receipts")

MAX_WHAT = 140
MIN_WORD = 3
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "who",
    "said", "they", "would", "doing", "going", "gonna",
}
DATE_FIELDS = ("due", "created_at", "done_at", "claimed_at", "ding_sent_at")


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
    # set when the promise came from a sign-up list (接龙), so the board can say so.
    list_id: str | None = None
    # ding: ✅ on any nudge sets acked. the last-call dm sets ding_sent_at. the cubbie ding sets dinged.
    acked: bool = False
    ding_sent_at: datetime | None = None
    dinged: bool = False

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


@dataclass
class SignupList:
    """one 接龙 sign-up list: a title, optional slot count, and who joined with what."""
    id: str
    channel_id: int
    title: str
    slots: int | None
    starter_message_id: int
    post_message_id: int
    author_id: int
    created_at: datetime
    status: str = "open"
    entries: list = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SignupList":
        data = dict(data)
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


def words(text: str) -> set[str]:
    found = re.split(r"[^a-z]+", text.lower())
    return {w for w in found if len(w) >= MIN_WORD and w not in STOPWORDS}


def write_state(path: Path, data: dict) -> None:
    """write one snapshot atomically: temp file, fsync, then swap into place."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(data, indent=2))
        # push it to disk before the swap, so a power cut can't leave an empty file.
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _log_write_failure(future: Future) -> None:
    if future.cancelled():
        return
    error = future.exception()
    if error is not None:
        # the path is not secret, but the policy is the same everywhere: type only.
        log.info("state_write_failed error=%s", type(error).__name__)


class Store:
    def __init__(self, path, background: bool = False):
        self.path = Path(path)
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="state") if background else None
        self._last_write: Future | None = None
        self._receipts: dict[str, Receipt] = {}
        self._channels: set[int] = set()
        self._links: dict[int, tuple[str, str]] = {}
        self._offset = 0
        self._awards_week: str | None = None
        self._cubbie: dict[int, str] = {}
        self._lists: dict[str, SignupList] = {}
        self._opted_out: set[int] = set()
        self._backfill_marks: dict[int, int] = {}
        self._ding: set[int] = set()
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
        self._cubbie = {int(k): v for k, v in data.get("cubbie_topics", {}).items()}
        for raw in data.get("lists", []):
            lst = SignupList.from_dict(raw)
            self._lists[lst.id] = lst
        self._opted_out = set(data.get("opted_out", []))
        self._backfill_marks = {int(k): v for k, v in data.get("backfill_marks", {}).items()}
        self._ding = set(data.get("ding_users", []))

    def snapshot(self) -> dict:
        return {
            "receipts": [r.to_dict() for r in self._receipts.values()],
            "tracked_channels": sorted(self._channels),
            "links": {str(k): list(v) for k, v in self._links.items()},
            "clock_offset_seconds": self._offset,
            "last_awards_week": self._awards_week,
            "cubbie_topics": {str(k): v for k, v in self._cubbie.items()},
            "lists": [lst.to_dict() for lst in self._lists.values()],
            "opted_out": sorted(self._opted_out),
            "backfill_marks": {str(k): v for k, v in self._backfill_marks.items()},
            "ding_users": sorted(self._ding),
        }

    def save(self) -> None:
        """inline by default. in background mode the snapshot is taken now and written on the worker."""
        data = self.snapshot()
        if self._writer is None:
            write_state(self.path, data)
            return
        self._last_write = self._writer.submit(write_state, self.path, data)
        self._last_write.add_done_callback(_log_write_failure)

    async def flushed(self) -> None:
        """wait for the newest queued write to land. raises what the write raised, once: the
        error goes to whoever was waiting on that write, then is cleared so a later call that
        queued nothing new does not trip over it. cancelling the waiter never cancels the write."""
        future = self._last_write
        if future is None:
            return
        try:
            await asyncio.shield(asyncio.wrap_future(future))
        except Exception:
            if self._last_write is future:
                self._last_write = None
            raise

    def wait(self) -> None:
        """block until the newest queued write has landed. for shutdown and tests."""
        if self._last_write is not None:
            self._last_write.result()

    def close(self) -> None:
        if self._writer is not None:
            self._writer.shutdown(wait=True)

    # receipts

    def add(self, user_id, what, due, channel_id, message_id, message_link, now,
            list_id: str | None = None) -> Receipt:
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
            list_id=list_id,
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
        self._set(receipt_id, nudged=True)

    def mark_acked(self, receipt_id) -> None:
        self._set(receipt_id, acked=True)

    def mark_ding_sent(self, receipt_id, now) -> None:
        self._set(receipt_id, ding_sent_at=now)

    def mark_dinged(self, receipt_id) -> None:
        self._set(receipt_id, dinged=True)

    def _set(self, receipt_id, **fields) -> None:
        r = self.get(receipt_id)
        if r is None:
            return
        self._receipts[receipt_id] = replace(r, **fields)
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

    # sign-up lists (接龙)

    def add_list(self, channel_id, title, slots, starter_message_id, post_message_id,
                 author_id, now) -> SignupList:
        lst = SignupList(
            id=uuid.uuid4().hex[:8],
            channel_id=channel_id,
            title=title[:MAX_WHAT],
            slots=slots,
            starter_message_id=starter_message_id,
            post_message_id=post_message_id,
            author_id=author_id,
            created_at=now,
        )
        self._lists[lst.id] = lst
        self.save()
        return lst

    def get_list(self, list_id: str) -> SignupList | None:
        return self._lists.get(list_id)

    def find_list_by_starter(self, message_id: int) -> SignupList | None:
        return next((l for l in self._lists.values() if l.starter_message_id == message_id), None)

    def find_list_by_post(self, message_id: int) -> SignupList | None:
        return next((l for l in self._lists.values() if l.post_message_id == message_id), None)

    def lists_in_channel(self, channel_id: int) -> list[SignupList]:
        found = [l for l in self._lists.values() if l.channel_id == channel_id]
        return sorted(found, key=lambda l: l.created_at, reverse=True)

    def open_list_in_channel(self, channel_id: int, now, window: timedelta) -> SignupList | None:
        """the newest open list in the channel that started within the window, if any."""
        for lst in self.lists_in_channel(channel_id):
            if lst.status == "open" and now - lst.created_at <= window:
                return lst
        return None

    def list_is_full(self, list_id: str) -> bool:
        lst = self.get_list(list_id)
        return lst is not None and lst.slots is not None and len(lst.entries) >= lst.slots

    def add_entry(self, list_id: str, user_id: int, item: str | None) -> dict | None:
        """join a list. a repeat join only counts when it adds an item to an entry without one."""
        lst = self.get_list(list_id)
        if lst is None or lst.status != "open":
            return None
        mine = next((e for e in lst.entries if e["user_id"] == user_id), None)
        if mine is not None:
            if item is None or mine["item"] is not None:
                return None
            entry = {**mine, "item": item[:MAX_WHAT]}
            lst.entries = [entry if e is mine else e for e in lst.entries]
        elif self.list_is_full(list_id):
            return None
        else:
            entry = {"user_id": user_id, "item": item[:MAX_WHAT] if item else None, "receipt_id": None}
            lst.entries = [*lst.entries, entry]
        self.save()
        return entry

    def set_entry_receipt(self, list_id: str, user_id: int, receipt_id: str) -> None:
        lst = self.get_list(list_id)
        if lst is None:
            return
        lst.entries = [{**e, "receipt_id": receipt_id} if e["user_id"] == user_id else e
                       for e in lst.entries]
        self.save()

    def lists_touching(self, user_id: int) -> tuple[list[SignupList], list[SignupList]]:
        """(lists this person started, lists they joined). forget() drops the first and scrubs the second."""
        started = [l for l in self._lists.values() if l.author_id == user_id]
        joined = [l for l in self._lists.values()
                  if l.author_id != user_id and any(e["user_id"] == user_id for e in l.entries)]
        return started, joined

    def close_list(self, list_id: str) -> SignupList | None:
        lst = self.get_list(list_id)
        if lst is None:
            return None
        lst.status = "closed"
        self.save()
        return lst

    # privacy

    def forget(self, user_id) -> int:
        gone = [
            r.id for r in self._receipts.values()
            if user_id in (r.user_id, r.previous_user_id, r.claimed_by)
        ]
        for rid in gone:
            del self._receipts[rid]
        self._cubbie.pop(user_id, None)
        self._ding.discard(user_id)
        dead_lists = [lid for lid, l in self._lists.items() if l.author_id == user_id]
        self._lists = {lid: l for lid, l in self._lists.items() if lid not in dead_lists}
        for lst in self._lists.values():
            lst.entries = [e for e in lst.entries if e["user_id"] != user_id]
        self._links = {m: v for m, v in self._links.items() if v[1] not in gone and v[1] not in dead_lists}
        # someone who asked to be forgotten is left out of any later backfill scan.
        self._opted_out.add(user_id)
        self.save()
        return len(gone)

    def opt_out(self, user_id: int) -> None:
        self._opted_out.add(user_id)
        self.save()

    def is_opted_out(self, user_id: int) -> bool:
        return user_id in self._opted_out

    # backfill. one message id per channel: the newest one the last scan looked at.

    def backfill_mark(self, channel_id: int) -> int:
        return self._backfill_marks.get(channel_id, 0)

    def set_backfill_mark(self, channel_id: int, message_id: int) -> None:
        self._backfill_marks[channel_id] = message_id
        self.save()

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

    def has_help_post(self, receipt_id: str) -> bool:
        return ("help", receipt_id) in self._links.values()

    # cubbie link. the topic works like a password, so it is never logged.

    def link_cubbie(self, user_id: int, topic: str) -> None:
        self._cubbie[user_id] = topic
        self.save()

    def unlink_cubbie(self, user_id: int) -> bool:
        if self._cubbie.pop(user_id, None) is None:
            return False
        self.save()
        return True

    def cubbie_topic(self, user_id: int) -> str | None:
        return self._cubbie.get(user_id)

    def cubbie_links(self) -> dict[int, str]:
        return dict(self._cubbie)

    # ding. off unless the user turned it on, and only linked users can.

    def set_ding(self, user_id: int, on: bool) -> None:
        if on:
            self._ding.add(user_id)
        else:
            self._ding.discard(user_id)
        self.save()

    def ding_on(self, user_id: int) -> bool:
        return user_id in self._ding

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
