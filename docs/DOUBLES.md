# Doubles support (experimental, isolated)

Status: **Phase 0 — 4-player tracking + roles.** All doubles code lives under
`src/badminton/doubles/` and is deliberately quarantined from the singles chain
(detect.py, pipeline.py, hits.py, shotclass.py, segment.py). If doubles doesn't pan
out, delete that package + `tests/test_doubles.py` + this doc and nothing else
regresses. Reuse is one-directional: doubles imports shared low-level helpers from the
singles modules; the singles modules never import from `doubles`.

Prefix below: `py` = `PYTHONPATH=src .venv/bin/python` (as in [ADD_A_MATCH.md](ADD_A_MATCH.md)).

## Why this is a separate workstream

Doubles is hard for reasons the singles pipeline never hit (see research notes in the
project memory): partners wear identical kit so appearance re-ID is useless, and the
four players occlude and cross constantly, causing identity switches. There is also **no
public doubles stroke dataset** — ShuttleSet is singles-only — so we generate strokes
with our own monocular chain rather than training on labels. The premise is that *roles*
(front/back, formation) are both more robust and more tactically meaningful than
persistent player identity, so we rely on geometry, not names.

## What Phase 0 ships

- `doubles/track.py` — `process_video`: like `detect.process_video`, but keeps the
  **top-2 detections per court half** and assigns each a stable slot — `near`/`near2`,
  `far`/`far2` — written to the existing `tracks` table (`player_id` already documents
  these). Identity is held by ByteTrack track-ids (persistence) with **velocity-based
  re-ID** to recover a slot when an id is dropped through occlusion.
  Slot labels are arbitrary persistence tags, *not* tactical meaning.
- `doubles/roles.py` — read-only, pure geometry over `tracks`: per frame + side it
  derives **front/back**, **left/right**, and **formation** (`attack` = stacked
  front-to-back, `defence` = side-by-side). Invariant to which physical player got
  `near` vs `near2`, by design.
- `tests/test_doubles.py` — covers slot persistence, velocity re-ID, and role geometry
  with no video/model/DB. Run: `py tests/test_doubles.py`.

## Run it on a doubles match

1. Register + calibrate exactly as in [ADD_A_MATCH.md](ADD_A_MATCH.md) steps 1–2, but set
   `discipline: doubles` in `config/matches.yaml`. Court geometry is identical — the
   homography already uses the **outer (doubles) corners**, so calibration is unchanged.
2. Track 4 players (instead of `parse_match.py` / `detect`):
   ```bash
   py -m badminton.doubles.track <match_id> --model yolo11x-pose.pt \
       --start-frame <F> --max-frames <N> --stride <S>
   ```
   Start with a short window (`--max-frames 600`) on one clean rally.
3. Sanity-check the geometry before anything downstream:
   ```bash
   py -m badminton.doubles.roles <match_id>     # per-side attack/defence %, median gaps
   ```
   Sane output: both sides present, formation split that isn't ~100% one way, and
   median depth/lateral gaps in single-digit metres. Garbage here (e.g. one side never
   has two players) means tracking/identity needs work before proceeding.

### Configured test match: `wtf_2024_md_sf`

Registered in `config/matches.yaml` (`discipline: doubles`): **Goh/Izzuddin vs
Fajar/Rian, HSBC BWF World Tour Finals 2024 SF** — 3 games (17-21, 21-16, 27-25),
81 min, six match points saved in the decider; elite men's doubles, so it stresses both
identity tracking (fast crossing/occlusion, identical kit) and formation transitions.
Source: BWF TV, https://www.youtube.com/watch?v=SRXM1E09gc0, fetched at 720p.

**Next manual step — court calibration** (needs your eyes, exactly like singles):
```bash
py -m badminton.calibrate_court wtf_2024_md_sf     # click the 4 OUTER corners
```
Until that writes a homography, `doubles.track` will exit with "no homography". After
it's calibrated, run the track → roles steps above.

