# tests for backfill on /receipts on: the pure scan, the store flags, and the ✅/❌ proposal in bot.py.
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

import backfill
from tests.test_bot import FakeInteraction, FakeRelay, bot_module  # noqa: F401
from tests.test_bot_lists import FakeChannel, FakeMessage


# ---- store flags


def test_opt_out_and_forget(tmp_store, now):
    assert tmp_store.is_opted_out(5) is False
    tmp_store.forget(5)
    assert tmp_store.is_opted_out(5) is True
    tmp_store.opt_out(6)
    assert tmp_store.is_opted_out(6) is True


def test_backfill_mark_round_trips(tmp_path, now):
    from store import Store
    store = Store(tmp_path / "s.json")
    assert store.backfill_mark(10) == 0
    store.set_backfill_mark(10, 500)
    assert Store(tmp_path / "s.json").backfill_mark(10) == 500


# ---- the pure scan


def history_message(message_id, content, user_id=1, age_hours=1, is_bot=False, now=None):
    created = (now or datetime.now(timezone.utc)) - timedelta(hours=age_hours)
    return NS(id=message_id, content=content, author=NS(id=user_id, bot=is_bot), created_at=created,
              jump_url=f"https://discord.com/channels/1/10/{message_id}", channel=NS(id=10))


def test_scan_keeps_fresh_promises_only(tmp_store, now):
    tmp_store.opt_out(4)
    tmp_store.add(1, "old receipt", None, 10, 100, "l", now)
    messages = [
        history_message(100, "I'll do the slides", age_hours=2, now=now),
        history_message(101, "I can book the room by friday", user_id=2, age_hours=3, now=now),
        history_message(102, "I'll bring snacks", user_id=3, age_hours=24 * 8, now=now),
        history_message(103, "I'll write the summary", user_id=4, age_hours=1, now=now),
        history_message(104, "I'll write the summary", user_id=5, age_hours=1, is_bot=True, now=now),
        history_message(105, "lol did anyone read the rubric", user_id=2, age_hours=1, now=now),
        history_message(106, "!demo", user_id=2, age_hours=1, now=now),
        history_message(50, "I'll do the related work", user_id=2, age_hours=1, now=now),
    ]
    tmp_store.set_backfill_mark(10, 60)
    found = backfill.scan(messages, tmp_store, now, mark=60)
    assert [c["message_id"] for c in found] == [101]
    assert found[0] == {"user_id": 2, "what": "book the room", "due": now.replace(day=23, hour=23, minute=59),
                        "message_id": 101, "message_link": "https://discord.com/channels/1/10/101", "channel_id": 10}


def test_scan_newest_id(tmp_store, now):
    messages = [history_message(7, "x"), history_message(12, "y"), history_message(3, "z")]
    assert backfill.newest_id(messages) == 12
    assert backfill.newest_id([]) == 0


# ---- the proposal in the bot


class HistoryChannel(FakeChannel):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages
        self.limits = []
        self.originals = {}

    async def history(self, limit):
        self.limits.append(limit)
        for message in self.messages:
            yield message

    async def fetch_message(self, message_id):
        if message_id in self.posts:
            return self.posts[message_id]
        return self.originals.setdefault(message_id, FakePost(message_id, ""))


class OnInteraction(FakeInteraction):
    def __init__(self, user_id, channel):
        super().__init__(user_id, channel.id)
        self.channel = channel


@pytest.fixture
def wired(bot_module, monkeypatch):
    relay = FakeRelay()
    monkeypatch.setattr(bot_module, "relay_client", relay)
    bot_module.store.link_cubbie(2, "receipts-topic-of-user-2")
    return relay


class FakePost:
    def __init__(self, message_id, content):
        self.id = message_id
        self.content = content
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


def turn_on(bot_module, messages, user_id=1):
    channel = HistoryChannel(messages)
    interaction = OnInteraction(user_id, channel)
    asyncio.run(bot_module.receipts_on.callback(interaction))
    return channel, interaction


def test_on_proposes_and_stores_nothing_yet(bot_module, wired, caplog):
    messages = [history_message(100, "I'll do the slides"), history_message(101, "I can book the room", user_id=2)]
    with caplog.at_level(logging.INFO):
        channel, interaction = turn_on(bot_module, messages)
    assert channel.limits == [200]
    assert interaction.calls == [("respond", bot_module.voice.on_text(), {})]
    assert channel.sent == ["found 2 promises from this week. keep them?"]
    post = channel.posts[9001]
    assert post.reactions == [bot_module.DONE_EMOJI, bot_module.UNDO_EMOJI]
    assert bot_module.store.all_receipts() == []
    assert bot_module.store.lookup_message(9001) is None
    assert bot_module.store.backfill_mark(10) == 101
    assert "backfill_proposed channel=10 count=2" in caplog.text
    assert "slides" not in caplog.text


