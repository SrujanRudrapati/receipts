# checks for the discord wiring. no network: discord calls are swapped for fakes.
import ast
import asyncio
import importlib
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import discord
import pytest
from discord.ext import commands

FAKE_TOKEN = "fake-token-abc123"


@pytest.fixture
def bot_module(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("USE_LLM", "false")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.delenv("GUILD_ID", raising=False)
    import bot

    return importlib.reload(bot)


def test_intents_are_the_minimum_set(bot_module):
    wanted = discord.Intents.none()
    wanted.guilds = True
    wanted.guild_messages = True
    wanted.message_content = True
    wanted.guild_reactions = True
    wanted.dm_messages = True
    wanted.dm_reactions = True
    assert bot_module.intents.value == wanted.value
    assert not bot_module.intents.members
    assert not bot_module.intents.presences


def test_no_mentions_by_default(bot_module):
    mentions = bot_module.bot.allowed_mentions
    assert mentions.everyone is False
    assert mentions.users is False
    assert mentions.roles is False


def test_who_pattern(bot_module):
    match = bot_module.WHO_PATTERN.match("who said they'd book the room?")
    assert match and match.group(1) == "book the room"
    assert bot_module.WHO_PATTERN.match("who's doing the slides")
    assert bot_module.WHO_PATTERN.match("I'll book the room") is None


def _log_calls_using(source: str, name: str) -> list[int]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "log":
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node)):
                found.append(node.lineno)
    return found


def test_no_log_call_uses_the_token():
    source = (Path(__file__).parent.parent / "bot.py").read_text()
    assert "log." in source
    assert _log_calls_using(source, "TOKEN") == []
    # the checker itself works
    assert _log_calls_using("log.info('x %s', TOKEN)", "TOKEN") == [1]


class FakeMessage:
    def __init__(self, message_id):
        self.id = message_id


def fake_dm(sent):
    async def dm(user_id, text, reactions=()):
        sent.append((user_id, text))
        return FakeMessage(5000 + len(sent))
    return dm


def fake_channels(posted, broken=()):
    async def get_channel(channel_id):
        if channel_id in broken:
            raise discord.HTTPException(NS(status=403, reason="no"), "missing access")

        async def send(text):
            posted.append((channel_id, text))
            return FakeMessage(9000 + len(posted))
        return NS(id=channel_id, send=send)
    return get_channel


def test_scheduler_never_logs_token(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("DISCORD_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    import bot
    mod = importlib.reload(bot)
    assert mod.TOKEN == FAKE_TOKEN
    sent = []
    monkeypatch.setattr(mod, "dm", fake_dm(sent))
    current = mod.now()
    mod.store.add(1, "slides", current + timedelta(hours=23), 10, 20, "link", current)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(mod.run_scheduler_once())
    assert len(sent) == 1
    assert "nudge_sent" in caplog.text
    assert FAKE_TOKEN not in caplog.text


def test_nudged_once_across_two_runs(bot_module, monkeypatch):
    sent, posted = [], []
    monkeypatch.setattr(bot_module, "dm", fake_dm(sent))
    monkeypatch.setattr(bot_module, "get_channel", fake_channels(posted))
    current = bot_module.now()
    r = bot_module.store.add(1, "slides", current + timedelta(hours=23), 10, 20, "link", current)
    asyncio.run(bot_module.run_scheduler_once())
    asyncio.run(bot_module.run_scheduler_once())
    assert [uid for uid, _ in sent] == [1]
    assert bot_module.store.get(r.id).nudged is True
    assert bot_module.store.lookup_message(5001) == ("nudge", r.id)


def test_one_bad_nudge_does_not_stop_others(bot_module, monkeypatch, caplog):
    sent = []

    async def dm(user_id, text, reactions=()):
        if user_id == 1:
            raise RuntimeError("boom")
        sent.append(user_id)
        return FakeMessage(1)
    monkeypatch.setattr(bot_module, "dm", dm)
    current = bot_module.now()
    bad = bot_module.store.add(1, "a", current + timedelta(hours=2), 10, 20, "l", current)
    bot_module.store.add(2, "b", current + timedelta(hours=3), 10, 21, "l", current)
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.run_scheduler_once())
        asyncio.run(bot_module.run_scheduler_once())
    assert sent == [2]
    assert f"nudge_failed receipt={bad.id}" in caplog.text
    assert bot_module.store.get(bad.id).nudged is True


def test_awards_bad_channel_posts_once_per_channel(bot_module, monkeypatch, caplog):
    posted = []

    async def name_of(uid):
        return "Yash"
    monkeypatch.setattr(bot_module, "name_of", name_of)
    monkeypatch.setattr(bot_module, "get_channel", fake_channels(posted, broken={11}))
    monkeypatch.setattr(bot_module.awards, "should_post",
                        lambda now, last: last != bot_module.awards.week_key(now))
    for channel_id in (11, 12):
        bot_module.store.set_channel(channel_id, True)
    current = bot_module.now()
    bot_module.store.add(1, "slides", None, 12, 30, "l", current)
    bot_module.store.add(2, "secret", None, 99, 31, "l", current)
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.run_scheduler_once())
        asyncio.run(bot_module.run_scheduler_once())
    assert [cid for cid, _ in posted] == [12]
    assert "Yash" in posted[0][1]
    assert "awards_failed channel=11" in caplog.text
    assert bot_module.store.last_awards_week == bot_module.awards.week_key(current)


