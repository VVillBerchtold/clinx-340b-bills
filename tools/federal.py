"""Federal bills that name the 340B program, built from the official bulk files of Congress.

In plain words: the Government Publishing Office publishes, free and without a key, one status file
for every bill in Congress and the text of every version of every bill. This tool reads those files
for one Congress, keeps each bill whose title, official summary or text names the 340B program (or
cites its section of federal law, 42 U.S.C. 256b), and writes one row per bill: what it is called,
who introduced it, how far it has got, its latest step in the official wording, and where the
official page and text are. Nothing is typed by hand and nothing is estimated: a value the files do
not hold is left blank.

Run it:  python3 -I tools/federal.py raw/govinfo federal-bills.csv

The files it reads are fetched by tools/fetch_federal.sh into raw/govinfo/.
"""

from __future__ import annotations

import csv
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

CONGRESS = 119
# A Congress ends at noon on 3 January of the odd year (Twentieth Amendment); its unpassed bills end with it.
CONGRESS_ENDS = "2027-01-03"

# The program by name ("340B") or by its section of federal law ("42 U.S.C. 256b"). Narrower than the
# laws table's test, which Claude checks by reading: "section 340(b)" of another act, or "section 5340(b)",
# is not the program, so a bare "340(b)" does not count here.
NAMES_PROGRAM = re.compile(r"(?<![0-9A-Za-z])340\s?B(?![0-9A-Za-z])|U\.\s?S\.\s?C\.\s?256b(?![0-9A-Za-z])")
TAGS = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
TEXT_FILE = re.compile(rf"BILLS-{CONGRESS}([a-z]+?)(\d+)([a-z][a-z0-9]*)\.xml$")

# How Congress writes each kind of measure, and the word for it in the address of its official page.
LABELS = {
    "HR": "H.R.",
    "S": "S.",
    "HJRES": "H.J.Res.",
    "SJRES": "S.J.Res.",
    "HCONRES": "H.Con.Res.",
    "SCONRES": "S.Con.Res.",
    "HRES": "H.Res.",
    "SRES": "S.Res.",
}
PAGE_WORDS = {
    "HR": "house-bill",
    "S": "senate-bill",
    "HJRES": "house-joint-resolution",
    "SJRES": "senate-joint-resolution",
    "HCONRES": "house-concurrent-resolution",
    "SCONRES": "senate-concurrent-resolution",
    "HRES": "house-resolution",
    "SRES": "senate-resolution",
}

# The Library of Congress marks each main step of a bill with a code. These are the codes found in
# the files of this Congress, in the order a bill meets them. A code not listed here moves no stage.
STEPS = {
    "1000": "introduced",
    "10000": "introduced",
    "1025": "introduced",
    "10025": "introduced",
    "5000": "reported",
    "1010": "reported",
    "14000": "reported",
    "8000": "passed-house",
    "17000": "passed-senate",
    "9000": "failed-house",
    "18000": "failed-senate",
    "28000": "to-president",
    "31000": "vetoed",
    "36000": "law",
    "41000": "law",
}
RANK = ["introduced", "reported", "passed-one", "passed-both", "to-president", "vetoed", "law"]
STAGE_WORDS = {
    "introduced": "Introduced",
    "reported": "Reported by committee",
    "passed-house": "Passed the House",
    "passed-senate": "Passed the Senate",
    "passed-both": "Passed both chambers",
    "to-president": "Sent to the President",
    "vetoed": "Vetoed",
    "law": "Became law",
}

COLUMNS = [
    "bill_id",
    "jurisdiction",
    "session",
    "session_end",
    "bill",
    "title",
    "official_title",
    "names_program_in",
    "text_mentions",
    "quote",
    "introduced_date",
    "sponsor",
    "cosponsors",
    "committees",
    "stage",
    "stage_date",
    "failed_vote",
    "latest_action_date",
    "latest_action",
    "law",
    "same_as",
    "bill_url",
    "text_version",
    "text_date",
    "text_url",
    "status_updated",
    "retrieved",
]

Key = tuple[str, int]


def plain(xml: str) -> str:
    """Return the words of an XML or HTML fragment on one line."""
    return SPACE.sub(" ", TAGS.sub(" ", xml)).strip()


