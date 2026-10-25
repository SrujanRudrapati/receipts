# turns phrases like "by thursday" or "fri 5pm" into a tz-aware datetime.
# pure functions. bad input gives None, never an error.
import re
from datetime import datetime, timedelta

WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3,
    "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

_DAY_WORDS = ["tonight", "today", "eod", "end of day", "tomorrow", "tmrw", "tmr",
              "this weekend", "next week"] + list(WEEKDAYS)
_DAY = "|".join(sorted(map(re.escape, _DAY_WORDS), key=len, reverse=True))
_STRONG = r"(?=\d{1,2}(?::\d{2}|\s*[ap]m\b))"


def _clock_re(tag: str) -> str:
    return (rf"(?P<h{tag}>\d{{1,2}})(?::(?P<m{tag}>\d{{2}}))?"
            rf"\s*(?P<ap{tag}>am|pm)?\b")


_LEAD = r"(?:(?:by|before|on|until|til)\s+)?"

# a day, optionally followed by a time. or a time on its own.
_PHRASE = re.compile(
    r"\b" + _LEAD + r"(?:(?P<day>" + _DAY + r")\b"
    r"(?:\s+(?:at\s+|" + _STRONG + r")" + _clock_re("1") + r")?"
    r"|(?:(?:by|before|until|til|at)\s+|" + _STRONG + r")" + _clock_re("2") + r")",
    re.IGNORECASE,
)

END_OF_DAY = (23, 59)


def find_due_text(text: str) -> str | None:
    m = _PHRASE.search(text or "")
    return m.group(0) if m else None


def strip_due(text: str) -> str:
    cleaned = _PHRASE.sub("", text or "", count=1)
    return re.sub(r"\s+", " ", cleaned).strip()


def _clock(m: re.Match) -> tuple[int, int] | None:
    tag = "1" if m.group("h1") else "2"
    hour = int(m.group("h" + tag))
    minute = int(m.group("m" + tag) or 0)
    ap = (m.group("ap" + tag) or "").lower()
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    elif not ap and 1 <= hour <= 6:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _at(day: datetime, hm: tuple[int, int]) -> datetime:
    return day.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def _day_target(word: str, now: datetime) -> tuple[datetime, tuple[int, int]]:
    """the date and the default time for a day word."""
    word = word.lower()
    if word == "tonight":
        return now, (21, 0) if now.hour < 21 else END_OF_DAY
    if word in ("today", "eod", "end of day"):
        return now, (17, 0) if now.hour < 17 else END_OF_DAY
    if word in ("tomorrow", "tmrw", "tmr"):
        return now + timedelta(days=1), END_OF_DAY
    if word == "this weekend":
        return now + timedelta(days=(5 - now.weekday()) % 7 or 7), END_OF_DAY
    if word == "next week":
        return now + timedelta(days=7 - now.weekday()), END_OF_DAY
    ahead = (WEEKDAYS[word] - now.weekday()) % 7 or 7
    return now + timedelta(days=ahead), END_OF_DAY


def parse_due(text: str, now: datetime) -> datetime | None:
    try:
        m = _PHRASE.search(text or "")
        if not m:
            return None
        has_time = bool(m.group("h1") or m.group("h2"))
        hm = _clock(m) if has_time else None
        if has_time and hm is None:
            return None
        if m.group("day"):
            day, default = _day_target(m.group("day"), now)
            return _at(day, hm or default)
        result = _at(now, hm)
        return result if result > now else result + timedelta(days=1)
    except (ValueError, KeyError, AttributeError, TypeError):
        return None
