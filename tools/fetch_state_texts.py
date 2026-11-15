"""Fetch each state bill's official text and check that it names the 340B program.

In plain words: Open States finds bills, but a bill is listed only when its own text, on the
legislature's own site, names the program. For every bill found, this tool fetches the newest
version of the text from the legislature's site (a web page where there is one, else a PDF), turns
it into plain words, counts how often it names the program and keeps the first passage that does.
If the newest version does not name it, up to three earlier versions are tried. What it fetched,
and what it found, is written to raw/state-texts/index.json; a bill already checked is not fetched
again.

It is polite: one request at a time, a pause between requests to the same site, and if a site
refuses (for example with a 403), the tool stops asking that site and says so. It never tries
another way in.

Run it:  python3 -I tools/fetch_state_texts.py raw/openstates raw/state-texts
Add --again to fetch every bill again (a bill already checked is otherwise left alone).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

# The program by name ("340B", "340b") or by its section of federal law ("42 U.S.C. 256b", "U.S.C. § 256b").
NAMES_PROGRAM = re.compile(r"(?<![0-9A-Za-z])340\s?-?[Bb](?![0-9A-Za-z])|U\.?\s?S\.?\s?C\.?\s?(?:§+\s?|[Ss]ec(?:tion|\.)\s?)?256b(?![0-9A-Za-z])")
TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
SPACE = re.compile(r"\s+")
WEB = {"text/html", "text/xml"}
PAUSE = 2.5
AGENT = "clinx-340b-bills (public data project)"


def web_address(url: str) -> str:
    """Return a link as a web address. Some legislatures put spaces in their links; they are written %20."""
    return urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")


def bill_id(bill: dict) -> str:
    """Return the row's stable name, for example ri-2025-sb114."""
    state = bill["jurisdiction"]["id"].split("state:")[1][:2]
    squash = lambda words: re.sub(r"[^a-z0-9]+", "", words.lower())  # noqa: E731
    return f"{state}-{squash(bill['session'])}-{squash(bill['identifier'])}"


def mentions_of(text: str) -> list[re.Match]:
    """Return each place the text names the program.

    One thing that looks like the program and is not: a state's own chapter 340B in a run of chapter
    numbers ("chapters 339D, 340A, 340B, 340E"). A 340B with a number and comma on both sides is left out.
    """
    found = []
    for match in NAMES_PROGRAM.finditer(text):
        in_a_run = re.search(r"\d[A-Z]?,\s$", text[max(0, match.start() - 8):match.start()]) and re.match(r",\s*(?:and\s+)?\d", text[match.end():match.end() + 8])
        if not in_a_run:
            found.append(match)
    return found


def quote_of(text: str) -> str:
    """Return the passage around the first place the text names the program, cut at word ends."""
    found = next(iter(mentions_of(text)), None)
    if not found:
        return ""
    start, end = max(0, found.start() - 170), min(len(text), found.end() + 170)
    passage = text[start:end]
    if start > 0:
        passage = "… " + passage.split(" ", 1)[-1]
    if end < len(text):
        passage = passage.rsplit(" ", 1)[0] + " …"
    return passage


def decode(data: bytes) -> str:
    """Return a page's characters. Some legislatures still publish in the older Windows alphabet."""
    declared = re.search(rb"charset=[\"']?([\w-]+)", data[:4000])
    for name in ([declared.group(1).decode("ascii")] if declared else []) + ["utf-8", "cp1252"]:
        try:
            return data.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("cp1252", "replace").replace("\ufffd", " ")


# A web page that prints each line's number in a cell of its own (Illinois, Kansas).
NUMBER_CELL = re.compile(r"<(td|span|div)[^>]*class=\"[^\"]*(?:\bnumber\b|linenum)[^\"]*\"[^>]*>\s*\d{1,3}\s*</\1>", re.I)
LINE_NUMBER = re.compile(r"[ \t\f]*(\d{1,3})(?=[ \t]|$)")


def without_line_numbers(text: str) -> str:
    """Return the text without the line numbers a bill prints down its margin.

    A number at the start of a line is taken for a line number only when it carries on the count
    from the line number before it (the same number again, or up to three more), or starts the
    count again at 1 or 2 and the next numbered line carries on from there. It is done only in a
    text where that happens at least ten times. A number the bill itself begins a line with, such
    as "30 days" or a page's "1 of 15", is left alone.
    """
    lines = text.split("\n")
    found = [(at, LINE_NUMBER.match(line)) for at, line in enumerate(lines)]
    starts = [(at, int(match.group(1)), match.end()) for at, match in found if match]
    numbered: list[tuple[int, int]] = []  # (which line, how many characters the number takes)
    last = None
    for i, (at, number, length) in enumerate(starts):
        carries_on = last is not None and last <= number <= last + 3
        after = starts[i + 1][1] if i + 1 < len(starts) else None
        starts_again = number <= 2 and after is not None and number <= after <= number + 3
        if carries_on or starts_again:
            numbered.append((at, length))
            last = number
    if len(numbered) < 10:
        return text
    for at, length in numbered:
        lines[at] = lines[at][length:]
    return "\n".join(lines)


