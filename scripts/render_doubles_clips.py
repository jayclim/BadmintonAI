"""Batch-render AI-annotated DOUBLES rally clips for the web app (ISOLATED).

One clip per rally (reprojected court + 4 boxes/pose skeletons + name/role labels +
formation banner + machine-read score, NO human labels), written to
web/public/clips/<match>/f<start>-<end>.mp4 — the same naming the web exporter maps onto
by frame-window overlap (so the doubles dashboard's AI-overlay toggle can swap footage,
exactly like singles).

Set-1 rallies get the roster athlete names (serve-anchored); other sets show the team
letter (A/B) — honest, since only set 1's within-pair identity is anchored. Front/back
role + formation are pure geometry and always shown.

  PYTHONPATH=src .venv/bin/python scripts/render_doubles_clips.py --match wtf_2024_md_sf [--limit N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import config  # noqa: E402
from badminton.doubles import identity, render, segment, sets  # noqa: E402

OUT = config.REPO_ROOT / "web" / "public" / "clips"
PRE, POST = 24, 30          # padding frames around the rally window
HEIGHT, CRF = 540, 27       # web weight: ~0.5-1.5 MB per rally


def render_match(match_id: str, limit: int | None = None,
                 max_gap: int = 20, min_len: int = 45) -> None:
    m = config.get_match(match_id)
    if m.get("discipline") != "doubles":
        print(f"!! {match_id} is not a doubles match — skipping")
        return
    windows = segment.rally_windows(match_id, max_gap, min_len)
    if not windows:
        print(f"!! {match_id}: no rallies (run doubles.track first)")
        return
    if limit:
        windows = windows[:limit]

    # OCR per-rally scores ONCE; reuse for both set detection (naming) and the on-clip score
    # readout (constant within a rally), so the render skips its own per-clip OCR.
    try:
        scores = identity.rally_scores_ocr(match_id, windows)   # (a,b,top,bot) per rally
        rsides = sets.rally_sides(scores)
    except Exception as e:
        print(f"note: scoreboard OCR failed ({e}); using a single set, no scores")
        scores = [(a, b, None, None) for a, b in windows]
        rsides = [{"set": 1, "near_pair": "A", "far_pair": "B"} for _ in windows]
    try:
        set1_names = identity.resolve(match_id, 1)     # slot -> athlete (set 1 only)
    except SystemExit:
        set1_names = None

    out_dir = OUT / match_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (a, b) in enumerate(windows):
        f0, f1 = max(0, int(a) - PRE), int(b) + POST
        out = out_dir / f"f{f0}-{f1}.mp4"
        if out.exists():
            continue
        rs = rsides[i] if i < len(rsides) else {"set": 1, "near_pair": "A", "far_pair": "B"}
        if rs["set"] == 1 and set1_names:
            names = set1_names
        else:
            names = {"near": rs["near_pair"], "near2": rs["near_pair"],
                     "far": rs["far_pair"], "far2": rs["far_pair"]}
        top, bot = scores[i][2], scores[i][3]
        score = f"{top}-{bot}" if top is not None and bot is not None else None
        t = time.time()
        render.render_rally(match_id, f0, f1, out, names=names, score=score,
                            out_height=HEIGHT, crf=CRF)
        print(f"[{match_id} {i + 1}/{len(windows)}] {out.name} set{rs['set']} "
              f"{out.stat().st_size / 1e6:.2f} MB in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="wtf_2024_md_sf")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    render_match(args.match, limit=args.limit)
    print("DONE")
