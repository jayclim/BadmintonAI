"""Hit detection + landing points from the TrackNetV3 shuttle track (Phase 2).

Hit = a sharp kink in the shuttle's image-space trajectory: compare the incoming and
outgoing velocity over a ±DELTA-frame window; a hit scores high when the direction
turns hard AND the shuttle is actually moving (suppresses lob apexes, where the
parabola turns gradually). Candidates are local maxima with a minimum gap.

Attribution = nearest player at the hit frame, by wrist keypoints (COCO 9/10 from the
`tracks` table; falls back to bbox center when wrist confidence is low).

Landing = follow the interpolated track after the rally's final hit until the shuttle
stops descending / disappears near the floor; project that image point through the
homography (valid: the shuttle is ON the floor plane at landing).

Alignment (HANDOFF gotcha 9): shuttle events live at video frame = ShuttleSet frame − 1
(SHUTTLE_OFFSET); player tracks at +6 (TRACK_OFFSET).

CLI:  PYTHONPATH=src python -m badminton.hits <match_id>   # validate vs ShuttleSet
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import config, court, db, insights

SHUTTLE_OFFSET = -1     # video frame = SS frame + SHUTTLE_OFFSET (shuttle events)
TRACK_OFFSET = 6        # video frame = SS frame + TRACK_OFFSET (player tracks)
DELTA = 4               # velocity estimation half-window (frames)
MIN_SPEED = 3.0         # px/frame — sustained-motion gate for the serve detector
MIN_DV = 30.0           # |Δv| px/frame threshold: velocity CHANGE at contact catches
                        # same-direction accelerations (a smash off a descending lob
                        # has no 2D turn). F1-optimal on the India Open sweep; the
                        # turn detector below carries the slow net exchanges.
MIN_TURN = 20.0         # (1−cosθ)·speed threshold: direction reversals, incl. slow
                        # net play where |Δv| is small. TP median ≈ 83, FP median ≈ 13.
MIN_TURN_COS = 0.5      # reversal requires ≥ 60° turn
MIN_GAP = 8             # min frames between hits (fastest exchanges ~0.3 s)
GAP_INTERP = 6          # interpolate visibility gaps up to this many frames
WRIST_IDX = (9, 10)     # COCO left/right wrist


def shuttle_series(match_id: str, f0: int, f1: int,
                   interpolate: bool = True) -> pd.DataFrame:
    """Shuttle track for video frames [f0, f1]; small gaps interpolated by default."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, img_x, img_y FROM shuttle WHERE match_id=? AND visible "
        "AND frame_num BETWEEN ? AND ? ORDER BY frame_num", [match_id, f0, f1]).df()
    con.close()
    full = pd.DataFrame({"frame_num": np.arange(f0, f1 + 1)})
    s = full.merge(df, on="frame_num", how="left").set_index("frame_num")
    if interpolate:
        return s.interpolate(limit=GAP_INTERP, limit_area="inside")
    return s


def _combined_score(v_in: np.ndarray, v_out: np.ndarray,
                    min_dv: float, min_turn: float) -> float:
    """Normalized union of the two contact signals (≥ 1.0 means 'hit'):
    |Δv| (accelerations) and (1−cosθ)·speed (reversals, incl. slow net play)."""
    sp_in, sp_out = float(np.linalg.norm(v_in)), float(np.linalg.norm(v_out))
    s_dv = float(np.linalg.norm(v_out - v_in)) / min_dv
    s_turn = 0.0
    if sp_in > 1.0 and sp_out > 1.0:
        cos = float(np.dot(v_in, v_out) / (sp_in * sp_out))
        if cos < MIN_TURN_COS:
            s_turn = (1.0 - cos) * min(sp_in, sp_out) * DELTA / min_turn
    return max(s_dv, s_turn)


