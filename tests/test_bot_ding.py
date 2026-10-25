# checks for the ding wiring in bot.py: opt-in, the last-call dm, the cubbie ding, and what the channel sees.
import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from tests.test_bot import FakeInteraction, FakeRelay, bot_module, fake_channels, fake_dm  # noqa: F401


@pytest.fixture
def wired(bot_module, monkeypatch):
    relay = FakeRelay()
    monkeypatch.setattr(bot_module, "relay_client", relay)
    sent, posted = [], []
    monkeypatch.setattr(bot_module, "dm", fake_dm(sent))
    monkeypatch.setattr(bot_module, "get_channel", fake_channels(posted))
    bot_module.store.set_channel(10, True)
    bot_module.store.link_cubbie(1, "receipts-topic-of-user-1")
    bot_module.store.set_ding(1, True)
    return NS(relay=relay, sent=sent, posted=posted)


def add(bot_module, hours, user=1, what="intro slides", msg=20):
    current = bot_module.now()
    return bot_module.store.add(user, what, current + timedelta(hours=hours), 10, msg, "l", current)


def run(bot_module):
    asyncio.run(bot_module.run_scheduler_once())


def advance(bot_module, hours):
    bot_module.nudges.tick(bot_module.store, hours)
    run(bot_module)


# ---- opt in


def test_ding_on_needs_a_link(bot_module):
    interaction = FakeInteraction(2, 10)
    asyncio.run(bot_module.receipts_ding.callback(interaction, "on"))
    assert interaction.calls == [("respond", bot_module.voice.ding_needs_link_text(), {"ephemeral": True})]
    assert bot_module.store.ding_on(2) is False


def test_ding_on_and_off(bot_module, caplog):
    bot_module.store.link_cubbie(2, "receipts-topic-of-user-2")
    on, off = FakeInteraction(2, 10), FakeInteraction(2, 10)
    with caplog.at_level(logging.INFO):
        asyncio.run(bot_module.receipts_ding.callback(on, "on"))
    assert on.calls == [("respond", bot_module.voice.ding_on_text(), {"ephemeral": True})]
    assert bot_module.store.ding_on(2) is True
    assert "ding_on user=2" in caplog.text
    asyncio.run(bot_module.receipts_ding.callback(off, "off"))
    assert off.calls == [("respond", bot_module.voice.ding_off_text(), {"ephemeral": True})]
    assert bot_module.store.ding_on(2) is False


# ---- the last call and the ding


def test_last_call_dm_goes_out_within_two_hours(bot_module, wired):
    r = add(bot_module, 1.5)
    run(bot_module)
    texts = [text for uid, text in wired.sent if uid == 1]
    assert any(text.startswith("last call: intro slides due") for text in texts)
    assert bot_module.store.get(r.id).ding_sent_at is not None
    assert bot_module.store.lookup_message(5000 + len(wired.sent)) == ("nudge", r.id)
    assert wired.relay.posts == [] and wired.posted == []


def test_quiet_for_thirty_minutes_dings_cubbie_and_the_channel_sees_only_the_bell(bot_module, wired, caplog):
    r = add(bot_module, 1.5)
    run(bot_module)
    with caplog.at_level(logging.INFO):
        advance(bot_module, 0.5)
    assert wired.relay.posts == [("receipts-topic-of-user-1", bot_module.cubbie.ding_line(bot_module.store.get(r.id)))]
    assert wired.posted == [(10, "🔔 reminded")]
    assert f"ding_sent receipt={r.id}" in caplog.text
    assert "intro slides" not in caplog.text
    # once only
    advance(bot_module, 0.5)
    assert len(wired.relay.posts) == 1 and len(wired.posted) == 1


def test_answering_the_last_call_stops_the_ding(bot_module, wired):
    r = add(bot_module, 1.5)
    run(bot_module)
    dm_id = 5000 + len(wired.sent)
    asyncio.run(bot_module.handle_dm_reaction(NS(message_id=dm_id, user_id=1), bot_module.DONE_EMOJI))
    assert bot_module.store.get(r.id).acked is True
    advance(bot_module, 0.5)
    assert wired.relay.posts == [] and wired.posted == []


