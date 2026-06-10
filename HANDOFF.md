# HANDOFF — Badminton CV Match Tracker & Analytics

Read this first. It's the single entry point for picking up this project. Deeper detail
lives in `docs/` and the inline docstrings; this file is the map + the hard-won gotchas.

---

## 1. What this is
An end-to-end system that turns badminton video into structured tactical data and a
coaching dashboard. It detects players (pose), maps them to real court metres via a
homography, validates that tracking against human-labeled ground truth (ShuttleSet), and
surfaces movement + tactics + pressure analytics, plus rally video clips (raw & annotated).

**Direction (locked):** controlled-capture eventually (any decent camera) · analytics
dashboard first → tactical commentary later · singles first → doubles later.

## 2. Current status (as of 2026-06-09)
- **Two matches fully wired end-to-end** (multi-match proven): the India Open 2022 final
  AND **denmark_open_2022_sf** (Lee Zii Jia def. Loh Kean Yew 21-18 21-15, Denmark Open
  2022 SF): 663 strokes imported, 93,375 track rows parsed (yolo11x@1280, 120 min),
  validated **median 0.643 m** (658/661 strokes; best frame offset −4, but the error
  curve is flat — the global +6 costs only ~2 cm, so no per-match offset plumbing yet).
- **Phase 0 (court + feet tracking): DONE & validated.** Median position error **0.566 m**
  vs ShuttleSet, match-wide (1,059/1,063 strokes). Lateral excellent; residual is mostly
  far-court depth + annotation noise. See `docs/PHASE0_RESULTS.md`.
- **Full match parsed:** the India Open 2022 final is fully parsed — **93,078 continuous
  track rows** across all 54 min, persisted in DuckDB. Every rally is instantly annotatable.
- **Phase 1 (analytics): substantially done.** Per-player & per-rally movement (distance,
  speed, coverage, recovery, court-zone time), shot-type tactics (winners/errors by shot),
  a **pressure** metric, rally-pattern analysis, and rally auto-clipping (raw + annotated).