def quote_of(text: str) -> str:
    """Return the passage around the first place the text names the program, cut at word ends."""
    found = NAMES_PROGRAM.search(text)
    if not found:
        return ""
    start = max(0, found.start() - 170)
    end = min(len(text), found.end() + 170)
    passage = text[start:end]
    if start > 0:
        passage = "… " + passage.split(" ", 1)[-1]
    if end < len(text):
        passage = passage.rsplit(" ", 1)[0] + " …"
    return passage


def read_texts(raw: Path) -> dict[Key, dict[str, tuple[int, str]]]:
    """Return, for every bill: version code -> (times the text names the program, the first passage)."""
    out: dict[Key, dict[str, tuple[int, str]]] = {}
    for archive in sorted(raw.glob(f"BILLS-{CONGRESS}-*.zip")):
        with zipfile.ZipFile(archive) as files:
            for name in files.namelist():
                if not name.endswith(".xml"):
                    continue
                parts = TEXT_FILE.search(name)
                if not parts:
                    raise SystemExit(f"A text file with a name this tool cannot read: {name}")
                xml = files.read(name).decode("utf-8")
                # The words of the bill itself, not the catalogue block at the head of the file.
                body = plain(xml.split("</metadata>", 1)[-1])
                key = (parts.group(1).upper(), int(parts.group(2)))
                out.setdefault(key, {})[parts.group(3)] = (len(NAMES_PROGRAM.findall(body)), quote_of(body))
    return out


def read_statuses(raw: Path) -> dict[Key, ET.Element]:
    """Return the status record of every bill of this Congress."""
    out: dict[Key, ET.Element] = {}
    for archive in sorted(raw.glob(f"BILLSTATUS-{CONGRESS}-*.zip")):
        with zipfile.ZipFile(archive) as files:
            for name in files.namelist():
                if not name.endswith(".xml"):
                    continue
                bill = ET.fromstring(files.read(name)).find("bill")
                if bill is None:
                    raise SystemExit(f"{name}: no bill inside")
                out[(need(bill, "type"), int(need(bill, "number")))] = bill
    return out


def need(node: ET.Element, path: str) -> str:
    """Return a value the file must hold."""
    value = node.findtext(path)
    if not value:
        raise SystemExit(f"A status file is missing {path}")
    return value.strip()


def stage_of(bill: ET.Element) -> tuple[str, str, str]:
    """Return (stage, the day it was reached, a failed vote if any), from the Library of Congress codes."""
    reached: dict[str, str] = {}
    failed = ""
    for action in bill.iterfind("actions/item"):
        if action.findtext("sourceSystem/name") != "Library of Congress":
            continue
        step = STEPS.get(action.findtext("actionCode") or "")
        day = action.findtext("actionDate") or ""
        if step is None:
            continue
        if step.startswith("failed"):
            failed = f"{day} {plain(action.findtext('text') or '')}"
            continue
        if step not in reached or day < reached[step]:
            reached[step] = day
    house, senate = reached.get("passed-house"), reached.get("passed-senate")
    if house and senate:
        reached["passed-both"] = max(house, senate)
    if house or senate:
        reached["passed-one"] = min(d for d in (house, senate) if d)
    best = max((s for s in reached if s in RANK), key=RANK.index, default="")
    if best == "":
        return "", "", failed
    if best == "passed-one":
        return STAGE_WORDS["passed-house" if house else "passed-senate"], reached[best], failed
    return STAGE_WORDS[best], reached[best], failed


