# discord wiring for receipts. the real logic lives in the small modules.
# this file only moves data between discord and them.
import asyncio
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import awards
import demo
import detect
import nudges
import voice
from store import Store

load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID = os.environ.get("GUILD_ID", "")
STATE_PATH = os.environ.get("STATE_PATH", "state.json")
TZ = ZoneInfo(os.environ.get("TZ_NAME", "America/Phoenix"))
DEMO_ROLE = os.environ.get("DEMO_ROLE", "receipts-demo")

SCHEDULER_SECONDS = 30
RECEIPT_EMOJI = "🧾"
DONE_EMOJI = "✅"
UNDO_EMOJI = "❌"
HELP_EMOJI = "🆘"
CLAIM_EMOJI = "🙋"
ACK_EMOJI = "👍"

# logs hold ids and event names only. never message text.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receipts")

WHO_PATTERN = re.compile(
    r"^\s*(?:who said they'?d|who said they would|who'?s doing|who is doing|who'?s got|who has)\s+(.+?)\s*\??\s*$",
    re.IGNORECASE,
)
UNDO_PHRASE = "not a promise"

intents = discord.Intents.none()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True
intents.guild_reactions = True
intents.dm_messages = True
intents.dm_reactions = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none(),
    help_command=None,
)
store = Store(STATE_PATH)
_name_cache: dict[int, str] = {}


def now() -> datetime:
    """current time in TZ, shifted by the demo clock."""
    return nudges.demo_now(store, datetime.now(TZ))


async def name_of(user_id: int) -> str:
    """display name for a user id. demo personas first, then discord. never stored on disk."""
    if user_id in demo.DEMO_PEOPLE:
        return demo.DEMO_PEOPLE[user_id]
    if user_id in _name_cache:
        return _name_cache[user_id]
    try:
        user = await bot.fetch_user(user_id)
        name = user.global_name or user.name
    except discord.HTTPException:
        name = voice.FALLBACK_NAME
    _name_cache[user_id] = name
    return name


async def names_for(user_ids) -> dict[int, str]:
    return {uid: await name_of(uid) for uid in set(user_ids)}


async def get_channel(channel_id: int):
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    return channel


async def dm(user_id: int, text: str, reactions=()) -> discord.Message | None:
    """send a private message. returns the message, or None if the DM failed."""
    try:
        user = await bot.fetch_user(user_id)
        message = await user.send(text)
        for emoji in reactions:
            await message.add_reaction(emoji)
        return message
    except discord.HTTPException:
        log.info("dm_failed user=%s", user_id)
        return None


def due_label(receipt) -> str:
    if receipt.due is None:
        return "whenever"
    return nudges.when_label(receipt.due, now())


# ---- catching promises ----

async def handle_candidate(message: discord.Message, text: str, author_id: int) -> None:
    """run the detector on one message and save a receipt if it is a promise."""
    if not detect.prefilter(text):
        return
    promise = await asyncio.to_thread(detect.extract, text, author_id, now())
    if promise is None:
        return
    store.add(author_id, promise["what"], promise["due"], message.channel.id,
              message.id, message.jump_url, now())
    await message.add_reaction(RECEIPT_EMOJI)
    log.info("promise_caught channel=%s message=%s user=%s", message.channel.id, message.id, author_id)


async def handle_undo_reply(message: discord.Message) -> bool:
    """'not a promise' as a reply to a receipted message removes it. returns True if handled."""
    if UNDO_PHRASE not in message.content.lower() or message.reference is None:
        return False
    receipt = store.find_by_message(message.reference.message_id)
    if receipt is None or receipt.user_id != message.author.id:
        return False
    store.remove(receipt.id)
    await clear_receipt_reaction(message.channel, receipt.message_id)
    await message.reply(voice.undo_text())
    log.info("receipt_undone receipt=%s", receipt.id)
    return True


async def handle_who(message: discord.Message) -> bool:
    """answer 'who said they'd ...' from the store. returns True if handled."""
    match = WHO_PATTERN.match(message.content)
    if not match:
        return False
    hits = store.ask_who(message.channel.id, match.group(1))
    if not hits:
        await message.reply(voice.who_none())
        return True
    hit = hits[0]
    await message.reply(voice.who_answer(await name_of(hit.user_id), hit.what, hit.message_link))
    return True


async def clear_receipt_reaction(channel, message_id: int) -> None:
    try:
        original = await channel.fetch_message(message_id)
        await original.remove_reaction(RECEIPT_EMOJI, bot.user)
    except discord.HTTPException:
        log.info("reaction_clear_failed message=%s", message_id)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)
    if message.guild is None or not store.is_tracked(message.channel.id):
        return
    if message.content.startswith(bot.command_prefix):
        return
    if await handle_undo_reply(message):
        return
    if await handle_who(message):
        return
    await handle_candidate(message, message.content, message.author.id)