## Full-match tracking + multi-set structure (`doubles/sets.py`)

The whole broadcast can be tracked end to end and the dashboard then covers the full match,
not a single span:

```bash
scripts/run_doubles_track.sh wtf_2024_md_sf 0 166650 20000     # ~4.5h MPS, chunked + resumable
py scripts/render_doubles_clips.py --match wtf_2024_md_sf       # annotated rally clips (≈4 min)
py -m badminton.doubles.export_web wtf_2024_md_sf              # set-aware export (OCRs each rally)
```

(Run `render_doubles_clips.py` BEFORE `export_web` so the exporter discovers each rally's clip
url by frame-window overlap. The export OCRs per-rally scores once and feeds both set detection
and the Points view; rendering then needs the same scores, so it OCRs once too.)

`run_doubles_track.sh` runs `doubles.track` in 20k-frame chunks; each chunk writes at its end
(`process_video` DELETEs then INSERTs its range), so progress persists and a crash only loses
the in-flight chunk — resume by re-running with the last chunk's start. On `wtf_2024_md_sf` the
full 166,650 frames produced ~405k track rows at ~10.5 fps.

A real match is several games, and **two things change across games that would otherwise
mis-attribute every stat**: the score resets, and the pairs **swap ends** between games (and
once more, mid-game, when a side first reaches 11 in the decider). `doubles/sets.py` handles
both, purely:

- **Set boundaries** come from the scoreboard OCR — the per-rally score TOTAL (top+bot) climbs
  within a game and collapses at the next game's first rally. The total is order-invariant, so
  it survives the end-swap and the OCR's only systematic confusion (8↔0). `assign_sets`.
- **Side↔pair** is then pure bookkeeping off the set-1 anchor: pair **A** := whoever started on
  the near end in set 1, **B** := the far pair; each game transition swaps ends, the deciding
  game adds one swap at 11 (`side_pair_map`, `deciding_swap_frame`). No per-set roster needed.
- `rally_sides` / `analyze` tie it together → each rally tagged `{set, near_pair, far_pair}`.

The exporter (`export_web.py`) aggregates **per TEAM (A/B)** across all sets by translating each
rally's geometric near/far through that map, and emits per-set breakdowns (`formationBySet`,
`meta.sets`). Per-pair movement combines each pair's two players onto one near half so it stays
correct through the swaps (`movement.team_movement`). Verified on `wtf_2024_md_sf`: 3 sets
detected (47 / 47 / 69 rallies), the decider's 11-point swap located at the right rally, and the
set-1 attack split (B 72% vs A 39%) matches who won that game. The web is fully team-keyed
(`Team = "A"|"B"`, `TEAM_COLOR`); dot/timeline colours follow the team through end-swaps.

Rally segmentation is **scoreboard-gated** (`segment.rally_windows`, on by default): the raw
tracks-only pass over-segments badly because there is no court-line detector — every detection is
projected through one hand-calibrated homography regardless of where the camera points, so intro /
crowd / warm-up footage AND mid-match replays + celebrations all show "4 players in court" and leak
in as fake rallies. The gate keeps a window only if the live BWF score overlay reads in it (live
play always carries the graphic; B-roll reads zero). On `wtf_2024_md_sf` this drops 43 of 163
candidates → **120 live rallies** (close to the ~127 true points), removing the intro footage and
replays the raw pass invented. It degrades to ungated if the score box can't be calibrated.

Caveats: the gate needs readable scoreboard OCR; a few real rallies are still missed where tracking
drops all four players (120 vs ~127); the per-player net-hunter is computed only for sets with a
`doubles_identity` roster (set 1 here).

## Persistent identity (optional layer — `doubles/identity.py`)

Roles above are identity-free and robust. When you also want **named** players (per-athlete
stats, "Goh smashed from the rear"), add a manual roster — this is what a self-uploader
would fill in. It does **not** replace roles; it sits on top.

