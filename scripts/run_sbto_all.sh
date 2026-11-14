#!/usr/bin/env bash
# The three reference runs, one after another (15-19 min each on 10 cores). Results: out/sbto_*/report.json
#   bash scripts/run_sbto_all.sh              # native
#   ./wq sim bash scripts/run_sbto_all.sh     # in the container
#   WORKERS=16 bash scripts/run_sbto_all.sh   # more cores
set -u
cd "$(dirname "$0")/.."
PY="${PY:-python}"; W="${WORKERS:-10}"; mkdir -p out
for spec in "k265 fixed" "furelise plan" "k265 human"; do
  set -- $spec
  "$PY" scripts/sbto_piano.py --piece "$1" --wrist "$2" --out "out/sbto_${1}_$2" --workers "$W" > "out/log_sbto_${1}_$2.txt" 2>&1
  echo "$1 $2 exit $?"
done
