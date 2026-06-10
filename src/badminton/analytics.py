"""Phase 1 analytics — per-player and per-rally movement metrics from continuous tracks.

Distance/coverage/speed are derived from the validated court-metre positions. Rally
boundaries come from ShuttleSet's stroke groupings (frame ranges), so each rally's
movement is bucketed cleanly.

Needs CONTINUOUS tracks over the analysed range (run detect.py on that window first).
"""

from __future__ import annotations

import numpy as np

from . import court, db

MAX_SPEED = 9.0   # m/s — cap to reject detection glitches (elite peak ~6–7 m/s)
SMOOTH_WIN = 5    # rolling-median window to de-jitter positions before distance
SS_OFFSET = 6     # video_frame = ss_frame + 6


def _smooth(a: np.ndarray, win: int = SMOOTH_WIN) -> np.ndarray:
    if len(a) < win:
        return a
    h = win // 2
    return np.array([np.median(a[max(0, i - h):i + h + 1]) for i in range(len(a))])


def player_series(match_id: str, fmin: int, fmax: int) -> dict[str, np.ndarray]:
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT frame_num,player_id,court_x,court_y FROM tracks WHERE match_id=? "
        "AND frame_num BETWEEN ? AND ? ORDER BY frame_num", [match_id, fmin, fmax]).fetchall()
    con.close()
    out: dict[str, list] = {"near": [], "far": []}
    for f, p, x, y in rows:
        if p in out:
            out[p].append((f, x, y))
    return {p: np.array(v, dtype=float) for p, v in out.items() if v}


def player_metrics(arr: np.ndarray, fps: float) -> dict:
    """arr: (N,3) of frame,court_x,court_y sorted by frame."""
    f = arr[:, 0]
    x, y = _smooth(arr[:, 1]), _smooth(arr[:, 2])
    dt = np.diff(f) / fps
    step = np.hypot(np.diff(x), np.diff(y))
    sp = np.divide(step, dt, out=np.zeros_like(step), where=dt > 0)
    good = (sp <= MAX_SPEED) & (dt > 0)

    # half-aware tactical metrics: recovery to base + front/mid/back court time
    hl = court.NET_Y_M                                   # half length 6.70 m
    near = y.mean() < court.NET_Y_M
    base_y = court.NET_Y_M - hl / 2 if near else court.NET_Y_M + hl / 2
    recovery = np.hypot(x - court.COURT_WIDTH_M / 2, y - base_y)
    d_net = np.abs(y - court.NET_Y_M)                    # distance from net (0=net, 6.7=baseline)
    front = float(np.mean(d_net < hl / 3) * 100)
    back = float(np.mean(d_net > 2 * hl / 3) * 100)

    return dict(
        distance_m=round(float(step[good].sum()), 1),
        duration_s=round(float((f[-1] - f[0]) / fps), 1),
        mean_speed=round(float(np.average(sp[good], weights=dt[good])) if good.any() else 0, 2),
        p95_speed=round(float(np.percentile(sp[good], 95)) if good.any() else 0, 2),
        mean_x=round(float(x.mean()), 2), mean_y=round(float(y.mean()), 2),
        spread_x=round(float(x.std()), 2), spread_y=round(float(y.std()), 2),
        coverage_m2=round(float(np.pi * 2 * x.std() * 2 * y.std()), 1),
        recovery_m=round(float(recovery.mean()), 2),
        front_pct=round(front), mid_pct=round(100 - front - back), back_pct=round(back),
        n_frames=int(len(arr)),
    )


def summary(match_id: str, fmin: int, fmax: int, fps: float) -> dict[str, dict]:
    return {p: player_metrics(a, fps) for p, a in player_series(match_id, fmin, fmax).items()}


def match_aggregate(match_id, fps) -> dict:
    """Whole-match per-player movement, aggregated over rallies (distance summed PER rally
    so camera cuts/replays don't add bogus jumps). Returns positions for the heatmap too."""
    from collections import defaultdict
    con = db.connect(read_only=True)
    rr = con.execute("SELECT set_no,rally_id,MIN(frame_num),MAX(frame_num) FROM strokes "
                     "WHERE match_id=? AND source='shuttleset' GROUP BY set_no,rally_id",
                     [match_id]).fetchall()
    con.close()
    dist, secs, pos = defaultdict(float), defaultdict(float), defaultdict(list)
    for _, _, f0, f1 in rr:
        for p, arr in player_series(match_id, f0 + SS_OFFSET, f1 + SS_OFFSET).items():
            if len(arr) < 3:
                continue
            mt = player_metrics(arr, fps)
            dist[p] += mt["distance_m"]; secs[p] += mt["duration_s"]
            pos[p].append(arr[:, 1:3])
    out = {}
    for p in pos:
        P = np.vstack(pos[p]); x, y = P[:, 0], P[:, 1]
        hl = court.NET_Y_M
        base_y = hl / 2 if y.mean() < court.NET_Y_M else court.NET_Y_M + hl / 2
        d_net = np.abs(y - court.NET_Y_M)
        front = round(float(np.mean(d_net < hl / 3) * 100))
        back = round(float(np.mean(d_net > 2 * hl / 3) * 100))
        out[p] = dict(distance_m=round(dist[p]), rally_time_s=round(secs[p]),
                      mean_speed=round(dist[p] / secs[p], 2) if secs[p] else 0.0,
                      coverage_m2=round(float(np.pi * 2 * x.std() * 2 * y.std()), 1),
                      recovery_m=round(float(np.hypot(x - court.COURT_WIDTH_M / 2, y - base_y).mean()), 2),
                      front_pct=front, mid_pct=100 - front - back, back_pct=back,
                      positions=P)
    return out


def rallies(match_id: str, fmin: int, fmax: int, fps: float, ss_offset: int = 6) -> list[dict]:
    """Per-(rally, player) metrics, using ShuttleSet rally groupings for boundaries."""
    con = db.connect(read_only=True)
    strokes = con.execute(
        "SELECT set_no,rally_id,frame_num FROM strokes WHERE match_id=? AND source='shuttleset' "
        "AND frame_num BETWEEN ? AND ? ORDER BY set_no,rally_id,ball_round",
        [match_id, fmin - ss_offset, fmax]).fetchall()
    con.close()

    spans: dict[tuple, list[int]] = {}
    for sn, rid, f in strokes:
        spans.setdefault((sn, rid), []).append(f + ss_offset)

    out = []
    for (sn, rid), frames in sorted(spans.items()):
        a, b = min(frames), max(frames)
        if b - a < fps * 0.5:          # skip 1-stroke / trivial rallies
            continue
        for p, arr in player_series(match_id, a, b).items():
            if len(arr) < 3:
                continue
            mt = player_metrics(arr, fps)
            out.append(dict(set=sn, rally=rid, player=p, shots=len(frames),
                            duration_s=mt["duration_s"], distance_m=mt["distance_m"],
                            mean_speed=mt["mean_speed"], coverage_m2=mt["coverage_m2"]))
    return out
