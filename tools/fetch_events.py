"""Fetch each state's list of legislative hearings from Open States, for the calendar.

    python3 -I tools/fetch_events.py raw/events 30

Asks only for the states that have a bill in the table, and only for events from the given number
of days ago onward (earlier hearings are already in each bill's own record of steps). One page of
20 at a time, with a pause between calls. The key is read from a private file outside this folder
and is never printed or saved. `events.py` then keeps only the hearings whose agenda names a
listed bill.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

KEY_FILE = Path.home() / ".config" / "clinx" / "openstates.key"


def read_key() -> str:
    """The Open States key: from the environment where a hosted job passes it, else from the private file."""
    return os.environ.get("OPENSTATES_KEY", "").strip() or KEY_FILE.read_text(encoding="utf-8").strip()
PAUSE = 7.0
MOST_PAGES = 15  # per state; a state with more hearings than this in the window is cut short and said so


def main() -> None:
    out, days = Path(sys.argv[1]), int(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    table = json.loads((Path(__file__).parent.parent / "data" / "340b-bills.json").read_text(encoding="utf-8"))
    states = sorted({bill["jurisdiction"].lower() for bill in table["bills"]} - {"us"})
    after = (date.today() - timedelta(days=days)).isoformat()
    key = read_key()
    for old in out.glob("*-page*.json"):
        old.unlink()
    total = 0
    for state in states:
        page, pages = 1, 1
        while page <= min(pages, MOST_PAGES):
            saved = out / f"{state}-page{page}.json"
            got = subprocess.run(
                ["curl", "-sS", "--max-time", "60", "-G", "https://v3.openstates.org/events", "-H", "@-",
                 "--data-urlencode", f"jurisdiction={state}", "--data-urlencode", f"after={after}",
                 "--data-urlencode", "include=agenda", "--data-urlencode", "include=sources",
                 "--data-urlencode", "per_page=20", "--data-urlencode", f"page={page}",
                 "-o", str(saved), "-w", "%{http_code}"],
                input=f"X-API-KEY: {key}\n", capture_output=True, text=True, check=False,
            )
            time.sleep(PAUSE)
            if got.stdout.strip() in ("401", "403", "429"):
                saved.unlink(missing_ok=True)
                raise SystemExit(f"Open States answered {got.stdout.strip()} at {state} page {page}: stopped")
            if got.stdout.strip() != "200":
                saved.unlink(missing_ok=True)
                print(f"{state}: page {page} answered {got.stdout.strip() or got.stderr.strip()[:60]}; skipped", flush=True)
                break
            answer = json.loads(saved.read_text(encoding="utf-8"))
            pages = answer.get("pagination", {}).get("max_page", 1)
            total += len(answer.get("results", []))
            page += 1
        if pages > MOST_PAGES:
            print(f"{state}: {pages} pages of events; only the first {MOST_PAGES} were fetched", flush=True)
        print(f"{state}: {min(pages, MOST_PAGES)} page(s)", flush=True)
    print(f"{total} events saved from {len(states)} states, from {after} onward")


if __name__ == "__main__":
    main()
