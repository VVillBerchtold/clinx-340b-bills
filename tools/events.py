"""Build the calendar: the dated steps of every listed bill, hearings, session days, and federal notices' dates.

    python3 -I tools/events.py raw/openstates raw/events raw/govinfo data

Four things go into one table (`data/events.csv`, and the same rows in `data/340b-events.json`),
one row per event:

1. Steps. Every dated step the official record holds for a listed bill that is one of: introduced,
   sent to a committee, reported by a committee, a vote on passage, sent for signature, signed,
   vetoed, became law. The wording is the legislature's own. For Congress the steps are the ones the
   Library of Congress marks with a code in each bill's status file.
2. Hearings. What `fetch_events.py` saved from Open States' list of legislative events, kept only
   where the agenda names a bill that is in the table.
3. Sessions. The day each legislature's session starts and ends, from Open States' list of
   sessions, for sessions that start or end on or after 1 January 2025.
4. Federal notices. For each rule, proposed rule or notice in the notices table that is about
   340B or has a part on it: the day it was published, the day comments close and the day it takes
   effect, as the Federal Register gives them, and any other day a person read in the document
   itself (`read/notice-dates.csv`). These rows carry the place code FED, for federal agencies,
   and name their document in `notice_id`. A document that only mentions 340B puts no date here.

5. Report days. The days a law or a budget sets for a state agency's or a covered entity's report,
   hand-kept in `read/report-dates.csv` (event_id, day, jurisdiction, what, body, official_words,
   link, read_on). Each day is quoted from the official source; its words are in the row. The file is
   added on every run. A row with a missing field, a day not written year-month-day, or a name
   already used by another event stops the build with a plain message.

Nothing is guessed: a step with no date, or a hearing with no bill of ours on its agenda, is left out.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from federal import CONGRESS, CONGRESS_ENDS, STEPS as CONGRESS_CODES, plain, read_statuses  # noqa: E402
from fetch_state_texts import bill_id, web_address  # noqa: E402

COLUMNS = ["event_id", "day", "time", "jurisdiction", "kind", "bill_id", "bill", "notice_id", "what", "body", "where", "link", "source", "retrieved"]
# The place code of rows that come from federal agencies' notices (Congress is US).
AGENCIES = "FED"

# Open States' label for a step -> the calendar's kind. A step with none of these labels is left out.
STEP_KINDS = {
    "introduction": "introduced",
    "filing": "introduced",
    "referral-committee": "sent to committee",
    "committee-passage": "reported by committee",
    "committee-passage-favorable": "reported by committee",
    "committee-passage-unfavorable": "reported by committee",
    "committee-failure": "failed in committee",
    "passage": "vote on passage",
    "failure": "vote on passage",
    "veto-override-passage": "vote on passage",
    "executive-receipt": "sent for signature",
    "executive-signature": "signed",
    "executive-veto": "vetoed",
    "executive-veto-line-item": "vetoed",
    "became-law": "became law",
}
# Where a step carries several labels, the one furthest along names it.
ORDER = ["introduced", "sent to committee", "failed in committee", "reported by committee", "vote on passage", "sent for signature", "vetoed", "signed", "became law"]
FIRST_DAY = "2025-01-01"
# The same for Congress, from the Library of Congress codes federal.py reads, plus the President's signature.
CONGRESS_KINDS = {
    "introduced": "introduced",
    "reported": "reported by committee",
    "passed-house": "vote on passage",
    "passed-senate": "vote on passage",
    "failed-house": "vote on passage",
    "failed-senate": "vote on passage",
    "to-president": "sent for signature",
    "vetoed": "vetoed",
    "law": "became law",
}
SIGNED_CODE = "E30000"
# What each kind of event means, in plain words; published with the table.
KINDS = {
    "introduced": "The bill was filed or introduced in a chamber. A bill that passes one chamber is introduced again in the other.",
    "sent to committee": "The bill was sent to a committee.",
    "reported by committee": "A committee acted on the bill and sent it on.",
    "failed in committee": "A committee voted the bill down.",
    "vote on passage": "A chamber voted on passing the bill; the official words say how the vote went.",
    "sent for signature": "The bill was sent to the governor, or to the President.",
    "signed": "The governor, or the President, signed the bill.",
    "vetoed": "The governor, or the President, vetoed the bill or part of it.",
    "became law": "The bill became law.",
    "hearing": "A committee meeting or hearing with the bill on its agenda.",
    "session starts": "The first day of a legislature's session.",
    "session ends": "The last day of a legislature's session.",
    "notice published": "A federal agency published a rule, a proposed rule or a notice in the Federal Register.",
    "comments close": "The last day a federal agency takes public comments on the document.",
    "takes effect": "The day the Federal Register gives as the document's effective date.",
    "report due": "The day a law or a budget sets for a state agency's or a covered entity's report. The day is quoted from the official source; its words are in the row.",
    "date set by a notice": "Another day the document itself sets, such as a deadline or a start day. A person read it in the document; its own words are in the notices table.",
}


REPORT_DATES = Path(__file__).parent.parent / "read" / "report-dates.csv"
REPORT_COLUMNS = ["event_id", "day", "jurisdiction", "what", "body", "official_words", "link", "read_on"]


def report_rows(path: Path = REPORT_DATES) -> list[dict[str, str]]:
    """Read the hand-kept report days as calendar rows; stop with a plain message on any bad row."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REPORT_COLUMNS:
            raise SystemExit(f"{path.name}: the columns must be {', '.join(REPORT_COLUMNS)}")
        found = list(reader)
    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for number, row in enumerate(found, start=2):
        label = f"{path.name} line {number}"
        for column in REPORT_COLUMNS:
            if not (row.get(column) or "").strip():
                raise SystemExit(f"{label}: no {column}")
        for column in ("day", "read_on"):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[column]):
                raise SystemExit(f"{label}: {column} is not a date written year-month-day")
        if not row["link"].startswith("https://"):
            raise SystemExit(f"{label}: link is not a web address")
        if row["event_id"] in names:
            raise SystemExit(f"{label}: {row['event_id']} is used twice")
        names.add(row["event_id"])
        rows.append({
            "event_id": row["event_id"], "day": row["day"], "jurisdiction": row["jurisdiction"], "kind": "report due",
            "what": row["what"], "body": row["body"], "link": row["link"],
            "source": f"the official source, read on {row['read_on']}: \"{row['official_words']}\"",
        })
    return rows


