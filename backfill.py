# backfill on /receipts on: look back through recent messages for promises made this week.
# this file is pure. it decides which messages are worth proposing and leaves storing to bot.py,
# which stores nothing until someone taps ✅. message text is never logged.
from datetime import datetime, timedelta

import detect

HISTORY_LIMIT = 200
LOOKBACK = timedelta(days=7)
COMMAND_PREFIX = "!"


def _eligible(message, store, now: datetime, mark: int) -> bool:
    if message.author.bot or store.is_opted_out(message.author.id):
        return False
    # the mark is the newest message id from the last scan. ids only grow, so nothing is seen twice.
    if message.id <= mark or store.find_by_message(message.id) is not None:
        return False
    if message.content.startswith(COMMAND_PREFIX):
        return False
    return now - message.created_at <= LOOKBACK


def newest_id(messages) -> int:
    return max((message.id for message in messages), default=0)


def scan(messages, store, now: datetime, mark: int) -> list[dict]:
    """the promises worth proposing, oldest first. same detector as live chat, rules and all."""
    found = []
    for message in sorted(messages, key=lambda m: m.id):
        if not _eligible(message, store, now, mark):
            continue
        promise = detect.extract(message.content, message.author.id, now)
        if promise is None:
            continue
        found.append({
            "user_id": message.author.id,
            "what": promise["what"],
            "due": promise["due"],
            "message_id": message.id,
            "message_link": message.jump_url,
            "channel_id": message.channel.id,
        })
    return found
