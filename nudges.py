# decides what is due soon and holds the demo clock for !tick.
import math
from datetime import timedelta

END_OF_DAY = (23, 59)
MAX_TICK_HOURS = 24 * 14
# ding: the last-call dm goes out this close to due, and cubbie hears about it after this much silence.
DING_HOURS = 2
DING_WAIT = timedelta(minutes=30)
# !tick walks the clock in steps this big, running the scheduler after each, so every stage fires in order.
TICK_STEP_HOURS = 0.5


def due_soon(store, now, hours=24):
    end = now + timedelta(hours=hours)
    found = [
        r for r in store.all_receipts()
        if r.status == "open" and not r.nudged
        and r.due is not None and now <= r.due <= end
    ]
    return sorted(found, key=lambda r: r.due)


def _armed(store, receipt) -> bool:
    """ding only reaches people who linked cubbie and turned it on, and only for open, unanswered receipts."""
    return (receipt.status == "open" and not receipt.acked
            and store.ding_on(receipt.user_id) and store.cubbie_topic(receipt.user_id) is not None)


def ding_due(store, now):
    """open receipts due within DING_HOURS whose owner has not answered and has not had the last call yet."""
    end = now + timedelta(hours=DING_HOURS)
    found = [
        r for r in store.all_receipts()
        if _armed(store, r) and r.ding_sent_at is None
        and r.due is not None and now <= r.due <= end
    ]
    return sorted(found, key=lambda r: r.due)


def ding_escalate(store, now):
    """last call went out DING_WAIT ago, still no answer, and cubbie has not been told."""
    found = [
        r for r in store.all_receipts()
        if _armed(store, r) and not r.dinged
        and r.ding_sent_at is not None and now - r.ding_sent_at >= DING_WAIT
    ]
    return sorted(found, key=lambda r: r.ding_sent_at)


def tick_steps(hours: float) -> list[float]:
    whole = int(hours // TICK_STEP_HOURS)
    rest = round(hours - whole * TICK_STEP_HOURS, 6)
    return [TICK_STEP_HOURS] * whole + ([rest] if rest > 0 else [])


def demo_now(store, real_now):
    return real_now + timedelta(seconds=store.clock_offset_seconds)


def valid_tick_hours(hours: float) -> bool:
    # a huge or weird value would break the clock for good, so only allow 0 to 2 weeks.
    return math.isfinite(hours) and 0 < hours <= MAX_TICK_HOURS


def tick(store, hours):
    store.clock_offset_seconds += int(round(hours * 3600))


def when_label(due, now):
    local = due.astimezone(now.tzinfo)
    days = (local.date() - now.date()).days
    if days == 0:
        day = "today"
    elif days == 1:
        day = "tomorrow"
    else:
        day = local.strftime("%A").lower()
    if (local.hour, local.minute) == END_OF_DAY:
        return day
    return f"{day} at {clock_text(local)}"


def clock_text(local):
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    if local.minute:
        return f"{hour}:{local.minute:02d}{suffix}"
    return f"{hour}{suffix}"
