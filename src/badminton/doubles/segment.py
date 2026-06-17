"""Doubles rally segmentation from 4-player tracks (ISOLATED, Phase 1).

A doubles rally = all four players on the calibrated court; dead-time between points =
the far players walk off court and their tracks vanish. So contiguous runs of
all-4-present frames ARE the rallies. Validated on wtf_2024_md_sf: all-4 runs line up
with real rallies (98% all-4 coverage in-rally) while between-point fragments — where
only the near pair lingers — fall out.

This is the tracks-only first cut (no shuttle needed). Later, shuttle motion + hits can
refine the exact start (serve) and end (landing), the same upgrade path the singles
`segment.py` took. Rally windows are also the anchors `identity.reanchor_at_serves` wants.

CLI:  PYTHONPATH=src python -m badminton.doubles.segment <match_id> [--max-gap 20] [--min-len 45]
"""

from __future__ import annotations

import argparse

from .. import db
from .track import SLOTS as _SLOTS_BY_HALF

SLOTS = frozenset(s for half in _SLOTS_BY_HALF.values() for s in half)


def _merge_runs(frames, max_gap: int, min_len: int) -> list[tuple[int, int]]:
    """Contiguous runs of `frames`, bridging gaps <= max_gap (within-rally dropouts),
    keeping only runs spanning >= min_len frames. Pure; no DB."""
    frames = sorted(frames)
    if not frames:
        return []
    runs, start, prev = [], frames[0], frames[0]
    for f in frames[1:]:
        if f - prev <= max_gap:
            prev = f
        else:
            runs.append((start, prev))
            start = prev = f
    runs.append((start, prev))
    return [(a, b) for a, b in runs if b - a + 1 >= min_len]


def _active_frames(match_id: str) -> list[int]:
    """Frames where all four slots are present (real or gap-filled)."""
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT frame_num FROM tracks WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "GROUP BY frame_num HAVING COUNT(DISTINCT player_id)=4 ORDER BY frame_num",
        [match_id]).fetchall()
    con.close()
    return [r[0] for r in rows]


def rally_windows(match_id: str, max_gap: int = 20, min_len: int = 45) -> list[tuple[int, int]]:
    """(start_frame, end_frame) per detected rally."""
    return _merge_runs(_active_frames(match_id), max_gap, min_len)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles rally segmentation from tracks (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=20, help="bridge within-rally dropouts up to N frames")
    ap.add_argument("--min-len", type=int, default=45, help="discard runs shorter than N frames")
    ap.add_argument("--fps", type=float, default=30.0)
    args = ap.parse_args()
    w = rally_windows(args.match_id, args.max_gap, args.min_len)
    print(f"{len(w)} rallies:")
    for i, (a, b) in enumerate(w, 1):
        print(f"  {i:2d}. frames {a}-{b}  ({(b - a + 1) / args.fps:.1f}s)")
    if w:
        tot = sum(b - a + 1 for a, b in w)
        print(f"total rally span: {tot} frames ({tot / args.fps:.1f}s)")


if __name__ == "__main__":
    main()
