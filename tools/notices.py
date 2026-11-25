"""Build the notices table: federal rules, proposed rules and notices that name the 340B program.

    python3 -I tools/notices.py raw/notices data

In plain words: `fetch_notices.py` saved the Federal Register's list of documents whose text holds
"340B" or "256b", and each document's text. This tool turns that into one table, one row per
document: the official facts as the Federal Register gives them (title, agency, the day it was
published, the day comments close, the day it takes effect, the official words about dates), where
the document names the program, and a short passage from the first place it does.

Three files Claude keeps after reading are joined in:

- `read/notices.csv`: for each document Claude has read, whether it is about 340B, has a part on
  it or only mentions it, and one plain sentence on what it does about 340B.
- `read/notice-dates.csv`: other days a document itself sets (a deadline, a start day), each with
  the document's own words for it.
- `not-notices.csv`: documents the search returns that are not about the drug program at all
  ("340B" is also an aircraft and part of other numbers), each with the reason.

"340B" alone does not list a document: its text must also hold one of the phrases that go with the
drug program (PROGRAM below). What is left out is written, with the reason, to
`notices-not-listed.csv`. A document nobody has read yet is still listed, with its role and
sentence left blank.

The facts read from each text (how often it names the program, the passage) are kept in
`notices-index.json`, so a machine that starts without the texts does not fetch them all again.
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import ROLES, rows_of  # noqa: E402
from federal import NAMES_PROGRAM, quote_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = [
    "notice_id", "document_number", "citation", "type", "action", "agencies", "title", "role", "summary",
    "names_program_in", "text_mentions", "quote", "published", "comments_close", "effective", "dates",
    "docket", "pages", "notice_url", "pdf_url", "retrieved",
]
# The Federal Register's four kinds of document.
TYPES = ["Rule", "Proposed Rule", "Notice", "Presidential Document"]
# Phrases that go with the drug program. A document needs one of them, besides "340B", to be listed.
PROGRAM = re.compile(
    r"340B (?:Drug Pricing |Rebate Model Pilot |Prescription Drug )?Program"
    r"|340B[- ](?:covered entit|ceiling price|acquired|eligible|related|drug|claim|patient|provider|modifier|unit|price|discount|remedy|repository)"
    r"|section 340B\(|section 340B of the (?:Public Health Service|PHS) Act"
    r"|U\.\s?S\.\s?C\.\s?256b(?![0-9A-Za-z])",
    re.IGNORECASE,
)
# The web wrapper's tags, and the page markers the Federal Register puts in the middle of sentences.
TAGS = re.compile(r"<[^>]+>|\[\[Page \d+\]\]")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def words_of(saved: Path) -> str:
    """A saved text without its thin web wrapper, as one line of words."""
    return " ".join(html.unescape(TAGS.sub(" ", saved.read_text(encoding="utf-8", errors="replace"))).split())


def squash(words: str) -> str:
    """Letters and digits only, so that a quote is found whatever the line breaks and punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", words.lower()).strip()


