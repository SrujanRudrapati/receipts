# Receipts

A Discord bot that catches the promises people make in a group chat and keeps the receipts.

## Why groups need it

Every project group chat has the same problem. Someone says "ok I'll do the intro slides by thursday", the chat moves on, and three days later nobody remembers who said what. Receipts sits in the channel, notices those lines, and keeps a small board of who promised what. It nudges you privately before something is due, lets you ask for help with one tap, and hands out playful awards on Friday.

Built for the Cubbie Hackathon, Track 3: an AI that joins a group chat and makes it more useful, playful, or surprising for campus life.

## Useful, playful, surprising

| | What it does | Where you see it in the demo |
|---|---|---|
| Surprising | Nobody types a command. You just talk, and a 🧾 reaction shows up on your message. "who's in for the potluck?" turns into a 接龙 sign-up list on its own. | Steps 2 and 3. |
| Useful | `/receipts board`, private nudges before things are due, the 🆘 → 🙋 handoff, "who said they'd ...?" answers with a link to the original message, and a ding to Cubbie when you go quiet right before something is due. | Steps 1 to 6. |
| Playful | `/awards` every Friday at 5pm. Most reliable, biggest comeback, most promises, the closer. Never mean, no shaming, no overdue list. | Step 7. |

## How it works

- `/receipts on` in a channel turns tracking on. Nothing is read anywhere else. It also looks back through the last 200 messages for promises from this week and asks once: "found N promises from this week:", a line per promise with who said it and when it's due (at most 5 lines in all), then "keep them?" with ✅ and ❌. Nothing is stored until ✅. Bots and anyone who ran `/forgetme` are skipped, and no message is proposed twice.
- Each message goes through a cheap keyword prefilter first ("I'll", "I can", "on it", ...). Most messages stop there and cost nothing.
- Candidate messages go to `claude-haiku-5-5` with a strict JSON prompt, at most 80 output tokens and 500 characters of input. If the model is off (`USE_LLM=false`), errors, or returns anything that is not the expected JSON, a rule based extractor takes over. The bot works fully without the model.
- The bot reacts 🧾 to the message. React ❌ or reply "not a promise" to undo. React ✅ or run `/done <what>` when it is finished.
- About 24 hours before something is due you get a DM: "intro slides due tomorrow. still on it?" with ✅ and 🆘. Tap 🆘 and the bot asks the channel for a hand. The first 🙋 takes it over and both people get a confirmation.
- Ask "who said they'd book the room?" in the channel and you get the name and a link to the message.
- "who's in for the potluck friday? need 4 people" starts a 接龙 (jiēlóng), WeChat's group sign-up list. The bot posts one list message and edits it in place: title, numbered entries, empty slots if a number was given, and a 🙋 to join. "me", "+1", "I'm in", "I'll bring chips", "I can drive" as a reply to the starter or within 30 minutes add you. Entries with an item or a time become normal receipts, 🧾 on your reply, linked to the list. `/receipts list close` locks it. Starters are matched by rules first; Haiku only sees the ones the rules missed. Also catches "what's everyone bringing", "need 3 drivers" and "sign up for ...".
- `/receipts ding on` is a stronger reminder, off by default and only for linked users. If something is due within 2 hours and you have not tapped ✅ on a nudge, you get one last-call DM. If 30 minutes pass with no answer, Cubbie hears "ding id=<id> what=<summary> due=<time>" on your topic, texts you, and if you opted into calls, phones you with a 30-minute block to offer. The channel only sees "🔔 reminded", never why. `/receipts ding off` turns it back off.
- `/receipts link` connects Cubbie. The bot DMs you a private token, and from then on each of your receipts is relayed to Cubbie through ntfy.sh. Cubbie can send an sos back, and the bot runs the same 🆘 flow in the channel. `/receipts unlink` stops it. See "The Cubbie link" below.

## What we store and what we don't

