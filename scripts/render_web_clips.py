"""Batch-render AI-annotated rally clips for the web app.

One clip per label-free rally (boxes + skeletons + shuttle trail + BST shot calls +
OCR score + minimap, NO human labels), written to web/public/clips/<match>/
as f<start>-<end>.mp4 (video-frame window in the name so BOTH data sources can map
their rallies onto the same clip by overlap at export time).

  PYTHONPATH=src .venv/bin/python scripts/render_web_clips.py [--match ID] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import config, labelfree, render_overlay  # noqa: E402

OUT = config.REPO_ROOT / "web" / "public" / "clips"
PRE, POST = 36, 42          # padding frames around the rally window
HEIGHT, CRF = 540, 27       # web weight: ~0.5-1.5 MB per rally


def render_match(match_id: str, limit: int | None = None) -> None:
    snap = json.loads(labelfree.snapshot_path(match_id).read_text())
    rallies = snap["rallies"][:limit]
    out_dir = OUT / match_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rallies):
        f0, f1 = max(0, r["f0"] - PRE), r["f1"] + POST
        out = out_dir / f"f{f0}-{f1}.mp4"
        if out.exists():
            continue
        t = time.time()
        render_overlay.render(match_id, f0, f1, out, ai_only=True,
                              out_height=HEIGHT, crf=CRF)
        print(f"[{match_id} {i + 1}/{len(rallies)}] {out.name} "
              f"{out.stat().st_size / 1e6:.2f} MB in {time.time() - t:.0f}s",
              flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    ids = [args.match] if args.match else \
        ["india_open_2022_final", "denmark_open_2022_sf"]
    for mid in ids:
        render_match(mid, limit=args.limit)
    print("DONE")
