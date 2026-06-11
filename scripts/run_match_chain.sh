set -e
cd /Users/jaydenl/Dev/AI/badminton
export PYTHONPATH=src
PY=.venv/bin/python
M=${1:-all_england_2022_sf}
START=${2:-10344}
END=${3:-145948}
log(){ echo "[$(date '+%H:%M:%S')] $1"; }

log "1/8 player tracks (yolo11x, ~3.5-4h)"
$PY scripts/parse_match.py --match $M --model yolo11x-pose.pt --start $START --end $END --resume
log "2/8 track validation + offset sweep"
$PY -m badminton.validate $M --search -10 10 1 || true
log "3/8 shuttle track (TrackNetV3, ~3h)"
$PY -m badminton.shuttle $M --window $START $END
log "4/8 label-free strokes (hits + BST)"
$PY -m badminton.pipeline $M --label-free --write
log "5/8 score OCR snapshot + 3-set validation"
$PY -m badminton.labelfree $M --build --validate
log "6/8 AI-annotated clips"
$PY scripts/render_web_clips.py --match $M
log "7/8 web export (all matches, full validation)"
$PY -m badminton.export_web
log "8/8 web build"
cd web && npm run build
log "CHAIN DONE"
