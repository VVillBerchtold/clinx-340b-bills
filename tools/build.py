"""Put the federal and state bills into one table, with what Claude has read about each.

In plain words: tools/federal.py and tools/state.py each write the automatic part of the table
(what the official record says). The files in read/ hold the part Claude adds after reading a
bill: whether the bill is about 340B or only mentions it, its kinds, and one plain sentence on
what it would do. This tool joins them, checks the result, and writes the two files people
download: data/bills.csv and data/340b-bills.json.

A bill nobody has read yet is still listed, with those three columns left blank.

One more hand-kept file, read/outcomes.csv, ends the story of a bill that died: it sets the
stage to "Did not pass" and the stage date to the day given, and leaves the rest of the row as
the official record has it. See apply_outcomes() below.

Run it:  python3 -I tools/build.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from federal import COLUMNS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
READ_COLUMNS = ["role", "kinds", "summary"]
# The files Claude keeps about bills. (read/ also holds the files about federal notices, which notices.py reads.)
READ_FILES = ["federal.csv", "state.csv"]
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# What a bill is to the program: about it, changes it in one part, or only names it in passing.
ROLES = {
    "main": "About 340B",
    "part": "Has a part on 340B",
    "mention": "Mentions 340B",
}
# The same kinds, in the same order, as the laws table of the clinx-340b dataset.
KINDS = ["contract-pharmacy", "payer-nondiscrimination", "reporting", "medicaid", "use-of-savings", "study", "other"]
STAGES = [
    "Introduced",
    "Reported by committee",
    "Passed the House",
    "Passed the Senate",
    "Passed one chamber",
    "Passed both chambers",
    "Passed the legislature",
    "Sent to the President",
    "Sent to the governor",
    "Vetoed",
    "Did not pass",
    "Became law",
]
# The stages Claude can set in read/outcomes.csv after reading the record: the end of a bill that died.
OUTCOMES = ["Did not pass"]
OUTCOME_COLUMNS = ["bill_id", "outcome", "day", "official_words", "source_url", "read_on"]


def rows_of(path: Path) -> list[dict[str, str]]:
    """Return a CSV file's rows; an absent file has none."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def apply_outcomes(bills: list[dict[str, str]], outcomes: list[dict[str, str]]) -> list[str]:
    """Set the stage of each bill that read/outcomes.csv names; return what is wrong, in plain words.

    The stage becomes the outcome and the stage date the day given. Nothing else in the row moves,
    so the bill's latest action stays as the legislature worded it. An outcome that names a bill
    not in the table, a bill that became law, a stage that is not an outcome, or a missing or
    badly written field is a problem, and the build stops on it.
    """
    problems: list[str] = []
    by_name = {b["bill_id"]: b for b in bills}
    done: set[str] = set()
    for row in outcomes:
        name = row.get("bill_id", "")
        for column in OUTCOME_COLUMNS:
            if not (row.get(column) or "").strip():
                problems.append(f"read/outcomes.csv: {name or 'a row'} has no {column}")
        if name in done:
            problems.append(f"read/outcomes.csv: {name} is named twice")
        done.add(name)
        bill = by_name.get(name)
        if bill is None:
            problems.append(f"read/outcomes.csv: {name} is not in the table")
            continue
        if row.get("outcome") not in OUTCOMES:
            problems.append(f"read/outcomes.csv: {name}: {row.get('outcome')!r} is not an outcome (one of: {', '.join(OUTCOMES)})")
        for column in ("day", "read_on"):
            if row.get(column) and not DAY.fullmatch(row[column]):
                problems.append(f"read/outcomes.csv: {name}: {column} is not a date written year-month-day")
        if not (row.get("source_url") or "").startswith("https://"):
            problems.append(f"read/outcomes.csv: {name}: source_url is not a web address")
        if bill["stage"] == "Became law" or bill["law"]:
            problems.append(f"read/outcomes.csv: {name} became law, so it cannot be marked as not passed")
            continue
        if not problems:
            bill["stage"], bill["stage_date"] = row["outcome"], row["day"]
    return problems