def test_answering_the_day_before_nudge_counts_too(bot_module, wired):
    r = add(bot_module, 20)
    run(bot_module)
    nudge_id = 5000 + len(wired.sent)
    assert bot_module.store.lookup_message(nudge_id) == ("nudge", r.id)
    asyncio.run(bot_module.handle_dm_reaction(NS(message_id=nudge_id, user_id=1), bot_module.DONE_EMOJI))
    advance(bot_module, 19)
    assert not any(text.startswith("last call") for _, text in wired.sent)
    assert wired.relay.posts == [] and wired.posted == []


def test_ding_off_users_get_nothing_extra(bot_module, wired):
    bot_module.store.set_ding(1, False)
    add(bot_module, 1.5)
    run(bot_module)
    advance(bot_module, 0.5)
    assert not any(text.startswith("last call") for _, text in wired.sent)
    assert wired.relay.posts == [] and wired.posted == []


def test_unlinked_users_get_nothing_extra(bot_module, wired):
    bot_module.store.unlink_cubbie(1)
    add(bot_module, 1.5)
    run(bot_module)
    advance(bot_module, 0.5)
    assert not any(text.startswith("last call") for _, text in wired.sent)
    assert wired.posted == []


def test_done_before_the_ding_stops_it(bot_module, wired):
    r = add(bot_module, 1.5)
    run(bot_module)
    bot_module.store.mark_done(r.id, bot_module.now())
    advance(bot_module, 0.5)
    assert wired.relay.posts == [] and wired.posted == []


def test_channel_off_still_dings_cubbie_but_posts_nothing(bot_module, wired):
    r = add(bot_module, 1.5)
    run(bot_module)
    bot_module.store.set_channel(10, False)
    advance(bot_module, 0.5)
    assert len(wired.relay.posts) == 1 and wired.posted == []


def test_cubbie_failure_logs_type_only_and_channel_still_hears(bot_module, wired, caplog):
    r = add(bot_module, 1.5)
    run(bot_module)
    wired.relay.broken = True
    with caplog.at_level(logging.INFO):
        advance(bot_module, 0.5)
    assert f"cubbie_post_failed receipt={r.id} error=RuntimeError" in caplog.text
    assert "topic-of-user-1" not in caplog.text
    assert wired.posted == [(10, "🔔 reminded")]
    assert bot_module.store.get(r.id).dinged is True


# ---- one !tick runs the whole thing


def _ctx(sent):
    async def send(text):
        sent.append(text)
    return NS(guild=NS(owner_id=1), author=NS(id=1, roles=[]), send=send)


def test_one_tick_walks_through_nudge_last_call_and_ding(bot_module, wired):
    r = add(bot_module, 30)
    replies = []
    asyncio.run(bot_module.tick.callback(_ctx(replies), 29))
    texts = [text for _, text in wired.sent]
    assert any(text.startswith("intro slides due") for text in texts)
    assert any(text.startswith("last call: intro slides due") for text in texts)
    assert wired.relay.posts == [("receipts-topic-of-user-1", bot_module.cubbie.ding_line(bot_module.store.get(r.id)))]
    assert wired.posted == [(10, "🔔 reminded")]
    assert bot_module.store.clock_offset_seconds == 29 * 3600
    assert replies[0].startswith("moved the clock 29 hours ahead.")


def test_tick_reply_and_offset_are_unchanged_for_small_steps(bot_module, wired):
    replies = []
    asyncio.run(bot_module.tick.callback(_ctx(replies), 0.25))
    assert bot_module.store.clock_offset_seconds == 900


def test_no_channel_post_ever_carries_the_summary(bot_module, wired):
    add(bot_module, 1.5, what="a very private summary")
    run(bot_module)
    advance(bot_module, 0.5)
    for _, text in wired.posted:
        assert "private" not in text and text == "🔔 reminded"