def test_awards_message_only_counts_that_channel(bot_module, monkeypatch):
    async def name_of(uid):
        return {1: "Yash", 2: "Suraj"}[uid]
    monkeypatch.setattr(bot_module, "name_of", name_of)
    current = bot_module.now()
    bot_module.store.add(1, "slides", None, 12, 30, "l", current)
    bot_module.store.add(2, "secret", None, 99, 31, "l", current)
    text = asyncio.run(bot_module.awards_message(current, 12))
    assert "Yash" in text and "Suraj" not in text


def test_command_errors_do_not_log_what_was_typed(bot_module, caplog):
    error = commands.CommandNotFound('Command "secretword" is not found')
    with caplog.at_level(logging.DEBUG):
        asyncio.run(bot_module.on_command_error(None, error))
    assert "secretword" not in caplog.text
    assert "command_error type=CommandNotFound" in caplog.text


class FakeInteraction:
    def __init__(self, user_id, channel_id):
        self.user = NS(id=user_id)
        self.channel_id = channel_id
        self.calls = []

        async def defer(**kwargs):
            self.calls.append(("defer", None, kwargs))

        async def send_message(text, **kwargs):
            self.calls.append(("respond", text, kwargs))

        async def followup_send(text, **kwargs):
            self.calls.append(("followup", text, kwargs))

        self.response = NS(defer=defer, send_message=send_message)
        self.followup = NS(send=followup_send)


def test_board_defers_and_shows_only_my_overdue(bot_module, monkeypatch):
    async def name_of(uid):
        return {1: "Yash", 2: "Suraj"}[uid]
    monkeypatch.setattr(bot_module, "name_of", name_of)
    current = bot_module.now()
    store = bot_module.store
    store.add(1, "my late thing", current - timedelta(days=1), 10, 1, "l", current)
    store.add(2, "their late thing", current - timedelta(days=1), 10, 2, "l", current)
    store.add(2, "their open thing", None, 10, 3, "l", current)
    interaction = FakeInteraction(1, 10)
    asyncio.run(bot_module.receipts_board.callback(interaction))
    kinds = [c[0] for c in interaction.calls]
    assert kinds == ["defer", "followup", "followup"]
    board, overdue = interaction.calls[1], interaction.calls[2]
    assert "their open thing" in board[1] and "late" not in board[1]
    assert board[2] == {}
    assert overdue[2] == {"ephemeral": True}
    assert "my late thing" in overdue[1]
    assert "their late thing" not in overdue[1] and "Suraj" not in overdue[1]


def test_commands_are_guild_only(bot_module):
    assert bot_module.receipts_group.guild_only is True
    assert bot_module.done_command.guild_only is True
    assert bot_module.awards_command.guild_only is True


def _demo_ctx(sent):
    async def send(text):
        sent.append(text)
    return NS(guild=NS(owner_id=1), author=NS(id=1, roles=[]), send=send)


@pytest.mark.parametrize("hours", [float("inf"), float("nan"), -2, 0, 337, 1e12])
def test_tick_rejects_bad_hours(bot_module, hours):
    sent = []
    asyncio.run(bot_module.tick.callback(_demo_ctx(sent), hours))
    assert sent == [bot_module.voice.tick_bad_text()]
    assert bot_module.store.clock_offset_seconds == 0