| We store | We do not store |
|---|---|
| Your Discord user id | Your username or display name |
| A short summary of the promise, 140 characters max | The full message text |
| Due date, if there was one | Any other message in the channel |
| Open or done | Anything from channels without `/receipts on` |
| Channel id and a link to the original message | Reactions or who reacted, beyond the one action they trigger |
| Ids of the bot's own nudge and help messages, so reactions on them can be routed | Logs with message content. Logs only have ids and event names |
| When a promise was made, when it was marked done, and when someone claimed it | |
| Whether you already got a nudge for it, so you only get one | |
| If someone took it over with 🙋: the old owner's user id and the claimer's user id | |
| The ids of channels where `/receipts on` was run | |
| The demo clock offset from `!tick`, in seconds | |
| Your private Cubbie topic, if you ran `/receipts link`. It works like a password and is never logged | Anything Cubbie says on the topic other than a valid sos |
| Sign-up lists: the title, the slot count, who joined (user ids) and the few words they said they'd bring | The starter message or the replies |
| Whether you turned ding on, and for each receipt whether the last call went out, whether you answered, and whether Cubbie was told | The channel never gets the summary, only "🔔 reminded" |
| Your user id in a skip list after `/forgetme`, so a later backfill never re-reads your old messages | |
| One message id per channel: the newest one the last backfill looked at, so nothing is proposed twice | The messages themselves. A backfill proposal lives in memory until ✅ or ❌ |

State lives in one JSON file (`state.json`) written atomically on a background thread, so a slow disk never delays a reply. `/forgetme` deletes everything the bot has on you. `/receipts off` stops tracking a channel. Nudges go by DM. Overdue items are never posted in the channel. When you run `/receipts board` you see only your own overdue items, in a reply only you can see.

## Setup

You need Python 3.12.

```
git clone https://github.com/SrujanRudrapati/receipts
cd receipts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Then fill in `.env`:

1. Go to discord.com/developers, make a New Application called "Receipts", open Bot, Reset Token, paste it as `DISCORD_TOKEN`. Turn on Message Content Intent.
2. OAuth2 URL generator: scopes `bot` and `applications.commands`. Permissions: Send Messages, Read Message History, Add Reactions, Embed Links. Open the URL and invite it to your server.
3. Right click your server, Copy Server ID, paste it as `GUILD_ID`.
4. Add `ANTHROPIC_API_KEY`, or set `USE_LLM=false` to run on rules only.
5. Leave `NTFY_URL` alone unless you self-host ntfy. It defaults to `https://ntfy.sh`.

Run it:

```
python3 bot.py
```

In Discord: `/receipts on` in a channel, then `!demo` to seed a fake group chat. `!demo` and `!tick <hours>` only work for the server owner, anyone with a role called `receipts-demo`, or user ids listed in `DEMO_USER_IDS` (comma-separated). Anyone else gets a short "only demo runners can do this." reply.

Tests:

```
USE_LLM=false pytest
```

## 90-second demo script

1. Backfill. The group has been chatting for a week. `/receipts on`. The bot lists them, "found 3 promises from this week:" with a line per person and promise, then "keep them?" Tap ✅. 🧾 pops on the three old messages and `/receipts board` shows them.
2. Live. Teammates chat naturally: "ok I'll do the intro slides by tomorrow", "I can book a hayden room for sunday". 🧾 pops on each.
3. 接龙. Bhavana: "who's in for the potluck friday? need 4 people". The bot posts a list with four open slots and a 🙋. Yash: "me". Suraj: "I'll bring chips". Someone taps 🙋. The list fills in as they go, and Suraj's chips get a 🧾 of their own. `/receipts list close` locks it.
4. `!tick 24`. Yash gets a DM, "intro slides due tomorrow. still on it?", and taps 🆘.
5. The channel asks for help. Suraj taps 🙋 and it's reassigned, with both confirmed.
6. Ding. Yash has `/receipts link` and `/receipts ding on`. `!tick 10` walks the clock up to the deadline: Yash gets "last call: intro slides due today at 11:59pm. still on it?", says nothing, and 30 minutes later the channel sees "🔔 reminded" and Yash's phone rings. Cubbie: "receipts says intro slides is due tonight and hasn't heard back. still on it? want me to block 8 to 8:30 for it?"
7. `/awards`.

`!demo` seeds steps 2 and 3. For step 1, run `/receipts on` in a channel that already has a week of chat.

## Commands

