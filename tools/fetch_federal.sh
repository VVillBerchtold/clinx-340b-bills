#!/bin/sh
# Fetches the official bulk files of one Congress from GovInfo (the Government Publishing Office):
# the status file of every bill, and the text of every version of every House and Senate bill.
# No key or account is needed. Run from the bills folder:  sh tools/fetch_federal.sh
set -eu
CONGRESS=119
OUT="raw/govinfo"
# The name this tool gives when it asks for a file.
AGENT="ClinX Open Data Reader (+https://clinx.org/methods/)"
mkdir -p "$OUT"
# One file: fetched to a side name and moved into place only when it arrived whole. A file already
# held is asked for only if the official copy is newer, so a quiet day downloads almost nothing.
fetch() {
  if [ -f "$OUT/$1" ]; then
    curl -sS --fail -R -A "$AGENT" -z "$OUT/$1" -o "$OUT/$1.part" "$2"
  else
    curl -sS --fail -R -A "$AGENT" -o "$OUT/$1.part" "$2"
  fi
  if [ -s "$OUT/$1.part" ]; then mv "$OUT/$1.part" "$OUT/$1"; echo "fetched $1"; else rm -f "$OUT/$1.part"; echo "unchanged $1"; fi
}
for kind in hr s hjres sjres hconres sconres hres sres; do
  fetch "BILLSTATUS-$CONGRESS-$kind.zip" "https://www.govinfo.gov/bulkdata/BILLSTATUS/$CONGRESS/$kind/BILLSTATUS-$CONGRESS-$kind.zip"
  sleep 1
done
for session in 1 2; do
  for kind in hr s; do
    fetch "BILLS-$CONGRESS-$session-$kind.zip" "https://www.govinfo.gov/bulkdata/BILLS/$CONGRESS/$session/$kind/BILLS-$CONGRESS-$session-$kind.zip"
    sleep 1
  done
done
ls -l "$OUT"