def main() -> None:
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    today = date.today().isoformat()
    found: dict[str, dict] = {}
    for page in sorted(raw.glob("list*-page*.json")):
        for document in json.loads(page.read_text(encoding="utf-8"))["results"]:
            found.setdefault(document["document_number"], document)
    if not found:
        raise SystemExit(f"no saved list in {raw}: run fetch_notices.py first")

    index_file = ROOT / "notices-index.json"
    index: dict[str, dict] = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
    read = {row["notice_id"]: row for row in rows_of(ROOT / "read" / "notices.csv")}
    left_out = {row["notice_id"]: row["reason"] for row in rows_of(ROOT / "not-notices.csv")}
    dates_read: dict[str, list[dict[str, str]]] = {}
    for row in rows_of(ROOT / "read" / "notice-dates.csv"):
        dates_read.setdefault(row["notice_id"], []).append(row)

    problems: list[str] = []
    notices: list[dict] = []
    not_listed: list[dict[str, str]] = []
    for number, document in sorted(found.items(), key=lambda item: (item[1]["publication_date"], item[0]), reverse=True):
        name = f"fr-{number}"
        title = " ".join((document.get("title") or "").split())
        abstract = " ".join((document.get("abstract") or "").split())
        saved = raw / f"{number}.txt"
        text = words_of(saved) if saved.exists() and saved.stat().st_size > 0 else ""
        if text:
            index[number] = {
                "mentions": len(NAMES_PROGRAM.findall(text)),
                "program": bool(PROGRAM.search(" ".join((title, abstract, text)))),
                "in_text": bool(NAMES_PROGRAM.search(text)),
                "quote": quote_of(text),
            }
        facts = index.get(number)
        if facts is None:
            problems.append(f"{name}: no text held and no record of one: run fetch_notices.py")
            continue
        address = document.get("html_url") or ""
        if name in left_out or (not facts["program"] and name not in read):
            if name in read:
                problems.append(f"{name}: read, and also in not-notices.csv")
            reason = left_out.get(name) or "names 340B, but with none of the phrases that go with the drug program"
            not_listed.append({"notice_id": name, "published": document["publication_date"], "title": title, "reason": reason, "notice_url": address})
            continue
        note = read.get(name, {})
        places = [place for place, there in (("title", NAMES_PROGRAM.search(title)), ("summary", NAMES_PROGRAM.search(abstract)), ("text", facts["in_text"])) if there]
        agencies = [" ".join((a.get("name") or a.get("raw_name") or "").split()) for a in document.get("agencies") or []]
        notice = {
            "notice_id": name,
            "document_number": number,
            "citation": document.get("citation") or "",
            "type": document.get("type") or "",
            "action": " ".join((document.get("action") or "").split()),
            "agencies": [a for a in agencies if a],
            "title": title,
            "role": note.get("role", ""),
            "summary": note.get("summary", ""),
            "names_program_in": places,
            "text_mentions": facts["mentions"],
            "quote": facts["quote"],
            "published": document.get("publication_date") or "",
            "comments_close": document.get("comments_close_on") or "",
            "effective": document.get("effective_on") or "",
            "dates": "" if (document.get("dates") or "None") == "None" else " ".join(document["dates"].split()),
            "docket": ";".join(document.get("docket_ids") or []),
            "pages": document.get("page_length") or "",
            "notice_url": address,
            "pdf_url": document.get("pdf_url") or "",
            "retrieved": today,
            "dates_read": [{"day": row["day"], "what": row["what"], "words": row["words"]} for row in sorted(dates_read.get(name, []), key=lambda row: row["day"])],
        }
        if notice["type"] not in TYPES:
            problems.append(f"{name}: unknown type {notice['type']}")
        if notice["role"] and notice["role"] not in ROLES:
            problems.append(f"{name}: unknown role {notice['role']}")
        if notice["role"] and not notice["summary"]:
            problems.append(f"{name}: read, but no sentence")
        if not places:
            problems.append(f"{name}: listed, but nothing says where it names the program")
        for column in ("published", "comments_close", "effective"):
            if notice[column] and not DAY.fullmatch(notice[column]):
                problems.append(f"{name}: {column} is not a date written year-month-day")
        if not notice["published"]:
            problems.append(f"{name}: no day of publication")
        for column in ("notice_url", "pdf_url"):
            if notice[column] and (not notice[column].startswith("https://") or " " in notice[column]):
                problems.append(f"{name}: {column} is not a web address")
        if not notice["notice_url"]:
            problems.append(f"{name}: no official page")
        for row in notice["dates_read"]:
            if not DAY.fullmatch(row["day"]) or not row["what"] or not row["words"]:
                problems.append(f"{name}: a date in read/notice-dates.csv needs a day, what happens and the document's words")
            elif text and squash(row["words"]) not in squash(text):
                problems.append(f"{name}: the words given for {row['day']} are not in the document")
        notices.append(notice)

    listed = {notice["notice_id"] for notice in notices}
    for name in read:
        if name not in listed and name not in left_out:
            problems.append(f"read/notices.csv has {name}, which is not in the Federal Register's list")
    for name in dates_read:
        if name not in listed:
            problems.append(f"read/notice-dates.csv has {name}, which is not a listed document")
    if problems:
        raise SystemExit("Not written:\n  " + "\n  ".join(problems))

    out.mkdir(parents=True, exist_ok=True)
    with (out / "notices.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for notice in notices:
            writer.writerow({column: notice[column] for column in COLUMNS} | {"agencies": "; ".join(notice["agencies"]), "names_program_in": ";".join(notice["names_program_in"])})
    document = {
        "retrieved": today,
        "source": "The Federal Register's own data service, federalregister.gov/api/v1",
        "roles": [{"role": role, "label": label} for role, label in ROLES.items()],
        "types": TYPES,
        "notices": notices,
    }
    (out / "340b-notices.json").write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with (ROOT / "notices-not-listed.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["notice_id", "published", "title", "reason", "notice_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(not_listed)
    index_file.write_text(json.dumps({number: index[number] for number in sorted(index) if number in found}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(found)} documents found; {len(notices)} listed ({sum(1 for n in notices if n['role'])} read); {len(not_listed)} not listed")


if __name__ == "__main__":
    main()
