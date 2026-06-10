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
| `commentary.py` | LLM tactical match report: `build_dossier` (~6 KB JSON from insights/tactics, real names) → provider-pluggable `generate` (gemini = REST + JSON mode, claude = `messages.parse` structured output; both pydantic-validated) → cached at `data/commentary/<id>.<provider>.json`. Keys in repo-root `.env` (gitignored): `GEMINI_API_KEY` (default provider, free tier; `GEMINI_MODEL` overrides gemini-2.5-flash) / `ANTHROPIC_API_KEY`. CLI: `python -m badminton.commentary <id> [--provider g\|c] [--force\|--dossier-only]`. |
| `clip.py` | `list_rallies`, `clip_rally` (raw), `annotated_rally` (detect+render, skips detect if parsed), `reason_en` |
| `render_overlay.py` | annotated overlay video (boxes + minimap + SS labels) |
| `viz.py` | top-down court minimap (cv2) + `mpl_court` (matplotlib) |
| `shuttle.py` | Phase 2: TrackNetV3 shuttle tracking → `shuttle` table. Runs the vendored `third_party/TrackNetV3` predict.py unmodified via runpy with `.cuda()`→MPS + `torch.load`→CPU monkeypatches. `--window F0 F1` = frame-accurate cv2 cut of the match video; full-match mode uses `--large_video`. ~12–18 fps on MPS. Setup: `git clone qaz812345/TrackNetV3 third_party/TrackNetV3` + `gdown 1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA` → unzip to its `ckpts/`. |
| `hits.py` | Phase 2: hit detection + landing points from the shuttle track. Hits = union of two per-frame signals over ±4-frame velocities — \|Δv\| ≥ 30 px/f (accelerations; a smash off a descending lob has NO 2D direction turn, this was the key insight) and (1−cosθ)·speed ≥ 20 (reversals, slow net play) — plus a raw-series gap-boundary pass (blur hides contact) and a motion-onset serve detector (serves have v_in≈0, can't kink). **India Open: P 89.2% / R 86.7% / F1 87.9 (tol ±6), attribution 90.0%** (nearest wrist from `tracks` keypoints — NOTE tracks & shuttle share the video timeline, no offset between them). Landing = lowest screen point of the continuous post-hit track (gap-chained, jump-gated) → homography: **median 0.548 m, p90 2.34 m (n=52)** vs labeled landings. Thresholds tuned on India Open — Denmark is a clean held-out test. |
| `bst_eval.py` | Phase 2: **pretrained BST-0** (CVPRW'26 SOTA, `third_party/BST` + `bst_weights/bst_0_JnB_bone_merged.pt`) evaluated on OUR CV inputs (YOLO pose bbox-normalized their way + TrackNetV3 shuttle/(1280,720), ±15-frame window at contact, m-order [far=Top, near=Bottom]): **71.8% shot class (10 EN), 98.2% side, 69.6% end-to-end** with zero fine-tuning — ≈ its published accuracy on its own preprocessing, and +15 pts over geometry-on-CV (56.6%). BST-0 takes (JnB, shuttle, video_len) — no court pos. Next: swap into `pipeline.py` at DETECTED hit frames (this eval centers on label frames); deps: positional-encodings, torchinfo. |
| `pipeline.py` | Phase 2: **label-free Tier-1 writer** — detected hits + tracked positions + landings + geometry classes → `strokes` `source='pipeline'` rows (1,001 written for India Open vs 1,071 labels). End-to-end vs labels: **85.1% coverage, 90.0% hitter, 56.6% shot type on matched** (label-feature ceiling: 85.6%). Key conventions: landing(i) = NEXT hitter's tracked feet (floor-plane-valid; the mid-air shuttle projects metres deep — that bug cost 50 points), classifier trains on the OTHER match with `feet_landing=True`, implausible features (missed-next-hit) gated to NaN. Gap to ceiling = hit-frame jitter + ball_round drift + attribution errors → learned hit detector / BST. Rally windows + side map still come from labels (rally segmenter = future work). |
| `shotclass.py` | Phase 2: geometry-only shot classifier (sklearn HistGB, NaN-native). CV-deployable features (normalized positions, landing, dt, derived speed/deltas): **87.8% / 84.0% cross-match, 87.2% pooled 5-fold** on the 10 canonical classes. Labeled contact-height adds only ~1 pt. Weak classes: drive, push/rush (pose needed — BST's job). |
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
9. **The +6 frame offset is NOT right for the shuttle.** Phase 0's `+6` was fit on player
   feet, whose error curve is flat over ±10 frames. The shuttle moves 20+ px/frame and
   pins the true contact sharply — AND it's **per match**: the offset-sweep minimum is
   −1 for india_open (median 115.5 px, 99.8% detected, 980 strokes) but **−3 for
   denmark_open** (85.2 px, 586 strokes). Stored as `ss_shuttle_offset` in
   `config/matches.yaml`; always go through `hits.shuttle_offset(match_id)`. Keep +6
   for the (insensitive) player tracks. The ~115 px residual is the same scale as ShuttleSet's
   once-per-stroke click noise (~100 px ≈ Phase 0's 0.566 m); visually TrackNet is dead-on
   (~15–20 px) for normal shots and the p90 tail is smash motion-blur. Also: serves
   (ball_round 1) have EMPTY hit_x/hit_y, and stroke N's hit point ≈ stroke N−1's landing.
10. **`ffmpeg -ss` second-based cuts are NOT frame-exact** for validation purposes — use
   `shuttle.cut_exact()` (cv2 seek by frame index) when frame numbers must line up.

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
- **Phase 2 IN PROGRESS (2026-06-10).** TrackNetV3 integrated AND full India-Open match
  tracked: 128,400 frames in `shuttle` table (79.4% visible — includes non-rally broadcast
  footage), validated vs all 980 labeled hit points: **99.8% detected, median 115.5 px at
  offset −1** (≈ label-noise floor; see gotcha 9). 3h50m wall on MPS (~12 fps with the
  sliding-window ensemble; `--eval-mode nonoverlap` is ~8× faster if a match needs a quick
  pass). Geometry shot baseline done (`shotclass.py`, 84–88% cross-match). Hit detection
  + landings DONE (`hits.py`: F1 87.9, attribution 90%, landings 0.548 m median — see
  module map). **HELD-OUT TEST PASSED (denmark, all thresholds untouched, 2026-06-10):**
  hits P 90.2 / R 81.7 / F1 85.8 (india: 87.9), attribution 94.5%, landings median
  1.12 m; **BST 82.8% shot class / 82.0% end-to-end (india: 71.8/69.6)** — no overfit,
  and BST beats geometry-on-CV by ~15–26 pts on both matches. Next: (a) swap BST into
  `pipeline.py` at DETECTED hit frames (predict_df is the interface); (b) rally
  segmentation (serve-onset + visibility runs + replay rejection) to drop the last
  label dependency; (c) BST adapter —
  `third_party/BST` cloned, pretrained ShuttleSet weights + preprocessed eval npy on its
  README Drive links; inputs (17 COCO joints bbox-normalized, court-normalized positions,
  shuttle xy) all exist in our `tracks`/`shuttle` tables. CPU/MPS-friendly (plain PyTorch).
  (d) run `python -m badminton.shuttle denmark_open_2022_sf` overnight for match 2.
- **Tactical commentary layer: WORKING (2026-06-10).** `commentary.py` + the 🎙️ Commentary
  dashboard page, generated end-to-end with Gemini (free tier, key in `.env`) for both
  matches. Multi-provider: add `ANTHROPIC_API_KEY` to `.env` to enable the Claude option
  (better model; untested path — verify on first use). Possible refinements: per-set
  commentary, rally-level evidence links (reuse coach-note keys → Film room deep links),
  prompt tuning in `SYSTEM`.
  Note: a stray `/opt/homebrew/bin/ant` exists but it's **Apache Ant**, not the Anthropic
  CLI — don't suggest `ant auth login` on this machine.
- **Phase 2 shuttle tracking** (TrackNetV3 → MonoTrack) for landing points / shot classes
  from video rather than relying on ShuttleSet labels.
- **Far-court accuracy / robustness**: small-target pose is the weak spot (see PHASE0_RESULTS).

## 11. Pointers
- Plan/architecture: `docs/DESIGN.md` · Schema: `docs/SCHEMA.md` · Datasets: `docs/DATASETS.md`
- Phase 0 results: `docs/PHASE0_RESULTS.md` · This repo's README has run/usage details.
