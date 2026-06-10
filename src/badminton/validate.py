"""Phase 0 validation: do our extracted player positions match ShuttleSet's labels?

Both our detections and ShuttleSet's labels live in the SAME broadcast pixel space
(same video), so the one calibrated homography H maps both to court metres — we compare
in metres (resolution-independent, interpretable).

At each ShuttleSet stroke (frame_num F, hitter feet pixel), we:
  1. map the labeled feet pixel -> court metres via H,
  2. look up OUR track at the aligned frame on the same court half,
  3. record the Euclidean error in metres.
Phase 0 passes if the median error is small (target < ~0.5 m).

Frame alignment: our video may start at a different point than ShuttleSet's, so
  our_frame = ss_frame - offset.  Use --search to auto-pick the best offset.

Usage:
    python -m badminton.validate india_open_2022_final --offset 0
    python -m badminton.validate india_open_2022_final --search -300 300 30
"""

from __future__ import annotations

import argparse

import numpy as np

from . import config, court, db


def _ss_labels(con, match_id: str, H: np.ndarray):
    """ShuttleSet hitter feet -> (frame_num, court_xy_m, half). One per stroke."""
    rows = con.execute(
        "SELECT frame_num, hitter_x, hitter_y FROM strokes "
        "WHERE match_id=? AND source='shuttleset' AND hitter_x IS NOT NULL "
        "ORDER BY frame_num", [match_id],
    ).fetchall()
    out = []
    for f, px, py in rows:
        cxy = court.image_to_court(np.array([[px, py]], np.float32), H)[0]
        out.append((int(f), cxy, court.which_half(float(cxy[1]))))
    return out


def _our_index(con, match_id: str):
    """(frame, half) -> court_xy for our detections."""
    idx = {}
    for f, pid, x, y in con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks WHERE match_id=?",
        [match_id],
    ).fetchall():
        idx[(int(f), pid)] = np.array([x, y])
    return idx


def errors_for_offset(labels, our_idx, offset: int) -> np.ndarray:
    """Match each label to the NEAREST of our (≤2) detected players at the aligned
    frame — avoids half-assignment flips for players near the net."""
    errs = []
    for ss_frame, ss_xy, _half in labels:
        f = ss_frame - offset
        cands = [our_idx[(f, h)] for h in ("near", "far") if (f, h) in our_idx]
        if cands:
            errs.append(min(float(np.linalg.norm(c - ss_xy)) for c in cands))
    return np.array(errs)


def report(errs: np.ndarray, offset: int, n_labels: int) -> None:
    if len(errs) == 0:
        print(f"offset={offset}: no overlapping frames (is detect.py run? offset right?)")
        return
    print(f"offset={offset}: matched {len(errs)}/{n_labels} labels | "
          f"median={np.median(errs):.3f} m  mean={errs.mean():.3f} m  "
          f"p90={np.percentile(errs,90):.3f} m  <0.5m={np.mean(errs<0.5)*100:.0f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--search", nargs=3, type=int, metavar=("LO", "HI", "STEP"),
                    help="scan frame offsets to minimize median error")
    args = ap.parse_args()

    m = config.get_match(args.match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    con = db.connect(read_only=True)
    labels = _ss_labels(con, args.match_id, H)
    our_idx = _our_index(con, args.match_id)
    con.close()
    if not our_idx:
        raise SystemExit("no track rows — run detect.py first")

    if args.search:
        lo, hi, step = args.search
        best = None
        for off in range(lo, hi + 1, step):
            errs = errors_for_offset(labels, our_idx, off)
            med = np.median(errs) if len(errs) else float("inf")
            if best is None or med < best[0]:
                best = (med, off, errs)
        report(best[2], best[1], len(labels))
        print(f"best offset = {best[1]} frames (median {best[0]:.3f} m)")
    else:
        report(errors_for_offset(labels, our_idx, args.offset), args.offset, len(labels))


if __name__ == "__main__":
    main()
