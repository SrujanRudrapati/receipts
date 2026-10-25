# decides what is due soon and holds the demo clock for !tick.
from datetime import timedelta

END_OF_DAY = (23, 59)


def due_soon(store, now, hours=24):
    end = now + timedelta(hours=hours)
    found = [
        r for r in store.all_receipts()
        if r.status == "open" and not r.nudged
        and r.due is not None and now <= r.due <= end
    ]
    return sorted(found, key=lambda r: r.due)


def demo_now(store, real_now):
    return real_now + timedelta(seconds=store.clock_offset_seconds)


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
