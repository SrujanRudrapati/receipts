#!/usr/bin/env python3
"""Ask the group for a hand with one of the student's open promises.

Posts exactly "sos id=<id> source=cubbie" to the student's private ntfy topic. The Receipts bot picks it
up and asks the channel, the same as tapping the SOS reaction on a nudge. Nothing else goes out: no reason,
no course, no grade. The id must be an open receipt from pull.py, so Cubbie cannot ask about a made up one.

  RECEIPTS_LINK_TOKEN="$RECEIPTS_LINK_TOKEN" python3 scripts/sos.py --id ab12cd34
  python3 scripts/sos.py --id ab12cd34 --sample

Exit codes: 0 sent, 2 bad or unknown id, 3 token missing, 4 ntfy unreachable, 5 topic rejected, 6 other ntfy error.
"""

from __future__ import annotations

import argparse
import sys
import time

import receipts_link as link


def sos_line(receipt_id: str) -> str:
    return f"sos id={receipt_id} source=cubbie"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", required=True, help="the receipt id from pull.py")
    parser.add_argument("--again", action="store_true", help="send even though the group was already asked")
    parser.add_argument("--sample", action="store_true", help="print the line without sending it or touching state")
    args = parser.parse_args(argv)

    if not link.valid_id(args.id):
        link.fail("receipt ids are 8 lowercase hex characters.", link.EXIT_ARGS)
    if args.sample:
        print(f"would send: {sos_line(args.id)}")
        return link.EXIT_OK
    topic = link.require_topic()
    state = link.load_state()
    receipt = state["receipts"].get(args.id)
    if receipt is None or receipt.get("status") != "open":
        link.fail(f"{args.id} is not one of the student's open receipts. Run pull.py first and use an id from it.",
                  link.EXIT_ARGS)
    if receipt.get("sos_sent") and not args.again:
        link.fail("the group was already asked about this one. Add --again only if the student wants to ask once more.",
                  link.EXIT_ARGS)
    link.publish(topic, sos_line(args.id))
    receipts = {**state["receipts"], args.id: {**receipt, "sos_sent": int(time.time())}}
    link.save_state({**state, "receipts": receipts})
    print(f"sent. the group will hear that you could use a hand with {receipt['what']}.")
    return link.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
