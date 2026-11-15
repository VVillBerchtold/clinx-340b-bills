#!/bin/sh
# The whole refresh, in order. Run from the bills folder:  sh tools/refresh.sh
#
# In plain words: fetch what Congress, the state legislatures and the Federal Register say today,
# rebuild the three tables (bills, federal notices and calendar), and say what changed. It asks each site only for what it does not already
# hold in raw/, and it stops at the first step that fails, so a half-finished refresh is never
# mistaken for a finished one. Nothing here publishes anything: the tables are left in data/ for a
# person, or the hosted job, to look at and commit.
#
# The Open States key comes from the environment (OPENSTATES_KEY) on the hosted job, or from the
# private file on the machine of whoever runs it by hand. It is never printed.
set -eu
SINCE="2025-01-01"   # bills created, and federal notices published, since this day are looked for
BACK=30              # hearings from this many days back are asked for

mkdir -p raw/before raw/state-texts
cp data/bills.csv data/events.csv data/notices.csv raw/before/

# Which bill texts have been read, and what each said, is kept in this repository
# (state-texts-index.json). A machine that starts with an empty raw/ takes that record first, so
# it does not ask every legislature for every bill again.
if [ ! -f raw/state-texts/index.json ]; then cp state-texts-index.json raw/state-texts/index.json; fi

echo "== Congress"
sh tools/fetch_federal.sh
python3 -I tools/federal.py raw/govinfo federal-bills.csv

echo "== States: find, fetch new texts, build rows"
python3 -I tools/find_state.py raw/openstates "$SINCE"
python3 -I tools/fetch_state_texts.py raw/openstates raw/state-texts
cp raw/state-texts/index.json state-texts-index.json
python3 -I tools/state.py raw/openstates raw/state-texts state-bills.csv state-bills-not-listed.csv

echo "== One table"
python3 -I tools/build.py

echo "== Federal notices"
python3 -I tools/fetch_notices.py raw/notices "$SINCE"
python3 -I tools/notices.py raw/notices data

echo "== Calendar"
python3 -I tools/fetch_events.py raw/events "$BACK"
python3 -I tools/events.py raw/openstates raw/events raw/govinfo data

echo "== What changed"
python3 -I tools/changes.py raw/before raw/report.md
