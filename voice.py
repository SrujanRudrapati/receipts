"""Every string the bot says, as short lowercase-casual templates.

Names are plain text and no template contains an at sign. Pings happen
elsewhere via Discord's own mention mechanism.
"""
import re

MAX_POLISH_LEN = 120
END_OF_DAY = (23, 59)
FALLBACK_NAME = "someone"

_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
         "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"}
_MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december",
           "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
_CALENDAR_WORDS = _DAYS | _MONTHS


def nudge_dm(what, when_label):
    return f"{what} due {when_label}. still on it?"


def got_it():
    return "got it."


def help_wanted(name, what):
    return f"{name} could use a hand with {what}. anyone?"


def claimed_channel(claimer, what):
    return f"{claimer} is on {what} now. nice."


def claimed_dm_old(claimer, what):
    return f"{claimer} picked up {what}, so it's off your plate. thanks for flagging it."


def claimed_dm_new(what, when_label):
    return f"you picked up {what}. it's due {when_label}."


def who_answer(name, what, link):
    return f"{name} said they'd {what}. {link}"


def who_none():
    return "i don't have a receipt for that."


def _name(names, user_id):
    return names.get(user_id) or FALLBACK_NAME


def _date_label(due):
    if due is None:
        return "no date"
    label = due.strftime("%a %b %d").lower()
    label = re.sub(r" 0(\d)$", r" \1", label)
    if (due.hour, due.minute) != END_OF_DAY:
        hour = due.hour % 12 or 12
        suffix = "am" if due.hour < 12 else "pm"
        minute = f":{due.minute:02d}" if due.minute else ""
        label += f" {hour}{minute}{suffix}"
    return label


def _lines(receipts):
    return [f"• {r.what} (due {_date_label(r.due)})" for r in receipts]


def board_text(groups, names, include_overdue):
    sections = [("open", None), ("done", "done:")]
    if include_overdue:
        sections.append(("overdue", "overdue:"))
    blocks = []
    for user_id, buckets in groups.items():
        body = []
        for key, label in sections:
            lines = _lines(buckets.get(key, []))
            if lines:
                body.extend(([label] if label else []) + lines)
        if body:
            blocks.append("\n".join([f"{_name(names, user_id)}"] + body))
    if not blocks:
        return "nothing on the board yet."
    return "\n\n".join(blocks)


def overdue_text(groups, names):
    blocks = []
    for user_id, buckets in groups.items():
        lines = _lines(buckets.get("overdue", []))
        if lines:
            blocks.append("\n".join([_name(names, user_id)] + lines))
    if not blocks:
        return "nothing overdue."
    return "\n\n".join(blocks)


def _join_names(user_ids, names):
    parts = [_name(names, uid) for uid in user_ids]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _count(value, singular, plural):
    n = int(value)
    return f"{n} {singular if n == 1 else plural}"


_AWARD_LINES = (
    ("most_reliable", lambda who, v: f"most reliable: {who}. said it, did it."),
    ("biggest_comeback", lambda who, v: f"biggest comeback: {who}. back on track."),
    ("most_promises", lambda who, v: f"most promises: {who}, with {_count(v, 'promise', 'promises')}. big energy."),
    ("the_closer", lambda who, v: f"the closer: {who}. finished things right at the buzzer."),
)


def awards_text(result, names):
    lines = []
    for key, render in _AWARD_LINES:
        award = result.get(key)
        if award:
            lines.append(render(_join_names(award["user_ids"], names), award["value"]))
    return "\n".join(lines) if lines else "quiet week. no awards yet."


def help_text():
    return "\n".join([
        "i catch promises in channels where someone ran `/receipts on`.",
        "react ❌ or reply \"not a promise\" to undo one.",
        "react ✅ or use `/done <what>` when it's finished.",
        "`/receipts board` shows who said what.",
        "ask \"who said they'd ...\" and i'll dig up the receipt.",
        "`/awards` for the playful weekly awards.",
        "`/forgetme` wipes everything i have on you.",
        "`/receipts off` turns me off in a channel.",
    ])


def on_text():
    return "ok, i'm listening here. say what you'll do and i'll keep the receipt."


def off_text():
    return "ok, i've stopped listening here."


def forgot_text(count):
    return f"forgot you. {_count(count, 'receipt', 'receipts')} gone."


def undo_text():
    return "ok, undone. not a promise."


def done_text(what):
    return f"nice, {what} is done."


def not_found_text():
    return "couldn't find that one."


def demo_banner():
    return ("demo mode: the next few messages are a fake CSE 511 group chat "
            "so you can see receipts get caught.")


def tick_text(hours, when):
    return f"moved the clock {_count(hours, 'hour', 'hours')} ahead. pretending it is {when} now."


_DIGITS = re.compile(r"\d+")
_CAP_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _sentence_initial(text, start):
    before = text[:start].rstrip()
    return not before or before[-1] in ".!?\n"


def validate_polish(text, allowed_numbers, allowed_names):
    if "@" in text or "<@" in text or len(text) > MAX_POLISH_LEN:
        return False
    if any(run not in allowed_numbers for run in _DIGITS.findall(text)):
        return False
    for match in _CAP_WORD.finditer(text):
        word = match.group()
        if not word[0].isupper() or _sentence_initial(text, match.start()):
            continue
        if word.lower() in _CALENDAR_WORDS or word in allowed_names:
            continue
        return False
    return True


def polish(text, allowed_numbers, allowed_names, llm_call=None):
    if llm_call is None:
        return text
    try:
        candidate = llm_call(text)
        if isinstance(candidate, str) and validate_polish(candidate, allowed_numbers, allowed_names):
            return candidate
    except Exception:
        pass
    return text