- **Per set** (pairs swap ends between sets): an `anchor_frame` at the set's first serve +
  the four service-court quadrants → names, under `doubles_identity` in `matches.yaml`.
  At a serve the four players sit in four distinct quadrants, so the labels are unambiguous;
  names then carry by slot through the set.
- Run: `py -m badminton.doubles.identity <match_id> --set N` → prints slot→name and tags
  every tracked row.
- **Robust re-anchor (built): `identity.reanchor_at_serves`.** Re-derives slot->name every
  rally from the serving-rule parity, correcting slot swaps from the previous rally's
  dead-time. Invariant (`identity.service_courts`): within a game a side's even-court
  player is in the right service court when the side's score is even. Given per-rally
  scores + an even-court seed per side, it assigns each side's two slots to the right/left
  service-court player by court_x at the rally's first all-4 frame. Verified on
  wtf_2024_md_sf (rallies 3 vs 4, same 9/14 score, produced different slot->name —
  correcting a slot swap between them).
- **Fully automatic now: `identity.auto_reanchor`** = segment rallies -> `rally_scores_ocr`
  (reuses `scoreboard.py`; majority-voted over frames per rally) -> parity re-anchor. The
  existing BWF digit templates transfer to this doubles broadcast; the only systematic OCR
  error is 8<->0, which is parity-preserving, and the re-anchor needs only parity — so OCR
  is sufficient. Verified: OCR parities match the hand-read scores for all 5 rallies and
  reproduce the same names. REMAINING niceties: seed even-court from the set's first serve
  (currently a passed dict), and derive the scoreboard row->side map per set from `side_map`
  (currently top->near, bot->far).

## Coverage finding (smoke test) — it's segmentation, not tracking

Measured on `wtf_2024_md_sf`: aggregate all-4-players coverage over a 30s window was only
~46%, but on the **longest continuous rally (12.1s) it's 98%**. The gap is dead-time
between points (far players off the calibrated court), where missing stretches are 50-180
frames long — not short dropouts. So the lever is **rally segmentation** (exclude
dead-time), not better detection.

`doubles/segment.py` does this from the 4-player tracks alone (no shuttle yet): contiguous
runs of all-4-present frames = rallies, bridging within-rally dropouts (`--max-gap`) and
dropping sub-`--min-len` fragments. On `wtf_2024_md_sf` it isolated the one real rally
(27493-27847, 11.8s) and discarded the between-point fragments. These windows are also the
anchors `identity.reanchor_at_serves` needs. (`doubles/smooth.py` gap-fills the occasional
short dropout — idempotent, marks `pose_conf=-1.0`, `--max-gap` — but is a minor utility,
not the coverage fix.)

## Web dashboard — the COURTSIDE doubles surface (BUILT)

Doubles has its own dashboard surface, kept as isolated on the web side as the Python
package is on the backend: a SEPARATE route (`/d/<id>`), a SEPARATE manifest
(`web/public/data/doubles_index.json`), and self-contained components — so the singles
dashboard is untouched and the whole doubles web layer is deletable. (The singles
`export_web.py` already excludes doubles automatically, since it iterates the `strokes`
table, which doubles has no rows in.)

- **Exporter:** `py -m badminton.doubles.export_web <match_id>` writes
  `web/public/data/<id>/doubles.json` (meta + per-rally formation report w/ annotated-clip url +
  per-side match summary + per-player front-court share + **per-PLAYER movement** (4 per set) +
  formation `flow` + **`points`** (per-set score trajectory) + label-free `showcase` + rule-based
  coach `notes` + stroke-derived `shots`: team mix, response matrix, **per-player mix** (keyed
  (set, team, idx) like movement), **serve/receive point split** and **finishing shots** — the
  last two join strokes to the OCR rally winners), per-rally 4-player replay tracks (now with the
  per-rally **stroke sequence**) under `.../dreplay/r<n>.json`, and upserts `doubles_index.json`. The per-rally scoreboard OCR runs ONCE and feeds both `sets` and `points`.
  Re-implements export_web's tiny `_js`/`_write`/`_yt_id` helpers locally to keep the isolation
  rule (no import of the high-level singles `export_web`).
