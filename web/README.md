# COURTSIDE — the badminton match-intelligence web app

Static Next.js dashboard for the badminton CV project. Replaces the Streamlit app for
presentation: coach analytics (overview, points, court maps, patterns, film room) plus
an **AI Lab** that shows every CV pipeline stage working, with honest validation numbers.
Each match renders from two data sources — **GROUND TRUTH** (ShuttleSet labels) and
**AI VISION** (the fully label-free chain) — switchable from the top bar.

## How it works

- Pure static export (`output: 'export'`) — no server, no Python at runtime.
- All data is precomputed JSON in `public/data/` by
  `PYTHONPATH=src python -m badminton.export_web` (run from the repo root; re-run after
  re-parsing matches). Per-rally replay payloads are lazy-loaded.
- Rally video = YouTube embeds at frame-accurate timestamps (the analyzed videos ARE the
  official BWF uploads), so video costs zero hosting.
- No chart library — every visual is a bespoke SVG/canvas component (`components/`).

## Develop

```bash
cd web
npm install
npm run dev          # http://localhost:3000
npm run build        # static site in out/
```

## Deploy to Vercel (custom domain)

1. Push the repo to GitHub.
2. In Vercel: **Add New Project** → import the repo → set **Root Directory = `web`**.
   Framework auto-detects as Next.js; no env vars, no build settings needed.
3. Add your domain under Project → Settings → Domains.

CLI alternative: `cd web && npx vercel --prod`.

Any other static host works too — upload `web/out/` as-is.
