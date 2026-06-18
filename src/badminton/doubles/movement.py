"""Doubles per-slot movement from the `tracks` table (ISOLATED, Phase 1, read-only).

The singles "Court" view answers "who did the running"; this is its doubles analogue,
but per SLOT (near/near2/far/far2 = the four players on court) instead of per side.
For each slot it derives, over the rally span only:

  - distance covered (m), mean speed (m/s), coverage area (m^2);
  - front / mid / back court occupancy (front = hunting the net, back = covering the
    rear) — the role split that singles can't express the same way;
  - a positional heatmap, NORMALISED so every player lands on a single near-half court
    (net at the top), exactly the shape the singles `court.tsx::HeatMap` expects.

Normalisation mirrors the far side (x -> W-x, y -> L-y) onto the near half so all four
players are directly comparable. Everything is rally-scoped via `segment.rally_windows`
so dead-time between points never inflates distance/coverage; distance is summed PER
rally (never across the gap between rallies) and positions are median-smoothed before
differencing, so tracker jitter doesn't bloat the totals — the same de-jitter the
singles `analytics.player_metrics` does, re-implemented here to keep the doubles surface
self-contained and deletable (the isolation rule: import only court/db + siblings).

CLI:  PYTHONPATH=src python -m badminton.doubles.movement <match_id>
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import court, db
from . import segment

SLOTS = ("near", "near2", "far", "far2")
NEAR_SLOTS = frozenset({"near", "near2"})
SIDE_OF = {"near": "near", "near2": "near", "far": "far", "far2": "far"}

W = court.COURT_WIDTH_M          # 6.10
L = court.COURT_LENGTH_M         # 13.40
NET = court.NET_Y_M              # 6.70

SMOOTH_WIN = 5                   # rolling-median window, de-jitter before distance
MAX_SPEED = 9.0                  # m/s cap — reject detection glitches (elite peak ~6-7)
HEAT_BINS = (12, 14)             # must match singles export_web for HeatMap reuse
HEAT_RANGE = ((0.0, W), (0.0, NET + 0.5))


def _smooth(a: np.ndarray, win: int = SMOOTH_WIN) -> np.ndarray:
    """Rolling median (de-jitter), matching analytics._smooth."""
    if len(a) < win:
        return a
    h = win // 2
    return np.array([np.median(a[max(0, i - h):i + h + 1]) for i in range(len(a))])


def _heat(P: np.ndarray) -> dict:
    """2D occupancy histogram over the near half — identical bins/shape to the singles
    exporter so `court.tsx::HeatMap` renders it unchanged."""
    h, _, _ = np.histogram2d(P[:, 0], P[:, 1], bins=HEAT_BINS, range=HEAT_RANGE)
    cells = [[i, j, int(h[i, j])] for i in range(HEAT_BINS[0])
             for j in range(HEAT_BINS[1]) if h[i, j] > 0]
    return dict(nx=HEAT_BINS[0], ny=HEAT_BINS[1],
                x1=HEAT_RANGE[0][1], y1=HEAT_RANGE[1][1], cells=cells)


def _to_near_half(P: np.ndarray, slot: str) -> np.ndarray:
    """Mirror a far-side slot's (x, y) onto the near half so every player is plotted on
    one comparable half-court (net at top). Near slots pass through unchanged."""
    if slot in NEAR_SLOTS:
        return P
    out = P.copy()
    out[:, 0] = W - out[:, 0]
    out[:, 1] = L - out[:, 1]
    return out


def _slot_tracks(match_id: str, windows) -> dict[str, list[np.ndarray]]:
    """Per slot, the list of per-rally (N,3) frame/x/y arrays inside the rally windows."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "ORDER BY frame_num", [match_id]).fetch_df()
    con.close()
    out: dict[str, list[np.ndarray]] = {s: [] for s in SLOTS}
    if df.empty:
        return out
    for a, b in windows:
        win = df[(df.frame_num >= a) & (df.frame_num <= b)]
        for slot in SLOTS:
            g = win[win.player_id == slot]
            if len(g) >= 3:
                out[slot].append(g[["frame_num", "court_x", "court_y"]].to_numpy(float))
    return out


def slot_movement(match_id: str, fps: float,
                  max_gap: int = 20, min_len: int = 45) -> dict[str, dict]:
    """Per-slot movement metrics + normalised positions for the heatmap. Distance/seconds
    accumulate PER rally; positions accumulate across rallies for heat/coverage/occupancy."""
    windows = segment.rally_windows(match_id, max_gap, min_len)
    tracks = _slot_tracks(match_id, windows)

    out: dict[str, dict] = {}
    for slot in SLOTS:
        dist = secs = 0.0
        pos: list[np.ndarray] = []
        for arr in tracks[slot]:
            f = arr[:, 0]
            x, y = _smooth(arr[:, 1]), _smooth(arr[:, 2])
            dt = np.diff(f) / fps
            step = np.hypot(np.diff(x), np.diff(y))
            sp = np.divide(step, dt, out=np.zeros_like(step), where=dt > 0)
            good = (sp <= MAX_SPEED) & (dt > 0)
            dist += float(step[good].sum())
            secs += float((f[-1] - f[0]) / fps)
            pos.append(_to_near_half(np.column_stack([x, y]), slot))
        if not pos:
            continue
        P = np.vstack(pos)
        px, py = P[:, 0], P[:, 1]
        d_net = np.abs(py - NET)                       # 0 = at net, NET = own baseline
        front = round(float(np.mean(d_net < NET / 3) * 100))
        back = round(float(np.mean(d_net > 2 * NET / 3) * 100))
        out[slot] = dict(
            slot=slot, side=SIDE_OF[slot],
            distM=round(dist), secs=round(secs),
            speed=round(dist / secs, 2) if secs else 0.0,
            cov=round(float(np.pi * 2 * px.std() * 2 * py.std()), 1),
            front=front, mid=100 - front - back, back=back,
            heat=_heat(P),
        )
    return out


