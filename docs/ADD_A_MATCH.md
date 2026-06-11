# Runbook — add a match (inject data)

Two paths into the system:

- **Path B (label-free)** — any BWF broadcast video. The CV chain produces everything;
  ShuttleSet is not involved. This is the normal path.
- **Path A (labeled)** — the match exists in ShuttleSet22. Import the human labels too,
  which unlocks the GROUND TRUTH dashboard source and per-stage validation.

All commands run from the repo root. Prefix: `PYTHONPATH=src .venv/bin/python`
(abbreviated `py` below). Stages persist to DuckDB (`data/db/badminton.duckdb`) keyed by
`match_id` — each runs **once**, everything downstream just reads.

## 0. One-time setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # torch/MPS, ultralytics, duckdb…
brew install ffmpeg                                                      # clip cutting / encoding
# shuttle tracker (vendored) + checkpoints (~200 MB):
git clone https://github.com/qaz812345/TrackNetV3 third_party/TrackNetV3
.venv/bin/gdown 1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA && unzip -d third_party/TrackNetV3/ckpts ckpts.zip
# BST shot classifier weights → third_party/BST/bst_weights/bst_0_JnB_bone_merged.pt (see HANDOFF §6)
```

YOLO pose weights auto-download on first use. Scoreboard digit templates ship in the repo
(`data/scoreboard_digits.npz`) and transfer across BWF tournaments.

## 1. Register + fetch video (~5 min)

1. Add an entry to `config/matches.yaml`: `match_id`, `tournament`, `round`, `fps: 30.0`,
   `video_url` (official BWF YouTube upload), and `players` as **[loser, winner]** —
   `players[1]` is displayed as player A (the winner) everywhere.
2. Download at **720p** (the pixel pipeline assumes 1280×720):
   ```bash
   py -m badminton.fetch_video <match_id>        # → data/raw/<match_id>.mp4
   ```

## 2. Calibrate the court homography (~15 min, manual)

Read the 4 **outer** court-corner pixels off gridded zoom crops of a few frames (or use
the GUI `py -m badminton.calibrate_court <match_id>`), save via `config.update_match`.
Verify by projecting the court model onto frames **from different sets** (catches camera
moves). Details + gotchas: `HANDOFF.md` §9.5.

## 3. Player tracks (~100 ms/frame on MPS; a 1 h match ≈ 3 h, resumable)

```bash
py scripts/parse_match.py --match <match_id> --model yolo11x-pose.pt \
    --start <first play frame> --end <last play frame> --resume
```

(`--start/--end` bound the broadcast's match portion — pre/post-show footage just wastes
GPU hours. Eyeball them with `py -m badminton.fetch_video <match_id> --frame-at HH:MM:SS`.)

## 4. Shuttle track (~12 fps on MPS; a 1 h match ≈ 2.5 h)

```bash
py -m badminton.shuttle <match_id>
```

## 5. Label-free stroke table (≈ 10 min)

Detected rallies + hits + hitters + landings + BST shot classes → `strokes` rows
(`source='pipeline'`):

```bash
py -m badminton.pipeline <match_id> --label-free --write
```

## 6. Score OCR snapshot (≈ 5 min: scans the broadcast for the score overlay)

Scores after every rally, per-rally winners, set boundaries, per-set side map →
`data/labelfree/<match_id>.json`:

```bash
py -m badminton.labelfree <match_id> --build
```

## 7. AI-annotated clips + web export (≈ 10 min)

```bash
py scripts/render_web_clips.py --match <match_id>   # 540p overlay clip per rally → web/public/clips
py -m badminton.export_web                          # all matches → web/public/data
cd web && npm run build                             # rebuild the static site
```

The match now appears on the web app home page with the **AI VISION** source.

## Path A extras — the match is in ShuttleSet22

Run these **before** step 5 (they also sharpen it: labeled matches get validation):

```bash
# CSVs from CoachAI-Projects/CoachAI-Challenge-IJCAI2023 → data/shuttleset/<match_id>/
py -m badminton.shuttleset <match_id>                  # import labels (source='shuttleset')
py -m badminton.validate <match_id> --search -10 10 1  # pin the per-match frame offset
py -m badminton.labelfree <match_id> --build --validate  # scores OCR vs labels
```

`export_web` then emits **both** dashboard sources (GROUND TRUTH + AI VISION) and the
AI Lab agreement panel automatically.

## Refresh cycle (data already parsed)

Changed analytics/export code only? Skip the slow validation reruns — previously computed
values are preserved:

```bash
py -m badminton.export_web --skip-slow && cd web && npm run build
```

## Known constraints

- Deciding-set (3rd game) mid-game end change at 11 is not yet modeled in the side map.
- Set finals read from the overlay can miss the last point(s) — broadcasts cut to
  celebration before the graphic updates. Displayed as read, by design.
- Avoid ShuttleSet folders ending in `_Trim` (frame numbers won't match full uploads).