def words_of(data: bytes, kind: str, scratch: Path) -> str:
    """Return the plain words of a fetched page or PDF, on one line."""
    if data[:5] == b"%PDF-":
        scratch.write_bytes(data)
        done = subprocess.run(["pdftotext", "-layout", str(scratch), "-"], capture_output=True, check=False)
        scratch.unlink()
        text = done.stdout.decode("utf-8", "replace")
    else:
        text = html.unescape(TAGS.sub(" ", NUMBER_CELL.sub(" ", decode(data))))
    return SPACE.sub(" ", without_line_numbers(text)).strip()


# Where a legislature's page prints other things above the bill (a menu, a summary), the bill starts
# where the second phrase follows the first.
TEXT_STARTS = {"assembly.state.ny.us": (" Text: ", "STATE OF NEW YORK ")}


def bill_text(url: str, words: str) -> str:
    """Return the words of the bill itself, without what its page prints above it."""
    before, start = TEXT_STARTS.get(urllib.parse.urlparse(url).netloc, ("", ""))
    at = words.find(before + start) if start else -1
    return words[at + len(before):] if at >= 0 else words


# Links the finder files under a bill's versions that lead to something other than the bill's text
# (Michigan: a committee's page of records).
NOT_A_TEXT = ("legislature.mi.gov/Committees/",)


# The finder seldom dates a bill's versions, so the newest is told from what each version is called.
# Higher is later in a bill's life. A name no rule knows ranks just above an amendment.
VERSION_RANKS = [
    (0.0, r"amendment|proposal of amend|summary|fiscal|analysis|statement|vote|preamended|^pa\d|veto|comparison|transmittal|excerpt|minority report"),
    (4.5, r"slip law|session law|^sl \d|^act \d|public act|acts? chapter|^chapter \d|chaptered|signed act|as enacted"),
    (4.0, r"enrol|enact|ratified|truly agreed|passed leg|passed by both|final|current version|_cd\d|_x\b"),
    (3.6, r"rerevised"),
    (3.5, r"revised"),
    (3.2, r"reengrossed"),
    (3.0, r"engross|as passed|perfected|reprint|third reading|as amended|amended"),
    (2.0, r"substitute|^sub\b|committee|reported|pending|edition|floor|_[hs]d\d|\bc\d\b|printer"),
    (1.0, r"introduc|filed|prefil|original|^bill$|^bill text$"),
]
# States whose lists of versions run from the newest to the oldest.
NEWEST_LISTED_FIRST = {"KS", "OR", "KY", "CO", "SC"}


def version_rank(note: str, state: str, number: str = "") -> float:
    """Say how late in a bill's life a version is, from its name."""
    name = " ".join(note.lower().split())
    rank = next((value for value, words in VERSION_RANKS if re.search(words, name)), 0.5)
    if rank == 2.0 and re.match(r"senate|house", name) and number[:1].upper() in "HS" and name[0] != number[:1].lower():
        rank = 3.5  # the other chamber's substitute comes after the first chamber has passed the bill
    if state == "UT" and "committee report" in name:
        rank = 0.0  # in Utah a committee report is a one-page letter, not a text of the bill
    number = re.search(r"(\d+)(?:st|nd|rd|th)? (?:engrossment|substitute)|(?:edition|reprint|engrossment) (\d+)|_(\d+)(?:\(\d+\))?\.pdf$|pn ?(\d+)", name)
    if number and rank:
        rank += min(int(next(g for g in number.groups() if g)), 9999) / 100000
    if state == "HI":
        # Hawaii: HB712, then its House drafts (HD1, HD2), then the Senate's (SD1, SD2), then the conference draft (CD1).
        draft = re.search(r"^([hs])b\d+(?:_([hsc])d(\d))?$", name)
        if draft:
            rank = 1.0 if not draft.group(2) else 4.0 if draft.group(2) == "c" else (2.0 if draft.group(2) == draft.group(1) else 2.5) + int(draft.group(3)) / 10
    if state == "NY":
        letter = re.search(r"^[asr]\d+([a-z])?$", name)  # A1234, then its amended prints A1234A, A1234B
        if letter:
            rank = 1.0 + (ord(letter.group(1)) - 96) / 100 if letter.group(1) else 1.0
    if re.match(r"\d\d/\d\d/\d{4}", name):
        rank = 1.5  # South Carolina names a later print by its day
    if "unofficial" in name:
        rank -= 0.01
    return rank


