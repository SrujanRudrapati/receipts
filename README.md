# Receipts

A Discord bot that catches the promises people make in a group chat and keeps the receipts.

## Why groups need it

Every project group chat has the same problem. Someone says "ok I'll do the intro slides by thursday", the chat moves on, and three days later nobody remembers who said what. Receipts sits in the channel, notices those lines, and keeps a small board of who promised what. It nudges you privately before something is due, lets you ask for help with one tap, and hands out playful awards on Friday.

Built for the Cubbie Hackathon, Track 3: an AI that joins a group chat and makes it more useful, playful, or surprising for campus life.

## Useful, playful, surprising

| | What it does | Where you see it in the demo |
|---|---|---|
| Surprising | Nobody types a command. You just talk, and a 🧾 reaction shows up on your message. | Step 2, the 🧾 pops on three normal chat messages. |
| Useful | `/receipts board`, private nudges before things are due, the 🆘 → 🙋 handoff, and "who said they'd ...?" answers with a link to the original message. | Steps 2 to 5. |
| Playful | `/awards` every Friday at 5pm. Most reliable, biggest comeback, most promises, the closer. Never mean, no shaming, no overdue list. | Step 6. |

## How it works

- `/receipts on` in a channel turns tracking on. Nothing is read anywhere else.
- Each message goes through a cheap keyword prefilter first ("I'll", "I can", "on it", ...). Most messages stop there and cost nothing.
- Candidate messages go to `claude-haiku-5-5` with a strict JSON prompt, at most 80 output tokens and 500 characters of input. If the model is off (`USE_LLM=false`), errors, or returns anything that is not the expected JSON, a rule based extractor takes over. The bot works fully without the model.
- The bot reacts 🧾 to the message. React ❌ or reply "not a promise" to undo. React ✅ or run `/done <what>` when it is finished.
- About 24 hours before something is due you get a DM: "intro slides due tomorrow. still on it?" with ✅ and 🆘. Tap 🆘 and the bot asks the channel for a hand. The first 🙋 takes it over and both people get a confirmation.
- Ask "who said they'd book the room?" in the channel and you get the name and a link to the message.

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

State lives in one JSON file (`state.json`) written atomically. `/forgetme` deletes everything the bot has on you. `/receipts off` stops tracking a channel. Nudges go by DM. Overdue items are never posted in the channel. When you run `/receipts board` you see only your own overdue items, in a reply only you can see.

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

Run it:

```
python3 bot.py
```

In Discord: `/receipts on` in a channel, then `!demo` to seed a fake group chat. `!demo` and `!tick <hours>` only work for the server owner, anyone with a role called `receipts-demo`, or user ids listed in `DEMO_USER_IDS` (comma-separated). Anyone else gets a short "only demo runners can do this." reply.

Tests:

```
USE_LLM=false pytest
```

## 60-second demo script

1. `/receipts on`, then teammates chat naturally: "ok I'll do the intro slides by thursday", "I can book a hayden room", "I got snacks".
2. 🧾 pops on each one. `/receipts board`.
3. `!tick 24`. Yash gets a DM, "intro slides due tomorrow. still on it?", and taps 🆘.
4. The channel asks for help. Suraj taps 🙋 and it's reassigned, with both confirmed.
5. "who said they'd book the room?" gets a link to the message.
6. `/awards`.

## Commands

| Command | What it does |
|---|---|
| `/receipts on` / `/receipts off` | start or stop tracking this channel |
| `/receipts board` | who promised what, grouped by person |
| `/done <what>` | mark one of your promises done |
| `/awards` | this week's awards |
| `/forgetme` | delete everything the bot has on you |
| `/help` | short help |
| `!demo` | seed a fake CSE 511 group chat (owner, demo role, or `DEMO_USER_IDS`) |
| `!tick <hours>` | move the demo clock forward (owner, demo role, or `DEMO_USER_IDS`) |

## Layout

```
bot.py      discord events, commands, scheduler
detect.py   keyword prefilter, model extraction, rule fallback
dates.py    "by thursday", "tomorrow", "fri 5pm" -> datetime
store.py    receipts, channel opt in, forgetme, atomic save
nudges.py   what is due soon, demo clock
awards.py   weekly awards from the store
voice.py    every line the bot says
demo.py     the !demo seed
tests/      pytest, runs in CI with USE_LLM=false
```

## What's next

- Cubbie can add receipts to your calendar, so a promise in chat becomes a calendar event with a reminder.
- Smarter "on it" handling: when someone replies "on it" to a request, use the request as the summary.
- Per-channel awards time instead of one global Friday 5pm.
