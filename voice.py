# every line the bot says, as short lowercase templates.
# names are plain text and no template has an at sign. the bot never pings anyone.
import re

MAX_POLISH_LEN = 120
MAX_BOARD_CHARS = 1900
MORE_LINE = "...and more. use /done to clear some."
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


# ding. the dm asks once more. the channel only ever sees the bell.

def ding_dm(what, when_label):
    return f"last call: {what} due {when_label}. still on it?"


def reminded_text():
    return "🔔 reminded"


def ding_on_text():
    return "ok, ding is on. if you go quiet before something is due, cubbie hears about it."


def ding_off_text():
    return "ok, ding is off."


def ding_needs_link_text():
    return "link cubbie first with /receipts link."


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
    out = []
    for r in receipts:
        tag = ", list" if getattr(r, "list_id", None) else ""
        out.append(f"• {r.what} (due {_date_label(r.due)}{tag})")
    return out


def _cap(text: str) -> str:
    # discord rejects messages over 2000 chars. cut at a whole line and say there is more.
    if len(text) <= MAX_BOARD_CHARS:
        return text
    room = MAX_BOARD_CHARS - len(MORE_LINE) - 1
    kept = text[:room].rsplit("\n", 1)[0]
    return kept + "\n" + MORE_LINE


def _list_summary(lst):
    count = len(lst.entries)
    if lst.status != "open":
        return f"{lst.title}: {count} in (closed)"
    if lst.slots is None:
        return f"{lst.title}: {count} in"
    return f"{lst.title}: {count} in, {max(lst.slots - count, 0)} open"


def board_text(groups, names, include_overdue, lists=()):
    sections = [("open", None), ("done", "done:")]
    if include_overdue:
        sections.append(("overdue", "overdue:"))
    blocks = []
    if lists:
        blocks.append("\n".join(["lists"] + [_list_summary(lst) for lst in lists]))
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
    return _cap("\n\n".join(blocks))


def overdue_text(groups, names):
    blocks = []
    for user_id, buckets in groups.items():
        lines = _lines(buckets.get("overdue", []))
        if lines:
            blocks.append("\n".join([_name(names, user_id)] + lines))
    if not blocks:
        return "nothing overdue."
    return _cap("\n\n".join(blocks))


# sign-up lists (接龙). one post the bot edits in place.

def list_text(title, entries, slots, names, closed):
    head = f"📋 {title}" + (" (closed)" if closed else "")
    lines = []
    for number, entry in enumerate(entries, start=1):
        who = _name(names, entry["user_id"])
        item = f": {entry['item']}" if entry.get("item") else ""
        lines.append(f"{number}. {who}{item}")
    if slots is not None and not closed:
        lines.extend(f"{number}. open" for number in range(len(entries) + 1, slots + 1))
    if not lines:
        lines.append("nobody yet.")
    if not closed:
        lines.append("react 🙋 to join")
    return _cap("\n".join([head] + lines))


def list_removed_text():
    return "📋 list removed"


def list_closed_text(title, count):
    return f"closed {title}. {count} in."


def list_none_text():
    return "no open list here."


def list_full_text(title):
    return f"{title} is full."


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
    ("the_closer", lambda who, v: f"the closer: {who}. jumped in when someone needed a hand."),
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
        "say \"who's in for ...\" or \"need 3 drivers\" and i'll start a 接龙 sign-up list. reply \"me\" or react 🙋 to join. `/receipts list close` locks it.",
        "`/awards` for the playful weekly awards.",
        "`/forgetme` wipes everything i have on you.",
        "`/receipts off` turns me off in a channel.",
        "`/receipts link` connects cubbie, so it hears about your receipts. `/receipts unlink` stops that.",
        "`/receipts ding on` lets cubbie hear when you go quiet right before something is due. off by default.",
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


def tick_bad_text():
    return "give me a number of hours between 0 and 336."


def demo_denied_text():
    return "only demo runners can do this."


# backfill on /receipts on. the proposal says how many, never what.

def backfill_proposal_text(count):
    if count == 1:
        return "found 1 promise from this week. keep it?"
    return f"found {count} promises from this week. keep them?"


def backfill_kept_text(count):
    return f"kept {_count(count, 'receipt', 'receipts')}."


def backfill_dropped_text():
    return "ok, dropped them. nothing stored."


# cubbie link. the token goes by dm only, and the channel replies never repeat it.

def link_dm(topic):
    return "\n".join([
        "save this in Cubbie as RECEIPTS_LINK_TOKEN. it works like a password.",
        topic,
    ])


def link_reply():
    return "sent you a dm with your cubbie token."


def link_dm_failed():
    return "i couldn't dm you. open your dms for this server and try again."


def unlink_text():
    return "ok, unlinked. cubbie won't hear about your receipts anymore."


def unlink_none_text():
    return "you weren't linked to cubbie."


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
