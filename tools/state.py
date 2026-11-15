"""State bills that name the 340B program: turn what was found and checked into table rows.

In plain words: tools/find_state.py saved what Open States knows about each bill it found, and
tools/fetch_state_texts.py fetched each bill's text from the legislature's own site and checked it.
This tool puts the two together and writes one row per bill, in the same columns as the federal
table. A bill is listed only when its title, its official summary or its fetched text names the
program. A bill that Open States found but whose text could not be read, or does not name the
program, is written to a second file with the reason, and is not listed.

How far a bill has got is worked out from the steps Open States recorded from the legislature's
site. The latest step is given in the legislature's own wording, with a link to its own page.

Run it:  python3 -I tools/state.py raw/openstates raw/state-texts state-bills.csv state-bills-not-listed.csv
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from federal import COLUMNS  # noqa: E402
from fetch_state_texts import bill_id, bill_text, links_of, mentions_of, quote_of, web_address  # noqa: E402

RANK = ["introduced", "reported", "passed-one", "passed-both", "to-governor", "vetoed", "law"]


def stage_of(bill: dict) -> tuple[str, str, str]:
    """Return (stage, the day it was reached, a failed vote if any) from the bill's recorded steps."""
    reached: dict[str, str] = {}
    passed: dict[str, tuple[str, str]] = {}  # chamber kind -> (day, chamber name)
    failed = ""

    def mark(step: str, day: str) -> None:
        if step not in reached or day < reached[step]:
            reached[step] = day

    for action in bill["actions"]:
        day = action["date"][:10]
        kinds = set(action["classification"])
        chamber = action["organization"]["classification"]
        if kinds & {"introduction", "filing"}:
            mark("introduced", day)
        if kinds & {"committee-passage", "committee-passage-favorable"}:
            mark("reported", day)
        if "passage" in kinds and chamber in ("lower", "upper", "legislature"):
            if chamber not in passed or day < passed[chamber][0]:
                passed[chamber] = (day, action["organization"]["name"])
        if "failure" in kinds:
            failed = f"{day} {action['description'].strip()}"
        if "executive-receipt" in kinds:
            mark("to-governor", day)
        if "executive-veto" in kinds and "veto-override-passage" not in {k for a in bill["actions"] for k in a["classification"]}:
            mark("vetoed", day)
        if kinds & {"executive-signature", "became-law"}:
            mark("law", day)
    if passed:
        reached["passed-one"] = min(day for day, _ in passed.values())
        if "legislature" in passed or {"lower", "upper"} <= set(passed):
            reached["passed-both"] = max(day for day, _ in passed.values())
    if not reached and bill["actions"]:
        # Some legislatures record no step called "introduced"; a bill with any step has been introduced.
        reached["introduced"] = min(a["date"][:10] for a in bill["actions"])
    best = max(reached, key=RANK.index, default="")
    words = {
        "": "",
        "introduced": "Introduced",
        "reported": "Reported by committee",
        "passed-one": f"Passed the {min(passed.values())[1]}" if passed else "",
        "passed-both": "Passed the legislature",
        "to-governor": "Sent to the governor",
        "vetoed": "Vetoed",
        "law": "Became law",
    }
    return words[best], reached.get(best, ""), failed


def page_of(bill: dict, text_url: str) -> str:
    """Return the legislature's own page for the bill; where the record names only a front page, its text."""
    for source in bill["sources"]:
        url = source["url"]
        if url.startswith("http") and len(url.split("/", 3)[-1]) > 1 and "api." not in url and "webservices" not in url:
            return url
    return text_url or bill["sources"][0]["url"]