- **Annotated clips (`doubles/render.py` + `scripts/render_doubles_clips.py`):** one MP4 per rally
  with the reprojected court, 4 pose skeletons/boxes, name (set-1 roster) + front/back role labels,
  the attack/defence formation banner, and the machine-read score, encoded 540p H.264 — the doubles
  analogue of `render_overlay.render(ai_only=True)` (doubles has no shuttle/shot calls). Written to
  `web/public/clips/<id>/f<a>-<b>.mp4` (same naming the exporter maps on by overlap), git-tracked
  like the singles clips. `roles.roles_df(match_id, start, end)` is windowed so each per-rally
  render is cheap (~1.6s) instead of re-scanning the whole-match tracks.
- **Points (`doubles/points.py`, pure + unit-tested):** the score story from the per-rally
  scoreboard OCR — per-set worm trajectory, set winners, longest momentum run, and short/mid/long
  win splits. Scoreboard rows are FIXED BY TEAM on this broadcast (top row = team A, verified
  3 ways), anchored by `scoreboard_top_team` (default 'A', overridable in matches.yaml). The
  broadcast cuts away on a game's final point, so the worm can stop one point short — the official
  scoreline (matches.yaml `result`) is shown in the header.
- **Movement (`doubles/movement.py`):** per-slot distance / speed / coverage / front-mid-
  back occupancy + a positional heatmap, rally-scoped and median-smoothed, with far-side
  positions mirrored (x→W-x, y→L-y) onto a single near half so all four players are
  directly comparable. The heat dict matches the singles `_heat` contract exactly, so the
  web `court.tsx::HeatMap` renders it unchanged. Also `court_control()` — a per-frame
  2-player Voronoi over each team's own half giving each player's nearest-partner
  **territory** share (whole-court Voronoi is the wrong tool: the net splits the court and
  reach-coverage% is identical for both pairs, so only the intra-pair split is informative).
  Self-contained (re-implements `_smooth`, the speed cap, the bins — imports only
  `court`/`db` + sibling `segment`).
- **Validation (`doubles/validate.py`):** label-free tracking-quality metrics for the AI
  Lab — all-4 in-rally coverage, per-slot recall, identity stability (median court step +
  count of non-physical >1.5 m ID jumps), and segmentation — from tracks alone.
- **Insights (`doubles/insights.py`):** added `formation_flow()` (per-rally attack/defence
  run-length segments + per-side aggregates: attack-first share, median attack hold,
  rotation cadence, a2d/d2a transitions) and the shared `_form_segments()` (the exporter and
  replay both call it now, no duplication).
- **Web (Next.js):** `web/lib/doubles.ts` (types + client loaders + `playerLabel` fallback), route
  `web/app/d/[id]/[view]/page.tsx` (`generateStaticParams` from the doubles manifest),
  `web/components/DoublesDashboard.tsx` (six tabs + the shared **AI-overlay navbar toggle**,
  `useOverlayPref`), and **six** views in `web/components/doubles/`:
  **Overview** (AI scouting-notes strip + attack/defence split, rotations, front-swaps,
  median gaps, "who plays the net", rally log), **Points** (`Points.tsx`: per-set score worm +
  sets-won + longest momentum run + short/mid/long win splits, from the scoreboard OCR), **Court**
  (`Movement.tsx`: **per-PLAYER** heatmaps — 4 cards, one per person, with a set selector —
  distance/speed/coverage + NET/MID/REAR occupancy, reusing `court.tsx::HeatMap`), **Patterns**
  (`Patterns.tsx`: formation-flow — who seizes/holds the attack, rotation rate, transitions,
  per-rally attack⇄defence dual trace), **Film** (4-player animated 2D replay in `court4.tsx` +
  the annotated rally clip / YouTube embed via `DoublesVideo`; formation timeline with rotation
  tick markers), and **AI Lab** (`Lab.tsx`: label-free validation showcase + per-player
  tracking-quality table + a two-up rally x-ray = annotated broadcast beside the 4-player replay).
  Front/back is recomputed every frame from geometry, so it survives slot swaps. The home page has
  an additive "Doubles" section linking to `/d/<id>/`.
