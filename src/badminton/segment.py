"""Label-free rally segmentation (Phase 2) — drops the last ShuttleSet dependency.

Primary signal: BOTH players tracked in-court ("camera runs"). The broadcast only
shows the calibrated main-camera view during play; replays, close-ups and crowd
shots break the homography geometry, so in-court near+far detections vanish.
Measured: both-tracked on 97.6–98.2% of rally frames vs 7–18% of gap frames.
(Shuttle visibility is NOT discriminative — TrackNet fires on replays too:
83–94% in-rally vs 77–82% in gaps.)

Label-free rejection layers clean up what leaks through:
1. bbox-height bands, self-calibrated per match: rally runs dominate the run
   population and cluster tightly (near ≈ 2× far); close-ups and zoomed replays
   land far outside the cluster. (A pixel court-line check was tried first and
   abandoned: the hand-picked calibration corners sit on the lines' OUTER edge,
   so per-line offsets of 2–5 px defeat any thin-line brightness test. A
   serve-stance gate was also tried and abandoned: tracks are often missing in
   the 0.5 s before the serve, and ~13% of real serves fail it on track
   glitches.)
2. restart truncation: a non-first hit whose INCOMING speed is ~zero is a
   dead-shuttle restart (post-landing pickup tap, knock-back to the server) —
   the rally ended before it. NOTE invisible/static raw-shuttle spells do NOT
   work for this: lobs leave the frame top for up to 62 frames mid-rally.

Within each surviving run, hits.detect_hits provides the fine boundaries:
rally start = first hit (the serve — detect_hits has a dedicated motion-onset
serve pass), rally end = last hit, extended to the landing when the trajectory
yields one.

CLI:  PYTHONPATH=src python -m badminton.segment <match_id>   # validate vs labels
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import db, hits, insights

MERGE_GAP = 45      # frames: bridge both-tracked dropouts shorter than this
MIN_RUN = 45        # frames: drop camera runs shorter than this (1.5 s)
RUN_PAD = 30        # frames: pad each run before hit detection (serve can precede
                    # the second player's first in-court detection slightly)
SPLIT_GAP = 90      # frames: consecutive hits farther apart belong to different
                    # rallies (longest labeled intra-rally hit gap is ~69; 3 s of
                    # no contact = rally over)
MIN_SOLO_SCORE = 3.0  # a 1-hit rally (service fault/ace) must be an unambiguous
                      # contact; stray kinks from shuttle handling score near 1
RESTART_SPEED = 2.5  # px/f: a non-first hit with incoming speed below this is a
                     # dead-shuttle restart (pickup tap / knock-back) — rally over
BBOX_TOL = 0.25     # run bbox-height median may deviate this fraction from the
                    # match-wide cluster reference
GROUP_WRIST_PX = 150  # group MEDIAN hit-to-wrist distance above this = nobody is
                      # actually striking (TrackNet ghost kinks in close-ups):
                      # real-rally groups median 52 px, spurious groups 264 px
TRAIL_WRIST_PX = 130  # trailing hits beyond this from any wrist are floor/net
                      # impacts (the shuttle kinks hard on the floor too) — trim
MIN_PAIR_DT = 13    # frames: a 2-hit group needs at least this between serve and
                    # return (labeled median dt is 26; sub-0.5 s pairs are taps)
MERGE_SEG = 120     # frames: surviving segments closer than this are fragments of
                    # one rally (a missed hit can stretch the split gap past
                    # SPLIT_GAP; real consecutive rallies are >= 256 apart)


def both_tracked(match_id: str) -> np.ndarray:
    """bool[frame]: both 'near' and 'far' have an in-court track row."""
    con = db.connect(read_only=True)
    fmax = con.execute("SELECT MAX(frame_num) FROM shuttle WHERE match_id=?",
                       [match_id]).fetchone()[0]
    rows = con.execute(
        "SELECT frame_num FROM tracks WHERE match_id=? "
        "GROUP BY frame_num HAVING COUNT(DISTINCT player_id) = 2", [match_id]).fetchall()
    con.close()
    out = np.zeros(int(fmax) + 1, dtype=bool)
    out[[r[0] for r in rows]] = True
    return out


def camera_runs(match_id: str, merge_gap: int = MERGE_GAP,
                min_run: int = MIN_RUN) -> list[tuple[int, int]]:
    """Maximal [f0, f1] spans of the main-camera view (both players tracked),
    with short dropouts bridged and blips dropped."""
    bt = both_tracked(match_id)
    idx = np.where(bt)[0]
    if len(idx) == 0:
        return []
    runs: list[list[int]] = [[int(idx[0]), int(idx[0])]]
    for f in idx[1:]:
        if f - runs[-1][1] <= merge_gap:
            runs[-1][1] = int(f)
        else:
            runs.append([int(f), int(f)])
    return [(a, b) for a, b in runs if b - a >= min_run]


def _bbox_ok(match_id: str, runs: list[tuple[int, int]],
             tol: float = BBOX_TOL) -> list[bool]:
    """Self-calibrated person-scale filter: per-run median bbox heights must sit
    near the match-wide cluster (rally runs are the dominant, tight cluster;
    close-ups / zoomed replays are far off it). Label-free."""
    con = db.connect(read_only=True)
    meds = []
    for a, b in runs:
        d = dict(con.execute(
            "SELECT player_id, MEDIAN(bbox[4]) FROM tracks WHERE match_id=? "
            "AND frame_num BETWEEN ? AND ? GROUP BY 1", [match_id, a, b]).fetchall())
        meds.append((float(d.get("near") or 0), float(d.get("far") or 0)))
    con.close()
    ref_n = float(np.median([n for n, _ in meds]))
    ref_f = float(np.median([f for _, f in meds]))
    return [abs(n - ref_n) <= tol * ref_n and abs(f - ref_f) <= tol * ref_f
            for n, f in meds]


def _split_at_restarts(match_id: str, group: list[dict]) -> list[list[dict]]:
    """Split the group at every NON-FIRST hit whose incoming speed is ~zero.
    Every real mid-rally contact receives a moving shuttle (labeled strokes:
    only 3.2% under 3 px/f, those being label-frame noise); a dead-shuttle
    restart starts from rest, exactly like a serve. Each part is judged on its
    own: the REAL SERVE is itself a restart when pre-serve handling kinks
    precede it in the group (truncating instead of splitting threw the rally
    away and kept the junk), while post-landing pickup taps form weak trailing
    parts that the keep-rule drops."""
    if len(group) < 2:
        return [group]
    s = hits.shuttle_series(match_id, group[0]["frame"] - hits.DELTA,
                            group[-1]["frame"])
    xy = s[["img_x", "img_y"]].to_numpy()
    base = int(s.index[0])
    parts: list[list[dict]] = [[group[0]]]
    for h in group[1:]:
        i = h["frame"] - base
        if hits.DELTA <= i < len(xy):
            a, b = xy[i - hits.DELTA], xy[i]
            if not (np.isnan(a).any() or np.isnan(b).any()) \
                    and np.linalg.norm(b - a) / hits.DELTA < RESTART_SPEED:
                h["restart"] = True
                parts.append([h])
                continue
        parts[-1].append(h)
    return parts


def _keep_group(g: list[dict]) -> bool:
    """A plausible rally, judged by structure:
    - mostly attributable to SOMEONE (kinks with no player tracked nearby are
      TrackNet ghosts in non-play footage);
    - 3+ hits: the hitter must alternate at least once — every real exchange
      does, same-player-only kink trains are shuttle handling. (Not applied to
      2-hit groups: one attribution error there kills a real serve+return.)
    - 2 hits: at least MIN_PAIR_DT apart (the serve must cross the court; 0.3 s
      double-taps are handling), plus the emphatic/serve rule below;
    - 1-2 hits: emphatic or serve-flagged — a restart-started part counts only
      via its score, since pickup taps are restarts too, and they score low."""
    if not g:
        return False
    players = [h.get("player") for h in g]
    if sum(p is None for p in players) * 2 > len(g):
        return False
    if len(g) >= 3:
        known = [p for p in players if p is not None]
        return any(a != b for a, b in zip(known, known[1:]))
    if len(g) == 2 and g[1]["frame"] - g[0]["frame"] < MIN_PAIR_DT:
        return False
    return any(h.get("serve") for h in g) \
        or any(h["score"] >= MIN_SOLO_SCORE for h in g)


def segments(match_id: str) -> pd.DataFrame:
    """Detected rallies: one row per rally with frame window + hit frames.

    rally_key is a sequential index over the whole match (label-free: set
    boundaries are unknown here — score OCR / long-break detection is future work).
    """
    runs = camera_runs(match_id)
    keep = _bbox_ok(match_id, runs)
    rows = []
    for (f0, f1), ok in zip(runs, keep):
        if not ok:
            continue
        dh = hits.detect_hits(match_id, max(0, f0 - RUN_PAD), f1 + RUN_PAD)
        if not dh:
            continue
        hits.attribute_hits(match_id, dh)
        groups: list[list[dict]] = [[dh[0]]]
        for h in dh[1:]:
            if h["frame"] - groups[-1][-1]["frame"] > SPLIT_GAP:
                groups.append([h])
            else:
                groups[-1].append(h)
        for g0 in groups:
            for g in _split_at_restarts(match_id, g0):
                dists = [h["dist_px"] for h in g if h.get("dist_px") is not None]
                if dists and float(np.median(dists)) > GROUP_WRIST_PX:
                    continue
                while g and (g[-1].get("dist_px") or 0) > TRAIL_WRIST_PX:
                    g.pop()
                if not _keep_group(g):
                    continue
                start, end = g[0]["frame"], g[-1]["frame"]
                land = hits.find_landing(match_id, end)
                rows.append(dict(run_f0=f0, run_f1=f1, start=start,
                                 end=land["frame"] if land else end,
                                 last_hit=end, n_hits=len(g),
                                 serve_player=g[0].get("player"),
                                 hit_frames=[h["frame"] for h in g]))
    rows.sort(key=lambda r: r["start"])

    # Re-merge fragments: a false mid-rally restart (v_in is noise-zero on ~3%
    # of real strokes) splits one rally into two surviving segments.
    merged: list[dict] = []
    for r in rows:
        if merged and r["start"] - merged[-1]["last_hit"] <= MERGE_SEG:
            m = merged[-1]
            m["end"] = max(m["end"], r["end"])
            m["last_hit"] = max(m["last_hit"], r["last_hit"])
            m["hit_frames"] += r["hit_frames"]
            m["n_hits"] = len(m["hit_frames"])
        else:
            merged.append(r)

    df = pd.DataFrame(merged).sort_values("start").reset_index(drop=True)
    df.insert(0, "rally_key", df.index + 1)
    return df


# ---------------------------------------------------------------- validation

def validate(match_id: str, verbose: bool = True) -> dict:
    """Match detected segments to labeled rally windows (greedy best-overlap,
    one-to-one). Reports recall/precision + boundary errors."""
    sdf = insights.stroke_df(match_id)
    off = hits.shuttle_offset(match_id)
    lab = (sdf.groupby(["set_no", "rally_id"])["frame_num"].agg(["min", "max"]) + off
           ).sort_values("min").reset_index()
    det = segments(match_id)

    cands = []  # (overlap, lab_i, det_j)
    for i, lr in lab.iterrows():
        a, b = int(lr["min"]) - 15, int(lr["max"]) + 15
        for j, dr in det.iterrows():
            ov = min(b, dr["end"]) - max(a, dr["start"])
            if ov > 0:
                cands.append((ov, i, j))
    cands.sort(reverse=True)
    lab_m: dict[int, int] = {}
    det_m: dict[int, int] = {}
    for _, i, j in cands:
        if i not in lab_m and j not in det_m:
            lab_m[i] = j
            det_m[j] = i

    start_err = [det.loc[j, "start"] - int(lab.loc[i, "min"]) for i, j in lab_m.items()]
    end_err = [det.loc[j, "last_hit"] - int(lab.loc[i, "max"]) for i, j in lab_m.items()]
    rec = len(lab_m) / len(lab)
    prec = len(det_m) / len(det) if len(det) else 0.0
    out = dict(
        n_label=len(lab), n_detected=len(det), n_matched=len(lab_m),
        recall=round(rec, 4), precision=round(prec, 4),
        f1=round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
        start_err_median=float(np.median(start_err)) if start_err else None,
        start_err_p90=float(np.percentile(np.abs(start_err), 90)) if start_err else None,
        end_err_median=float(np.median(end_err)) if end_err else None,
        end_err_p90=float(np.percentile(np.abs(end_err), 90)) if end_err else None,
    )
    if verbose:
        print(f"labeled rallies: {len(lab)}  detected: {len(det)}  matched: {len(lab_m)}")
        print(f"recall {rec:.1%}  precision {prec:.1%}  F1 {out['f1']:.1%}")
        print(f"start error (det − label serve): median {out['start_err_median']:+.0f}, "
              f"|p90| {out['start_err_p90']:.0f} frames")
        print(f"end error (last hit − label last stroke): median {out['end_err_median']:+.0f}, "
              f"|p90| {out['end_err_p90']:.0f} frames")
        missed = [(int(lab.loc[i, 'set_no']), int(lab.loc[i, 'rally_id']))
                  for i in range(len(lab)) if i not in lab_m]
        if missed:
            print(f"missed rallies: {missed}")
        spurious = [int(det.loc[j, 'start']) for j in range(len(det)) if j not in det_m]
        if spurious:
            print(f"spurious segments at frames: {spurious}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rally segmentation validation")
    ap.add_argument("match_id")
    args = ap.parse_args()
    validate(args.match_id)