| Command | What it does |
|---|---|
| `/receipts on` / `/receipts off` | start or stop tracking this channel |
| `/receipts board` | who promised what, grouped by person, plus the open sign-up lists |
| `/receipts list close [what]` | lock the newest open 接龙 list, or the one whose title has those words |
| `/receipts ding on` / `/receipts ding off` | let cubbie hear when you go quiet right before something is due. off by default, linked users only |
| `/done <what>` | mark one of your promises done |
| `/awards` | this week's awards |
| `/forgetme` | delete everything the bot has on you |
| `/receipts link` | connect Cubbie. you get a private token by DM |
| `/receipts unlink` | disconnect Cubbie |
| `/help` | short help |
| `!demo` | seed a fake CSE 511 group chat (owner, demo role, or `DEMO_USER_IDS`) |
| `!tick <hours>` | move the demo clock forward in half-hour steps, running the scheduler after each (owner, demo role, or `DEMO_USER_IDS`) |

## Layout

```
bot.py      discord events, commands, scheduler
detect.py   keyword prefilter, model extraction, rule fallback
lists.py    接龙 sign-up lists: starters by rule then haiku, join phrases
backfill.py which old messages are worth proposing on /receipts on
dates.py    "by thursday", "tomorrow", "fri 5pm" -> datetime
store.py    receipts, sign-up lists, channel opt in, forgetme, atomic save
nudges.py   what is due soon, the ding timing, demo clock
awards.py   weekly awards from the store
voice.py    every line the bot says
cubbie.py   the lines we send to cubbie, the sos lines we accept, what counts as fresh
relay.py    ntfy over aiohttp, post and poll
demo.py     the !demo seed
receipts-link/  the Cubbie Skill: SKILL.md, scripts/pull.py, scripts/sos.py
tests/      pytest, runs in CI with USE_LLM=false
```

## The Cubbie link

Receipts and Cubbie talk through [ntfy.sh](https://ntfy.sh), a plain pub/sub relay. There is no account and no shared server. Each linked user gets a random private topic, `receipts-` plus 16 url-safe characters. Whoever knows the topic can read and write it, so it works like a password. It only ever goes out in a DM, and the logs never contain it.

`/receipts link` makes the topic, DMs it to you with "save this in Cubbie as RECEIPTS_LINK_TOKEN. it works like a password." and saves it. Running it again makes a new topic and the old one stops working. `/receipts unlink` and `/forgetme` both delete it.

What the bot posts to your topic, one line each:

```
receipt id=ab12cd34 what=intro slides due=2026-10-29T17:00:00-07:00 channel=cse511-group
receipt id=ab12cd34 event=done
receipt id=ab12cd34 event=reassigned
receipt id=ab12cd34 event=removed
ding id=ab12cd34 what=intro slides due=2026-10-29T17:00:00-07:00
```

The first line goes out when a promise is caught. The `ding` line only goes out if you ran `/receipts ding on`, something is due within 2 hours, and you did not answer the last-call DM within 30 minutes. It carries a summary and a time, never a reason. `due` is ISO 8601 with offset, or `none`. When someone takes a task over with 🙋, the old owner's topic gets `event=reassigned` and the new owner's topic gets a fresh `receipt` line, if they are linked.

What the bot reads back. It polls every linked topic every 5 seconds with `since=<last id>` and accepts exactly one shape:

```
sos id=ab12cd34 source=cubbie
```

It has to be your own open receipt, the line has to be under 10 minutes old, and each ntfy message counts once. Anything else on the topic is ignored, including the bot's own lines. A valid sos runs the same flow as tapping 🆘 on a nudge: the channel gets "Yash could use a hand with intro slides. anyone?" and the first 🙋 takes it. A second sos for a receipt that already has an open help post does nothing.

If ntfy is down, receipts keep working. A failed post or poll is logged by error type only and the bot moves on.

The Cubbie side lives in this repo too, as a Cubbie Skill in `receipts-link/`. A student installs it by texting Cubbie the folder's GitHub link, saves the token from `/receipts link`, and then Cubbie can answer "what did I promise", offer a calendar block before something is due, send the sos when the student says "I can't do the slides", and, when a ding arrives, text the student and place a phone check-in with a 30-minute block to offer. Its scripts use only the Python standard library. See `receipts-link/SKILL.md`.

## What's next

- Let Cubbie mark a receipt done from the calendar event, so finishing the block closes the receipt.
- Let people leave a 接龙 list by removing their 🙋.
- Smarter "on it" handling: when someone replies "on it" to a request, use the request as the summary.
- Per-channel awards time instead of one global Friday 5pm.
