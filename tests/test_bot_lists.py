# checks for the 接龙 sign-up list wiring in bot.py. no network: discord objects are fakes.
import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace as NS

import discord
import pytest

from tests.test_bot import FakeInteraction, FakeRelay, bot_module  # noqa: F401


class FakePost:
    def __init__(self, message_id, content):
        self.id = message_id
        self.content = content
        self.reactions = []
        self.edits = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def edit(self, content):
        self.edits.append(content)
        self.content = content


class FakeChannel:
    def __init__(self, channel_id=10, broken_edit=False):
        self.id = channel_id
        self.name = "cse511"
        self.posts = {}
        self.sent = []
        self.broken_edit = broken_edit

    async def send(self, text):
        post = FakePost(9000 + len(self.posts) + 1, text)
        self.posts[post.id] = post
        self.sent.append(text)
        return post

    async def fetch_message(self, message_id):
        if self.broken_edit:
            raise discord.HTTPException(NS(status=404, reason="no"), "unknown message")
        return self.posts[message_id]


class FakeMessage:
    def __init__(self, channel, content, message_id=20, user_id=1, reference=None):
        self.id = message_id
        self.content = content
        self.channel = channel
        self.author = NS(id=user_id, bot=False)
        self.reference = None if reference is None else NS(message_id=reference)
        self.jump_url = f"https://discord.com/channels/1/{channel.id}/{message_id}"
        self.reactions = []
        self.replies = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def reply(self, text):
        self.replies.append(text)


@pytest.fixture
def wired(bot_module, monkeypatch):
    channel = FakeChannel()

    async def get_channel(channel_id):
        return channel
    monkeypatch.setattr(bot_module, "get_channel", get_channel)

    async def name_of(uid):
        return {1: "Yash", 2: "Suraj", 3: "Bhavana"}.get(uid, "someone")
    monkeypatch.setattr(bot_module, "name_of", name_of)
    relay = FakeRelay()
    monkeypatch.setattr(bot_module, "relay_client", relay)
    bot_module.store.set_channel(10, True)
    return channel


def start(bot_module, channel, text="who's in for the potluck friday? need 3", user_id=1, message_id=20):
    message = FakeMessage(channel, text, message_id=message_id, user_id=user_id)
    handled = asyncio.run(bot_module.handle_list_starter(message, text, user_id))
    return handled, message


def join(bot_module, channel, text, user_id, message_id, reference=None):
    message = FakeMessage(channel, text, message_id=message_id, user_id=user_id, reference=reference)
    handled = asyncio.run(bot_module.handle_list_join(message, text, user_id))
    return handled, message


def test_starter_posts_a_list_with_a_join_reaction(bot_module, wired, caplog):
    with caplog.at_level(logging.INFO):
        handled, message = start(bot_module, wired)
    assert handled is True
    post = wired.posts[9001]
    assert post.content == "📋 potluck friday\n1. open\n2. open\n3. open\nreact 🙋 to join"
    assert post.reactions == [bot_module.CLAIM_EMOJI]
    lst = bot_module.store.find_list_by_starter(20)
    assert lst is not None and lst.slots == 3 and lst.post_message_id == 9001
    assert bot_module.store.lookup_message(9001) == ("list", lst.id)
    assert f"list_started list={lst.id} channel=10" in caplog.text
    assert "potluck" not in caplog.text


def test_non_starter_is_not_handled(bot_module, wired):
    handled, _ = start(bot_module, wired, text="I'll do the slides by thursday")
    assert handled is False and wired.sent == []


def test_plain_join_within_window_edits_the_post(bot_module, wired):
    start(bot_module, wired)
    handled, message = join(bot_module, wired, "me", 2, 21)
    assert handled is True
    assert wired.posts[9001].edits[-1] == "📋 potluck friday\n1. Suraj\n2. open\n3. open\nreact 🙋 to join"
    assert message.reactions == []
    assert bot_module.store.find_by_message(21) is None


