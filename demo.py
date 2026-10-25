# !demo seeds a fake CSE 511 group chat so judges can watch receipts get caught.
# Persona 0 is whoever ran !demo, so the nudge DM later lands in a real inbox.
# The other three are fake ids. They never get DMs, which is fine for a demo.
import voice

INVOKER = 0

DEMO_PEOPLE = {
    9000000000000001: "Yash",
    9000000000000002: "Suraj",
    9000000000000003: "Bhavana",
}

# (persona id, text). Mix of promises and normal chatter.
DEMO_LINES = [
    (9000000000000001, "ok who is doing what for the 511 checkpoint"),
    (INVOKER, "ok I'll do the intro slides by tomorrow"),
    (9000000000000001, "I can book a hayden room for sunday"),
    (9000000000000002, "yo did anyone look at the rubric yet"),
    (9000000000000003, "I got snacks"),
    (9000000000000001, "lol i got nothing for related work yet"),
    (9000000000000002, "ill write the related work section by friday"),
]


def name_for(persona_id, invoker_id, invoker_name):
    if persona_id == INVOKER or persona_id == invoker_id:
        return invoker_name
    return DEMO_PEOPLE.get(persona_id, "someone")


async def run(channel, invoker, handle_candidate):
    """Post the demo lines through the bot and run the detector on each one.

    channel: the discord channel to post in
    invoker: the discord user who ran !demo
    handle_candidate: async (message, text, author_id) -> None, from bot.py
    """
    invoker_name = invoker.display_name
    await channel.send(voice.demo_banner())
    for persona_id, text in DEMO_LINES:
        author_id = invoker.id if persona_id == INVOKER else persona_id
        name = name_for(persona_id, invoker.id, invoker_name)
        sent = await channel.send(f"[demo] {name}: {text}")
        await handle_candidate(sent, text, author_id)