def detect_hits(match_id: str, f0: int, f1: int, min_dv: float = MIN_DV,
                min_turn: float = MIN_TURN) -> list[dict]:
    """Hit candidates in video-frame window [f0, f1]: |Δv| spikes OR hard turns."""
    s = shuttle_series(match_id, f0, f1)
    xy = s[["img_x", "img_y"]].to_numpy()
    frames = s.index.to_numpy()
    n = len(xy)
    score = np.zeros(n)
    for i in range(DELTA, n - DELTA):
        if np.isnan(xy[i - DELTA : i + DELTA + 1]).any():
            continue
        v_in = (xy[i] - xy[i - DELTA]) / DELTA
        v_out = (xy[i + DELTA] - xy[i]) / DELTA
        score[i] = _combined_score(v_in, v_out, min_dv, min_turn)

    hits = []
    order = np.argsort(-score)
    taken = np.zeros(n, dtype=bool)
    for i in order:
        if score[i] < 1.0:
            break
        if taken[max(0, i - MIN_GAP) : i + MIN_GAP + 1].any():
            continue
        taken[i] = True
        hits.append(dict(frame=int(frames[i]), x=float(xy[i, 0]), y=float(xy[i, 1]),
                         score=float(score[i])))

    # Second pass — contacts INSIDE visibility gaps (fast shots blur the shuttle
    # invisible at contact; interpolation draws a line through the gap and flattens
    # |Δv|). Compare velocities across RAW visible run-boundaries instead.
    raw = shuttle_series(match_id, f0, f1, interpolate=False)
    xy = raw[["img_x", "img_y"]].to_numpy()
    vis = ~np.isnan(xy[:, 0])
    vi = np.where(vis)[0]
    for a, b in zip(vi[:-1], vi[1:]):
        gap = b - a
        if not (2 <= gap <= 14) or a < 2 or b > n - 3:
            continue
        if not (vis[a - 2 : a + 1].all() and vis[b : b + 3].all()):
            continue
        v_in = (xy[a] - xy[a - 2]) / 2.0
        v_out = (xy[b + 2] - xy[b]) / 2.0
        sc = _combined_score(v_in, v_out, min_dv, min_turn)
        if sc >= 1.0:
            mid = (a + b) // 2
            if not any(abs(int(frames[mid]) - h["frame"]) < MIN_GAP for h in hits):
                hits.append(dict(frame=int(frames[mid]),
                                 x=float((xy[a, 0] + xy[b, 0]) / 2),
                                 y=float((xy[a, 1] + xy[b, 1]) / 2),
                                 score=float(sc), in_gap=True))

    # The SERVE can't be a kink (the shuttle starts from rest, v_in ≈ 0): detect it as
    # the first sustained FAST motion onset (≥ 2×MIN_SPEED — the pre-serve toss and
    # hand creep sit below that), if no kink-hit is nearby.
    sp = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    for i in range(len(sp) - 2):
        seg = sp[i : i + 3]
        if not np.isnan(seg).any() and (seg >= 2 * MIN_SPEED).all():
            if not any(abs(int(frames[i]) - h["frame"]) <= 2 * MIN_GAP for h in hits):
                hits.append(dict(frame=int(frames[i]), x=float(xy[i, 0]),
                                 y=float(xy[i, 1]), score=float(seg.sum()),
                                 serve=True))
            break

    hits.sort(key=lambda h: h["frame"])
    return hits


def _player_refs(match_id: str, f0: int, f1: int) -> dict:
    """(frame, player_id) -> list of reference points (wrists or bbox center)."""
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT frame_num, player_id, keypoints, bbox FROM tracks "
        "WHERE match_id=? AND frame_num BETWEEN ? AND ?", [match_id, f0, f1]).fetchall()
    con.close()
    refs = {}
    for f, pid, kps, bbox in rows:
        pts = []
        if kps is not None:
            for j in WRIST_IDX:
                x, y, c = kps[3 * j], kps[3 * j + 1], kps[3 * j + 2]
                if c > 0.3:
                    pts.append((x, y))
        if not pts and bbox is not None:
            pts.append((bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2))
        refs[(f, pid)] = pts
    return refs


def attribute_hits(match_id: str, hits: list[dict]) -> None:
    """Set hit['player'] ('near'/'far') + hit['dist_px'] by nearest wrist/bbox.
    `tracks` and `shuttle` share the video frame timeline — no shift between them
    (the −1/+6 offsets only align ShuttleSet LABELS to video, see gotcha 9)."""
    if not hits:
        return
    f_lo = min(h["frame"] for h in hits) - 2
    f_hi = max(h["frame"] for h in hits) + 2
    refs = _player_refs(match_id, f_lo, f_hi)
    for h in hits:
        best, best_d = None, np.inf
        for df_ in (-1, 0, 1):
            for pid in ("near", "far"):
                for (x, y) in refs.get((h["frame"] + df_, pid), []):
                    d = float(np.hypot(x - h["x"], y - h["y"]))
                    if d < best_d:
                        best, best_d = pid, d
        h["player"] = best
        h["dist_px"] = best_d if best else None


