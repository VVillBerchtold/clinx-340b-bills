#!/bin/sh
# Fetches the official bulk files of one Congress from GovInfo (the Government Publishing Office):
# the status file of every bill, and the text of every version of every House and Senate bill.
# No key or account is needed. Run from the bills folder:  sh tools/fetch_federal.sh
set -eu
CONGRESS=119
OUT="raw/govinfo"
mkdir -p "$OUT"
for kind in hr s hjres sjres hconres sconres hres sres; do
  curl -sS --fail -o "$OUT/BILLSTATUS-$CONGRESS-$kind.zip" "https://www.govinfo.gov/bulkdata/BILLSTATUS/$CONGRESS/$kind/BILLSTATUS-$CONGRESS-$kind.zip"
  sleep 1
done
for session in 1 2; do
  for kind in hr s; do
    curl -sS --fail -o "$OUT/BILLS-$CONGRESS-$session-$kind.zip" "https://www.govinfo.gov/bulkdata/BILLS/$CONGRESS/$session/$kind/BILLS-$CONGRESS-$session-$kind.zip"
    sleep 1
  done
done
ls -l "$OUT"
