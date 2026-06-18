"""Doubles validation metrics from the `tracks` table (ISOLATED, Phase 1, read-only).

The singles AI-Lab shows agreement against ShuttleSet's human labels. Doubles has NO
labels — that is the whole premise of this workstream — so its validation story is
different and honest: how good is the *label-free* 4-player tracking on its own terms?
This computes exactly that, from tracks alone (no video, no models):

  - coverage      : share of in-rally frames where all four players are simultaneously
                    tracked (the segmentation claim — ~98% in-rally on wtf_2024_md_sf);
  - per-slot recall: how often each slot is present across the rally span (the far pair
                    is smaller / more occluded, so its recall is lower);
  - identity stability: median per-frame court displacement per slot, and the count of
                    non-physical >1.5 m jumps between adjacent detections — the ID-swap
                    "teleports" the doubles papers flag as the hard failure mode;
  - segmentation   : rallies isolated from dead-time, and the tracked span.

Rally-scoped via segment.rally_windows so dead-time never skews the numbers. Self-
contained (imports only db + sibling segment) to honour the isolation rule.

CLI:  PYTHONPATH=src python -m badminton.doubles.validate <match_id>
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import db
from . import segment

SLOTS = ("near", "near2", "far", "far2")
TELEPORT_M = 1.5        # a court jump this large between adjacent detections = ID swap
TELEPORT_MAXGAP = 5     # only over near-adjacent frames (a long bridged gap may be real)


def _tracks_in_windows(match_id: str, windows) -> pd.DataFrame:
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "ORDER BY frame_num", [match_id]).fetch_df()
    con.close()
    if df.empty or not windows:
        return df.iloc[0:0]
    mask = np.zeros(len(df), bool)
    for a, b in windows:
        mask |= (df.frame_num >= a) & (df.frame_num <= b)
    return df[mask]


def showcase(match_id: str, fps: float, max_gap: int = 20, min_len: int = 45,
             names: dict | None = None) -> dict | None:
    windows = segment.rally_windows(match_id, max_gap, min_len)
    if not windows:
        return None
    span = sum(b - a + 1 for a, b in windows)
    df = _tracks_in_windows(match_id, windows)

    # coverage: frames (within windows) where all four slots are present
    per_frame = df.groupby("frame_num").player_id.nunique()
    all4 = int((per_frame == 4).sum())

    slots = []
    for slot in SLOTS:
        g = df[df.player_id == slot].sort_values("frame_num")
        present = len(g)
        rec = round(100 * present / span, 1) if span else 0.0
        med_step_cm, teleports = None, 0
        if present >= 2:
            f = g.frame_num.to_numpy()
            x, y = g.court_x.to_numpy(), g.court_y.to_numpy()
            df_f = np.diff(f)
            dist = np.hypot(np.diff(x), np.diff(y))
            adj = df_f > 0
            per = dist[adj] / df_f[adj]                       # metres per frame
            med_step_cm = round(float(np.median(per)) * 100, 1) if per.size else None
            teleports = int(np.sum((dist > TELEPORT_M) & (df_f <= TELEPORT_MAXGAP)))
        slots.append({"slot": slot, "name": (names or {}).get(slot) or slot,
                      "recallPct": rec, "medStepCm": med_step_cm, "teleports": teleports})

    return {
        "coverage": {"inRallyPct": round(100 * all4 / span, 1) if span else 0.0,
                     "frames": int(span), "all4": all4},
        "slots": slots,
        "segmentation": {"rallies": len(windows), "spanS": round(span / fps, 1),
                         "minLen": min_len, "maxGap": max_gap},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles label-free validation metrics (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    from .. import config
    fps = args.fps if args.fps is not None else float(config.get_match(args.match_id)["fps"])
    sc = showcase(args.match_id, fps, args.max_gap, args.min_len)
    if sc is None:
        print(f"no rallies for {args.match_id} — run doubles.track first")
        return
    c = sc["coverage"]
    print(f"coverage: {c['inRallyPct']}% all-4 in-rally ({c['all4']}/{c['frames']} frames)")
    print(f"segmentation: {sc['segmentation']['rallies']} rallies, {sc['segmentation']['spanS']}s span")
    print(pd.DataFrame(sc["slots"]).to_string(index=False))


if __name__ == "__main__":
    main()