def _pos_metrics(dist: float, secs: float, pos: list[np.ndarray]) -> dict | None:
    """Shared distance/speed/coverage/occupancy/heat block from accumulated positions."""
    if not pos:
        return None
    P = np.vstack(pos)
    px, py = P[:, 0], P[:, 1]
    d_net = np.abs(py - NET)
    front = round(float(np.mean(d_net < NET / 3) * 100))
    back = round(float(np.mean(d_net > 2 * NET / 3) * 100))
    return dict(
        distM=round(dist), secs=round(secs),
        speed=round(dist / secs, 2) if secs else 0.0,
        cov=round(float(np.pi * 2 * px.std() * 2 * py.std()), 1),
        front=front, mid=100 - front - back, back=back,
        heat=_heat(P),
    )


def team_movement(match_id: str, fps: float, rally_sides: list[dict]) -> dict[str, dict]:
    """Per-TEAM movement across the whole match, swap-safe. `rally_sides` gives each rally's
    {start, end, near_pair, far_pair}; for every rally the near side's two players feed the
    near_pair and the far side's feed the far_pair, with far positions mirrored onto the near
    half. Combining a pair's two players (rather than tracking each across set end-swaps)
    keeps it robustly correct — a pair's heatmap shows the team's court coverage regardless
    of which physical slot held which player in which set."""
    con = db.connect(read_only=True)
    acc: dict[str, dict] = {}  # pair -> {dist, secs, pos[]}
    for r in rally_sides:
        a, b = r["start"], r["end"]
        df = con.execute(
            "SELECT frame_num, player_id, court_x, court_y FROM tracks WHERE match_id=? "
            "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ? "
            "ORDER BY frame_num", [match_id, a, b]).fetch_df()
        if df.empty:
            continue
        for side, slots, pair in (("near", ("near", "near2"), r["near_pair"]),
                                  ("far", ("far", "far2"), r["far_pair"])):
            t = acc.setdefault(pair, {"dist": 0.0, "secs": 0.0, "pos": []})
            for slot in slots:
                g = df[df.player_id == slot]
                if len(g) < 3:
                    continue
                arr = g[["frame_num", "court_x", "court_y"]].to_numpy(float)
                f = arr[:, 0]
                x, y = _smooth(arr[:, 1]), _smooth(arr[:, 2])
                dt = np.diff(f) / fps
                step = np.hypot(np.diff(x), np.diff(y))
                sp = np.divide(step, dt, out=np.zeros_like(step), where=dt > 0)
                good = (sp <= MAX_SPEED) & (dt > 0)
                t["dist"] += float(step[good].sum())
                t["secs"] += float((f[-1] - f[0]) / fps)
                t["pos"].append(_to_near_half(np.column_stack([x, y]), slot))
    con.close()
    out: dict[str, dict] = {}
    for pair, t in acc.items():
        m = _pos_metrics(t["dist"], t["secs"], t["pos"])
        if m:
            out[pair] = dict(pair=pair, **m)
    return out