def find_landing(match_id: str, last_hit_frame: int, search: int = 120) -> dict | None:
    """Follow the track after the final hit. Two phases: lobs/clears ASCEND first
    (image y decreasing) — skip that; once the shuttle is descending, landing = where
    the descent ends (direction reversal = bounce/pickup, near-zero speed = settled,
    or the track vanishing near the floor). Returns image + court coordinates."""
    s = shuttle_series(match_id, last_hit_frame + 2, last_hit_frame + search)
    xy = s[["img_x", "img_y"]].to_numpy()
    frames = s.index.to_numpy()
    # Walk the CONTINUOUS post-hit track only (a gap or a >40 px jump = occlusion,
    # camera cut, or replay — nothing past it belongs to this flight). The landing is
    # the lowest screen point reached: the floor is the bottom of every flight arc,
    # which sidesteps ascent/descent phase logic entirely.
    land_i = None
    steps = 0
    prev = None                                 # last valid index
    for i in range(len(xy)):
        if np.isnan(xy[i]).any():
            continue
        if prev is not None and steps:
            gap = i - prev
            d = float(np.linalg.norm(xy[i] - xy[prev]))
            # plausible continuation: smashes reach ~100 px/frame on consecutive
            # frames; across a gap the shuttle has decelerated, so cap the total
            # displacement — anything bigger is a cut, replay, or different object
            if d > (100.0 if gap == 1 else min(45.0 * gap, 250.0)):
                break
        if land_i is None or xy[i, 1] > xy[land_i, 1]:
            land_i = i
        prev = i
        steps += 1
    if land_i is None or steps < 3:
        return None
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    cx, cy = court.image_to_court(xy[land_i : land_i + 1].astype(np.float32), H)[0]
    return dict(frame=int(frames[land_i]), img_x=float(xy[land_i, 0]),
                img_y=float(xy[land_i, 1]), court_x=float(cx), court_y=float(cy))


# ---------------------------------------------------------------- validation

def validate(match_id: str, tol: int = 6, verbose: bool = True,
             min_dv: float = MIN_DV) -> dict:
    """Score detected hits + landings against ShuttleSet labels, rally by rally."""
    sdf = insights.stroke_df(match_id)
    rdf = insights.rally_df(match_id, sdf)
    smap = insights.side_map_from(sdf)
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)

    tp = fp = fn = attr_ok = attr_n = 0
    land_errs = []
    for (sn, rid), g in sdf.groupby(["set_no", "rally_id"]):
        g = g.sort_values("ball_round")
        lab_frames = (g["frame_num"] + SHUTTLE_OFFSET).to_numpy()
        f0, f1 = int(lab_frames.min() - 20), int(lab_frames.max() + 20)
        hits = detect_hits(match_id, f0, f1, min_dv=min_dv)
        attribute_hits(match_id, hits)

        used = np.zeros(len(hits), dtype=bool)
        for lf, hitter in zip(lab_frames, g["hitter"]):
            cands = [(abs(h["frame"] - lf), j) for j, h in enumerate(hits)
                     if not used[j] and abs(h["frame"] - lf) <= tol]
            if not cands:
                fn += 1
                continue
            _, j = min(cands)
            used[j] = True
            tp += 1
            want = smap.get((int(sn), hitter))
            if hits[j]["player"] is not None and want is not None:
                attr_n += 1
                attr_ok += hits[j]["player"] == want
        fp += int((~used).sum())

        # landing: only rallies that end on the floor (winner or 'Out' error)
        rrow = rdf[(rdf["set_no"] == sn) & (rdf["rally_id"] == rid)]
        if len(rrow) and rrow.iloc[0]["category"] in ("Winner", "Out"):
            end = g.iloc[-1]
            if pd.notna(end["landing_x"]):
                land = find_landing(match_id, int(lab_frames[-1]))
                if land is not None:
                    lab = court.image_to_court(np.array(
                        [[end["landing_x"], end["landing_y"]]], np.float32), H)[0]
                    land_errs.append(float(np.hypot(land["court_x"] - lab[0],
                                                    land["court_y"] - lab[1])))

    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    out = dict(
        n_label=tp + fn, tp=tp, fp=fp, fn=fn,
        precision=round(prec, 4), recall=round(rec, 4),
        f1=round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
        attribution_acc=round(attr_ok / attr_n, 4) if attr_n else None,
        n_landing=len(land_errs),
        landing_median_m=round(float(np.median(land_errs)), 3) if land_errs else None,
        landing_p90_m=round(float(np.percentile(land_errs, 90)), 3) if land_errs else None,
    )
    if verbose:
        print(f"hits: {tp}/{out['n_label']} matched (tol ±{tol})  "
              f"P {prec:.1%}  R {rec:.1%}  F1 {out['f1']:.1%}  (FP {fp})")
        print(f"attribution: {attr_ok}/{attr_n} = "
              f"{attr_ok / attr_n:.1%}" if attr_n else "attribution: n/a")
        if land_errs:
            print(f"landings (n={len(land_errs)}): median {out['landing_median_m']} m, "
                  f"p90 {out['landing_p90_m']} m")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Hit detection + landing validation")
    ap.add_argument("match_id")
    ap.add_argument("--tol", type=int, default=6, help="frame tolerance for a match")
    args = ap.parse_args()
    validate(args.match_id, tol=args.tol)
