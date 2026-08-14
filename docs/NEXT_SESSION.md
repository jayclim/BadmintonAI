# NEXT SESSION — what to run on a machine with the DuckDB

Written 2026-08-14 from a web session (fresh clone, no `data/db/badminton.duckdb`, no
video, no torch/OpenCV). Everything that could be done without those is **done and
pushed**. This file is the pickup point for the parts that need the real database.

Branch: `claude/badminton-analytics-improvements-svr9p2` · CI: green on every commit.

---

## 1. State — what is already done

| Commit | What |
|---|---|
| `3b773d4` | `score_seq.py` — rule-constrained score decoder (repair → expand → complete) |
| `f55640d` | `doubles/track.py` — slot identity fixes (gap-scaled re-ID, optimal match, sticky halves) |
| `e488bac` | `.github/workflows/tests.yml` — both suites in CI, no video/DB/weights needed |
| `8a9b548` | `labelfree.py` — `--from-snapshot` rebuild, deterministic side map, **all 4 snapshots regenerated** |
| `41cf4de` | this handoff |
| _(below)_ | `web/public/data/*/ai.json` — score layer patched from the corrected snapshots |

Tests: **18/18** (`test_score_seq.py`) + **48/48** (`test_doubles.py`). Both run with no
video, no DuckDB and no model weights — that is deliberate, keep it that way.

### Already fixed, needs no further work
All four labeled snapshots in `data/labelfree/` now carry the true scoreline, verified
against the ShuttleSet `roundscore` columns:

```
india_open_2022_final        24-22  21-17     (was 24-22  19-17)
denmark_open_2022_sf         21-18  21-15     (was 21-18  20-15)
all_england_2022_sf          21-13  12-21  21-19   (was 20-13  12-20  21-19)
all_england_2022_ws_final    21-15  21-15    (was 19-15  20-15)
```

`test_committed_snapshots_carry_the_right_scoreline` locks this in CI — a stale snapshot
now fails the build instead of quietly shipping to the dashboard.

---

## 2. The dashboard is already correct — but re-export anyway

The web bundles were patched directly from the corrected snapshots, so
`web/public/data/<match>/ai.json` now carries the true scoreline and the site renders it.
Verified by building the static export and rendering it headless: all four matches show
the right scoreline on **both** the AI and labels toggles.

That patch was a stopgap. It touched only what is a pure function of the snapshot (or of
the snapshot plus the committed strokes):

```
rally a, b, pa, pb, winner, clutch, category, endPhrase
meta.sets, meta.totals.points
insights.pointsWon, insights.clutch
```

Everything DB-derived — strokes, movement, tactics, commentary — was left untouched, and
`labels.json` and `index.json` were already correct (they come from ShuttleSet). So the
bundles are *consistent*, not *regenerated*. Run the real export when convenient:

```bash
cd <repo>
PYTHONPATH=src .venv/bin/python -m badminton.export_web
cd web && npm run build
```

It should be close to a no-op on the score fields and will authoritatively refresh
everything else. `labelfree --build` is **not** needed first — the snapshots are already
correct and committed (see §4).

### One caveat worth knowing

On All England WS final, set 1 rally 29 changed **winner `B` → `A`**, not just a score
bump. That match has 10 undetected rallies, and the rule-completion gives the game's
final points to the last rally the segmenter *did* find. The set final is exact; that
particular rally's attribution is approximate. Fixing it properly is the segmentation
work in §5.1 — until then, do not quote per-rally attribution near a set's end as exact.

### Verify it worked

```bash
python3 -c "
import json,glob
for f in sorted(glob.glob('web/public/data/*/ai.json')):
    m=json.load(open(f))['meta']
    print(f.split('/')[-2], [(s['a'],s['b']) for s in m['sets']])
"
```

Expect the table in §1. If any match still reads `19-17`, `export_web` did not pick up
the snapshot — check `labelfree.rally_df()` is reading `data/labelfree/<id>.json` and
that the working tree actually has commit `8a9b548`.

Then eyeball it per `CLAUDE.md` (no browser MCP):

```bash
python3 -m http.server --directory web/out 8080 &
chromium --headless --virtual-time-budget=8000 --dump-dom http://localhost:8080/ > /tmp/out.html
```

---

## 3. Doubles tracking — read before spending MPS-hours

`f55640d` fixed three real defects in `doubles/track.py`. **It only affects new tracking
runs.** Every `tracks` row currently in the DuckDB was written by the old assigner, so
the 126 far-slot / 95 far2 teleports in `showcase.json` will not improve until the match
is re-tracked.

