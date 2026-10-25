#!/usr/bin/env python3
"""Print the student's open Receipts promises.

Polls the student's private ntfy topic for the last 24 hours of receipt lines, folds them into the
saved state under HOME, and prints the open ones. 'new' means Cubbie has not offered a time block for it
yet; run with --offered <id> after offering so it is not brought up again. 'ding' means the bot sent its
last call and heard nothing; run with --dinged <id> once the student has been told.

  RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/pull.py --now "<student's local date and time>"
  RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/pull.py --offered ab12cd34
  RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/pull.py --dinged ab12cd34
  python3 scripts/pull.py --sample

Exit codes: 0 ok, 2 bad arguments, 3 token missing, 4 ntfy unreachable, 5 topic rejected, 6 other ntfy error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import receipts_link as link

SAMPLE = Path(__file__).resolve().parent.parent / "assets" / "sample_poll.ndjson"
SINCE = "24h"


def sample_messages() -> list[dict]:
    out = []
    for raw in SAMPLE.read_text().splitlines():
        if raw.strip():
            out.append(json.loads(raw))
    return out


def render(state: dict, now: str | None) -> str:
    receipts = link.open_receipts(state)
    lines = [f"open {len(receipts)}"]
    if not receipts:
        lines.append("no open receipts.")
    for r in receipts:
        tag = "seen" if r.get("offered") else "new"
        if r.get("ding_at") and not r.get("ding_handled"):
            tag = "ding"
        due = link.due_label(r.get("due"), now)
        if r.get("due") and now:
            due = f"{due} ({r['due']})"
        parts = [f"{tag} {r['id']}", r["what"], f"due {due}", f"#{r['channel']}"]
        if r.get("sos_sent"):
            parts.append("help asked")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def mark(receipt_id: str, flag: str, label: str, option: str) -> int:
    state = link.load_state()
    if receipt_id not in state["receipts"]:
        link.fail(f"{receipt_id} is not a receipt I know. Run pull.py without {option} first.", link.EXIT_ARGS)
    receipts = {**state["receipts"], receipt_id: {**state["receipts"][receipt_id], flag: True}}
    link.save_state({**state, "receipts": receipts})
    print(f"marked {receipt_id} as {label}.")
    return link.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--now", help="the student's local date and time, ISO 8601 with offset")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offered", metavar="ID", help="remember that a time block was offered for this receipt")
    mode.add_argument("--dinged", metavar="ID", help="remember that the student was told about this ding")
    mode.add_argument("--sample", action="store_true", help="offline demo with assets/sample_poll.ndjson, no state")
    args = parser.parse_args(argv)

    for value, flag, label, option in ((args.offered, "offered", "offered", "--offered"),
                                       (args.dinged, "ding_handled", "handled", "--dinged")):
        if value:
            if not link.valid_id(value):
                link.fail("receipt ids are 8 lowercase hex characters.", link.EXIT_ARGS)
            return mark(value, flag, label, option)
    if args.sample:
        print(render(link.apply_messages({"receipts": {}}, sample_messages()), args.now))
        return link.EXIT_OK
    topic = link.require_topic()
    state = link.apply_messages(link.load_state(), link.poll(topic, SINCE))
    link.save_state(state)
    print(render(state, args.now))
    return link.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
