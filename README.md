# Badminton CV — Match Tracker & Tactical Analytics

Computer-vision + AI system that turns badminton video into structured tactical data,
then into a coaching analytics dashboard and (later) natural-language advice.

> **Picking this up?** Read [`HANDOFF.md`](HANDOFF.md) first — it's the single entry point
> (status, architecture, run commands, and the hard-won gotchas).

## Status: Phase 0 validated (0.566 m) · full match parsed · Phase 1 analytics in dashboard

## Direction
- **Capture:** start from broadcast feeds; design toward *user-controlled capture*
  (anyone sets up one good-enough camera). Controlled capture makes court calibration
  a one-time step.
- **Product order:** analytics dashboard first → tactical commentary/advice later.
- **Discipline order:** singles first → doubles later.

## Docs
- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture, tooling choices (with trade-offs), phased plan.
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — the two-tier data model, built as a superset of ShuttleSet.
- [`schema/schema.sql`](schema/schema.sql) — DuckDB DDL, ready to run.
- [`docs/DATASETS.md`](docs/DATASETS.md) — existing annotated datasets and how to access them.

## Data persistence & multiple matches
**Parsed data is durable** — every stroke and track is stored in `data/db/badminton.duckdb`
on disk, keyed by `match_id`. It survives across sessions, so **you parse a match once**
and the dashboard just reads it. (The DB is gitignored; it's a local cache, not committed.)

The dashboard has a **Match selector** (sidebar) populated from the DB, so multiple matches
coexist and are pickable. To add a new match:
1. Register it in `config/matches.yaml` (players, video_url, etc.).
2. `python -m badminton.shuttleset <match_id>` — import its ShuttleSet labels.
3. `python -m badminton.fetch_video <match_id> --url ...` then `calibrate_court` — get the homography.
4. `python scripts/parse_match.py --match <match_id>` — parse it once (cached forever after).

## Viewing results
- **Coaching dashboard:** `PYTHONPATH=src .venv/bin/streamlit run app.py` — seven pages:
  Match story (score worm + auto Coach's notes that deep-link to the supporting rally
  clips), Commentary (LLM tactical match report — Gemini or Claude, key in the
  repo-root `.env`, cached per provider after first generation), Points won & lost, Court maps
  (shot placement + movement), Patterns & pressure, Film room (filterable rally clips
  with rally map + per-shot pressure), and Lab (CV validation diagnostics;
  see [`docs/PHASE0_RESULTS.md`](docs/PHASE0_RESULTS.md)).
- **Annotated overlay video:** `data/raw/overlay.mp4` — player boxes + foot-dots, live
  top-down minimap, ShuttleSet labels overlaid. Re-render any window:
  `python -m badminton.detect <match> --start-frame F --max-frames N` then
  `python -m badminton.render_overlay <match> --start F --end F+N`.

## The key insight driving everything
**ShuttleSet** (36,492 labeled pro strokes with player positions) is effectively our
Tier-1 events table already. So: build the analytics/commentary layer on ShuttleSet
*now*, and make the CV pipeline's job to *reproduce ShuttleSet's exact format*. That
gives free validation, model portability, and a commentary layer that works before the
vision pipeline exists.