def check_outcomes_code() -> None:
    """Prove, on a made-up table, that the outcomes step does what it says. Runs on every build."""
    table = lambda: [{"bill_id": "x-1", "stage": "Passed the legislature", "stage_date": "2025-05-06", "law": "", "latest_action": "Adhere"}, {"bill_id": "x-2", "stage": "Became law", "stage_date": "2025-05-06", "law": "", "latest_action": ""}]
    good = {"bill_id": "x-1", "outcome": "Did not pass", "day": "2025-05-07", "official_words": "Status: Lost", "source_url": "https://example.org/x", "read_on": "2026-11-16"}
    rows = table()
    assert apply_outcomes(rows, [good]) == [], "a good outcome was refused"
    assert (rows[0]["stage"], rows[0]["stage_date"], rows[0]["latest_action"]) == ("Did not pass", "2025-05-07", "Adhere"), "the outcome was not applied as written"
    assert rows[1]["stage"] == "Became law", "another bill moved"
    assert apply_outcomes(table(), [good | {"bill_id": "x-9"}]), "a bill not in the table was accepted"
    assert apply_outcomes(table(), [good | {"bill_id": "x-2"}]), "a bill that became law was accepted"
    assert apply_outcomes(table(), [good | {"outcome": "Vetoed"}]), "a stage that is not an outcome was accepted"
    assert apply_outcomes(table(), [good | {"official_words": ""}]), "a missing field was accepted"


def main() -> None:
    check_outcomes_code()
    bills = rows_of(ROOT / "federal-bills.csv") + rows_of(ROOT / "state-bills.csv")
    read: dict[str, dict[str, str]] = {}
    for path in (ROOT / "read" / name for name in READ_FILES):
        for row in rows_of(path):
            if row["bill_id"] in read:
                raise SystemExit(f"{row['bill_id']} is read twice")
            read[row["bill_id"]] = row
    problems: list[str] = []
    seen: set[str] = set()
    for bill in bills:
        name = bill["bill_id"]
        if name in seen:
            problems.append(f"{name}: listed twice")
        seen.add(name)
        note = read.get(name, {})
        for column in READ_COLUMNS:
            bill[column] = note.get(column, "")
        if bill["role"] and bill["role"] not in ROLES:
            problems.append(f"{name}: unknown role {bill['role']}")
        for kind in filter(None, bill["kinds"].split(";")):
            if kind not in KINDS:
                problems.append(f"{name}: unknown kind {kind}")
        if bill["role"] == "mention" and bill["kinds"]:
            problems.append(f"{name}: a bill that only mentions the program has no kind")
        if bill["role"] in ("main", "part") and not bill["kinds"]:
            problems.append(f"{name}: read, but no kind")
        if bill["role"] and not bill["summary"]:
            problems.append(f"{name}: read, but no sentence")
        if not bill["names_program_in"]:
            problems.append(f"{name}: listed, but nothing says where it names the program")
        if bill["stage"] and bill["stage"] not in STAGES and not bill["stage"].startswith("Passed the "):
            problems.append(f"{name}: unknown stage {bill['stage']}")
        for column in ("bill_url", "text_url"):
            if bill[column] and (not bill[column].startswith(("https://", "http://")) or " " in bill[column]):
                problems.append(f"{name}: {column} is not a web address")
        for column in ("session_end", "introduced_date", "stage_date", "latest_action_date", "text_date", "status_updated", "retrieved"):
            if bill[column] and not DAY.fullmatch(bill[column]):
                problems.append(f"{name}: {column} is not a date written year-month-day")
        if not bill["session_end"]:
            problems.append(f"{name}: no end date for its session")
        if not bill["bill_url"]:
            problems.append(f"{name}: no official page")
    for name in read:
        if name not in seen:
            problems.append(f"read/ has {name}, which is not in the table")
    problems += apply_outcomes(bills, rows_of(ROOT / "read" / "outcomes.csv"))
    if problems:
        raise SystemExit("Not written:\n  " + "\n  ".join(problems))

    cut = COLUMNS.index("names_program_in")  # the read columns sit just before the automatic detail
    columns = COLUMNS[:cut] + READ_COLUMNS + COLUMNS[cut:]
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    with (out / "bills.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(bills)
    document = {
        "retrieved": max(b["retrieved"] for b in bills),
        "roles": [{"role": role, "label": label} for role, label in ROLES.items()],
        "kinds": KINDS,
        "bills": [
            {
                **{c: b[c] for c in columns},
                "kinds": [k for k in b["kinds"].split(";") if k],
                "names_program_in": b["names_program_in"].split(";"),
                "text_mentions": int(b["text_mentions"]) if b["text_mentions"] else None,
                "cosponsors": int(b["cosponsors"]) if b["cosponsors"] else None,
            }
            for b in bills
        ],
    }
    (out / "340b-bills.json").write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    places = {b["jurisdiction"] for b in bills}
    print(f"{len(bills)} bills in {len(places)} places ({sum(1 for b in bills if b['role'])} read); written to data/")


if __name__ == "__main__":
    main()
