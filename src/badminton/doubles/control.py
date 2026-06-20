"""Doubles court-control / dominant-region (Voronoi) — research-aligned tactic (ISOLATED).

Each court point is "controlled" by the team whose nearer player is closer to it — a
Voronoi / nearest-reach partition. It's the broadcast-tractable proxy for the drone-view
"control area" probability surface in the doubles literature (Springer 2023): no extra
camera, computed from the four court-metre positions we already track.

Per frame the near team's control = the fraction of the court closer to near|near2 than to
far|far2. >50% means the near pair commands more than its own half — the spatial signature
of being on the attack (its front player has pushed control across the net); <50% means
it's pinned back. Everything is rally-scoped (segment.py) so dead-time never counts.

CAVEAT (measured): far-side court-y is biased ~1.4 m toward the net (near players average
3.97 m from the net, far players 2.58 m) — a far-end foot-projection / calibration artifact
(the homography is very sensitive at the compressed far baseline). This puts a static ~45/55
near/far floor under RAW control, so the tactical read is the per-rally **control index** =
near% minus the match baseline (deviation cancels the constant bias; + = near controlled
more court than its own norm that rally). Fixing the upstream far-y bias would make raw
control directly meaningful; until then prefer the index. The control MAP is still a fair
visual — the bias is a near-uniform shift, so dominance ZONES still read.

Outputs: per-rally raw + indexed control share, the match baseline, and a court-zone control
MAP (per cell, the fraction of rally frames the near team held it) for a diverging overlay.

CLI:  PYTHONPATH=src python -m badminton.doubles.control <match_id>
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import court, db
from . import segment

GRID_STEP = 0.30  # m; ~20x45 cells over the 6.10 x 13.40 court — fine enough, cheap per frame
SLOTS = ("near", "near2", "far", "far2")


def _grid():
    """Cell-centre coordinate grids (gx, gy) tiling the court, each shape (ny, nx)."""
    xs = np.arange(GRID_STEP / 2, court.COURT_WIDTH_M, GRID_STEP)
    ys = np.arange(GRID_STEP / 2, court.COURT_LENGTH_M, GRID_STEP)
    gx, gy = np.meshgrid(xs, ys)
    return gx, gy


def near_control_mask(pos: dict, gx, gy):
    """Boolean grid: True where the near team is closer than the far team.
    `pos` maps each slot -> (x, y) in court metres. A cell belongs to the team whose
    NEARER player is closer (team distance = min over its two players)."""
    def d2(p):
        return (gx - p[0]) ** 2 + (gy - p[1]) ** 2
    dn = np.minimum(d2(pos["near"]), d2(pos["near2"]))
    df = np.minimum(d2(pos["far"]), d2(pos["far2"]))
    return dn < df


def _frame_positions(match_id: str, windows):
    """Per rally frame (all 4 slots present), {slot: (x, y)} — restricted to rally windows."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks WHERE match_id=? "
        "AND player_id IN ('near','near2','far','far2') ORDER BY frame_num", [match_id]).fetch_df()
    con.close()
    keep = pd.Series(False, index=df.index)
    for a, b in windows:
        keep |= (df.frame_num >= a) & (df.frame_num <= b)
    df = df[keep]
    out = {}
    for fr, g in df.groupby("frame_num"):
        p = {r.player_id: (r.court_x, r.court_y) for r in g.itertuples(index=False)}
        if all(s in p for s in SLOTS):
            out[int(fr)] = p
    return out


def control_series(match_id: str, max_gap: int = 20, min_len: int = 45, windows=None):
    """(per-frame near-control fraction dict, accumulated near-control map, frame count, windows).
    The map is a (ny, nx) grid of the fraction of frames the near team held each cell.
    Pass `windows` to scope to a subset (e.g. one set, so near=A orientation is consistent)."""
    if windows is None:
        windows = segment.rally_windows(match_id, max_gap, min_len)
    gx, gy = _grid()
    frac_by_frame: dict[int, float] = {}
    acc = np.zeros_like(gx, dtype=np.float64)
    n = 0
    for fr, pos in _frame_positions(match_id, windows).items():
        m = near_control_mask(pos, gx, gy)
        frac_by_frame[fr] = float(m.mean())
        acc += m
        n += 1
    cmap = (acc / n) if n else acc
    return frac_by_frame, cmap, n, windows


def match_baseline(frac_by_frame: dict) -> float:
    """Frame-weighted mean near-control over all rally frames (the static-bias floor)."""
    return 100 * float(np.mean(list(frac_by_frame.values()))) if frac_by_frame else 50.0


def rally_control(match_id: str, max_gap: int = 20, min_len: int = 45) -> pd.DataFrame:
    """Per-rally near/far control share (%) and the bias-cancelled control index
    (near% minus the match baseline; + = near controlled more court than its norm)."""
    frac, _, _, windows = control_series(match_id, max_gap, min_len)
    base = match_baseline(frac)
    rows = []
    for i, (a, b) in enumerate(windows, 1):
        vals = [v for f, v in frac.items() if a <= f <= b]
        if not vals:
            continue
        near = 100 * float(np.mean(vals))
        rows.append({"rally": i, "frames": len(vals),
                     "near_control_%": round(near, 0), "far_control_%": round(100 - near, 0),
                     "near_index": round(near - base, 1)})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles court-control (Voronoi) — isolated")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    frac, _, n, _ = control_series(args.match_id, args.max_gap, args.min_len)
    rc = rally_control(args.match_id, args.max_gap, args.min_len)
    if rc.empty:
        print("no rally frames — run doubles.track + doubles.segment first")
        return
    base = match_baseline(frac)
    print(f"match baseline (static bias floor): near {base:.0f}% / far {100 - base:.0f}%")
    print("control index = near% - baseline (+ = near controlled more court than its norm)\n")
    top = rc.reindex(rc.near_index.abs().sort_values(ascending=False).index).head(8)
    print("=== most one-sided rallies by control index ===")
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
