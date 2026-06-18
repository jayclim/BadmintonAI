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
with our own monocular chain rather than training on labels. The bet is that *roles*
(front/back, formation) are both more robust and more tactically meaningful than
persistent player identity, so we lean on geometry, not names.

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
scripts/run_doubles_track.sh wtf_2024_md_sf 0 166650 20000   # ~4.5h MPS, chunked + resumable
py -m badminton.doubles.export_web wtf_2024_md_sf            # set-aware export (OCRs each rally)
```

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

Caveats: rally segmentation is tracks-only (no shuttle yet), so the count slightly over-segments
(163 windows vs ~127 actual points); set detection needs readable scoreboard OCR; the per-player
net-hunter is computed only for sets with a `doubles_identity` roster (set 1 here).

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
  `web/public/data/<id>/doubles.json` (meta + per-rally formation report + per-side match
  summary + per-player front-court share + per-slot movement + formation `flow` + label-free
  `showcase` + rule-based coach `notes`), per-rally 4-player replay tracks under
  `.../dreplay/r<n>.json` (near/near2/far/far2 court-metre paths + debounced formation
  run-length segments), and upserts `doubles_index.json`. Re-implements export_web's tiny
  `_js`/`_write`/`_yt_id` helpers locally to keep the isolation rule (no import of the
  high-level singles `export_web`).
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
- **Web (Next.js):** `web/lib/doubles.ts` (types + client loaders), route
  `web/app/d/[id]/[view]/page.tsx` (`generateStaticParams` from the doubles manifest),
  `web/components/DoublesDashboard.tsx`, and **five** views in `web/components/doubles/`:
  **Overview** (AI scouting-notes strip + attack/defence split, rotations, front-swaps,
  median gaps, "who hunts the net", rally log), **Court** (`Movement.tsx`: per-player
  heatmaps + distance/speed/coverage + NET/MID/REAR occupancy + territory, reusing
  `court.tsx::HeatMap`), **Patterns** (`Patterns.tsx`: formation-flow — who seizes/holds the
  attack, rotation rate, transitions, per-rally attack⇄defence dual trace), **Film**
  (4-player animated 2D replay in `court4.tsx`; formation timeline with rotation tick
  markers; YouTube rally clip), and **AI Lab** (`Lab.tsx`: label-free validation showcase +
  per-player tracking-quality table + rally x-ray reusing the 4-player replay). Front/back is
  recomputed every frame from geometry, so it survives slot swaps. The home page gained an
  additive "Doubles" section linking to `/d/<id>/`.
- Verified on `wtf_2024_md_sf`: `next build` (static export) emits all five routes
  (`overview`/`court`/`patterns`/`film`/`lab`); all render the real data. `tests/test_doubles.py`
  = 28/28. The official scoreline lives in `matches.yaml` as `result:` (display-only context).

To refresh after re-tracking: `py -m badminton.doubles.export_web <id>` then `cd web && npm run build`.

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
- **Serve-seeded persistent identity.** Anchor `near` to a specific athlete using the
  service court (fixed by score parity, which we already OCR). Only needed for
  per-athlete career stats; roles don't depend on it.
- **Richer doubles tactics + web.** Five views are built (Overview + scouting notes, Court
  movement heatmaps + territory, Patterns formation-flow, Film replay + rotation markers, AI
  Lab validation showcase) — see "Web dashboard" above. Still open: a **Points/momentum
  view** from the OCR scores (scores computed on demand via `identity.rally_scores_ocr` but
  not yet persisted into the export; only ~4 distinct score points across the 5 tracked
  rallies, so low value until more is tracked), and **LLM coach notes** (the current notes
  are rule-based; an `anthropic` generation step would add prose). A full per-pixel Voronoi
  map was deliberately skipped — see Movement note above.
- **Validation set.** Hand-annotate ~1–2 doubles matches to measure accuracy (mirrors
  the SOTA paper, which labeled exactly two).