def test_join_with_item_becomes_a_receipt_linked_to_the_list(bot_module, wired):
    bot_module.store.link_cubbie(2, "receipts-topic-of-user-2")
    start(bot_module, wired)
    handled, message = join(bot_module, wired, "I'll bring chips by 5pm", 2, 21, reference=20)
    assert handled is True
    receipt = bot_module.store.find_by_message(21)
    lst = bot_module.store.find_list_by_starter(20)
    assert receipt.what == "bring chips" and receipt.list_id == lst.id and receipt.user_id == 2
    assert receipt.due is not None
    assert message.reactions == [bot_module.RECEIPT_EMOJI]
    assert lst.entries == [{"user_id": 2, "item": "bring chips", "receipt_id": receipt.id}]
    assert "1. Suraj: bring chips" in wired.posts[9001].edits[-1]
    assert bot_module.relay_client.posts[0][0] == "receipts-topic-of-user-2"
    assert bot_module.relay_client.posts[0][1].startswith(f"receipt id={receipt.id} what=bring chips")


def test_reply_to_the_post_joins_too(bot_module, wired):
    start(bot_module, wired)
    handled, _ = join(bot_module, wired, "+1", 3, 21, reference=9001)
    assert handled is True
    assert [e["user_id"] for e in bot_module.store.find_list_by_starter(20).entries] == [3]


def test_duplicate_join_adds_nothing(bot_module, wired):
    start(bot_module, wired)
    join(bot_module, wired, "me", 2, 21)
    handled, _ = join(bot_module, wired, "I'm in", 2, 22)
    assert handled is True
    assert len(bot_module.store.find_list_by_starter(20).entries) == 1
    assert len(wired.posts[9001].edits) == 1


def test_full_list_says_so_and_takes_nobody(bot_module, wired):
    start(bot_module, wired, text="need 1 driver for saturday")
    join(bot_module, wired, "I can drive", 2, 21)
    handled, message = join(bot_module, wired, "me", 3, 22)
    assert handled is True
    assert message.replies == ["driver for saturday is full."]
    assert [e["user_id"] for e in bot_module.store.find_list_by_starter(20).entries] == [2]


def test_closed_list_ignores_joins(bot_module, wired):
    start(bot_module, wired)
    lst = bot_module.store.find_list_by_starter(20)
    bot_module.store.close_list(lst.id)
    handled, _ = join(bot_module, wired, "me", 2, 21, reference=20)
    assert handled is False
    assert bot_module.store.get_list(lst.id).entries == []


def test_join_outside_the_window_without_a_reply_is_not_a_join(bot_module, wired):
    current = bot_module.now()
    post = asyncio.run(wired.send("📋 potluck"))
    old = bot_module.store.add_list(10, "potluck", None, 20, post.id, 1, current - timedelta(minutes=31))
    handled, _ = join(bot_module, wired, "me", 2, 21)
    assert handled is False
    handled, _ = join(bot_module, wired, "me", 2, 22, reference=20)
    assert handled is True
    assert [e["user_id"] for e in bot_module.store.get_list(old.id).entries] == [2]


def test_reaction_joins_and_repeat_reaction_does_nothing(bot_module, wired):
    start(bot_module, wired)
    lst = bot_module.store.find_list_by_starter(20)
    payload = NS(message_id=9001, user_id=2, channel_id=10)
    asyncio.run(bot_module.handle_list_reaction(payload, lst.id))
    asyncio.run(bot_module.handle_list_reaction(payload, lst.id))
    assert [e["user_id"] for e in bot_module.store.get_list(lst.id).entries] == [2]
    assert len(wired.posts[9001].edits) == 1
    assert "1. Suraj" in wired.posts[9001].edits[0]


def test_edit_failure_logs_type_only(bot_module, wired, caplog):
    start(bot_module, wired)
    wired.broken_edit = True
    with caplog.at_level(logging.INFO):
        handled, _ = join(bot_module, wired, "me", 2, 21)
    assert handled is True
    lst = bot_module.store.find_list_by_starter(20)
    assert f"list_edit_failed list={lst.id} error=HTTPException" in caplog.text
    assert "unknown message" not in caplog.text


