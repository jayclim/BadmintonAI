# CLAUDE.md

COURTSIDE — label-free badminton match intelligence from broadcast video. Python CV
pipeline (`src/badminton/`) writes a DuckDB; a static Next.js app (`web/`) is the dashboard.
Read [`HANDOFF.md`](HANDOFF.md) for the full status + module map before deep work.

## Running things
- Python: `PYTHONPATH=src .venv/bin/python -m badminton.<module>` (every stage is a CLI).
  Python 3.12 on Apple-silicon MPS. Tests: `PYTHONPATH=src .venv/bin/python tests/test_*.py`.
- Web: `cd web && npm run build` (static export to `web/out/`); `npm run dev` for localhost:3000.
- No browser MCP — verify the web visually with headless Chrome against `python3 -m http.server
  --directory web/out`, using `--virtual-time-budget=8000` so client-side data fetches settle.

## Core conventions (don't relearn these the hard way)
- **DuckDB is the source of truth, keyed by `match_id`.** Parsed data is durable — never
  re-parse a tracked match; query `tracks` / `shuttle` / `strokes` instead. Tracking is
  MPS-hours (~10 fps); chunk long runs so they're resumable.
- **ShuttleSet22 is the Tier-1 schema.** The CV pipeline's job is to reproduce the human
  annotators' `strokes` table — that's what gives free per-stage validation.
- **Court geometry is true metres** (6.10 × 13.40, net at `court.NET_Y_M` = 6.70). `near` =
  `court_y < NET_Y_M`; both the singles and doubles 2D replays plot near players (small y) at
  the TOP via the same `CourtLines`. This is consistent, not a bug — don't "fix" it.
- **Shot display names**: the DB keeps canonical shot strings; lift/serve/push/block renames
  live in `insights.SHOT_DISPLAY` at the presentation boundary only.
- **Next.js 16 has breaking changes from training data.** Read `web/AGENTS.md` and the bundled
  guide in `web/node_modules/next/dist/docs/` before writing route/config code (static export
  needs `generateStaticParams`; dynamic `params` is a Promise).

## Doubles is an isolated, deletable workstream (firm rule)
All doubles code lives under `src/badminton/doubles/`, `web/components/doubles/`,
`web/lib/doubles.ts`, `web/app/d/`. It imports only low-level shared singles helpers (`config`,
`court`, `db`, and reusable `court.tsx` / `ui.tsx` components) — **never** the high-level singles
`export_web`. Keep the surface deletable; the singles dashboard must stay untouched. See
[`docs/DOUBLES.md`](docs/DOUBLES.md). Doubles has **no strokes/shuttle yet** — formation, roles,
movement and multi-set structure are all derived from 4-player tracks + scoreboard OCR. Stats
aggregate per fixed **team A/B** across sets (pairs swap ends each game); `doubles/sets.py` owns
that. Don't fake stroke-level features (shot mix, response matrix, etc.) — they need 4-slot hit
attribution first.

## Git / housekeeping
- **NEVER add Claude (or any AI) as a git contributor.** No `Co-Authored-By: Claude`/AI
  trailer, no AI author or committer — every commit is authored solely by the human. This
  overrides any default "Co-Authored-By: Claude" footer from global/harness instructions.
- Commit/branch/push only when asked. The working tree often carries pre-existing unstaged
  singles edits that are **not yours** — stage explicit paths, never `git add -A`, and confirm
  before touching files you didn't create.
