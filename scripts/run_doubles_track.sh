#!/usr/bin/env bash
# Durable chunked driver for the full-match doubles 4-player track.
# Each chunk is a separate process that writes its rows at the end (process_video
# DELETEs [start,start+span) then INSERTs), so progress persists incrementally and a
# crash only loses the in-flight chunk — resume by re-running with START = last chunk.
#
#   scripts/run_doubles_track.sh [match_id] [start_frame] [end_frame] [chunk]
set -e
cd /Users/jaydenl/Dev/AI/badminton
export PYTHONPATH=src
PY=.venv/bin/python
M=${1:-wtf_2024_md_sf}
START=${2:-0}
END=${3:-166650}
CHUNK=${4:-20000}
log(){ echo "[$(date '+%H:%M:%S')] $1"; }

log "FULL doubles track: $M frames $START..$END (chunk $CHUNK)"
f=$START
while [ "$f" -lt "$END" ]; do
  n=$CHUNK
  if [ $((f + n)) -gt "$END" ]; then n=$((END - f)); fi
  log "chunk: frames $f .. $((f + n))"
  $PY -m badminton.doubles.track "$M" --start-frame "$f" --max-frames "$n"
  f=$((f + n))
done
log "FULL TRACK DONE ($START..$END)"
