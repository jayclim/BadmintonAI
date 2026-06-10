# Data Model — two tiers, built as a superset of ShuttleSet

The pipeline's job is to **produce Tier 2, then reduce it into Tier-1 rows in
ShuttleSet's exact format.** Payoff: (1) validate extraction against ShuttleSet's human
labels, (2) any model trained on ShuttleSet runs unchanged on our data, (3) the
commentary layer is built once and works on both.

```
TIER 1 — strokes   ← ShuttleSet IS this. One row per stroke. The tactical truth the LLM reads.
TIER 2 — tracks    ← Our extension. Per-frame player xy + 17 pose keypoints + shuttle xy.
                     Feeds movement analytics; gets reduced into Tier-1 rows.
```

## ShuttleSet22 reference (verified against the India Open 2022 final)

Files per match: `set1.csv`, `set2.csv`, ... (one per game). **No `homography.csv` or
`match.csv` is shipped.**

Actual per-stroke columns: `rally, ball_round, time, frame_num, roundscore_A,
roundscore_B, player, server, type, aroundhead, backhand, hit_height, hit_area, hit_x,
hit_y, landing_height, landing_area, landing_x, landing_y, lose_reason, win_reason,
getpoint_player, flaw, player_location_area, player_location_x/y, opponent_location_area,
opponent_location_x/y, db`.

**Three spatial points per stroke:** hitter feet (`player_location_*`), shuttle contact
(`hit_*`), shuttle landing (`landing_*`); plus opponent feet (`opponent_location_*`).

**Coordinates are RAW BROADCAST PIXELS** — no homography is provided. We compare in
metres by calibrating one homography on the same video (it maps both our detections and
ShuttleSet's labels, since they share the pixel space). 30 fps (frame_num = sec × fps).
`*_area` are grid zones; `*_height` are above/below-net codes (1.0 / 2.0).

**Shot types: 10 canonical English classes** (ShuttleSet22 collapses the original KDD
18). `type` is Chinese; we map it via the official two-step dict from their
`preprocess_data.py` (see `src/badminton/shuttleset.py`): short service, long service,
clear, drive, drop, lob, net shot, smash, push/rush, defensive shot. `未知球種`/`小平球`
→ unknown (kept raw in `shot_type_raw`).

`player` is `A`/`B` (A = match winner); we keep A/B on import and relabel to near/far
later via the homography (court half).

## Two schema decisions

1. **Neutral player IDs, not A/B-as-winner.** ShuttleSet sets `player A = match winner`,
   which leaks the outcome into the ID — fine for offline analysis, broken for a live
   system. We use `near`/`far` (court half — also our singles tracking trick). Winner is
   *derived* from `getpoint_player`.
2. **Keep ShuttleSet's 16-grid `area`** alongside continuous `x,y`. It's LLM-friendly
   ("you keep landing it in zone 7") and battle-tested by national teams.

## Caveats
- ShuttleSet `landing_x/y` are **human-estimated**, not tracker-derived → treat as
  approximate ground truth when validating the shuttle tracker.
- ShuttleSet has **no per-frame tracks or pose** — only contact-moment snapshots. Tier 2
  is entirely our contribution (and what enables movement/coverage metrics).
- `source` column on every row distinguishes `shuttleset`-imported from `pipeline`-extracted
  so both coexist in one DB.

See [`../schema/schema.sql`](../schema/schema.sql) for the runnable DuckDB DDL.