def main() -> None:
    found_dir, texts_dir, out, left_out = (Path(a) for a in sys.argv[1:5])
    index = json.loads((texts_dir / "index.json").read_text(encoding="utf-8"))
    sessions: dict[tuple[str, str], tuple[str, str]] = {}  # (place, session) -> (its name, the day it ends)
    for page in sorted(found_dir.glob("jurisdictions*.json")):
        for place in json.loads(page.read_text(encoding="utf-8"))["results"]:
            for session in place["legislative_sessions"]:
                sessions[(place["id"], session["identifier"])] = (session["name"], (session.get("end_date") or "")[:10])
    bills: dict[str, dict] = {}
    for page in sorted(found_dir.glob("phrase*-page*.json")):
        for bill in json.loads(page.read_text(encoding="utf-8"))["results"]:
            if bill["jurisdiction"]["classification"] == "state":
                bills[bill_id(bill)] = bill
    today = date.today().isoformat()
    # Massachusetts files a bill first as a docket (HD, SD) and then gives it a bill number (H, S).
    # Where both are found, only the numbered bill is listed.
    numbered: dict[tuple[str, str], list[str]] = {}
    for bill in bills.values():
        if bill["jurisdiction"]["id"].endswith("state:ma/government") and not bill["identifier"].startswith(("HD", "SD")):
            numbered.setdefault((bill["session"], bill["title"]), []).append(bill["identifier"])
    rows, not_listed = [], []
    # Things the finder returns that a person has read and found are not bills (not-bills.csv), with the reason.
    with (Path(__file__).parent.parent / "not-bills.csv").open(encoding="utf-8", newline="") as handle:
        not_bills = {row["bill_id"]: row["reason"] for row in csv.DictReader(handle)}
    for name in sorted(bills):
        bill = bills[name]
        text = dict(index.get(name, {"result": "not checked yet"}))
        saved = texts_dir / f"{name}.txt"
        if text["result"] in ("named", "not named") and saved.exists():
            # Count and quote from the saved words of the bill itself (not what its page prints above it).
            words = bill_text(text["url"], saved.read_text(encoding="utf-8").strip())
            text["mentions"] = len(mentions_of(words))
            text["quote"] = quote_of(words)
            text["result"] = "named" if text["mentions"] else "not named"
        titles = [bill["title"]] + [t["title"] for t in bill.get("other_titles", [])]
        summaries = [a["abstract"] for a in bill.get("abstracts", [])]
        where = []
        if any(mentions_of(t or "") for t in titles):
            where.append("title")
        if any(mentions_of(s or "") for s in summaries):
            where.append("summary")
        newest = links_of(bill)
        if text["result"] == "named":
            # "text" only where the paper read is the newest version of the bill itself, as the versions rank today.
            where.append("text" if newest and text.get("url") == newest[0][2] else "earlier text")
        state = bill["jurisdiction"]["id"].split("state:")[1][:2].upper()
        docket_of = numbered.get((bill["session"], bill["title"])) if state == "MA" and bill["identifier"].startswith(("HD", "SD")) else None
        if docket_of:
            not_listed.append({"bill_id": name, "jurisdiction": state, "bill": bill["identifier"], "title": bill["title"], "reason": f"a filing docket; the bill is listed as {', '.join(sorted(docket_of))}", "finder_url": bill["openstates_url"]})
            continue
        if name in not_bills:
            not_listed.append({"bill_id": name, "jurisdiction": state, "bill": bill["identifier"], "title": bill["title"], "reason": not_bills[name], "finder_url": bill["openstates_url"]})
            continue
        if not where:
            not_listed.append({"bill_id": name, "jurisdiction": state, "bill": bill["identifier"], "title": bill["title"], "reason": text["result"], "finder_url": bill["openstates_url"]})
            continue
        stage, stage_date, failed = stage_of(bill)
        first = [s["name"] for s in bill["sponsorships"] if s["primary"]]
        # The text that was read; for a bill whose text has not been read, the newest text its record names.
        text_url = text.get("url") or (newest[0][2] if newest else "")
        quote = text.get("quote") or next((quote_of(t) for t in titles + summaries if mentions_of(t or "")), "")
        rows.append(
            {
                "bill_id": name,
                "jurisdiction": state,
                "session": sessions[(bill["jurisdiction"]["id"], bill["session"])][0],
                "session_end": sessions[(bill["jurisdiction"]["id"], bill["session"])][1],
                "bill": bill["identifier"],
                "title": bill["title"],
                "official_title": "",
                "names_program_in": ";".join(where),
                "text_mentions": str(text["mentions"]) if text["result"] in ("named", "not named") else "",
                "quote": quote,
                "introduced_date": (bill.get("first_action_date") or "")[:10],
                "sponsor": "; ".join(first),
                "cosponsors": str(len(bill["sponsorships"]) - len(first)),
                "committees": "",
                "stage": stage,
                "stage_date": stage_date,
                "failed_vote": failed,
                "latest_action_date": (bill.get("latest_action_date") or "")[:10],
                "latest_action": (bill.get("latest_action_description") or "").strip(),
                "law": "",
                "same_as": "",
                "bill_url": web_address(page_of(bill, text_url)),
                "text_version": text.get("version", ""),
                "text_date": text.get("date", ""),
                "text_url": web_address(text_url),
                "status_updated": bill["updated_at"][:10],
                "retrieved": today,
            }
        )
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with left_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bill_id", "jurisdiction", "bill", "title", "reason", "finder_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(not_listed)
    print(f"{len(bills)} bills found; {len(rows)} listed; {len(not_listed)} not listed")


if __name__ == "__main__":
    main()
