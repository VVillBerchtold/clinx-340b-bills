"""Fetch the Federal Register's documents that name the 340B program, and the text of each.

    python3 -I tools/fetch_notices.py raw/notices 2025-01-01

In plain words: the Federal Register is where federal agencies publish their rules, proposed rules
and notices. Its own data service (federalregister.gov/api, run by the Office of the Federal
Register and the Government Publishing Office; no key needed) is asked for every document
published since the given day whose text holds "340B" or "256b" (the program's section of federal
law). The list is saved as it came. Then the full text of each document is fetched once: a
published document does not change, so a text already held, or one whose facts `notices.py` has
already put on record in `notices-index.json`, is never asked for again.

One request at a time, with a pause between them. If the service answers that it does not allow
this (403) or that it is being asked too fast (429), the tool stops and does not look for a way
round. `notices.py` then reads what was saved.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

API = "https://www.federalregister.gov/api/v1/documents.json"
AGENT = "clinx-340b-bills (public data project)"
PAUSE = 2.0
PHRASES = ['"340B"', '"256b"']
# What is asked for about each document. Every value shown in the table comes from these.
FIELDS = [
    "document_number", "citation", "type", "title", "agencies", "publication_date", "comments_close_on",
    "effective_on", "dates", "action", "abstract", "html_url", "pdf_url", "raw_text_url", "docket_ids",
    "page_length", "start_page", "end_page", "correction_of", "corrections", "regulation_id_numbers",
]
MOST_PAGES = 20


def ask(address: str, saved: Path, params: list[tuple[str, str]] | None = None) -> str:
    """Fetch one address into a file and return the answer's status code."""
    command = ["curl", "-sS", "-L", "--max-time", "120", "-A", AGENT, "-o", str(saved), "-w", "%{http_code}"]
    if params:
        command.append("-G")
        for name, value in params:
            command += ["--data-urlencode", f"{name}={value}"]
    got = subprocess.run(command + [address], capture_output=True, text=True, check=False)
    time.sleep(PAUSE)
    status = got.stdout.strip()
    if status in ("403", "429"):
        saved.unlink(missing_ok=True)
        raise SystemExit(f"the Federal Register answered {status} for {address}: stopped")
    if status != "200":
        saved.unlink(missing_ok=True)
    return status or got.stderr.strip()[:80]


def main() -> None:
    out, since = Path(sys.argv[1]), sys.argv[2]
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, dict] = {}
    for number, phrase in enumerate(PHRASES, start=1):
        page, pages = 1, 1
        while page <= min(pages, MOST_PAGES):
            saved = out / f"list{number}-page{page}.json"
            params = [("conditions[term]", phrase), ("conditions[publication_date][gte]", since), ("per_page", "200"), ("page", str(page)), ("order", "newest")]
            params += [("fields[]", field) for field in FIELDS]
            status = ask(API, saved, params)
            if status != "200":
                raise SystemExit(f"the Federal Register's list answered {status} for {phrase} page {page}: stopped")
            answer = json.loads(saved.read_text(encoding="utf-8"))
            pages = int(answer.get("total_pages") or 1)
            for document in answer.get("results") or []:
                found.setdefault(document["document_number"], document)
            page += 1
        # A page file from an earlier, longer list would be read as part of this one.
        for old in out.glob(f"list{number}-page*.json"):
            if int(old.stem.split("page")[1]) >= page:
                old.unlink()

    # What notices.py read from each text is on record in notices-index.json. A text is fetched only
    # for a document that is neither held here nor on that record.
    record = Path(__file__).resolve().parent.parent / "notices-index.json"
    known = set(json.loads(record.read_text(encoding="utf-8"))) if record.exists() else set()
    fetched = 0
    for name, document in sorted(found.items()):
        saved = out / f"{name}.txt"
        if name in known or (saved.exists() and saved.stat().st_size > 0):
            continue
        address = document.get("raw_text_url") or ""
        if not address.startswith("https://www.federalregister.gov/"):
            print(f"{name}: no text address; left without a text", flush=True)
            continue
        status = ask(address, saved)
        if status != "200":
            print(f"{name}: its text answered {status}; left without a text", flush=True)
            continue
        fetched += 1
    print(f"{len(found)} documents published since {since} hold the phrase; {fetched} texts fetched now, {len(found) - fetched} already held or without a text")


if __name__ == "__main__":
    main()