def links_of(bill: dict) -> list[tuple[str, str, str]]:
    """Return (version name, date, link) to try, newest version first, a web page before a PDF."""
    state = bill["jurisdiction"]["id"].split("state:")[1][:2].upper() if "state:" in bill["jurisdiction"]["id"] else ""
    turn = -1 if state in NEWEST_LISTED_FIRST else 1
    ranked = sorted(
        enumerate(bill["versions"]),
        key=lambda pair: (version_rank(pair[1].get("note") or "", state, bill.get("identifier") or ""), pair[1].get("date") or "", turn * pair[0]),
        reverse=True,
    )
    out = []
    for _, version in ranked:
        links = [link for link in version["links"] if link.get("media_type") in WEB] + [link for link in version["links"] if link.get("media_type") == "application/pdf"]
        links = [link for link in links if not any(part in link["url"] for part in NOT_A_TEXT)]
        if links:
            out.append((version.get("note") or "", (version.get("date") or "")[:10], links[0]["url"]))
    return out[:5]


def main() -> None:
    found_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    again = "--again" in sys.argv[3:]  # fetch every bill again, for example after a change to how a page is read
    out.mkdir(parents=True, exist_ok=True)
    index_file = out / "index.json"
    index: dict[str, dict] = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
    bills: dict[str, dict] = {}
    for page in sorted(found_dir.glob("phrase*-page*.json")):
        for bill in json.loads(page.read_text(encoding="utf-8"))["results"]:
            if bill["jurisdiction"]["classification"] == "state":
                bills[bill_id(bill)] = bill
    if "--reread" in sys.argv[3:]:
        # Read every saved page again without fetching it, for example after a change to how a page is read.
        changed = 0
        for name in sorted(index):
            source = out / f"{name}.src"
            if index[name]["result"] not in ("named", "not named") or not source.exists():
                continue
            text = bill_text(index[name]["url"], words_of(source.read_bytes(), "", out / "scratch.pdf"))
            mentions = len(mentions_of(text))
            before = (out / f"{name}.txt").read_text(encoding="utf-8")
            changed += before != text + "\n"
            (out / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
            index[name].update({"result": "named" if mentions else "not named", "mentions": mentions, "quote": quote_of(text)})
        index_file.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{changed} saved texts read differently")
        return
    last: dict[str, float] = {}
    refused: dict[str, str] = {}
    for name in sorted(bills):
        saved = out / f"{name}.txt"
        garbled = saved.exists() and "\ufffd" in saved.read_text(encoding="utf-8")  # read in the wrong alphabet: fetch again
        if name in index and index[name]["result"] in ("named", "not named", "site refused") and not garbled and not again:
            continue
        tried = []
        entry: dict = {"result": "no text to read", "tried": tried}
        for note, day, url in links_of(bills[name]):
            host = urllib.parse.urlparse(url).netloc
            if host in refused:
                entry = {"result": "site refused", "tried": tried, "why": refused[host]}
                break
            wait = PAUSE - (time.time() - last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            last[host] = time.time()
            address = web_address(url)
            # curl uses this Mac's own list of trusted certificates, which Python's does not always match.
            got = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", "60", "-A", AGENT, "-o", str(out / "scratch.bin"), "-w", "%{http_code}", address],
                capture_output=True, text=True, check=False,
            )
            code = int(got.stdout.strip() or 0) if got.stdout.strip().isdigit() else 0
            if code in (401, 403, 429):
                tried.append({"url": url, "answer": code})
                refused[host] = f"answered {code}"
                entry = {"result": "site refused", "tried": tried, "why": refused[host]}
                break
            if got.returncode != 0 or code != 200:
                tried.append({"url": url, "answer": code or got.stderr.strip()[:80]})
                entry = {"result": "could not fetch", "tried": tried}
                continue
            data = (out / "scratch.bin").read_bytes()
            (out / "scratch.bin").unlink()
            text = bill_text(url, words_of(data, "", out / "scratch.pdf"))
            mentions = len(mentions_of(text))
            tried.append({"url": url, "answer": 200, "words": len(text.split()), "mentions": mentions})
            if len(text.split()) < 40:
                entry = {"result": "text could not be read", "tried": tried}
                continue
            (out / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
            (out / f"{name}.src").write_bytes(data)  # the page or PDF as it came, so it can be read again without fetching
            entry = {
                "result": "named" if mentions else "not named",
                "version": note,
                "date": day,
                "url": url,
                "mentions": mentions,
                "quote": quote_of(text),
                "sha256": hashlib.sha256(data).hexdigest(),
                "newest": len(tried) == 1,
                "tried": tried,
            }
            if mentions:
                break
        if name in index and index[name]["result"] in ("named", "not named") and entry["result"] not in ("named", "not named"):
            print(f"{name}: {entry['result']} this time; the earlier reading is kept", flush=True)
            continue
        index[name] = entry
        index_file.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{name}: {entry['result']}", flush=True)
    for host, why in refused.items():
        print(f"STOPPED asking {host}: it {why}")
    print(f"{len(index)} bills checked")


if __name__ == "__main__":
    main()