- **Dashboard: redesigned coach-first (2026-06-09).** Six sidebar pages: 📖 Match story
  (score worm + auto **Coach's notes** whose "Watch" buttons deep-link into video),
  🎯 Points won & lost (weapons/leaks, rally-length win rates, serve/receive, clutch),
  🗺️ Court maps (shot placement + side-swap-corrected movement), 🧠 Patterns & pressure
  (ending sequences w/ watch buttons, forced/unforced errors, backhand vulnerability),
  🎞️ Film room (filterable rally clips + rally map + per-shot pressure), 🔬 Lab (the old
  CV diagnostics). Derived data lives in `src/badminton/insights.py` (pure pandas, no
  Streamlit). Multi-match ready.

## 3. Quick start
```bash
cd /Users/jaydenl/Dev/AI/badminton
# env already exists at .venv (Python 3.12, arm64, torch 2.12 + MPS, ultralytics, streamlit…)
PYTHONPATH=src .venv/bin/streamlit run app.py        # the dashboard
# modules run as:  PYTHONPATH=src .venv/bin/python -m badminton.<module>
```
The DuckDB database is `data/db/badminton.duckdb` (gitignored; it's the durable cache).
The match video is `data/raw/india_open_2022_final.mp4` (720p, 30fps, gitignored).

## 4. The validation match & key constants
- **Loh Kean Yew vs Lakshya Sen, India Open 2022 Final** (Lakshya won 24–22, 21–17).
  Chosen because it's labeled in **ShuttleSet22** AND a great Loh match. Video: official
  BWF upload `https://youtu.be/7_O5r9CLOVw`.
- **Coordinate frame:** origin at one outer court corner, X across 6.10 m width, Y along
  13.40 m length, net at Y=6.70 m, metres. (`src/badminton/court.py`)
- **Homography:** hand-calibrated from 4 outer corners (read off gridded crops; there is
  **no court-line detection**). Stored in `config/matches.yaml`. Corners px:
  nL(185,658) nR(1010,653) fR(858,277) fL(372,278).
- **Frame offset:** our video frame = ShuttleSet frame + 6 (validation uses offset −6/−7).
- **Foot/ground point:** `ankle_y + 0.65*(bbox_bottom_y − ankle_y)`, lateral x from ankles
  (`FOOT_BLEND=0.65` in `detect.py`) — minimizes the ankle-above-ground depth bias.
- **Detection config (validated):** yolo11x-pose @ imgsz 1280 on MPS, in-court margin 0.7.

## 5. Data model (two tiers, superset of ShuttleSet) — see `schema/schema.sql`, `docs/SCHEMA.md`
- `matches` — registry (players, homography, video, fps). Mirrors `config/matches.yaml`.
- `strokes` — **Tier 1**, one row per stroke. ShuttleSet import (`source='shuttleset'`,
  `coord_space='pixel'`) + our pipeline rows. Carries hitter/receiver feet, shuttle
  **hit** and **landing**, shot type (10 canonical EN, mapped from Chinese), outcomes.
- `tracks` — **Tier 2**, per-frame player court positions + 17 COCO keypoints + bbox.
- `shuttle` — per-frame shuttle (unused so far; Phase 2).
Everything is partitioned by `match_id`. The dashboard reads a **Match** from the sidebar.

## 6. Module map (`src/badminton/`)
| File | Role |
|---|---|
| `court.py` | coordinate frame, homography apply, `which_half`, `in_court` |
| `db.py` | DuckDB connect (`read_only` param), `init_db` from schema |
| `config.py` | load/save `config/matches.yaml` |
| `fetch_video.py` | yt-dlp download + frame grab |
| `calibrate_court.py` | interactive 4-corner picker (GUI) → homography |
| `shuttleset.py` | import ShuttleSet22 CSVs → `strokes` (CN→EN shot map) |
| `detect.py` | YOLO pose + ByteTrack → `tracks`; `process_video` (continuous, `--stride`), `process_frames` (sparse). `ground_point`/`FOOT_BLEND`. |
| `validate.py` | compare our tracks vs ShuttleSet labels → median error (m) |
| `analytics.py` | movement metrics: `player_metrics`, `summary`, `rallies`, `match_aggregate` |
| `tactics.py` | `shot_outcomes`, `pressure_*`, `pressure_by_shot`, `rally_patterns`, `rally_detail` |
| `insights.py` | coach-facing derived data: `stroke_df`/`rally_df` (court-metre + normalized coords, winner from score deltas), `side_map` (per-set near/far↔A/B), placement/serve/clutch/pattern/error-pressure stats, `movement_by_player` (side-swap aware), `coach_notes` (rule-based insight cards w/ supporting rally keys) |
| `commentary.py` | LLM tactical match report: `build_dossier` (~6 KB JSON from insights/tactics, real names), `generate` (Claude `claude-opus-4-8`, structured output via pydantic, adaptive thinking), cached at `data/commentary/<match_id>.json`. CLI: `python -m badminton.commentary <id> [--force\|--dossier-only]`. Needs `ANTHROPIC_API_KEY` or `ant auth login`. |
| `clip.py` | `list_rallies`, `clip_rally` (raw), `annotated_rally` (detect+render, skips detect if parsed), `reason_en` |
| `render_overlay.py` | annotated overlay video (boxes + minimap + SS labels) |
| `viz.py` | top-down court minimap (cv2) + `mpl_court` (matplotlib) |
| `scripts/parse_match.py` | chunked/resumable full-match parse |
| `app.py` | Streamlit dashboard (7 tabs) |

## 7. Key results (India Open 2022 final)
- Validation: **0.566 m** median (near 0.53, far 0.59), p90 1.06.
- Movement: Lakshya ran **~1,831 m**, Loh **~1,782 m** over ~912 s rally time.
  (Earlier "1,928 vs 1,685" figures were keyed by raw near/far and MIXED the players —
  see gotcha 7. The side-swap-corrected numbers come from `insights.movement_by_player`.)
- Tactics: smash wins most points (12); defensive shot (12) & lob (11) cause most errors.
  `lob → smash` is the top winning pattern; `smash → defensive shot` the top losing one.
- Pressure (required speed to reach a shot): Loh applied slightly more (2.42 vs 2.31 m/s)
  but lost on errors. A *defensive shot* makes the opponent cover the most ground (3.34).

## 8. CRITICAL GOTCHAS (these cost real time — don't relearn them)
1. **DuckDB concurrency:** one read-write (exclusive) OR many read-only (shared) across
   processes. Readers (dashboard, analytics, tactics, clip, render_overlay) MUST use
   `db.connect(read_only=True)`. Writers (`detect`) **defer** the DB open+write to the END
   so the lock is held seconds, not the whole run. **Same-process rule:** never mix
   read_only and read-write connections in one process → "different configuration" error.
2. **Streamlit testing:** `curl`/health checks do NOT execute the script body. Use
   `streamlit.testing.v1.AppTest.from_file('app.py').run()` then `assert not at.exception`.
3. **Streamlit magic:** never write a bare ternary `st.x(...) if c else st.y(...)` as a
   statement — magic-display tries to AST-parse it and can crash. Use `if/else`.
4. **Module reload:** `app.py` runs `importlib.reload` on the `badminton` submodules each
   rerun, because Streamlit only hot-reloads the main script, not imports. Without it,
   edits to `analytics.py` etc. are silently ignored → stale-attribute crashes.
5. **Background jobs:** do NOT put `&` inside a `run_in_background` command — it orphans the
   real work and the harness falsely reports "completed". Let the tool background it.
6. **ShuttleSet coords are pixels** (no homography shipped); shot types are **Chinese**
   (mapped in `shuttleset.py`/`tactics.py`); `player` A/B where **A = match winner**
   (we keep A/B on import; near/far comes from the homography). The importer stores
   roundscore_A/B in the `roundscore_near/far` columns — they're the score AFTER the rally.
7. **Players swap court ends between sets.** Track rows are keyed `near`/`far`, so any
   match-wide aggregation by raw near/far MIXES the two players. Always go through
   `insights.side_map()` ((set_no, 'A'|'B') -> side) / `insights.movement_by_player()`.
   (A deciding-set mid-game end change at 11 is not yet modeled.)
8. **Streamlit widget-key writes:** you cannot set `st.session_state[key]` for a widget
   already instantiated this run. The dashboard's insight→Film-room deep links stage the
   jump in `nav_jump` and apply it at the TOP of the next run, before the nav radio exists.

## 9. Add a new match (multi-match is supported; done twice now)
1. Find the match folder in ShuttleSet22 (`CoachAI-Projects/CoachAI-Challenge-IJCAI2023/
   ShuttleSet22/set/` on GitHub; original 2018–21 ShuttleSet is at `ShuttleSet/set/`).
   `match.csv` there gives winner/loser/date/sets (dir name = winner first). Download the
   `set*.csv` into `data/shuttleset/<match_id>/`.
2. Add an entry to `config/matches.yaml` — players list = [loser, winner] so that
   players[1] = ShuttleSet 'A' (the app's NAME mapping relies on this).
3. `python -m badminton.shuttleset <match_id>` — import labels; sanity-check that A wins
   the final scores.
4. Video: find the official BWF TV YouTube upload (ShuttleSet `time`/`frame_num` are
   consistent with it at 30 fps — first stroke time ≈ frame/30). **Download 720p**
   (`-f "bv*[height=720][ext=mp4]"`) — label pixels assume the 1280×720 frame. Avoid
   matches whose ShuttleSet dir ends in `_Trim` (frame numbers won't match full uploads).
5. Homography: ShuttleSet22 DOES ship `set/homography.csv` (matrix → their ~49.2 px/m viz
   canvas + 4 corner picks) — use the corners only as a STARTING GUESS; they were ±10–70 px
   off on both matches checked. Read true outer-corner px off gridded zoom crops (no GUI
   needed), build H with `cv2.getPerspectiveTransform`, save via `config.update_match`,
   then verify by projecting `viz._segments()` onto frames from BOTH sets (also catches
   camera moves).
6. `python scripts/parse_match.py --match <match_id> --model yolo11x-pose.pt --start <first
   labeled frame> --end <last+128> --resume` (~100 ms/frame on MPS), then
   `python -m badminton.validate <match_id> --search -10 10 1` to pin the frame offset.
It then appears in the dashboard's Match selector automatically (uncalibrated matches get
a friendly setup notice instead of a crash).

## 10. Suggested next steps
- **Tactical commentary layer: BUILT (2026-06-10), needs first generation.** `commentary.py`
  + the 🎙️ Commentary dashboard page are wired end-to-end; no Anthropic credentials were
  configured on this machine, so no report has actually been generated yet. Run
  `ant auth login` (CLI installed) or export `ANTHROPIC_API_KEY`, then
  `PYTHONPATH=src python -m badminton.commentary india_open_2022_final` and review the
  output quality (tune `SYSTEM` / dossier contents if it's generic or hallucinatory).
- **Phase 2 shuttle tracking** (TrackNetV3 → MonoTrack) for landing points / shot classes
  from video rather than relying on ShuttleSet labels.
- **Far-court accuracy / robustness**: small-target pose is the weak spot (see PHASE0_RESULTS).

## 11. Pointers
- Plan/architecture: `docs/DESIGN.md` · Schema: `docs/SCHEMA.md` · Datasets: `docs/DATASETS.md`
- Phase 0 results: `docs/PHASE0_RESULTS.md` · This repo's README has run/usage details.
