"""Put the federal and state bills into one table, with what a person has read about each.

In plain words: tools/federal.py and tools/state.py each write the automatic part of the table
(what the official record says). The files in read/ hold the part a person adds after reading a
bill: whether the bill is about 340B or only mentions it, its kinds, and one plain sentence on
what it would do. This tool joins them, checks the result, and writes the two files people
download: data/bills.csv and data/340b-bills.json.

A bill nobody has read yet is still listed, with those three columns left blank.

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
    "Became law",
]


def rows_of(path: Path) -> list[dict[str, str]]:
    """Return a CSV file's rows; an absent file has none."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    bills = rows_of(ROOT / "federal-bills.csv") + rows_of(ROOT / "state-bills.csv")
    read: dict[str, dict[str, str]] = {}
    for path in sorted((ROOT / "read").glob("*.csv")):
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