- Verified on `wtf_2024_md_sf`: `next build` (static export) emits all six routes
  (`overview`/`points`/`court`/`patterns`/`film`/`lab`); all render the real data, 163/163 rally
  clips mapped. `tests/test_doubles.py` = 35/35. The official scoreline lives in `matches.yaml`
  as `result:` (display-only context).

To refresh after re-tracking: `py scripts/render_doubles_clips.py --match <id>` then
`py -m badminton.doubles.export_web <id>` then `cd web && npm run build`.

## AI commentary (`doubles/commentary.py`)

LLM doubles-coach report, mirroring the singles `commentary.py` but isolated (re-implements
the provider/.env plumbing locally; no import of the singles module). Source of truth is the
exported `doubles.json` — condensed to a compact dossier (heatmaps and replay grids dropped),
sent to the model, validated into a `DoublesCommentary` (headline, match story, turning points,
per-pair strengths / weaknesses / training / gameplan).

- Providers: `gemini` (GEMINI_API_KEY) and `claude` (ANTHROPIC_API_KEY, `claude-opus-4-8`,
  `messages.parse` + adaptive thinking); default is gemini when both keys are in the repo-root `.env`.
- `py -m badminton.doubles.commentary <id>` caches `data/commentary/<id>.doubles.<provider>.json`
  and publishes `web/public/data/<id>/analysis.json`.
- Web: `useDoublesAnalysis` loads `analysis.json`; the Overview shows an **AI ANALYSIS** section
  at the top (renders nothing if it hasn't been generated).
- Full flow: `export_web <id>` → `commentary <id>` → `cd web && npm run build`.

## Not done yet (deferred Phase 1+)

These are intentionally *not* built, to keep the singles chain untouched until Phase 0
tracking proves out on real footage:

- **Stroke attribution (one-line singles touch).** `hits.attribute_hits`
  ([hits.py:182](../src/badminton/hits.py)) hard-codes `for pid in ("near", "far")`.
  Generalising it to all four slots makes the existing shuttle→hit→attribution chain
  work for doubles with zero retraining. Left for Phase 1 so we change singles code only
  once tracking is trusted.
- **Shot type.** `shotclass.py` is singles geometry and assumes a single "receiver";
  doubles needs the receiver chosen as the opponent nearest the projected landing.
- **Per-athlete identity across sets.** Per-player movement names players only in set 1 (the
  roster-anchored set); sets 2-3 show the pair label + P1/P2 because the pairs swap ends and the
  within-pair slots aren't re-anchored there. `identity.reanchor_at_serves` (score-parity) is the
  built hook to extend this — wiring it into the per-player export would name all sets. Only needed
  for per-athlete career stats; roles/team stats don't depend on it.
- **Richer doubles tactics + web.** Six views are built (Overview + scouting notes + LLM
  commentary, Points score worm + serve/receive + finishing shots, Court per-player heatmaps +
  top shots, Patterns shot mix / response matrix / formation-flow, Film replay + shot sequence +
  annotated clips, AI Lab validation showcase) — see "Web dashboard" above. A full per-pixel
  Voronoi map was deliberately skipped — see Movement note above.
- **Validation set.** Hand-annotate ~1–2 doubles matches to measure accuracy (mirrors
  the SOTA paper, which labeled exactly two).
