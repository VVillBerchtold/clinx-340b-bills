"""Say what a refresh changed, list what needs reading, and stop a refresh that looks broken.

    python3 -I tools/changes.py raw/before raw/report.md

In plain words: before a refresh starts, the published tables are copied to `raw/before/`.
After it, this tool compares the new tables with those copies and writes a short report: bills
that are new, bills that moved to another stage, bills with a newer text, new federal notices, and
new dates on the calendar. It also writes `needs-reading.csv`, the list of what a person still has
to read: a bill nobody has read, a bill whose text is newer than the one that was read, a bill
that became law after it was read (so its sentence is in the wrong tense), and a federal notice
nobody has read. A notice is listed there under its own name (fr-...), with FED as its place.

It stops with an error, and nothing is published, when the new tables look broken: far fewer
bills, notices or dates than before, or a place that had bills and now has none. A legislature
does not lose its bills overnight; a fetch that failed does.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import READ_FILES  # noqa: E402

ROOT = Path(__file__).parent.parent
MOST_LOST = 0.05  # a refresh may list up to this share fewer bills, or dates, than the day before


def rows_of(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def needs_reading(bills: list[dict[str, str]], notices: list[dict[str, str]]) -> list[dict[str, str]]:
    """The bills and federal notices a person still has to read, each with the reason."""
    read: dict[str, dict[str, str]] = {}
    for path in (ROOT / "read" / name for name in READ_FILES):
        read.update({row["bill_id"]: row for row in rows_of(path)})
    todo = []
    for bill in bills:
        note = read.get(bill["bill_id"])
        if note is None:
            why = "not read yet"
        elif note.get("text_read") and bill["text_url"] and note["text_read"] != bill["text_url"]:
            why = "a newer text has been posted since it was read"
        elif note.get("stage_read") and bill["stage"] == "Became law" and note["stage_read"] != "Became law":
            why = "became law since it was read"
        else:
            continue
        todo.append({"bill_id": bill["bill_id"], "jurisdiction": bill["jurisdiction"], "bill": bill["bill"], "why": why, "stage": bill["stage"], "text_version": bill["text_version"], "text_url": bill["text_url"]})
    for notice in notices:
        if not notice["role"]:
            todo.append({"bill_id": notice["notice_id"], "jurisdiction": "FED", "bill": notice["citation"], "why": "not read yet", "stage": notice["type"], "text_version": "", "text_url": notice["notice_url"]})
    return todo


def main() -> None:
    before_dir, report = Path(sys.argv[1]), Path(sys.argv[2])
    old = {row["bill_id"]: row for row in rows_of(before_dir / "bills.csv")}
    bills = rows_of(ROOT / "data" / "bills.csv")
    new = {row["bill_id"]: row for row in bills}
    old_events = {row["event_id"]: row for row in rows_of(before_dir / "events.csv")}
    events = rows_of(ROOT / "data" / "events.csv")
    old_notices = {row["notice_id"]: row for row in rows_of(before_dir / "notices.csv")}
    notices = rows_of(ROOT / "data" / "notices.csv")
    today = bills[0]["retrieved"] if bills else ""

    # The guard: a refresh that lost a lot is a failed fetch, not news.
    problems = []
    if old and len(new) < len(old) * (1 - MOST_LOST):
        problems.append(f"{len(new)} bills listed, {len(old)} the day before")
    if old_events and len(events) < len(old_events) * (1 - MOST_LOST):
        problems.append(f"{len(events)} dates on the calendar, {len(old_events)} the day before")
    if old_notices and len(notices) < len(old_notices) * (1 - MOST_LOST):
        problems.append(f"{len(notices)} federal notices listed, {len(old_notices)} the day before")
    gone_places = sorted({row["jurisdiction"] for row in old.values()} - {row["jurisdiction"] for row in bills})
    if gone_places:
        problems.append("no bills any more in: " + ", ".join(gone_places))
    if problems:
        raise SystemExit("The refresh looks broken; nothing should be published:\n  " + "\n  ".join(problems))

    added = [new[name] for name in sorted(set(new) - set(old))]
    gone = [old[name] for name in sorted(set(old) - set(new))]
    moved = [(old[name], new[name]) for name in sorted(set(new) & set(old)) if old[name]["stage"] != new[name]["stage"]]
    retexted = [(old[name], new[name]) for name in sorted(set(new) & set(old)) if old[name]["text_url"] != new[name]["text_url"]]
    new_events = [row for row in events if row["event_id"] not in old_events]
    lost_events = [row for name, row in sorted(old_events.items()) if name not in {e["event_id"] for e in events}]
    new_notices = [row for row in notices if row["notice_id"] not in old_notices]
    todo = needs_reading(bills, notices)

    with (ROOT / "needs-reading.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bill_id", "jurisdiction", "bill", "why", "stage", "text_version", "text_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(todo)

    def label(bill: dict[str, str]) -> str:
        return f"{bill['jurisdiction']} {bill['bill']} ({bill['bill_id']}): {bill['title'][:90]}"

    lines = [f"# Refresh of {today}", ""]
    quiet = not (added or gone or moved or retexted or new_notices or new_events or lost_events)
    lines.append(f"{len(new)} bills listed ({len(old)} before). {len(notices)} federal notices ({len(old_notices)} before). {len(events)} dates on the calendar ({len(old_events)} before)." + (" Nothing changed." if quiet else ""))
    for title, items in (
        ("New bills", [f"{label(b)} {b['bill_url']}" for b in added]),
        ("No longer listed", [label(b) for b in gone]),
        ("Moved to another stage", [f"{label(b)}: {a['stage']} -> {b['stage']}" for a, b in moved]),
        ("A newer text", [f"{label(b)}: {a['text_version'] or 'none'} -> {b['text_version'] or 'none'}" for a, b in retexted]),
        ("New federal notices", [f"{n['published']} {n['citation']} ({n['notice_id']}): {n['title'][:90]} {n['notice_url']}" for n in new_notices]),
        ("New dates", [f"{e['day']} {e['jurisdiction']} {e['kind']}: {e['bill']} {e['what'][:90]}".rstrip() for e in new_events]),
        ("Dates no longer on the calendar", [f"{e['day']} {e['jurisdiction']} {e['kind']}: {e['bill']} {e['what'][:90]}".rstrip() for e in lost_events]),
        ("To read", [f"{t['jurisdiction']} {t['bill']} ({t['bill_id']}): {t['why']}" for t in todo]),
    ):
        if items:
            lines += ["", f"## {title} ({len(items)})", ""] + [f"- {item}" for item in items[:60]]
            if len(items) > 60:
                lines.append(f"- and {len(items) - 60} more")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = f"{len(added)} new bills, {len(moved)} moved on, {len(retexted)} with a newer text, {len(new_notices)} new federal notices, {len(new_events)} new dates, {len(todo)} to read"
    (report.parent / "report-line.txt").write_text(("no changes" if quiet else summary) + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