That is a deliberate exception to the "never re-parse a tracked match" rule in
`CLAUDE.md` — the existing doubles tracks are known-corrupt in player identity. It is
your call whether the re-track is worth the hours:

```bash
PYTHONPATH=src .venv/bin/python -m badminton.doubles.track wtf_2024_md_sf --stride 3
PYTHONPATH=src .venv/bin/python -m badminton.doubles.export_web wtf_2024_md_sf
```

Chunk it (`--start-frame` / `--max-frames`) so it is resumable.

**What is verified and what is not.** The new logic was A/B'd against the old
implementation on two scenarios and is correct on both:

| Scenario | Old | New |
|---|---|---|
| Crossing under a 10-frame occlusion | identities swapped | correct |
| Far player lunging past the net line | player dropped entirely | correct |

That second one is worse than a mislabel: the old code pushed the lunging far player to
the near half, where the 2-per-half area cap discarded them, so the `far` slot went empty
for those frames. Silent data loss on every far-court net lunge.

**Not verified:** that the teleport count actually falls on real video. Only synthetic
scenarios were available in the web container. After re-tracking, check
`showcase.json`'s teleport counts before claiming any improvement — and if the four
per-player Court heatmaps still show all four players within ~8 m of each other in set 3,
identity is still being averaged and the fix did not take.

---

## 4. Rebuilding snapshots (only if you need to)

`labelfree --build` now has three modes:

```bash
# score layer only, from the committed snapshot — no DB, no video, no OpenCV
PYTHONPATH=src python -m badminton.labelfree <id> --build --from-snapshot

# normal: DB rally list + cached OCR events (no video scan, and no longer needs cv2)
PYTHONPATH=src .venv/bin/python -m badminton.labelfree <id> --build

# full re-scan of the broadcast overlay (slow; needs video + OpenCV)
PYTHONPATH=src .venv/bin/python -m badminton.labelfree <id> --build --rescan
```

`--from-snapshot` carries the cached side map through unchanged, because serve-side
detection is the one input that genuinely needs the DB. If you run a full `--build` on
the DB and the scorelines change, trust the DB run and re-commit the snapshots.

---

## 5. Remaining quick wins, in payoff order

Numbers in brackets are the original estimates from the roadmap artifact.

1. **Score-driven segmentation repair** [half day] — the decoder now reports
   `rallies_missing` per set: All England WS final is missing 7 and 3 rallies, All
   England SF has +5 in set 1 and *invented* windows in sets 2 and 3 (−1, −2). You now
   know exactly how many rallies each set must contain; re-search the temporal holes
   with relaxed thresholds until the counts agree. This is the ceiling on per-rally
   attribution — alignment is not the bottleneck, recall is.
2. **Fuse `serve_court_parity` into the decoder** [half day] — written and validated at
   96.3% across 299 serves, not yet wired in. Gives the score a second independent
   channel and lets a match with an unreadable overlay still be decoded.
3. **Surface `rallies_missing` in the AI Lab** [1 hr] — it ships in the snapshot now but
   nothing displays it. "This set had 38 points; we found 31 rallies" is more credible
   than a bare accuracy number.
4. **Serve re-anchoring for doubles identity** [3 hrs] — `identity.reanchor_at_serves`
   is stubbed, and per-rally scores now exist to drive it. Caps any identity swap at one
   rally instead of one match. Do this *before* the expensive re-track in §3 so one run
   gets both fixes.
5. **Investigate All England SF hit attribution** [2 hrs] — 74.1% against 90–94.5%
   everywhere else, and it is also the tightest camera framing.
6. **One-command `add-match` CLI** [half day] — already scoped as HANDOFF item (a2).

Deeper projects (pose-based pressure with a BadmintonGRF physics anchor, FineBadminton
benchmarking) are in the roadmap artifact, not repeated here.

---

## 6. Gotchas found this session

- **The git identity in web sessions defaults to `Claude <noreply@anthropic.com>`.**
  `CLAUDE.md` forbids an AI author or committer. Set `user.name`/`user.email` before the
  first commit, or the history has to be rewritten afterwards.
- **A correct decoder plus a stale artefact still ships the bug.** `score_seq` was wired
  into `labelfree.py` at `3b773d4` and the dashboard was still wrong, because the
  snapshots on disk predated it. When a fix lives in generated data, regenerate and
  commit the data in the same change.
- **`max(set(xs), key=xs.count)` is a hash-order coin flip on ties.** It silently made
  the deciding set's `side_a` nondeterministic. Worth grepping for the pattern elsewhere.