def state_of(jurisdiction_id: str) -> str:
    """ocd-jurisdiction/country:us/state:ri/government -> RI."""
    return jurisdiction_id.split("/state:")[1].split("/")[0].upper() if "/state:" in jurisdiction_id else ""


def main() -> None:
    found_dir, events_dir, congress_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    out = out_dir / "events.csv"
    today = date.today().isoformat()
    table = json.loads((Path(__file__).parent.parent / "data" / "340b-bills.json").read_text(encoding="utf-8"))
    listed = {bill["bill_id"]: bill for bill in table["bills"]}
    rows: list[dict[str, str]] = []

    # 1. Steps of listed state bills.
    seen: set[str] = set()
    for page in sorted(found_dir.glob("phrase*-page*.json")):
        for bill in json.loads(page.read_text(encoding="utf-8"))["results"]:
            if bill["jurisdiction"]["classification"] != "state":
                continue
            name = bill_id(bill)
            if name not in listed or name in seen:
                continue
            seen.add(name)
            for action in bill.get("actions", []):
                kinds = sorted({STEP_KINDS[c] for c in action.get("classification") or [] if c in STEP_KINDS}, key=ORDER.index)
                day = (action.get("date") or "")[:10]
                if not kinds or len(day) != 10:
                    continue
                rows.append({
                    "event_id": f"{name}-step-{action['order']}",
                    "day": day,
                    "jurisdiction": listed[name]["jurisdiction"],
                    "kind": kinds[-1],
                    "bill_id": name,
                    "bill": listed[name]["bill"],
                    "what": " ".join((action.get("description") or "").split()),
                    "body": (action.get("organization") or {}).get("name", ""),
                    "link": listed[name]["bill_url"],
                    "source": "the bill's record of steps",
                })

    # 1b. Steps of listed bills in Congress.
    for (kind, number), bill in sorted(read_statuses(congress_dir).items()):
        name = f"us-{bill.findtext('congress')}-{kind.lower()}{number}"
        if name not in listed:
            continue
        taken: set[tuple[str, str]] = set()
        for action in bill.iterfind("actions/item"):
            if action.findtext("sourceSystem/name") != "Library of Congress":
                continue
            code = action.findtext("actionCode") or ""
            step = "signed" if code == SIGNED_CODE else CONGRESS_KINDS.get(CONGRESS_CODES.get(code, ""))
            day = action.findtext("actionDate") or ""
            if not step or len(day) != 10 or (day, step) in taken:
                continue
            taken.add((day, step))
            words = plain(action.findtext("text") or "")
            rows.append({
                "event_id": f"{name}-{day}-{step.replace(' ', '-')}",
                "day": day,
                "jurisdiction": "US",
                "kind": step,
                "bill_id": name,
                "bill": listed[name]["bill"],
                "what": words,
                "body": "Senate" if "Senate" in words and "House" not in words else "House" if "House" in words and "Senate" not in words else "",
                "link": listed[name]["bill_url"],
                "source": "the bill's record of steps",
            })

    # 2. Hearings whose agenda names a listed bill.
    called_off: set[str] = set()  # the first eight letters of each fetched hearing that was cancelled or withdrawn
    by_number: dict[tuple[str, str], list[str]] = {}
    for name, bill in listed.items():
        by_number.setdefault((bill["jurisdiction"], "".join(bill["bill"].split()).upper()), []).append(name)
    for page in sorted(events_dir.glob("*-page*.json")) if events_dir.exists() else []:
        for event in json.loads(page.read_text(encoding="utf-8")).get("results", []):
            if event.get("deleted") or event.get("status") == "cancelled":
                called_off.add(event["id"].split("/")[-1][:8])
                continue
            place = state_of(event["jurisdiction"]["id"])
            start = event.get("start_date") or ""
            numbers = {"".join(entity["name"].split()).upper() for item in event.get("agenda") or [] for entity in item.get("related_entities") or [] if entity.get("entity_type") == "bill" and entity.get("name")}
            for number in sorted(numbers):
                # A number is matched within the session the hearing falls in: the bill whose session has not ended before it.
                for name in by_number.get((place, number), []):
                    if listed[name]["session_end"] < start[:10] or (listed[name]["introduced_date"] or FIRST_DAY) > start[:10]:
                        continue
                    sources = event.get("sources") or []
                    rows.append({
                        "event_id": f"{name}-hearing-{event['id'].split('/')[-1][:8]}",
                        "day": start[:10],
                        "time": start[11:16] + " UTC" if len(start) > 10 and not event.get("all_day") else "",
                        "jurisdiction": place,
                        "kind": "hearing",
                        "bill_id": name,
                        "bill": listed[name]["bill"],
                        "what": " ".join((event.get("name") or "").split()),
                        "where": " ".join(((event.get("location") or {}).get("name") or "").split()),
                        "link": web_address(sources[0]["url"]) if sources else listed[name]["bill_url"],
                        "source": "the legislature's list of hearings",
                    })

    # 2b. A hearing that has already happened stays on the calendar after it leaves the list that is
    # fetched (the list only reaches back a few weeks). A coming hearing that is no longer on the
    # legislature's list is dropped: it was moved or called off.
    fetched = {row["event_id"] for row in rows}
    if out.exists():
        with out.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["kind"] == "hearing" and row["day"] < today and row["event_id"] not in fetched and row["bill_id"] in listed and row["event_id"].rsplit("-", 1)[-1] not in called_off:
                    rows.append({column: row.get(column, "") for column in COLUMNS if column != "retrieved"})

    # 3. The days sessions start and end.
    sessions_seen: set[str] = set()
    for page in sorted(found_dir.glob("jurisdictions*.json")):
        for place in json.loads(page.read_text(encoding="utf-8"))["results"]:
            code = state_of(place["id"])
            if not code:
                continue
            for session in place.get("legislative_sessions", []):
                for kind, day in (("session starts", session.get("start_date") or ""), ("session ends", session.get("end_date") or "")):
                    name = f"{code.lower()}-{kind.split()[1]}-{''.join(c for c in session['identifier'].lower() if c.isalnum())}"
                    if len(day) == 10 and day >= FIRST_DAY and name not in sessions_seen:
                        sessions_seen.add(name)
                        rows.append({
                            "event_id": name,
                            "day": day,
                            "jurisdiction": code,
                            "kind": kind,
                            "what": session["name"],
                            "link": place.get("url") or "",
                            "source": "Open States' list of sessions",
                        })

    # Congress: the day this Congress ends. Its start day is set by law each time, so it is not guessed here.
    rows.append({
        "event_id": f"us-ends-{CONGRESS}",
        "day": CONGRESS_ENDS,
        "jurisdiction": "US",
        "kind": "session ends",
        "what": f"{CONGRESS}th Congress",
        "link": "https://www.congress.gov/",
        "source": "the Constitution's Twentieth Amendment",
    })

    # 4. Federal notices: the days the Federal Register gives, and the days a person read in the document.
    notices_file = out_dir / "340b-notices.json"
    for notice in json.loads(notices_file.read_text(encoding="utf-8"))["notices"] if notices_file.exists() else []:
        # About 340B or with a part on it; one nobody has read yet counts when its title names the program.
        if notice["role"] not in ("main", "part") and not (notice["role"] == "" and "title" in notice["names_program_in"]):
            continue
        name = notice["notice_id"]
        # The agency that wrote it comes last in the Federal Register's list, after its department.
        about = {"jurisdiction": AGENCIES, "notice_id": name, "body": notice["agencies"][-1] if notice["agencies"] else "", "link": notice["notice_url"]}
        for kind, day in (("notice published", notice["published"]), ("comments close", notice["comments_close"]), ("takes effect", notice["effective"])):
            if len(day) == 10 and day >= FIRST_DAY:
                rows.append(about | {"event_id": f"{name}-{kind.split()[-1]}", "day": day, "kind": kind, "what": notice["title"], "source": "the Federal Register"})
        for row in notice["dates_read"]:
            rows.append(about | {"event_id": f"{name}-date-{row['day']}", "day": row["day"], "kind": "date set by a notice", "what": row["what"], "source": "the document's own words, read by a person"})

    # 5. Report days a person read in a law or a budget.
    rows += report_rows()

    ids = [row["event_id"] for row in rows]
    doubled = sorted({i for i in ids if ids.count(i) > 1})
    if doubled:
        raise SystemExit(f"two events share a name: {doubled[:5]}")
    rows.sort(key=lambda row: (row["day"], row["jurisdiction"], row.get("bill_id", ""), row["event_id"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    unknown = sorted({row["kind"] for row in rows} - set(KINDS))
    if unknown:
        raise SystemExit(f"an event kind with no plain meaning: {unknown}")
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS} | {"retrieved": today})
    events = [{column: row.get(column, "") for column in COLUMNS} | {"retrieved": today} for row in rows]
    (out_dir / "340b-events.json").write_text(json.dumps({"retrieved": today, "kinds": KINDS, "events": events}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print(f"{len(rows)} events; " + ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
