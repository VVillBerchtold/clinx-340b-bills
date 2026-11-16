"""Find state bills that may name the 340B program, using Open States as the finder.

In plain words: Open States keeps a searchable copy of the bills of every state legislature. This
tool asks it for every bill whose text holds one of a few phrases ("340B", "U.S.C. 256b"), and
saves the answers as they came, one file per page, in raw/openstates/. It decides nothing: another
tool reads these answers, checks each bill, and builds the table.

It needs a free Open States key, kept in a private file outside this repository. The key is never
printed and never saved with the answers.

Run it:  python3 -I tools/find_state.py raw/openstates 2025-01-01

Two things learned the hard way about the search:
* a bare 340B finds nothing (the service reads it as a bill number), so every phrase is in quotes;
* it answers at most 20 bills a page, so the tool walks the pages, a few seconds apart.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://v3.openstates.org/bills"
JURISDICTIONS = "https://v3.openstates.org/jurisdictions"
KEY_FILE = Path.home() / ".config" / "clinx" / "openstates.key"


def read_key() -> str:
    """The Open States key: from the environment where a hosted job passes it, else from the private file."""
    return os.environ.get("OPENSTATES_KEY", "").strip() or KEY_FILE.read_text(encoding="utf-8").strip()


PHRASES = ['"340B"', '"U.S.C. 256b"', '"USC 256b"', '"U.S.C. Sec. 256b"', '"U.S.C. Section 256b"']
INCLUDE = ["abstracts", "actions", "sources", "sponsorships", "versions", "documents", "other_titles"]
PAUSE = 7.0  # seconds between calls; the free key's limits are not published


def ask(key: str, params: list[tuple[str, str]], api: str = "") -> dict:
    """Return one page of answers. Stops the run on any refusal rather than pressing on."""
    request = urllib.request.Request(f"{api or API}?{urllib.parse.urlencode(params)}", headers={"X-API-KEY": key, "User-Agent": "ClinX Open Data Reader (+https://clinx.org/methods/)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return json.load(answer)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Open States answered {error.code} ({error.reason}). Stopping; run again later.") from None


def main() -> None:
    out, since = Path(sys.argv[1]), sys.argv[2]
    # Everything is saved to a side folder first and swapped in only when every call has answered,
    # so a run that stops half way leaves yesterday's answers whole.
    final, out = out, out / "incoming"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    key = read_key()
    calls = 0
    # The list of each state's sessions, with the days they start and end (two pages).
    page = 1
    while True:
        if calls:
            time.sleep(PAUSE)
        found = ask(key, [("classification", "state"), ("include", "legislative_sessions"), ("per_page", "52"), ("page", str(page))], JURISDICTIONS)
        calls += 1
        (out / ("jurisdictions.json" if page == 1 else f"jurisdictions-{page}.json")).write_text(json.dumps(found, indent=1), encoding="utf-8")
        if page >= found["pagination"]["max_page"]:
            break
        page += 1
    for number, phrase in enumerate(PHRASES, start=1):
        page = 1
        while True:
            params = [("q", phrase), ("created_since", since), ("per_page", "20"), ("page", str(page)), ("sort", "updated_desc")]
            params += [("include", name) for name in INCLUDE]
            if calls:
                time.sleep(PAUSE)
            found = ask(key, params)
            calls += 1
            (out / f"phrase{number}-page{page:03d}.json").write_text(json.dumps({"phrase": phrase, "since": since, **found}, indent=1), encoding="utf-8")
            pages = found["pagination"]["max_page"]
            print(f"{phrase}: page {page} of {pages}, {found['pagination']['total_items']} bills in all", flush=True)
            if page >= pages:
                break
            page += 1
    for old in list(final.glob("phrase*-page*.json")) + list(final.glob("jurisdictions*.json")):
        old.unlink()
    for new in sorted(out.glob("*.json")):
        new.rename(final / new.name)
    out.rmdir()
    print(f"{calls} calls made")


if __name__ == "__main__":
    main()
