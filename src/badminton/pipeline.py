"""Label-free Tier-1: assemble the CV outputs into `strokes` rows (source='pipeline').

Per rally: detected hits (hits.py) → hitter/receiver court positions (tracks at the
hit frame) → landing = next contact's shuttle position (final stroke: find_landing)
→ geometry shot classifier (shotclass.py) trained on the OTHER match's labels.

Still label-dependent (deliberately, for now): rally WINDOWS + the per-set side map
come from ShuttleSet. Replacing those needs a rally segmenter (shuttle-motion runs +
replay rejection) — listed in HANDOFF next steps. Everything inside a rally is CV-only.

CLI:
  PYTHONPATH=src python -m badminton.pipeline <match_id>          # build + evaluate
  PYTHONPATH=src python -m badminton.pipeline <match_id> --write  # also persist to DB
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import config, court, db, hits, insights, shotclass

W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M


def _track_pos(con, match_id: str, frame: int, player: str, img: bool = False):
    row = con.execute(
        "SELECT court_x, court_y, img_y FROM tracks WHERE match_id=? AND player_id=? "
        "AND frame_num BETWEEN ? AND ? ORDER BY ABS(frame_num - ?) LIMIT 1",
        [match_id, player, frame - 3, frame + 3, frame]).fetchone()
    if row is None:
        return (None, None, None) if img else (None, None)
    return (float(row[0]), float(row[1]), float(row[2])) if img \
        else (float(row[0]), float(row[1]))


def build_strokes(match_id: str) -> pd.DataFrame:
    """One row per DETECTED stroke, with court coords + geometry features."""
    sdf = insights.stroke_df(match_id)
    H = np.array(config.get_match(match_id)["homography"], np.float32).reshape(3, 3)
    con = db.connect(read_only=True)

    rows = []
    for (sn, rid), g in sdf.groupby(["set_no", "rally_id"]):
        lab_f = (g["frame_num"].astype(int) - 1)
        f0, f1 = int(lab_f.min() - 20), int(lab_f.max() + 20)
        dh = hits.detect_hits(match_id, f0, f1)
        hits.attribute_hits(match_id, dh)
        dh = [h for h in dh if h.get("player") in ("near", "far")]
        if not dh:
            continue

        # Landing of stroke i ≈ where the NEXT hitter stands at contact i+1. Player
        # feet are ON the floor plane (homography-valid, tracked to ~0.57 m); the
        # shuttle's image position at contact is MID-AIR and projects metres deep.
        # The final stroke uses the real floor landing from the trajectory.
        land_xy = [_track_pos(con, match_id, dh[i + 1]["frame"], dh[i + 1]["player"])
                   for i in range(len(dh) - 1)]
        fin = hits.find_landing(match_id, dh[-1]["frame"])
        land_xy.append((fin["court_x"], fin["court_y"]) if fin else (None, None))

        for i, h in enumerate(dh):
            hitter = h["player"]
            recv = "far" if hitter == "near" else "near"
            hx, hy, h_img_y = _track_pos(con, match_id, h["frame"], hitter, img=True)
            rx, ry = _track_pos(con, match_id, h["frame"], recv)
            lx, ly = land_xy[i]
            rows.append(dict(
                match_id=match_id, set_no=int(sn), rally_id=int(rid),
                ball_round=i + 1, frame_num=h["frame"], hitter=hitter, receiver=recv,
                hitter_x=hx, hitter_y=hy, receiver_x=rx, receiver_y=ry,
                hit_img_x=h["x"], hit_img_y=h["y"], landing_x=lx, landing_y=ly,
                contact_rel_px=(h["y"] - h_img_y) if h_img_y is not None else np.nan,
                hit_score=h["score"], is_serve=bool(h.get("serve")),
                dt_prev=h["frame"] - dh[i - 1]["frame"] if i else np.nan,
                dt_next=dh[i + 1]["frame"] - h["frame"] if i + 1 < len(dh) else np.nan,
            ))
    con.close()
    df = pd.DataFrame(rows)

    # normalized geometry features (hitter at the bottom), mirroring shotclass
    flip = (df["hitter"] == "far").to_numpy()
    for src_x, src_y, nx, ny in [("hitter_x", "hitter_y", "hitter_nx", "hitter_ny"),
                                 ("receiver_x", "receiver_y", "recv_nx", "recv_ny"),
                                 ("landing_x", "landing_y", "land_nx", "land_ny")]:
        df[nx] = np.where(flip, W - df[src_x], df[src_x])
        df[ny] = np.where(flip, L - df[src_y], df[src_y])
    df["depth_delta"] = df["land_ny"] - df["hitter_ny"]
    df["lat_delta"] = (df["land_nx"] - df["hitter_nx"]).abs()
    dist = np.hypot(df["land_nx"] - df["hitter_nx"], df["land_ny"] - df["hitter_ny"])
    df["speed_proxy"] = dist / df["dt_next"]
    df["opp_depth_delta"] = df["land_ny"] - df["recv_ny"]

    # Plausibility gates: a MISSED next hit poisons landing/dt (the landing then
    # points at the hit-after, on the wrong side). NaN degrades gracefully in the
    # NaN-native classifier; garbage values do not.
    land_cols = ["landing_x", "landing_y", "land_nx", "land_ny",
                 "depth_delta", "lat_delta", "speed_proxy", "opp_depth_delta"]
    bad = (df["dt_next"] > 60) | (df["land_ny"] < 5.5)   # >2 s flight / didn't cross
    df.loc[bad, land_cols] = np.nan
    df.loc[df["dt_next"] > 60, "dt_next"] = np.nan
    df.loc[df["dt_prev"] > 60, "dt_prev"] = np.nan
    return df


def classify(df: pd.DataFrame, train_match: str) -> pd.DataFrame:
    """Predict shot_type for pipeline strokes with a model trained on ANOTHER match."""
    tr = shotclass.build_features(train_match, feet_landing=True)
    clf = shotclass._model().fit(tr[shotclass.CV_FEATURES], tr["shot"])
    X = df[shotclass.CV_FEATURES]
    df = df.copy()
    df["shot_type"] = clf.predict(X)
    df["shot_type_conf"] = clf.predict_proba(X).max(axis=1)
    return df


def write_strokes(match_id: str, df: pd.DataFrame) -> int:
    """Persist as source='pipeline' rows (idempotent per match)."""
    con = db.connect()
    try:
        con.execute("DELETE FROM strokes WHERE match_id=? AND source='pipeline'",
                    [match_id])
        base = con.execute("SELECT COALESCE(MAX(stroke_id), 0) + 1 FROM strokes"
                           ).fetchone()[0]
        recs = [(int(base + i), match_id, int(r.set_no), int(r.rally_id),
                 int(r.ball_round), int(r.frame_num), r.hitter, r.receiver,
                 r.shot_type, "court_m",
                 r.hitter_x, r.hitter_y, r.receiver_x, r.receiver_y,
                 float(r.hit_img_x), float(r.hit_img_y),
                 r.landing_x, r.landing_y,
                 float(r.shot_type_conf), "pipeline")
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


def evaluate(match_id: str, train_match: str, verbose: bool = True) -> dict:
    """End-to-end agreement of pipeline strokes vs ShuttleSet labels."""
    df = classify(build_strokes(match_id), train_match)
    sdf = insights.stroke_df(match_id)
    smap = insights.side_map_from(sdf)

    n_match = hit_ok = shot_ok = shot_n = 0
    for (sn, rid), g in sdf.groupby(["set_no", "rally_id"]):
        ours = df[(df["set_no"] == sn) & (df["rally_id"] == rid)]
        used = np.zeros(len(ours), bool)
        of = ours["frame_num"].to_numpy()
        for _, lab in g.iterrows():
            lf = int(lab["frame_num"]) - 1
            cands = [(abs(int(of[j]) - lf), j) for j in range(len(ours))
                     if not used[j] and abs(int(of[j]) - lf) <= 6]
            if not cands:
                continue
            _, j = min(cands)
            used[j] = True
            n_match += 1
            mine = ours.iloc[j]
            if smap.get((int(sn), lab["hitter"])) == mine["hitter"]:
                hit_ok += 1
            if lab["shot"] in shotclass.CLASSES:
                shot_n += 1
                shot_ok += int(mine["shot_type"] == lab["shot"])

    out = dict(
        n_label=len(sdf), n_pipeline=len(df), n_matched=n_match,
        coverage=round(n_match / len(sdf), 4),
        hitter_acc=round(hit_ok / n_match, 4) if n_match else None,
        shot_acc_matched=round(shot_ok / shot_n, 4) if shot_n else None,
        end_to_end_shot=round(shot_ok / len(sdf), 4),
        df=df,
    )
    if verbose:
        print(f"pipeline strokes: {len(df)} (labels: {len(sdf)})")
        print(f"matched within ±6: {n_match} ({out['coverage']:.1%} of labels)")
        print(f"hitter agreement on matched: {out['hitter_acc']:.1%}")
        print(f"shot type on matched: {out['shot_acc_matched']:.1%}"
              f"  → end-to-end (× coverage): {out['end_to_end_shot']:.1%}")
    return out


OTHER = {"india_open_2022_final": "denmark_open_2022_sf",
         "denmark_open_2022_sf": "india_open_2022_final"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Label-free pipeline strokes + evaluation")
    ap.add_argument("match_id")
    ap.add_argument("--train-match", default=None,
                    help="match whose LABELS train the shot classifier "
                         "(default: the other wired match)")
    ap.add_argument("--write", action="store_true", help="persist to the strokes table")
    args = ap.parse_args()
    train = args.train_match or OTHER.get(args.match_id, args.match_id)
    res = evaluate(args.match_id, train)
    if args.write:
        n = write_strokes(args.match_id, res["df"])
        print(f"wrote {n} source='pipeline' rows")