# ---- reactions ----

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if bot.user is None or payload.user_id == bot.user.id:
        return
    emoji = str(payload.emoji)
    if payload.guild_id is None:
        await handle_dm_reaction(payload, emoji)
        return
    link = store.lookup_message(payload.message_id)
    if link is not None and link[0] == "help" and emoji == CLAIM_EMOJI:
        await handle_claim(payload, link[1])
        return
    receipt = store.find_by_message(payload.message_id)
    if receipt is None or receipt.user_id != payload.user_id:
        return
    channel = await get_channel(payload.channel_id)
    if emoji == UNDO_EMOJI:
        store.remove(receipt.id)
        await clear_receipt_reaction(channel, receipt.message_id)
        log.info("receipt_undone receipt=%s", receipt.id)
    elif emoji == DONE_EMOJI and receipt.status == "open":
        store.mark_done(receipt.id, now())
        original = await channel.fetch_message(receipt.message_id)
        await original.add_reaction(ACK_EMOJI)
        log.info("receipt_done receipt=%s", receipt.id)


async def handle_dm_reaction(payload, emoji: str) -> None:
    """✅ or 🆘 on a nudge DM."""
    link = store.lookup_message(payload.message_id)
    if link is None or link[0] != "nudge":
        return
    receipt = store.get(link[1])
    if receipt is None or receipt.user_id != payload.user_id:
        return
    if emoji == DONE_EMOJI:
        store.unlink_message(payload.message_id)
        await dm(payload.user_id, voice.got_it())
        log.info("nudge_ack receipt=%s", receipt.id)
    elif emoji == HELP_EMOJI:
        store.unlink_message(payload.message_id)
        # the channel was turned off, so we don't post there anymore.
        if not store.is_tracked(receipt.channel_id):
            log.info("help_channel_off receipt=%s", receipt.id)
            return
        channel = await get_channel(receipt.channel_id)
        post = await channel.send(voice.help_wanted(await name_of(receipt.user_id), receipt.what))
        await post.add_reaction(CLAIM_EMOJI)
        store.link_message(post.id, "help", receipt.id)
        log.info("help_requested receipt=%s", receipt.id)


async def handle_claim(payload, receipt_id: str) -> None:
    """first 🙋 on a help post takes the task."""
    receipt = store.get(receipt_id)
    if receipt is None or receipt.status != "open" or receipt.user_id == payload.user_id:
        return
    old_owner = receipt.user_id
    store.reassign(receipt.id, payload.user_id, now())
    store.unlink_message(payload.message_id)
    claimer = await name_of(payload.user_id)
    channel = await get_channel(payload.channel_id)
    await channel.send(voice.claimed_channel(claimer, receipt.what))
    await dm(old_owner, voice.claimed_dm_old(claimer, receipt.what))
    await dm(payload.user_id, voice.claimed_dm_new(receipt.what, due_label(receipt)))
    log.info("receipt_claimed receipt=%s from=%s to=%s", receipt.id, old_owner, payload.user_id)


# ---- scheduler ----

async def send_nudges(current: datetime) -> None:
    for receipt in nudges.due_soon(store, current):
        # mark it first, so a failure below can't make us nudge twice.
        store.mark_nudged(receipt.id)
        try:
            text = voice.nudge_dm(receipt.what, nudges.when_label(receipt.due, current))
            message = await dm(receipt.user_id, text, reactions=(DONE_EMOJI, HELP_EMOJI))
            if message is not None:
                store.link_message(message.id, "nudge", receipt.id)
            log.info("nudge_sent receipt=%s", receipt.id)
        except Exception as error:
            # one bad receipt should not stop the rest. only the error type is logged.
            log.info("nudge_failed receipt=%s error=%s", receipt.id, type(error).__name__)


async def post_awards(current: datetime) -> None:
    # save the week before sending, so one broken channel can't make us post again every 30s.
    store.last_awards_week = awards.week_key(current)
    for channel_id in store.tracked_channels():
        try:
            text = await awards_message(current, channel_id)
            channel = await get_channel(channel_id)
            await channel.send(text)
        except discord.HTTPException:
            log.info("awards_failed channel=%s", channel_id)
    log.info("awards_posted")


async def run_scheduler_once() -> None:
    """send nudges that are due and post awards on friday at 5."""
    current = now()
    await send_nudges(current)
    if awards.should_post(current, store.last_awards_week):
        await post_awards(current)


