# 340B bills and calendar

Every bill in Congress and in the state legislatures that names the federal 340B drug pricing
program, and a calendar of what has happened to each one. The tables are free to download and
build on. They are shown, state by state, at [clinx.org/bills](https://clinx.org/bills/) and
[clinx.org/calendar](https://clinx.org/calendar/).

## What it is

One table of bills (`data/bills.csv`, and the same rows in `data/340b-bills.json`): what each
bill is called, who introduced it, how far it has got, its latest step, a plain sentence on what
it does about 340B, and a link to the legislature's own page.

One table of dates (`data/events.csv`, and `data/340b-events.json`): the dated steps of every
listed bill, hearings that name one, and the days each session starts and ends.

Both are built from official sources: the Government Publishing Office's files for Congress, each
state legislature's record as gathered by Open States, and the bill texts on the legislatures' own
sites. For now the tables are refreshed by hand; the day each was last brought up to date is in
its `retrieved` column.

It sits beside the laws table, and the two join up: when a state bill becomes law, it is read by
hand, added to the laws table, and the bill's row links to the law.

## The rules

1. **Official sources only.** A bill's row links to the legislature's own page for that bill. A
   finder may be used to discover bills (Open States for the states), but nothing is copied from a
   paid tracker, and no value is shown that the official record does not hold.
2. **A bill is listed only if its title, official summary or text names the program**: "340B", or
   its section of federal law, "42 U.S.C. 256b". The automatic test is narrow on purpose: "section
   340(b)" of some other act does not count.
3. **Nothing is guessed.** The stage of a bill comes from the official record of its steps. A
   value the record does not hold is left blank.
4. **Where the program is named is said plainly**: in the title, in the summary, in the text, or
   only in an earlier version of the text. A bill about 340B and a large bill that mentions it
   once are both listed, and a reader can tell them apart.
5. **Kinds are assigned by reading**, with the same seven kinds as the laws table. A new bill
   appears the day it is found, with its official title and status; its kinds and one plain
   sentence about what it would do are added once it has been read. What a person adds is kept
   apart from what the record holds, in `read/`.
6. **A site that refuses is left alone.** The tools ask each legislature's site slowly, one page
   at a time. If a site answers that it does not allow this, the tools stop asking it and do not
   look for a way round. Its bills are then listed only where the title or summary names the
   program.

## The columns

| Column | What it holds |
|---|---|
| `bill_id` | A stable name for the row, for example `us-119-hr5256` |
| `jurisdiction` | `US` for Congress, or the state's two letters |
| `session` | The Congress or legislative session |
| `session_end` | The day that session ends or ended. A bill that has not become law by then goes no further |
| `bill` | The bill's number as the legislature writes it, for example `H.R. 5256` |
| `title` | Its short title, as printed |
| `official_title` | Its long title, as printed |
| `role` | Added by reading: `main` (the bill is about 340B), `part` (it has a part on 340B) or `mention` (it names 340B in passing). Blank until the bill has been read |
| `kinds` | Added by reading: the kinds of provision, from the laws table's seven |
| `summary` | Added by reading: one plain sentence on what the bill would do |
| `names_program_in` | Where it names 340B: `title`, `summary`, `text`, or `earlier text` |
| `text_mentions` | How many times the newest text names the program |
| `quote` | The first passage of the text that names the program |
| `introduced_date` | The day it was introduced |
| `sponsor` | Who introduced it, as printed |
| `cosponsors` | How many cosponsors |
| `committees` | The committees it was sent to |
| `stage` | How far it has got (see below) |
| `stage_date` | The day it reached that stage |
| `failed_vote` | A vote on passage that failed, if there was one |
| `latest_action_date`, `latest_action` | Its latest step, in the official wording |
| `law` | The law it became, if it did |
| `same_as` | An identical bill in the other chamber |
| `bill_url` | The legislature's own page for the bill |
| `text_version`, `text_date`, `text_url` | The newest text read, and where it is |
| `status_updated` | When the official record last changed |
| `retrieved` | The day the files were fetched |

Stages, in order: Introduced, Reported by committee, Passed the House / Passed the Senate, Passed
both chambers, Sent to the President (or Governor), Vetoed, Became law.

## What works today

Every tool is run from this folder. `raw/` holds what was fetched and is not part of the table.

**Congress.** `tools/fetch_federal.sh` fetches the official bulk files from GovInfo (the
Government Publishing Office; no key needed): a status file for every bill and the text of every
version. `tools/federal.py` reads them and writes `federal-bills.csv`.

On 15 November 2026 it read 19,962 bills of the 119th Congress and listed 42 that name the
program. Two of the 42 became law. All 42 have been read (`read/federal.csv`).

    sh tools/fetch_federal.sh
    python3 -I tools/federal.py raw/govinfo federal-bills.csv

**The states.** Three steps.

1. `tools/find_state.py` asks Open States for bills whose text holds the phrase "340B", filed since
   1 January 2025. Open States is only the finder. It needs a free key, which is kept in a private
   file outside this folder and is never written here.
2. `tools/fetch_state_texts.py` then fetches each bill's newest text from the legislature's own
   site and checks that the text names the program. It keeps the page as it came (`.src`) and its
   plain words (`.txt`). Run it again at any time: it skips what is settled. `--again` fetches
   everything afresh; `--reread` reads the kept pages again without fetching.
3. `tools/state.py` writes `state-bills.csv`, and `state-bills-not-listed.csv` for the bills that
   were found but are not listed, each with the reason.

On 15 November 2026 the finder returned 236 state bills; 220 are listed, in 43 states.

**Which version is read.** A legislature links several papers for one bill: the bill as
introduced, substitutes, engrossed and enrolled copies, the act or chapter it became, and
side papers such as amendments, summaries and fiscal notes. The reader ranks them by name
(`VERSION_RANKS` in `tools/fetch_state_texts.py`): the law as passed first, then enrolled,
engrossed, substitute and introduced copies, with side papers last. It reads the newest one
that it can open. Where only an older paper, or an amendment, names 340B and the newest text
does not, the table says `earlier text` and names the paper that was read.

**Things that are not bills.** `not-bills.csv` lists what the finder returns that is not a
bill, such as a committee report filed under a bill number, with the reason. They are left out.

    python3 -I tools/find_state.py raw/openstates 2025-01-01
    python3 -I tools/fetch_state_texts.py raw/openstates raw/state-texts
    python3 -I tools/state.py raw/openstates raw/state-texts state-bills.csv state-bills-not-listed.csv

**Read by hand.** `read/federal.csv` and `read/state.csv` hold, for each bill that has been
read, its role (`main`, `part` or `mention`), its kinds and one plain sentence on what it does
about 340B. Each state bill was read from the passages that name 340B in the version the table
names, and a second reader checked every row against the same passages. A law is written in the
present tense and a bill as what it would do. A row drawn from an amendment says so.

**One table.** `tools/build.py` joins Congress, the states and what has been read into
`data/bills.csv` and `data/340b-bills.json`, and stops if a date, a link or a session's end is not
in the expected form.

    python3 -I tools/build.py

## The calendar

`tools/events.py` writes `data/events.csv`, and the same rows in `data/340b-events.json`, one
row per dated event:

- **Steps.** Every dated step in the official record of a listed bill that is one of:
  introduced, sent to committee, reported by committee, failed in committee, vote on passage,
  sent for signature, signed, vetoed, became law. The words are the legislature's own. For
  Congress the steps are the ones the Library of Congress marks with a code.
- **Hearings.** `tools/fetch_events.py` saves each state's list of hearings from Open States.
  A hearing is kept only where its agenda names a listed bill. In November 2026, with most
  legislatures out of session, none does yet.
- **Session days.** The day each legislature's session starts and ends, from Open States' list
  of sessions, and the day this Congress ends.

The columns are `event_id`, `day`, `time`, `jurisdiction`, `kind`, `bill_id`, `bill`, `what`,
`body`, `where`, `link`, `source` and `retrieved`. The JSON file also says in plain words what
each kind means. Nothing is guessed: a step with no date is left out. A date can move, so the
link on every row goes to the legislature's own page.

    python3 -I tools/fetch_events.py raw/events 30
    python3 -I tools/events.py raw/openstates raw/events raw/govinfo data

## How a bill's text is read

A legislature's page is made for people, not for programs, so a few plain rules turn it into words:

- **Line numbers** printed down the margin are dropped, so a passage reads as prose. A number is
  taken for a line number only when it carries on the count from the line before. A number the
  bill itself starts a line with, such as "30 days", stays.
- **The page's alphabet** is the one the page declares. Some older pages are not in today's usual
  one; reading them the wrong way would break a section sign or a dash.
- **Other things on the page**, such as a menu or a summary above the bill, are cut where the page
  is known to carry them (New York).
- **"340B" as some other number** does not count. Hawaii has a chapter 340B of its own statutes;
  a bill that only lists it among chapter numbers is not listed.
- **Massachusetts filing dockets** (HD and SD numbers) are left out where the same bill is listed
  under its bill number.

## What the table does not hold yet

- For state bills: the committees, the law a bill became, and the identical bill in the other
  chamber. These are blank.
- For state bills: the stage and the session's end come from Open States' reading of the official
  record of steps. The latest step is in the legislature's own words.
- Five state bills have not been read, so they carry no role, kinds or plain sentence: their
  text could not be opened (California's site, a page drawn by a script) or does not show
  enough to say what the bill does about 340B.
- Hearings in Congress are not on the calendar yet.
- California's site does not allow the text check, so its bill is listed from its title and
  summary only.
- Hawaii carries a bill over from one year to the next, so such a bill appears under both.
- A few passages keep what the page prints between lines, such as a page footer.

## What is not built yet

- **The daily refresh.**
- **Hearings in Congress**, and a hearing list refreshed each day once sessions start.

## Licence

The code in `tools/` is under the [MIT licence](LICENSE). The tables in `data/` and `read/`, and
the working tables beside them, are under [Creative Commons Attribution 4.0](LICENSE-DATA). Bill
titles, the legislatures' own wording of each step and the passages quoted from bill texts are
public records; no rights in them are claimed.