def player_movement(match_id: str, fps: float, rally_sides: list[dict],
                    team_names: dict | None) -> list[dict]:
    """Per-PLAYER movement, one entry per (set, team, within-pair index) — i.e. FOUR
    players per set, the per-person answer the team-combined `team_movement` can't give.

    Keyed by TEAM (not court slot) so it survives the end-swaps: each rally's near side
    feeds `near_pair`, its far side feeds `far_pair`, and within a side the two tracker
    slots become within-pair indices 0/1 (near/far -> 0, near2/far2 -> 1). Far positions
    are mirrored onto the near half (`_to_near_half`) so all four players are comparable.
    Distance/seconds accumulate PER rally; positions accumulate for heat/coverage/zones.

    Names come from `team_names` ((team, idx) -> name) only for set 1 (the roster-anchored
    set); other sets carry name=None and the web shows the (always-known) pair name + P1/P2.
    `rally_sides`: [{start, end, set, near_pair, far_pair}, ...]."""
    team_names = team_names or {}
    con = db.connect(read_only=True)
    acc: dict[tuple, dict] = {}
    for r in rally_sides:
        a, b, sn = r["start"], r["end"], r["set"]
        df = con.execute(
            "SELECT frame_num, player_id, court_x, court_y FROM tracks WHERE match_id=? "
            "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ? "
            "ORDER BY frame_num", [match_id, a, b]).fetch_df()
        if df.empty:
            continue
        for slots, team in ((("near", "near2"), r["near_pair"]),
                            (("far", "far2"), r["far_pair"])):
            for idx, slot in enumerate(slots):
                g = df[df.player_id == slot]
                if len(g) < 3:
                    continue
                arr = g[["frame_num", "court_x", "court_y"]].to_numpy(float)
                f = arr[:, 0]
                x, y = _smooth(arr[:, 1]), _smooth(arr[:, 2])
                dt = np.diff(f) / fps
                step = np.hypot(np.diff(x), np.diff(y))
                sp = np.divide(step, dt, out=np.zeros_like(step), where=dt > 0)
                good = (sp <= MAX_SPEED) & (dt > 0)
                t = acc.setdefault((sn, team, idx), {"dist": 0.0, "secs": 0.0, "pos": []})
                t["dist"] += float(step[good].sum())
                t["secs"] += float((f[-1] - f[0]) / fps)
                t["pos"].append(_to_near_half(np.column_stack([x, y]), slot))
    con.close()
    out: list[dict] = []
    for (sn, team, idx), t in sorted(acc.items()):
        m = _pos_metrics(t["dist"], t["secs"], t["pos"])
        if m:
            # name ONLY set 1 (the roster-anchored set). In later sets the pairs swapped
            # ends and the within-pair index isn't re-anchored, so naming it would be a
            # 50/50 guess — leave None and let the web show the pair label + P1/P2.
            name = team_names.get((team, idx)) if sn == 1 else None
            out.append(dict(set=int(sn), team=team, idx=idx, name=name, **m))
    return out


REACH_M = 1.5          # how far a player can plausibly cover a cell (racket + lunge)
CTRL_GRID = (8, 10)    # nx, ny cells over one half (x in [0,W], y in [0,NET])


def court_control(match_id: str, fps: float,
                  max_gap: int = 20, min_len: int = 45) -> dict | None:
    """Per-team court control on its OWN half, time-averaged over in-rally frames.

    Whole-court Voronoi is the wrong tool for badminton (the net splits the court and
    each pair defends only its own half), so this answers the question that IS doubles:
    on a team's own half, which partner is responsible for each zone (nearest-partner
    territory share) and how much of the half is left uncovered (no partner within
    REACH_M — the gap a smash can exploit). Far-side positions are mirrored onto the
    near half (via _to_near_half) so both teams use one comparable coordinate frame."""
    windows = segment.rally_windows(match_id, max_gap, min_len)
    if not windows:
        return None
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "ORDER BY frame_num", [match_id]).fetch_df()
    con.close()
    if df.empty:
        return None
    mask = np.zeros(len(df), bool)
    for a, b in windows:
        mask |= (df.frame_num >= a) & (df.frame_num <= b)
    df = df[mask]

    nx, ny = CTRL_GRID
    xs = (np.arange(nx) + 0.5) / nx * W
    ys = (np.arange(ny) + 0.5) / ny * NET
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    cells = np.column_stack([gx.ravel(), gy.ravel()])       # (nx*ny, 2)

    out: dict = {}
    for side, slots in (("near", ("near", "near2")), ("far", ("far", "far2"))):
        sdf = df[df.player_id.isin(slots)]
        cov_acc, nf = 0.0, 0
        terr = {slots[0]: 0.0, slots[1]: 0.0}
        for _, g in sdf.groupby("frame_num"):
            pos = {r.player_id: (r.court_x, r.court_y) for r in g.itertuples(index=False)}
            if slots[0] not in pos or slots[1] not in pos:
                continue
            p0 = _to_near_half(np.array([pos[slots[0]]], float), slots[0])[0]
            p1 = _to_near_half(np.array([pos[slots[1]]], float), slots[1])[0]
            d0 = np.hypot(cells[:, 0] - p0[0], cells[:, 1] - p0[1])
            d1 = np.hypot(cells[:, 0] - p1[0], cells[:, 1] - p1[1])
            cov_acc += float((np.minimum(d0, d1) <= REACH_M).mean())
            nearer0 = d0 <= d1
            terr[slots[0]] += float(nearer0.mean())
            terr[slots[1]] += float((~nearer0).mean())
            nf += 1
        if nf == 0:
            continue
        out[side] = {
            "frames": nf,
            "coveragePct": round(100 * cov_acc / nf, 1),
            "gapPct": round(100 * (1 - cov_acc / nf), 1),
            "territory": {s: round(100 * terr[s] / nf, 1) for s in slots},
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles per-slot movement (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    from .. import config
    fps = args.fps if args.fps is not None else float(config.get_match(args.match_id)["fps"])
    mv = slot_movement(args.match_id, fps, args.max_gap, args.min_len)
    if not mv:
        print(f"no tracked slots for {args.match_id} — run doubles.track first")
        return
    rows = [{k: v for k, v in m.items() if k != "heat"} for m in mv.values()]
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