def test_close_command_locks_the_newest_open_list(bot_module, wired):
    start(bot_module, wired)
    join(bot_module, wired, "me", 2, 21)
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.list_close.callback(interaction, None))
    lst = bot_module.store.find_list_by_starter(20)
    assert lst.status == "closed"
    assert interaction.calls == [("defer", None, {"ephemeral": False}), ("followup", "closed potluck friday. 1 in.", {})]
    assert wired.posts[9001].edits[-1] == "📋 potluck friday (closed)\n1. Suraj"
    handled, _ = join(bot_module, wired, "me", 3, 22)
    assert handled is False


def test_close_command_picks_a_list_by_words(bot_module, wired):
    start(bot_module, wired, text="who's in for bowling", message_id=20)
    start(bot_module, wired, text="need 2 drivers for saturday", message_id=30)
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.list_close.callback(interaction, "bowling"))
    assert bot_module.store.find_list_by_starter(20).status == "closed"
    assert bot_module.store.find_list_by_starter(30).status == "open"


def test_close_command_with_nothing_open(bot_module, wired):
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.list_close.callback(interaction, None))
    assert interaction.calls == [("defer", None, {"ephemeral": True}),
                                 ("followup", bot_module.voice.list_none_text(), {"ephemeral": True})]


def test_board_shows_lists_and_list_receipts(bot_module, wired):
    start(bot_module, wired)
    join(bot_module, wired, "I'll bring chips", 2, 21)
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.receipts_board.callback(interaction))
    board = interaction.calls[1][1]
    assert "lists\npotluck friday: 1 in, 2 open" in board
    assert "• bring chips (due no date, list)" in board


def test_on_message_order_starter_then_join_then_promise(bot_module, wired, monkeypatch):
    seen = []

    async def handle_candidate(message, text, author_id):
        seen.append(text)
    monkeypatch.setattr(bot_module, "handle_candidate", handle_candidate)
    for text, uid, mid in [("who's in for the potluck friday?", 1, 20), ("I'll bring chips", 2, 21),
                           ("I'll do the slides by thursday", 3, 22)]:
        asyncio.run(bot_module.handle_chat(FakeMessage(wired, text, message_id=mid, user_id=uid), text, uid))
    assert seen == ["I'll do the slides by thursday"]
    assert [e["item"] for e in bot_module.store.find_list_by_starter(20).entries] == ["bring chips"]


def test_demo_lines_include_a_potluck_list(bot_module):
    texts = [text for _, text in bot_module.demo.DEMO_LINES]
    assert any(bot_module.lists.rule_starter(t) for t in texts)
    assert any(bot_module.lists.join(t, bot_module.now()) for t in texts)


# ---- review fixes


def test_starter_stores_the_list_before_reacting(bot_module, wired, monkeypatch):
    class NoReactChannel(FakeChannel):
        async def send(self, text):
            post = await super().send(text)

            async def add_reaction(emoji):
                raise discord.HTTPException(NS(status=403, reason="no"), "missing permissions")
            post.add_reaction = add_reaction
            return post
    channel = NoReactChannel()

    async def get_channel(channel_id):
        return channel
    monkeypatch.setattr(bot_module, "get_channel", get_channel)
    with pytest.raises(discord.HTTPException):
        start(bot_module, channel)
    assert bot_module.store.find_list_by_starter(20) is not None


def test_forgetme_scrubs_joined_lists_and_replaces_started_ones(bot_module, wired):
    start(bot_module, wired, text="who's in for bowling", user_id=1, message_id=20)
    start(bot_module, wired, text="who's in for the potluck", user_id=2, message_id=30)
    join(bot_module, wired, "I'll bring chips", 1, 31, reference=30)
    join(bot_module, wired, "me", 3, 32, reference=30)
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.forgetme_command.callback(interaction))
    assert wired.posts[9001].edits[-1] == "📋 list removed"
    assert wired.posts[9002].edits[-1] == "📋 potluck\n1. Bhavana\nreact 🙋 to join"
    assert bot_module.store.lookup_message(9001) is None
    assert bot_module.store.find_by_message(31) is None
    assert "Yash" not in wired.posts[9002].content and "chips" not in wired.posts[9002].content
