"""Doubles roles + formation from the `tracks` table (Phase 0, ISOLATED, read-only).

Pure geometric analysis over near/near2/far/far2 tracks — no model inference, no DB
writes. Per frame and side it derives the labels that actually drive doubles tactics:

  front / back  : the player closer to the net is 'front', the other 'back'
                  (attacker hunts the net, partner covers the rear).
  left / right  : by court_x, camera view (left = smaller x).
  formation     : 'attack'  when the pair is stacked front-to-back (depth gap > lateral
                  gap) — the offensive rotation;
                  'defence' when side-by-side (lateral gap >= depth gap) — receiving
                  a smash.

Crucially these are recomputed every frame from geometry, so they are INVARIANT to
which physical player the tracker tagged 'near' vs 'near2'. That is the whole reason
doubles tactics lean on roles instead of persistent names: role labels survive the
identity switches that broadcast occlusion makes inevitable.

(Persistent identity — pinning 'near' to a specific athlete all match — is the tracker's
job and is only needed for per-athlete career stats. A future refinement seeds it at the
serve, where the service court is fixed by score parity; roles below do not depend on it.)

CLI:
  PYTHONPATH=src python -m badminton.doubles.roles <match_id>   # formation summary
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import court, db

NEAR_SLOTS = ("near", "near2")
FAR_SLOTS = ("far", "far2")


# Hysteresis bands (metres). A binary call that flips whenever a margin crosses zero
# flickers every frame when the two players are near-balanced (diagonal stance, or equal
# depth), inflating rotation counts. Require the margin to clear ±band before switching —
# a Schmitt trigger. FORMATION_BAND: depth_gap vs lateral_gap. FRONT_BAND: the two
# players' net-distance difference (who is the front player).
FORMATION_BAND = 0.4
FRONT_BAND = 0.5


def hysteresis(margins, pos: str, neg: str, band: float) -> list[str]:
    """Debounced label sequence: switch to `pos` only when margin > +band, to `neg` only
    when < -band, else hold the previous state (seed from the sign of the first margin)."""
    state = None
    out = []
    for m in margins:
        if state is None:
            state = pos if m >= 0 else neg
        elif m > band:
            state = pos
        elif m < -band:
            state = neg
        out.append(state)
    return out


def hysteresis_formation(margins, band: float = FORMATION_BAND) -> list[str]:
    """Debounced attack/defence from a per-frame margin = depth_gap - lateral_gap."""
    return hysteresis(margins, "attack", "defence", band)


def _pair_roles(a: pd.Series, b: pd.Series) -> dict:
    """Roles for one side from its two players' rows (each has court_x, court_y).
    `front` is the slot closer to the net (smaller |y - net|)."""
    da = abs(a.court_y - court.NET_Y_M)
    db_ = abs(b.court_y - court.NET_Y_M)
    front, back = (a, b) if da <= db_ else (b, a)
    left, right = (a, b) if a.court_x <= b.court_x else (b, a)
    depth_gap = float(abs(a.court_y - b.court_y))
    lateral_gap = float(abs(a.court_x - b.court_x))
    return {
        "front": front.player_id, "back": back.player_id,
        "left": left.player_id, "right": right.player_id,
        "depth_gap": depth_gap, "lateral_gap": lateral_gap,
        # signed: >0 means slot a (first arg) is the front player; for debouncing front_swaps
        "front_margin": float(db_ - da),
        "formation": "attack" if depth_gap > lateral_gap else "defence",
    }


def roles_df(match_id: str) -> pd.DataFrame:
    """One row per (frame, side) where BOTH that side's players are tracked, with
    front/back/left/right slot labels, depth/lateral gaps, and formation."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "ORDER BY frame_num", [match_id]).fetch_df()
    con.close()

    rows = []
    for frame, g in df.groupby("frame_num"):
        by_id = {r.player_id: r for r in g.itertuples(index=False)}
        for side, slots in (("near", NEAR_SLOTS), ("far", FAR_SLOTS)):
            if slots[0] in by_id and slots[1] in by_id:
                rows.append({"frame_num": int(frame), "side": side,
                             **_pair_roles(by_id[slots[0]], by_id[slots[1]])})
    return pd.DataFrame(rows)


def formation_summary(match_id: str) -> pd.DataFrame:
    """Per-side share of attack vs defence frames + median gaps — the cheap sanity
    check that the 4-player tracking and role logic are producing sane geometry
    before any of it reaches the dashboard."""
    rd = roles_df(match_id)
    if rd.empty:
        return rd
    out = []
    for side, g in rd.groupby("side"):
        n = len(g)
        out.append({
            "side": side, "frames": n,
            "attack_%": round(100 * (g.formation == "attack").mean(), 1),
            "defence_%": round(100 * (g.formation == "defence").mean(), 1),
            "median_depth_gap_m": round(float(np.median(g.depth_gap)), 2),
            "median_lateral_gap_m": round(float(np.median(g.lateral_gap)), 2),
        })
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles roles/formation summary (isolated)")
    ap.add_argument("match_id")
    args = ap.parse_args()
    summ = formation_summary(args.match_id)
    if summ.empty:
        print(f"no two-per-side frames for {args.match_id} — run "
              f"`python -m badminton.doubles.track {args.match_id}` first")
    else:
        print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