def row_of(key: Key, bill: ET.Element, texts: dict[str, tuple[int, str]], today: str) -> dict[str, str]:
    """Return one bill's row."""
    kind, number = key
    titles = [bill.findtext("title") or ""] + [t.findtext("title") or "" for t in bill.iterfind("titles/item")]
    official = next((t.findtext("title") or "" for t in bill.iterfind("titles/item") if (t.findtext("titleType") or "").startswith("Official Title")), "")
    summaries = [plain(s.findtext("text") or "") for s in bill.iterfind("summaries/summary")]
    where = []
    if any(NAMES_PROGRAM.search(t) for t in titles):
        where.append("title")
    if any(NAMES_PROGRAM.search(s) for s in summaries):
        where.append("summary")

    # The newest text of the bill that is in the files, and whether that text names the program.
    # (The text of a public law is published in another collection, so for an enacted bill the
    # newest text read here is the enrolled bill: the text both chambers passed.)
    # The enrolled bill carries no date in the status file and is always the last text, so it goes first.
    versions = sorted(bill.iterfind("textVersions/item"), key=lambda v: (v.findtext("type") == "Enrolled Bill", v.findtext("date") or ""), reverse=True)
    text_version = text_date = text_url = ""
    mentions, quote = 0, ""
    for version in versions:
        url = next((f.findtext("url") or "" for f in version.iterfind("formats/item") if (f.findtext("url") or "").endswith(".xml")), "")
        code = TEXT_FILE.search(url)
        if not code or code.group(3) not in texts:
            continue
        found = texts[code.group(3)]
        if text_version == "":
            text_version, text_date, text_url = version.findtext("type") or "", (version.findtext("date") or "")[:10], url.replace(".xml", ".htm").replace("/xml/", "/html/")
            mentions, quote = found
            if mentions:
                where.append("text")
                break
        elif found[0]:
            # The newest text does not name the program, an earlier one does: quote the earlier one and say so.
            quote = found[1]
            where.append("earlier text")
            break
    if quote == "":
        quote = next((quote_of(t) for t in titles + summaries if NAMES_PROGRAM.search(t)), "")

    page = f"https://www.congress.gov/bill/{CONGRESS}th-congress/{PAGE_WORDS[kind]}/{number}"
    if (bill.findtext("legislationUrl") or page) != page:
        raise SystemExit(f"{kind} {number}: the official page is not at the address this tool expects")
    sponsor = bill.find("sponsors/item")
    stage, stage_date, failed = stage_of(bill)
    same = [f"{LABELS[need(r, 'type')]} {need(r, 'number')}" for r in bill.iterfind("relatedBills/item") if any((d.findtext("type") or "") == "Identical bill" for d in r.iterfind("relationshipDetails/item"))]
    return {
        "bill_id": f"us-{CONGRESS}-{kind.lower()}{number}",
        "jurisdiction": "US",
        "session": f"{CONGRESS}th Congress",
        "session_end": CONGRESS_ENDS,
        "bill": f"{LABELS[kind]} {number}",
        "title": need(bill, "title"),
        "official_title": official,
        "names_program_in": ";".join(where),
        "text_mentions": str(mentions) if text_version else "",
        "quote": quote,
        "introduced_date": need(bill, "introducedDate"),
        "sponsor": (sponsor.findtext("fullName") or "") if sponsor is not None else "",
        "cosponsors": str(len(bill.findall("cosponsors/item"))),
        "committees": "; ".join(f"{c.findtext('chamber')} {c.findtext('name')}" for c in bill.iterfind("committees/item")),
        "stage": stage,
        "stage_date": stage_date,
        "failed_vote": failed,
        "latest_action_date": bill.findtext("latestAction/actionDate") or "",
        "latest_action": plain(bill.findtext("latestAction/text") or ""),
        "law": "; ".join(f"{law.findtext('type')} {law.findtext('number')}" for law in bill.iterfind("laws/item")),
        "same_as": "; ".join(sorted(set(same))),
        "bill_url": page,
        "text_version": text_version,
        "text_date": text_date,
        "text_url": text_url,
        "status_updated": (bill.findtext("updateDateIncludingText") or "")[:10],
        "retrieved": today,
    }


def main() -> None:
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    texts = read_texts(raw)
    statuses = read_statuses(raw)
    keys = {key for key, versions in texts.items() if any(count for count, _ in versions.values())}
    for key, bill in statuses.items():
        words = [bill.findtext("title") or ""] + [t.findtext("title") or "" for t in bill.iterfind("titles/item")]
        words += [plain(s.findtext("text") or "") for s in bill.iterfind("summaries/summary")]
        if any(NAMES_PROGRAM.search(w) for w in words):
            keys.add(key)
    missing = sorted(k for k in keys if k not in statuses)
    if missing:
        raise SystemExit(f"Texts with no status file: {missing}")
    today = date.today().isoformat()
    order = list(LABELS)
    rows = [row_of(k, statuses[k], texts.get(k, {}), today) for k in sorted(keys, key=lambda k: (order.index(k[0]), k[1]))]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(statuses)} bills read; {len(rows)} name the program; written to {out}")


if __name__ == "__main__":
    main()
