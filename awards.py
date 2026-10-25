# works out the weekly awards from the store. it only returns data.
# the words for the awards live in voice.py.
from collections import Counter
from datetime import datetime, time, timedelta

FRIDAY = 4
POST_HOUR = 17
WEEK = timedelta(days=7)


def week_bounds(now: datetime) -> tuple[datetime, datetime]:
    # the awards week ends on a friday at 5pm.
    days_ahead = (FRIDAY - now.weekday()) % 7
    end = datetime.combine(
        (now + timedelta(days=days_ahead)).date(),
        time(POST_HOUR),
        tzinfo=now.tzinfo,
    )
    if now >= end:
        end += WEEK
    return end - WEEK, end


def week_key(now: datetime) -> str:
    # stays the same for the whole friday 5pm hour and through the weekend.
    start, end = week_bounds(now)
    after_post_time = now.weekday() > FRIDAY or (
        now.weekday() == FRIDAY and now.hour >= POST_HOUR
    )
    return (start if after_post_time else end).date().isoformat()


def should_post(now: datetime, last_week_key: str | None) -> bool:
    return (
        now.weekday() == FRIDAY
        and now.hour == POST_HOUR
        and week_key(now) != last_week_key
    )


def _winners(scores: dict[int, float]) -> dict | None:
    if not scores:
        return None
    best = max(scores.values())
    ids = sorted(u for u, v in scores.items() if v == best)
    return {"user_ids": ids, "value": best}


def _lowest(scores: dict[int, float]) -> dict | None:
    flipped = {u: -v for u, v in scores.items()}
    found = _winners(flipped)
    return None if found is None else {**found, "value": -found["value"]}


def _in_window(when: datetime | None, start: datetime, end: datetime) -> bool:
    return when is not None and start <= when < end


def _reliable(made: list) -> dict | None:
    total = Counter(r.user_id for r in made)
    done = Counter(r.user_id for r in made if r.status == "done")
    found = _winners({u: done[u] / total[u] for u in total})
    # nobody finished anything, so nobody gets "most reliable".
    if found is None or found["value"] == 0:
        return None
    return found


def _comeback(receipts: list, start: datetime, end: datetime) -> dict | None:
    gaps: dict[int, float] = {}
    for r in receipts:
        if r.status != "done" or r.due is None:
            continue
        if not _in_window(r.done_at, start, end) or r.done_at > r.due:
            continue
        gap = (r.due - r.done_at).total_seconds()
        gaps[r.user_id] = min(gap, gaps.get(r.user_id, gap))
    return _lowest(gaps)


def _closer(receipts: list, start: datetime, end: datetime) -> dict | None:
    claims = Counter(
        r.claimed_by for r in receipts
        if r.claimed_by is not None and _in_window(r.claimed_at, start, end)
    )
    return _winners(dict(claims))


def compute(store, week_start: datetime, week_end: datetime,
            channel_id: int | None = None) -> dict:
    receipts = store.all_receipts()
    # awards for one channel only count that channel, so names don't leak between groups.
    if channel_id is not None:
        receipts = [r for r in receipts if r.channel_id == channel_id]
    made = [r for r in receipts if _in_window(r.created_at, week_start, week_end)]
    counts = Counter(r.user_id for r in made)
    return {
        "most_reliable": _reliable(made),
        "biggest_comeback": _comeback(receipts, week_start, week_end),
        "most_promises": _winners(dict(counts)),
        "the_closer": _closer(receipts, week_start, week_end),
    }
