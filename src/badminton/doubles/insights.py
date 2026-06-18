"""Doubles tactical insights — the payoff layer (ISOLATED, Phase 1).

Combines the doubles pieces (rally windows + geometric roles + optional named identity)
into the tactics singles analytics can't express:

  - formation share per side: attack (front/back stack) vs defence (side-by-side);
  - rotations: how often a side switches formation, and how often the front player
    changes (the front/back swap that IS a doubles rotation), per rally;
  - per-player (when a roster is set): share of frames spent at the front vs the rear,
    and mean court position — i.e. who hunts the net vs who covers the rear.

Everything is rally-scoped (via segment.py) so dead-time never pollutes the numbers.

CLI:  PYTHONPATH=src python -m badminton.doubles.insights <match_id> [--set N]
"""

from __future__ import annotations

import argparse

import pandas as pd

from . import identity as _identity
from . import roles, segment


def _count_switches(seq) -> int:
    """Number of adjacent changes in a sequence (formation flips / front-player swaps)."""
    seq = list(seq)
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def rally_report(match_id: str, max_gap: int = 20, min_len: int = 45) -> pd.DataFrame:
    """One row per (rally, side): duration, attack share, formation + front-swap counts."""
    windows = segment.rally_windows(match_id, max_gap, min_len)
    rd = roles.roles_df(match_id)
    out = []
    for i, (a, b) in enumerate(windows, 1):
        seg = rd[(rd.frame_num >= a) & (rd.frame_num <= b)]
        for side in ("near", "far"):
            s = seg[seg.side == side].sort_values("frame_num")
            if s.empty:
                continue
            # de-noised formation + front-player, both via hysteresis (Schmitt) on their margins
            form = roles.hysteresis_formation((s.depth_gap - s.lateral_gap).tolist())
            front = roles.hysteresis(s.front_margin.tolist(), "a", "b", roles.FRONT_BAND)
            out.append({
                "rally": i, "side": side, "frames": len(s),
                "attack_%": round(100 * (pd.Series(form) == "attack").mean(), 0),
                "rotations": _count_switches(form),       # attack<->defence, debounced
                "front_swaps": _count_switches(front),    # front-player changes, debounced
            })
    return pd.DataFrame(out)


def _form_segments(s: pd.DataFrame) -> list[list]:
    """Run-length [startFrame, endFrame, 'attack'|'defence'] of the DEBOUNCED formation
    (Schmitt-triggered, matching roles/render) for one side over its sorted rows."""
    s = s.sort_values("frame_num")
    if s.empty:
        return []
    labels = roles.hysteresis_formation((s.depth_gap - s.lateral_gap).tolist())
    frames = s.frame_num.tolist()
    segs, start, cur, prev = [], frames[0], labels[0], frames[0]
    for f, lab in zip(frames[1:], labels[1:]):
        if lab != cur:
            segs.append([int(start), int(prev), cur])
            start, cur = f, lab
        prev = f
    segs.append([int(start), int(frames[-1]), cur])
    return segs


def formation_flow(match_id: str, max_gap: int = 20, min_len: int = 45) -> dict:
    """How each side's formation *flows* through a rally — the doubles answer to the
    singles shot-pattern view. Returns the per-rally attack/defence run-length segments
    (for a flow strip) plus per-side aggregates: who seizes the attack first, how long
    they hold it, rotation cadence, and the attack<->defence transition split.

    All segments are in VIDEO frames; the exporter converts to seconds for the web."""
    windows = segment.rally_windows(match_id, max_gap, min_len)
    rd = roles.roles_df(match_id)
    rallies: list[dict] = []
    agg = {side: {"attack_first": 0, "defence_first": 0, "rallies": 0,
                  "a2d": 0, "d2a": 0, "rotations": 0,
                  "attack_frames": 0, "total_frames": 0, "holds": []}
           for side in ("near", "far")}
    for i, (a, b) in enumerate(windows, 1):
        seg = rd[(rd.frame_num >= a) & (rd.frame_num <= b)]
        row: dict = {"rally": i, "f0": int(a), "f1": int(b)}
        for side in ("near", "far"):
            segs = _form_segments(seg[seg.side == side])
            row[side] = segs
            if not segs:
                continue
            g = agg[side]
            g["rallies"] += 1
            g["attack_first" if segs[0][2] == "attack" else "defence_first"] += 1
            for s0, s1, lab in segs:
                dur = s1 - s0 + 1
                g["total_frames"] += dur
                if lab == "attack":
                    g["attack_frames"] += dur
                    g["holds"].append(dur)
            for x, y in zip(segs, segs[1:]):
                g["a2d"] += x[2] == "attack" and y[2] == "defence"
                g["d2a"] += x[2] == "defence" and y[2] == "attack"
            g["rotations"] += len(segs) - 1
        rallies.append(row)
    return {"windows": windows, "rallies": rallies, "agg": agg}


def player_report(match_id: str, set_no: int = 1, max_gap: int = 20, min_len: int = 45):
    """Per named player: front share + mean court position over all rally frames.
    Returns None if no identity roster is set for the match/set."""
    try:
        slot_name = _identity.resolve(match_id, set_no)
    except SystemExit:
        return None
    windows = segment.rally_windows(match_id, max_gap, min_len)
    rd = roles.roles_df(match_id)
    in_rally = pd.concat([rd[(rd.frame_num >= a) & (rd.frame_num <= b)] for a, b in windows]) \
        if windows else rd.iloc[0:0]
    # front share per slot from role rows
    rows = []
    for side, slots in (("near", ("near", "near2")), ("far", ("far", "far2"))):
        s = in_rally[in_rally.side == side]
        if s.empty:
            continue
        n = len(s)
        for slot in slots:
            rows.append({"player": slot_name.get(slot, slot), "slot": slot,
                         "front_%": round(100 * (s.front == slot).mean(), 0), "frames": n})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles tactical insights (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--set", type=int, default=1)
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()

    rr = rally_report(args.match_id, args.max_gap, args.min_len)
    if rr.empty:
        print("no rallies found — run doubles.track (+ optionally doubles.smooth) first")
        return
    print("=== per-rally formation (attack = front/back, defence = side-by-side) ===")
    print(rr.to_string(index=False))

    # match-level per-side roll-up (frame-weighted attack share)
    g = rr.assign(aw=rr["attack_%"] * rr.frames).groupby("side")
    summ = g.agg(rallies=("rally", "nunique"), frames=("frames", "sum"),
                 rotations=("rotations", "sum"), front_swaps=("front_swaps", "sum"),
                 aw=("aw", "sum")).reset_index()
    summ["attack_%"] = (summ.aw / summ.frames).round(0)
    print("\n=== match summary (this span) ===")
    print(summ[["side", "rallies", "frames", "attack_%", "rotations", "front_swaps"]].to_string(index=False))
    pr = player_report(args.match_id, args.set, args.max_gap, args.min_len)
    if pr is not None and not pr.empty:
        print("\n=== per-player front-court share (who hunts the net) ===")
        print(pr.to_string(index=False))
    else:
        print("\n(no doubles_identity roster set — skipping per-player report)")


if __name__ == "__main__":
    main()