def test_tick_good_hours(bot_module, monkeypatch):
    sent = []
    monkeypatch.setattr(bot_module, "dm", fake_dm([]))
    asyncio.run(bot_module.tick.callback(_demo_ctx(sent), 2))
    assert bot_module.store.clock_offset_seconds == 7200
    assert sent[0].startswith("moved the clock 2 hours ahead.")
    assert "%" not in sent[0]


def test_can_run_demo_allows_env_user_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("USE_LLM", "false")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("DEMO_USER_IDS", " 42, 77,abc,, ")
    import bot
    module = importlib.reload(bot)
    assert module.DEMO_USER_IDS == frozenset({42, 77})
    ctx = NS(guild=NS(owner_id=1), author=NS(id=77, roles=[]))
    assert module.can_run_demo(ctx) is True
    ctx = NS(guild=NS(owner_id=1), author=NS(id=78, roles=[]))
    assert module.can_run_demo(ctx) is False


def test_demo_user_ids_default_empty(bot_module):
    assert bot_module.DEMO_USER_IDS == frozenset()


def _denied_ctx(sent):
    async def send(text):
        sent.append(text)
    return NS(guild=NS(owner_id=1), author=NS(id=99, roles=[]), channel=NS(id=10), command=NS(name="tick"), send=send)


def test_tick_denied_replies_and_logs(bot_module, caplog):
    sent = []
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.tick.callback(_denied_ctx(sent), 2))
    assert sent == [bot_module.voice.demo_denied_text()]
    assert bot_module.store.clock_offset_seconds == 0
    assert "demo_denied command=tick user=99" in caplog.text


def test_demo_denied_replies_and_logs(bot_module, caplog):
    sent = []
    bot_module.store.set_channel(10, True)
    ctx = _denied_ctx(sent)
    ctx.command = NS(name="demo")
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.demo_command.callback(ctx))
    assert sent == [bot_module.voice.demo_denied_text()]
    assert "demo_denied command=demo user=99" in caplog.text


def test_demo_in_untracked_channel_is_silent_for_runner(bot_module, caplog):
    sent = []
    ctx = _denied_ctx(sent)
    ctx.author = NS(id=1, roles=[])
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.demo_command.callback(ctx))
    assert sent == []
    assert "demo_denied" not in caplog.text


def test_clock_label_is_portable(bot_module, tz):
    from datetime import datetime
    assert bot_module.clock_label(datetime(2026, 10, 22, 14, 5, tzinfo=tz)) == "thu oct 22 2:05pm"
    assert bot_module.clock_label(datetime(2026, 10, 22, 9, 0, tzinfo=tz)) == "thu oct 22 9am"


def test_forgetme_drops_name_cache(bot_module):
    bot_module._name_cache[42] = "Someone Real"
    interaction = FakeInteraction(42, 10)
    asyncio.run(bot_module.forgetme_command.callback(interaction))
    assert 42 not in bot_module._name_cache
    assert interaction.calls[0][2] == {"ephemeral": True}


def test_help_request_skipped_when_channel_off(bot_module, monkeypatch, caplog):
    posted = []
    monkeypatch.setattr(bot_module, "get_channel", fake_channels(posted))
    current = bot_module.now()
    r = bot_module.store.add(1, "slides", None, 10, 20, "l", current)
    bot_module.store.link_message(700, "nudge", r.id)
    payload = NS(message_id=700, user_id=1)
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.handle_dm_reaction(payload, bot_module.HELP_EMOJI))
    assert posted == []
    assert f"help_channel_off receipt={r.id}" in caplog.text
    assert bot_module.store.lookup_message(700) is None


def test_help_request_posts_when_channel_on(bot_module, monkeypatch):
    posted = []

    async def name_of(uid):
        return "Yash"
    monkeypatch.setattr(bot_module, "name_of", name_of)

    async def add_reaction(emoji):
        return None

    async def get_channel(channel_id):
        async def send(text):
            posted.append(text)
            return NS(id=801, add_reaction=add_reaction)
        return NS(send=send)
    monkeypatch.setattr(bot_module, "get_channel", get_channel)
    bot_module.store.set_channel(10, True)
    current = bot_module.now()
    r = bot_module.store.add(1, "slides", None, 10, 20, "l", current)
    bot_module.store.link_message(700, "nudge", r.id)
    asyncio.run(bot_module.handle_dm_reaction(NS(message_id=700, user_id=1), bot_module.HELP_EMOJI))
    assert posted == ["Yash could use a hand with slides. anyone?"]
    assert bot_module.store.lookup_message(801) == ("help", r.id)
