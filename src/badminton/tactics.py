"""Shot-type tactics + a pressure metric, from ShuttleSet stroke data (whole match).

No detection needed — these use the human-labeled strokes, so they cover all 84 rallies.

Pressure model: how fast a player had to move to reach each shot. For stroke i (hitter P),
P was standing at their position when the opponent hit (= receiver position on stroke i−1),
and had to get to the contact point (P's hitter position on stroke i) within the elapsed
time. required_speed = distance / time. High = rushed / under pressure.
  - pressure FACED by P  = mean required_speed over P's own shots
  - pressure APPLIED by P = mean required_speed P forced on the opponent's next shot
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from . import config, court, db


def _h_fps(match_id):
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    return H, float(m["fps"])


def _rallies(match_id, cols):
    con = db.connect(read_only=True)
    rows = con.execute(
        f"SELECT set_no,rally_id,ball_round,{cols} FROM strokes WHERE match_id=? "
        "AND source='shuttleset' ORDER BY set_no,rally_id,ball_round", [match_id]).fetchall()
    con.close()
    g = defaultdict(list)
    for r in rows:
        g[(r[0], r[1])].append(r)
    return g


def shot_outcomes(match_id) -> dict:
    """Which shot types win points (winners) vs lose points (errors), match-wide."""
    g = _rallies(match_id, "hitter,shot_type,shot_type_raw,getpoint_player")
    win, err = Counter(), Counter()
    pwin, perr = defaultdict(Counter), defaultdict(Counter)
    for strk in g.values():
        _, _, _, hitter, st, raw, getp = strk[-1]
        if getp is None:
            continue
        shot = st or raw or "—"
        if getp == hitter:
            win[shot] += 1; pwin[hitter][shot] += 1
        else:
            err[shot] += 1; perr[hitter][shot] += 1
    return dict(win=win, err=err, pwin=pwin, perr=perr)


def shot_distribution(match_id) -> dict:
    g = _rallies(match_id, "hitter,shot_type,shot_type_raw")
    dist = defaultdict(Counter)
    for strk in g.values():
        for _, _, _, hitter, st, raw in strk:
            dist[hitter][st or raw or "—"] += 1
    return dist


def pressure_strokes(match_id) -> list[dict]:
    H, fps = _h_fps(match_id)
    g = _rallies(match_id, "hitter,frame_num,hitter_x,hitter_y,receiver_x,receiver_y,"
                           "hit_height,shot_type,shot_type_raw")
    out = []
    for strk in g.values():
        for i in range(1, len(strk)):
            c, p = strk[i], strk[i - 1]
            dt = (c[4] - p[4]) / fps           # c[4]=frame_num
            if dt <= 0 or c[5] is None or p[7] is None:
                continue
            now = court.image_to_court(np.array([[c[5], c[6]]], np.float32), H)[0]   # contact
            wait = court.image_to_court(np.array([[p[7], p[8]]], np.float32), H)[0]  # start pos
            spd = float(np.linalg.norm(now - wait) / dt)
            out.append(dict(set=c[0], rally=c[1], shot_no=c[2], hitter=c[3],
                            prev_hitter=p[3], req_speed=spd, low_contact=(c[9] == 2),
                            prev_shot=p[10] or p[11] or "—"))
    return out


def pressure_by_shot(match_id, min_n: int = 5) -> dict:
    """Which shot types force the opponent to scramble most — mean required speed of
    the OPPONENT's response to each shot type. Higher = more pressure generated."""
    from collections import defaultdict
    d = defaultdict(list)
    for x in pressure_strokes(match_id):
        d[x["prev_shot"]].append(x["req_speed"])
    return {k: round(float(np.mean(v)), 2) for k, v in d.items() if len(v) >= min_n}


def rally_patterns(match_id, n: int = 2):
    """Most common ending shot-type sequences for won rallies (winners) vs lost (errors)."""
    g = _rallies(match_id, "hitter,shot_type,shot_type_raw,getpoint_player")
    win, lose = Counter(), Counter()
    for strk in g.values():
        seq = [(s[4] or s[5] or "—") for s in strk]
        last = strk[-1]
        getp, hitter = last[6], last[3]
        if getp is None or len(seq) < n:
            continue
        pat = " → ".join(seq[-n:])
        (win if getp == hitter else lose)[pat] += 1
    return win, lose


def pressure_summary(match_id) -> dict:
    s = pressure_strokes(match_id)
    faced, applied = defaultdict(list), defaultdict(list)
    for x in s:
        faced[x["hitter"]].append(x["req_speed"])
        applied[x["prev_hitter"]].append(x["req_speed"])
    return {p: dict(faced=round(float(np.mean(faced[p])), 2) if faced[p] else 0.0,
                    applied=round(float(np.mean(applied[p])), 2) if applied[p] else 0.0,
                    n=len(faced[p])) for p in ("A", "B")}


def rally_detail(match_id, set_no, rally_id) -> list[dict]:
    """Stroke-by-stroke data for one rally, with per-shot pressure (required speed)."""
    H, fps = _h_fps(match_id)
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT ball_round,hitter,shot_type,shot_type_raw,hit_height,landing_area,"
        "frame_num,hitter_x,hitter_y,receiver_x,receiver_y FROM strokes WHERE match_id=? "
        "AND source='shuttleset' AND set_no=? AND rally_id=? ORDER BY ball_round",
        [match_id, set_no, rally_id]).fetchall()
    con.close()
    out, prev = [], None
    for br, hitter, st, raw, hh, la, fn, hx, hy, rx, ry in rows:
        req = None
        if prev and prev[1] is not None and hx is not None:
            dt = (fn - prev[0]) / fps
            if dt > 0:
                now = court.image_to_court(np.array([[hx, hy]], np.float32), H)[0]
                wait = court.image_to_court(np.array([[prev[1], prev[2]]], np.float32), H)[0]
                req = round(float(np.linalg.norm(now - wait) / dt), 1)
        out.append(dict(shot=br, hitter=hitter, type=st or raw or "—",
                        low_contact=bool(hh == 2), zone=la, pressure_mps=req))
        prev = (fn, rx, ry)
    return out
