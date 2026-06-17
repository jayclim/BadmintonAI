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
  `web/public/data/<id>/doubles.json` (meta + per-rally formation report + per-side
  match summary + per-player front-court share), per-rally 4-player replay tracks under
  `.../dreplay/r<n>.json` (near/near2/far/far2 court-metre paths + debounced formation
  run-length segments), and upserts `doubles_index.json`. Re-implements export_web's tiny
  `_js`/`_write`/`_yt_id` helpers locally to keep the isolation rule (no import of the
  high-level singles `export_web`).
- **Web (Next.js):** `web/lib/doubles.ts` (types + client loaders), route
  `web/app/d/[id]/[view]/page.tsx` (`generateStaticParams` from the doubles manifest),
  `web/components/DoublesDashboard.tsx`, and views in `web/components/doubles/`:
  **Overview** (attack/defence split, rotations, front-swaps, median gaps, "who hunts the
  net" per-player front share, rally log) and **Film** (4-player animated 2D replay in
  `court4.tsx` reusing `court.tsx::CourtLines`; formation timeline; YouTube rally clip).
  Front/back is recomputed every frame from geometry, so it survives slot swaps. The home
  page (`web/app/page.tsx`) gained an additive "Doubles" section linking to `/d/<id>/`.
- Verified on `wtf_2024_md_sf`: `next build` (static export) emits `/d/.../overview` and
  `/d/.../film`; both render the real data (formation cards, 4-player court). The official
  scoreline lives in `matches.yaml` as `result:` (display-only context).

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
- **Richer doubles tactics + web.** The dashboard (formation timeline, rotations,
  per-player front-court share, 4-player replay) is built — see "Web dashboard" above.
  Still open: Voronoi / court-control area, per-player movement heatmaps, and rotation
  *event* markers on the replay.
- **Validation set.** Hand-annotate ~1–2 doubles matches to measure accuracy (mirrors
  the SOTA paper, which labeled exactly two).
