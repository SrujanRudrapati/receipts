# smoke checks for the discord wiring. no network, just imports and settings.
import importlib
import logging

import discord
import pytest


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
    assert bot_module.bot.allowed_mentions == discord.AllowedMentions.none()


def test_who_pattern(bot_module):
    match = bot_module.WHO_PATTERN.match("who said they'd book the room?")
    assert match and match.group(1) == "book the room"
    assert bot_module.WHO_PATTERN.match("who's doing the slides")
    assert bot_module.WHO_PATTERN.match("I'll book the room") is None


def test_token_is_never_logged(bot_module, caplog):
    with caplog.at_level(logging.DEBUG):
        bot_module.log.info("ready guilds=%s", 1)
    assert "test-token" not in caplog.text
