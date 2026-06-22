"""Doubles Tier-1 strokes from the shuttle track + 4-player tracks (isolated).

Singles `hits.py` (velocity-kink detection + 2D nearest-wrist attribution) does NOT
transfer to this broadcast. The shuttle is AIRBORNE at contact, so it projects up-frame
toward the far court; 2D nearest-wrist is then systematically far-biased — measured
~37% net-crossing alternation on real rallies (a clean rally MUST alternate N/F/N/F, so
~37% means roughly half the hits are mis-sided or phantom). Don't build strokes on it.

Exploit the camera geometry instead: a contact is a local EXTREMUM of the shuttle's
image-y. The near corners sit at the BOTTOM of the frame (large img_y), far at the TOP,
so a near-court contact is a local MAX of img_y and a far-court contact a local MIN.
They alternate by physics — detection AND side for free (~90% alternation on real
rallies), with no airborne-shuttle attribution. Within a side, the slot (which partner)
is the nearest same-side player: noisy (partners stand close together) but it can never
cross sides, so the worst case is a partner swap, not a side error.

Honesty: doubles has NO ShuttleSet labels, so there is no per-shot accuracy gate. The
only real quality proxy is net-crossing alternation (computed below). Shot type is the
singles-trained geometry baseline (`shotclass.py`), stored with classifier='geometry' —
transparent that it is transferred, NOT validated on doubles. Don't read it as truth.

CLI:
  PYTHONPATH=src python -m badminton.doubles.strokes <id>          # build + report
  PYTHONPATH=src python -m badminton.doubles.strokes <id> --write  # persist to strokes
  PYTHONPATH=src python -m badminton.doubles.strokes <id> --demo   # self-check
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import config, court, db, hits, shotclass
from . import segment

W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M
SIDES = {"near": ("near", "near2"), "far": ("far", "far2")}
MIN_GAP = 7          # min frames between contacts (fastest doubles exchanges)
PROM_FRAC = 0.12     # extremum prominence as a fraction of the rally's img_y span
SMOOTH = 3           # img_y rolling-mean window (kills 1-frame tracker wobble)
TRAIN_MATCH = "india_open_2022_final"   # labels that train the geometry shot baseline


def contacts(match_id: str, f0: int, f1: int, min_visible: int = 10) -> list[dict]:
    """Contacts in video-frame window [f0, f1] as shuttle img_y extrema:
    local MAX = near-court contact, local MIN = far-court contact (see module docstring).
    Returns time-sorted dicts; near/far alternate by physics on a clean rally."""
    from scipy.signal import find_peaks
    s = hits.shuttle_series(match_id, f0, f1)          # interpolated img_x/img_y
    x, y = s["img_x"].to_numpy(), s["img_y"].to_numpy()
    frames = s.index.to_numpy()
    ok = ~np.isnan(y)
    if ok.sum() < min_visible:
        return []
    # fill the leading/trailing NaNs left by interpolate(limit_area='inside') so the
    # peak finder sees a continuous signal; smooth out single-frame tracker jitter.
    idx = np.arange(len(y))
    yi = np.interp(idx, idx[ok], y[ok])
    xi = np.interp(idx, idx[ok], x[ok])
    ys = np.convolve(yi, np.ones(SMOOTH) / SMOOTH, "same")
    prom = max(15.0, (ys.max() - ys.min()) * PROM_FRAC)
    pmax, mx = find_peaks(ys, prominence=prom, distance=MIN_GAP)
    pmin, mn = find_peaks(-ys, prominence=prom, distance=MIN_GAP)
    ev = [(int(i), "near", float(p)) for i, p in zip(pmax, mx["prominences"])] + \
         [(int(i), "far", float(p)) for i, p in zip(pmin, mn["prominences"])]
    ev.sort()
    return [dict(frame=int(frames[i]), x=float(xi[i]), y=float(yi[i]),
                 side=side, prom=prom_i) for i, side, prom_i in ev]


def enforce_alternation(cs: list[dict]) -> list[dict]:
    """Collapse consecutive same-side contacts, keeping the more extreme one — the
    real contact; its same-side neighbour is a flight apex or a tracker wobble that
    the extremum finder picked up. Result strictly alternates N/F. ponytail: greedy
    single pass, good enough; a DP that also recovers missed opposite-side contacts
    would help the few rallies where tracking drops the shuttle mid-flight."""
    out: list[dict] = []
    for c in cs:
        if out and out[-1]["side"] == c["side"]:
            # near wants the larger img_y (lower in frame), far the smaller
            c_more = (c["y"] > out[-1]["y"]) if c["side"] == "near" else (c["y"] < out[-1]["y"])
            if c_more:
                out[-1] = c
        else:
            out.append(c)
    return out


def attribute(match_id: str, cs: list[dict]) -> None:
    """Set c['slot'] (which of the side's two partners) + c['dist_px'] by nearest
    wrist/bbox WITHIN the contact's side. Side is fixed by geometry, so this can only
    pick the wrong partner, never the wrong side."""
    if not cs:
        return
    refs = hits._player_refs(match_id, min(c["frame"] for c in cs) - 2,
                             max(c["frame"] for c in cs) + 2)
    for c in cs:
        best, best_d = None, np.inf
        for slot in SIDES[c["side"]]:
            for df_ in (-1, 0, 1):
                for (px, py) in refs.get((c["frame"] + df_, slot), []):
                    d = float(np.hypot(px - c["x"], py - c["y"]))
                    if d < best_d:
                        best, best_d = slot, d
        c["slot"] = best or SIDES[c["side"]][0]      # fall back to the side's first slot
        c["dist_px"] = best_d if best else None


def _track_pos(con, match_id: str, frame: int, slot: str, img: bool = False):
    row = con.execute(
        "SELECT court_x, court_y, img_y FROM tracks WHERE match_id=? AND player_id=? "
        "AND frame_num BETWEEN ? AND ? ORDER BY ABS(frame_num - ?) LIMIT 1",
        [match_id, slot, frame - 3, frame + 3, frame]).fetchone()
    if row is None:
        return (None, None, None) if img else (None, None)
    return (float(row[0]), float(row[1]), row[2]) if img else (float(row[0]), float(row[1]))


def build(match_id: str) -> pd.DataFrame:
    """One row per detected doubles contact across all gated rallies, with court
    positions + landing + normalized geometry features (hitter at the bottom)."""
    H = np.array(config.get_match(match_id)["homography"], np.float32).reshape(3, 3)
    con = db.connect(read_only=True)
    rows = []
    for rid, (f0, f1) in enumerate(segment.rally_windows(match_id), 1):
        cs = enforce_alternation(contacts(match_id, f0, f1))
        attribute(match_id, cs)
        if len(cs) < 2:
            continue
        # landing(i) ≈ where the NEXT contact's hitter stands (feet on the floor plane,
        # homography-valid); the mid-air shuttle projects metres deep. Final contact
        # uses the trajectory's floor landing. Same convention as singles pipeline.py.
        land = [_track_pos(con, match_id, cs[i + 1]["frame"], cs[i + 1]["slot"])
                for i in range(len(cs) - 1)]
        fin = hits.find_landing(match_id, cs[-1]["frame"])
        land.append((fin["court_x"], fin["court_y"]) if fin else (None, None))

        for i, c in enumerate(cs):
            hitter, side = c["slot"], c["side"]
            recv = cs[i + 1]["slot"] if i + 1 < len(cs) else SIDES["far" if side == "near" else "near"][0]
            hx, hy, h_img_y = _track_pos(con, match_id, c["frame"], hitter, img=True)
            rx, ry = _track_pos(con, match_id, c["frame"], recv)
            lx, ly = land[i]
            rows.append(dict(
                match_id=match_id, set_no=0, rally_id=rid, ball_round=i + 1,
                frame_num=c["frame"], hitter=hitter, receiver=recv, side=side,
                hitter_x=hx, hitter_y=hy, receiver_x=rx, receiver_y=ry,
                hit_img_x=c["x"], hit_img_y=c["y"], landing_x=lx, landing_y=ly,
                contact_rel_px=(c["y"] - h_img_y) if h_img_y is not None else np.nan,
                hit_score=c["prom"], is_serve=(i == 0),
                dt_prev=c["frame"] - cs[i - 1]["frame"] if i else np.nan,
                dt_next=cs[i + 1]["frame"] - c["frame"] if i + 1 < len(cs) else np.nan,
            ))
    con.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    flip = (df["side"] == "far").to_numpy()            # normalize so the hitter is at the bottom
    for sx, sy, nx, ny in [("hitter_x", "hitter_y", "hitter_nx", "hitter_ny"),
                           ("receiver_x", "receiver_y", "recv_nx", "recv_ny"),
                           ("landing_x", "landing_y", "land_nx", "land_ny")]:
        df[nx] = np.where(flip, W - df[sx], df[sx])
        df[ny] = np.where(flip, L - df[sy], df[sy])
    df["depth_delta"] = df["land_ny"] - df["hitter_ny"]
    df["lat_delta"] = (df["land_nx"] - df["hitter_nx"]).abs()
    dist = np.hypot(df["land_nx"] - df["hitter_nx"], df["land_ny"] - df["hitter_ny"])
    df["speed_proxy"] = dist / df["dt_next"]
    df["opp_depth_delta"] = df["land_ny"] - df["recv_ny"]

    # plausibility gates (mirror pipeline): a missed neighbour poisons landing/dt.
    land_cols = ["landing_x", "landing_y", "land_nx", "land_ny",
                 "depth_delta", "lat_delta", "speed_proxy", "opp_depth_delta"]
    df.loc[(df["dt_next"] > 60) | (df["land_ny"] < 5.5), land_cols] = np.nan
    df.loc[df["dt_next"] > 60, "dt_next"] = np.nan
    df.loc[df["dt_prev"] > 60, "dt_prev"] = np.nan
    return df


def classify(df: pd.DataFrame, train_match: str = TRAIN_MATCH) -> pd.DataFrame:
    """Geometry shot baseline trained on a LABELED singles match (no BST, no labels for
    doubles). Stored with classifier='geometry' — a transferred guess, not validated."""
    if df.empty:
        return df
    tr = shotclass.build_features(train_match, feet_landing=True)
    clf = shotclass._model().fit(tr[shotclass.CV_FEATURES], tr["shot"])
    df = df.copy()
    df["shot_type"] = clf.predict(df[shotclass.CV_FEATURES])
    df["shot_type_conf"] = clf.predict_proba(df[shotclass.CV_FEATURES]).max(axis=1)
    df["classifier"] = "geometry"
    return df


def write(match_id: str, df: pd.DataFrame) -> int:
    """Persist as source='pipeline' rows keyed by match_id (idempotent per match).
    Shares the strokes table with singles — safe, every read filters by match_id and
    the doubles id never appears in a singles query."""
    con = db.connect()
    try:
        con.execute("DELETE FROM strokes WHERE match_id=? AND source='pipeline'", [match_id])
        base = con.execute("SELECT COALESCE(MAX(stroke_id), 0) + 1 FROM strokes").fetchone()[0]
        recs = [(int(base + i), match_id, int(r.set_no), int(r.rally_id),
                 int(r.ball_round), int(r.frame_num), r.hitter, r.receiver,
                 r.shot_type, "court_m", _f(r.hitter_x), _f(r.hitter_y),
                 _f(r.receiver_x), _f(r.receiver_y), float(r.hit_img_x), float(r.hit_img_y),
                 _f(r.landing_x), _f(r.landing_y), float(r.shot_type_conf), "pipeline")
                for i, r in enumerate(df.itertuples())]
        con.executemany(
            "INSERT INTO strokes (stroke_id, match_id, set_no, rally_id, ball_round,"
            " frame_num, hitter, receiver, shot_type, coord_space,"
            " hitter_x, hitter_y, receiver_x, receiver_y, hit_x, hit_y,"
            " landing_x, landing_y, shot_type_conf, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", recs)
    finally:
        con.close()
    return len(df)


def _f(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def alternation(df: pd.DataFrame) -> float:
    """Pooled fraction of adjacent contacts that switch side — the doubles quality
    proxy (a clean rally alternates N/F/N/F, so 1.0 is ideal)."""
    sw = tot = 0
    for _, g in df.groupby("rally_id"):
        s = g.sort_values("ball_round")["side"].to_numpy()
        sw += int((s[1:] != s[:-1]).sum())
        tot += len(s) - 1
    return sw / tot if tot else 0.0


def raw_alternation(match_id: str) -> float:
    """Pooled side-alternation of the detector BEFORE enforce_alternation — the real
    quality gate (post-collapse is 100% by construction). The singles nearest-wrist
    baseline scored ~37% here; the img_y-extrema detector should be ~90%."""
    sw = tot = 0
    for f0, f1 in segment.rally_windows(match_id):
        s = [c["side"] for c in contacts(match_id, f0, f1)]
        sw += sum(a != b for a, b in zip(s, s[1:]))
        tot += max(0, len(s) - 1)
    return sw / tot if tot else 0.0


def demo() -> None:
    """Self-check: the geometry detector must alternate sides far better than the
    singles nearest-wrist baseline did (~37%). Asserts on real tracked data."""
    df = build("wtf_2024_md_sf")
    raw = raw_alternation("wtf_2024_md_sf")
    print(f"[demo] {len(df)} contacts over {df['rally_id'].nunique()} rallies; "
          f"raw detector alternation {raw:.0%} (baseline ~37%)")
    assert len(df) > 500, f"too few contacts: {len(df)}"
    assert raw > 0.75, f"raw alternation {raw:.0%} — detector regressed (was ~90%)"
    print("[demo] OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Doubles strokes from img_y-extrema contacts")
    ap.add_argument("match_id", nargs="?", default="wtf_2024_md_sf")
    ap.add_argument("--write", action="store_true", help="persist to the strokes table")
    ap.add_argument("--demo", action="store_true", help="run the self-check")
    args = ap.parse_args()
    if args.demo:
        demo()
    else:
        df = classify(build(args.match_id))
        print(f"{len(df)} contacts, {df['rally_id'].nunique()} rallies, "
              f"alternation {alternation(df):.0%}")
        if not df.empty:
            print("shot mix (geometry baseline, unvalidated):")
            print(df["shot_type"].value_counts().to_string())
        if args.write:
            print(f"wrote {write(args.match_id, df)} source='pipeline' rows")