def test_on_with_nothing_found_posts_nothing(bot_module, wired):
    channel, _ = turn_on(bot_module, [history_message(100, "lol")])
    assert channel.sent == []


def test_yes_keeps_them_and_reacts_on_each(bot_module, wired):
    messages = [history_message(100, "I'll do the slides"), history_message(101, "I can book the room", user_id=2)]
    channel, _ = turn_on(bot_module, messages)
    payload = NS(message_id=9001, user_id=1, channel_id=10, guild_id=1)
    asyncio.run(bot_module.handle_backfill_reaction(payload, bot_module.DONE_EMOJI))
    receipts = sorted(bot_module.store.all_receipts(), key=lambda r: r.message_id)
    assert [(r.user_id, r.what, r.message_id) for r in receipts] == [(1, "do the slides", 100), (2, "book the room", 101)]
    assert channel.originals[100].reactions == [bot_module.RECEIPT_EMOJI]
    assert channel.originals[101].reactions == [bot_module.RECEIPT_EMOJI]
    assert channel.sent[-1] == "kept 2 receipts."
    assert bot_module.relay_client.posts[0][0] == "receipts-topic-of-user-2"
    assert bot_module.relay_client.posts[0][1].startswith(f"receipt id={receipts[1].id} what=book the room")
    # a second ✅ does nothing
    asyncio.run(bot_module.handle_backfill_reaction(payload, bot_module.DONE_EMOJI))
    assert len(bot_module.store.all_receipts()) == 2


def test_no_drops_them(bot_module, wired):
    channel, _ = turn_on(bot_module, [history_message(100, "I'll do the slides")])
    payload = NS(message_id=9001, user_id=1, channel_id=10, guild_id=1)
    asyncio.run(bot_module.handle_backfill_reaction(payload, bot_module.UNDO_EMOJI))
    assert bot_module.store.all_receipts() == []
    assert channel.sent[-1] == "ok, dropped them. nothing stored."
    assert 9001 not in bot_module._pending_backfill


def test_only_the_person_who_turned_it_on_decides(bot_module, wired):
    channel, _ = turn_on(bot_module, [history_message(100, "I'll do the slides")])
    asyncio.run(bot_module.handle_backfill_reaction(NS(message_id=9001, user_id=2, channel_id=10, guild_id=1),
                                                    bot_module.DONE_EMOJI))
    assert bot_module.store.all_receipts() == []
    assert 9001 in bot_module._pending_backfill


def test_same_message_is_never_proposed_twice(bot_module, wired):
    messages = [history_message(100, "I'll do the slides")]
    channel, _ = turn_on(bot_module, messages)
    asyncio.run(bot_module.handle_backfill_reaction(NS(message_id=9001, user_id=1, channel_id=10, guild_id=1),
                                                    bot_module.UNDO_EMOJI))
    channel2, _ = turn_on(bot_module, messages + [history_message(101, "I'll book the room", user_id=2)])
    assert channel2.sent == ["found 1 promise from this week. keep it?"]
    assert bot_module._pending_backfill[9001]["candidates"][0]["message_id"] == 101


def test_history_failure_is_logged_by_type_and_on_still_works(bot_module, wired, monkeypatch, caplog):
    import discord

    class BrokenChannel(FakeChannel):
        async def history(self, limit):
            raise discord.HTTPException(NS(status=403, reason="no"), "missing access")
            yield  # noqa: unreachable, makes this an async generator

    interaction = OnInteraction(1, BrokenChannel())
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.receipts_on.callback(interaction))
    assert bot_module.store.is_tracked(10)
    assert "backfill_failed channel=10 error=HTTPException" in caplog.text
    assert "missing access" not in caplog.text


def test_reaction_routing_reaches_backfill(bot_module, wired, monkeypatch):
    seen = []

    async def handle_backfill_reaction(payload, emoji):
        seen.append(emoji)
    monkeypatch.setattr(bot_module, "handle_backfill_reaction", handle_backfill_reaction)
    turn_on(bot_module, [history_message(100, "I'll do the slides")])
    bot_module.bot._connection.user = NS(id=777)
    payload = NS(message_id=9001, user_id=1, channel_id=10, guild_id=1, emoji="✅")
    asyncio.run(bot_module.on_raw_reaction_add(payload))
    assert seen == ["✅"]


def test_voice_counts():
    from voice import backfill_dropped_text, backfill_kept_text, backfill_proposal_text
    assert backfill_proposal_text(1) == "found 1 promise from this week. keep it?"
    assert backfill_proposal_text(3) == "found 3 promises from this week. keep them?"
    assert backfill_kept_text(1) == "kept 1 receipt."
    assert backfill_dropped_text() == "ok, dropped them. nothing stored."