async def awards_message(current: datetime, channel_id: int | None = None) -> str:
    start, end = awards.week_bounds(current)
    result = awards.compute(store, start, end, channel_id)
    user_ids = [uid for award in result.values() if award for uid in award["user_ids"]]
    return voice.awards_text(result, await names_for(user_ids))


@tasks.loop(seconds=SCHEDULER_SECONDS)
async def scheduler():
    try:
        await run_scheduler_once()
    except Exception:
        log.exception("scheduler_error")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # the default handler logs what the user typed after "!". we only log the error type.
    log.info("command_error type=%s", type(error).__name__)


@bot.event
async def on_ready():
    if not scheduler.is_running():
        scheduler.start()
    log.info("ready guilds=%s", len(bot.guilds))


# ---- prefix commands (demo only) ----

def can_run_demo(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    if ctx.author.id == ctx.guild.owner_id:
        return True
    roles = getattr(ctx.author, "roles", [])
    return any(role.name == DEMO_ROLE for role in roles)


def clock_label(when: datetime) -> str:
    # like "thu oct 22 2:30pm". built by hand because %-I does not work on windows.
    return when.strftime("%a %b %d").lower() + " " + nudges.clock_text(when)


@bot.command(name="tick")
async def tick(ctx: commands.Context, hours: float):
    if not can_run_demo(ctx):
        return
    if not nudges.valid_tick_hours(hours):
        await ctx.send(voice.tick_bad_text())
        return
    nudges.tick(store, hours)
    await run_scheduler_once()
    await ctx.send(voice.tick_text(hours, clock_label(now())))
    log.info("tick hours=%s", hours)


@bot.command(name="demo")
async def demo_command(ctx: commands.Context):
    if not can_run_demo(ctx) or not store.is_tracked(ctx.channel.id):
        return
    await demo.run(ctx.channel, ctx.author, handle_candidate)
    log.info("demo_seeded channel=%s", ctx.channel.id)


# ---- slash commands ----

# anyone in the server can turn it on or off (the spec says "someone ran /receipts on").
# guild_only just keeps these out of DMs.
receipts_group = app_commands.Group(
    name="receipts", description="track promises in this channel", guild_only=True,
)


@receipts_group.command(name="on", description="start catching promises here")
async def receipts_on(interaction: discord.Interaction):
    store.set_channel(interaction.channel_id, True)
    await interaction.response.send_message(voice.on_text())
    log.info("channel_on channel=%s", interaction.channel_id)


@receipts_group.command(name="off", description="stop catching promises here")
async def receipts_off(interaction: discord.Interaction):
    store.set_channel(interaction.channel_id, False)
    await interaction.response.send_message(voice.off_text())
    log.info("channel_off channel=%s", interaction.channel_id)


@receipts_group.command(name="board", description="who promised what")
async def receipts_board(interaction: discord.Interaction):
    # defer first. looking up names can take longer than discord's 3 second window.
    await interaction.response.defer()
    groups = store.board(interaction.channel_id, now())
    names = await names_for(groups.keys())
    await interaction.followup.send(voice.board_text(groups, names, include_overdue=False))
    # overdue only goes to the person who asked, and only their own items.
    mine = {uid: buckets for uid, buckets in groups.items() if uid == interaction.user.id}
    await interaction.followup.send(voice.overdue_text(mine, names), ephemeral=True)


@bot.tree.command(name="done", description="mark one of your promises done")
@app_commands.guild_only()
@app_commands.describe(what="a few words from the promise")
async def done_command(interaction: discord.Interaction, what: str):
    receipt = store.find_open(interaction.user.id, interaction.channel_id, what)
    if receipt is None:
        await interaction.response.send_message(voice.not_found_text(), ephemeral=True)
        return
    store.mark_done(receipt.id, now())
    await interaction.response.send_message(voice.done_text(receipt.what))
    log.info("receipt_done receipt=%s", receipt.id)


@bot.tree.command(name="awards", description="this week's receipts awards")
@app_commands.guild_only()
async def awards_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await interaction.followup.send(await awards_message(now(), interaction.channel_id))


@bot.tree.command(name="forgetme", description="delete everything receipts has on you")
async def forgetme_command(interaction: discord.Interaction):
    count = store.forget(interaction.user.id)
    _name_cache.pop(interaction.user.id, None)
    await interaction.response.send_message(voice.forgot_text(count), ephemeral=True)
    log.info("forget user=%s count=%s", interaction.user.id, count)


@bot.tree.command(name="help", description="how receipts works")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(voice.help_text(), ephemeral=True)


async def sync_commands() -> None:
    bot.tree.add_command(receipts_group)
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


bot.setup_hook = sync_commands


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. copy .env.example to .env and fill it in.")
    bot.run(TOKEN, log_handler=None)
