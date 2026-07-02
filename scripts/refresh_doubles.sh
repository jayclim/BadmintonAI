#!/bin/bash
# Refresh the whole doubles surface for a match, in dependency order. RESUMABLE:
# every step is idempotent — segmentation/score OCR are disk-cached (data/cache/),
# the clip renderer skips clips that already exist — so if a run is interrupted,
# just re-run this script and it continues where it stopped. Progress prints live.
#
#   scripts/refresh_doubles.sh [match_id]
set -e
cd "$(dirname "$0")/.."
ID=${1:-wtf_2024_md_sf}
PY="./.venv/bin/python"

echo "== [1/5] strokes (contacts -> strokes table; rally ids follow segmentation) =="
PYTHONPATH=src $PY -m badminton.doubles.strokes "$ID" --write

echo "== [2/5] annotated rally clips (skips existing; safe to interrupt) =="
PYTHONPATH=src $PY scripts/render_doubles_clips.py --match "$ID"

echo "== [3/5] web export (doubles.json + dreplay; OCR disk-cached) =="
PYTHONPATH=src $PY -m badminton.doubles.export_web "$ID"

echo "== [4/5] AI commentary (skipped if no LLM key in .env) =="
PYTHONPATH=src $PY -m badminton.doubles.commentary "$ID" --force || echo "  (skipped)"

echo "== [5/5] web build =="
cd web && npm run build

echo "DONE — $ID refreshed"
