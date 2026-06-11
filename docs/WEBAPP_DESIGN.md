# COURTSIDE — web dashboard design

The coach-facing web app that replaces the Streamlit dashboard for presentation. Static
Next.js app in `web/`, fed by precomputed JSON from `python -m badminton.export_web`.
Deploys to Vercel with zero config (pure static export — also hostable anywhere).

## 1. Who it's for, and what each user needs

| User | Job to be done | What must be obvious in <10 s |
|---|---|---|
| **Coach** | Prep a game plan against an opponent | His weapons, his leaks, the pattern to break, video proof |
| **Player** | Self-review after a match | Where my points went, what to drill next |
| **Analyst / demo viewer** | See the AI work | Raw broadcast in → full scouting report out, no human labels |

Design consequences:
- Every claim is **evidence-linked**: insight cards, pattern rows and chart marks deep-link
  into the Film room pre-filtered to the exact rallies.
- Two **data sources** per match where available: `labels` (ShuttleSet ground truth) and
  `ai` (the fully label-free CV chain). A global toggle swaps the ENTIRE dashboard between
  them — that toggle *is* the demo: same coach view, zero human input.
- A dedicated **AI Lab** page shows each pipeline stage working visually, with honest
  validation numbers (incl. the held-out match).

## 2. Stack and why

- **Next.js 15 (App Router) + TypeScript, `output: 'export'`** — pure static site: no
  server, instant CDN loads, free Vercel hosting on a custom domain, works on any host.
  All pages prerendered from `public/data/index.json` via `generateStaticParams`.
- **Tailwind CSS v4** for layout/spacing; design tokens as CSS variables.
- **No chart library.** Every visual is a bespoke SVG/canvas React component (~30–150
  lines each). Bundle stays tiny, and the court/worm/replay visuals need full control
  anyway. Tooltips are plain absolutely-positioned divs.
- **Video = YouTube embeds at frame-accurate timestamps.** The source videos ARE the
  official BWF uploads, and our frame numbers are native to them (`t = frame / 30`).
  So rally video costs zero bytes, zero hosting, and deep-links work from anywhere.
  (The annotated-overlay MP4s stay a local/Streamlit feature; the deployed app shows the
  AI layer via the 2D replay + trajectory charts instead.)
- **Data**: per match+source one `~200–400 KB` JSON with everything page-level; per-rally
  replay payloads split into lazy-loaded files so the initial load stays small.

```
web/public/data/
  index.json                         # match registry + sources + headline metrics
  <match>/labels.json  <match>/ai.json   # full per-source bundle (see §5)
  <match>/showcase.json              # validation + agreement + OCR demo (source-free)
  <match>/replay/<source>/s<set>r<rally>.json   # per-rally replay payloads (lazy)
  <match>/ocr/f<frame>.jpg           # scoreboard crop samples for the OCR demo
```

## 3. Aesthetic direction — "broadcast scouting dossier"

Stadium-at-night dark theme with the discipline of a printed scouting report and the
chrome of a broadcast graphics package.

- **Palette** (CSS vars): background `#0b1210` (green-tinted near-black) with a faint
  court-line geometry watermark + grain; ink `#e8efe9`; muted `#8fa39a`.
  Player A `#ff8a4a` (warm orange), player B `#34d3c8` (teal) — carried over from the
  Streamlit app's semantics. **Optic yellow `#d4f53c` is reserved for the AI layer**
  (detected hits, CV landings, OCR readings, AI-mode chrome) — the color of an actual
  shuttle's feathers, and an instant "this is machine-seen" signal.
  Win green `#4ade80`, error red `#fb6d5d`.
- **Type**: display = **Khand** (condensed, scoreboard energy) for headings and big
  numerals; body = **Archivo**; data/AI chrome = **IBM Plex Mono** (tabular numbers,
  metric badges, pipeline labels).
- **Motifs**: card borders drawn as thin double "court lines"; section dividers like
  service lines; stat tiles read like a stadium scoreboard; AI elements get a mono
  `[AI]` tick and optic-yellow accents.
- **Motion**: one orchestrated staggered reveal per page (CSS only); score worm draws in;
  count-up numerals on stat tiles; the rally replay is the only continuous animation.

## 4. Pages and every component

Shell (all pages): top bar (wordmark · match switcher · **LABELS / AI VISION** segmented
toggle · nav tabs) + persistent score header (players colored, set pills, tournament
meta, source badge). AI mode adds an optic-yellow hairline ribbon: "every number below
was inferred from the broadcast video — no human labels".

### 4.1 Overview (`/m/<id>/<src>` )
1. **Scoreboard hero** — winner trophy, big condensed set scores, date/round chips,
   match totals (rallies, shots, rally time, distance run).
2. **Score worm** (one SVG per set, side by side) — step line of the point lead; dots
   colored by rally winner, diamonds = clutch (18+); hover → tooltip (score, winner,
   how it ended, shots, secs); click → Film room at that rally. Dashed zero line;
   set-score annotation at the right edge.
3. **Stat duel tiles** — two-column per-player: points / winners / errors gifted /
   best run / metres run / pressure applied. Mirrored layout so the duel reads at a glance.
4. **Coach's notes** — the rule-based insight cards (icon, claim, body, score-ranked),
   each with "▶ watch the N rallies" → Film room preset. Identical component in AI mode
   (cards computed from CV data).
5. **AI match report** (when commentary JSON exists) — LLM headline, story, turning
   points, per-player strengths/weaknesses/training priorities/gameplan, in two player-
   colored panels. Model + token caption.

### 4.2 Points (`/points`)
1. **Weapons & leaks** — per player, diverging horizontal bars per shot type (winners →
   right in green, errors → left in red), sorted by involvement; the biggest red bar is
   the cheapest fix and gets a "⚠ leak" flag. Bar click → Film room (those enders).
2. **Where points came from** — per player 100% stacked bar: own winners / opponent out /
   opponent net / other.
3. **Rally length win rates** — grouped columns (short ≤4 / mid 5–9 / long 10+) per
   player vs a dashed 50% rule, n annotated. A ≥20-pt gap gets a callout chip.
4. **Serve & receive** — per player: serve-win% vs receive-win% paired bars plus
   per-serve-type mini-metrics (n, win%).
5. **Clutch duel** — big numerals: points won from 18+ each, with watch link.

### 4.3 Court (`/court`)
1. **Placement maps** — true-proportion SVG court per player (hitter normalized to
   bottom, hitting up): dim dots = in-rally shots, red ✕ = rally-ending errors, green ★ =
   winners. Filters: shot-type pills, "point-enders only" toggle. Hover mark → tooltip;
   click → that rally in Film room. Legend explains out-long / netted reading.
2. **Movement heat** — per player half-court heat grid (CV tracks, side-swap corrected,
   binned server-side), with distance / mean speed / recovery metrics and a front-mid-back
   zone bar. AI badge: "tracked at ±0.57 m".
3. **Pressure by shot** — horizontal bars: opponent's required movement speed after each
   shot type (m/s) — the pressure builders even when they don't end points.

### 4.4 Patterns (`/patterns`)
1. **Ending sequences** — 2-shot/3-shot toggle; each row: pattern ("lob → smash"), count,
   a split bar of who profited (player colors), watch button. Lopsided (≥75%) rows flagged.
2. **Forced vs unforced errors** — per player stacked bar (forced amber / unforced red)
   with the ≥2.5 m/s definition stated; unforced-heavy gets "free points to claw back".
3. **Shot mix butterfly** — mirrored horizontal bars, A left / B right, % of own shots
   per type — rally construction styles at a glance.
4. **Backhand vulnerability** (labels source only) — usage% vs error-share% dumbbell per
   player. In AI mode the slot states honestly: "needs wing labels — not yet inferred".

### 4.5 Film room (`/film`)
1. **Filter rail** — set, point-to, ended-by, final shot, length, clutch-first sort;
   or an **evidence banner** when arriving from a note/pattern link (one-click clear).
2. **Rally list** — compact table: score (clutch ❄ flag), winner chip, shots, seconds,
   "how it ended" phrase. Click selects.
3. **Broadcast player** — YouTube iframe seeked to `f0/30 − 2s` (+ end param), plus an
   "open on YouTube" deep link.
4. **2D replay** — animated SVG court synced to a scrubber: player dots with motion
   trails (CV tracks), hit flashes labeled with the shot type (AI mode: + confidence),
   stroke arcs hitter → landing, final landing star. Play/pause/0.5–2× speed. This is
   the per-rally AI showcase.
5. **Shot-by-shot strip** — numbered chips (hitter-colored) with shot type and a
   pressure bar (required m/s) per stroke; the ender chip gets the outcome badge.

### 4.6 AI Lab (`/lab`) — the showcase
1. **Pipeline stepper** — VIDEO → POSE/TRACKS (0.566 m median) → SHUTTLE (TrackNetV3,
   99.8% of hit points) → HITS (F1 87.9) → SHOT CLASSES (BST-0 72–83%) → RALLIES
   (F1 94–98 label-free) → SCORE OCR (95–97% trajectory) → COACH VIEW. Each node is a
   card with its metric badge; the held-out match's number shown second ("tuned / held-out").
2. **Rally X-ray** — rally picker; synchronized YouTube clip + **shuttle trajectory
   chart** (screen x/y vs frame, optic-yellow rules at detected hits, dashed gray at
   human labels where available) + the 2D replay + BST shot-call chips appearing per hit.
3. **Score OCR, live** — actual scoreboard crops with the machine-read score rendered
   beside them; the OCR event timeline as a staircase chart vs set progression; the
   derived side map; accuracy badges (95.2% / 97.3% transfer, side map 8/8).
4. **AI vs ground truth** — for labeled matches: coverage, hitter agreement, shot
   agreement; BST confusion matrix heatmap (rows = label, cols = prediction); per-class
   recall bars. Honest framing: thresholds tuned on India Open; Denmark untouched.

## 5. Per-source JSON bundle (what export_web.py emits)

`meta` (players, colors, youtube id, fps, sets, source) · `rallies[]` (set, rally, f0/f1,
t0/t1, shots, durS, server, serveType, winner, endHitter, endShot, endRound, category,
scoreA/B, prevA/B, clutch, bucket, pat2/3) · `strokes[]` (slim: set, rally, br, frame,
hitter, shot, conf, hitterXY, recvXY, landXY normalized + metres, pressure) · `insights`
(notes, pointsWon, lengthBuckets, serveStats, clutch, longestRun, patterns2/3,
errorPressure, backhand, shotOutcomes, shotMix, pressureByShot, pressureSummary) ·
`movement` (per player: metrics + heat bins + zonePcts) · `commentary?` (cached LLM
report). `showcase.json`: tracking/hits/landing/segmentation/OCR validation numbers,
labels-vs-AI agreement, BST confusion + recall, OCR events + crop manifest.

## 6. Honest-numbers policy

The Lab never rounds up: every metric states its evaluation basis (vs ShuttleSet labels,
±6 frames, etc.) and shows the held-out match beside the tuned one. AI-mode coach pages
carry the ribbon; categories the CV can't infer yet (backhand, exact lose reasons) say so
instead of faking it.
