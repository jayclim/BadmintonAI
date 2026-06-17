"""Doubles annotated rally renderer (ISOLATED, Phase 1) — the visual payoff.

Writes an MP4 of a rally with: the reprojected court, the four players boxed and labelled
with name (if a roster/mapping is given) + front/back role, and a banner showing each
side's debounced formation. Self-contained — reads `tracks` + the homography only.

CLI:
  PYTHONPATH=src python -m badminton.doubles.render <match_id> START END [-o out.mp4] [--set N]
"""

from __future__ import annotations

import argparse

import numpy as np

from .. import config, court, db
from . import identity, roles

COL = {"near": (80, 255, 80), "near2": (255, 200, 0),       # BGR: green / cyan (near pair)
       "far": (60, 255, 255), "far2": (255, 60, 255)}        #      yellow / magenta (far pair)


def _court_lines(H: np.ndarray):
    """Court-model line segments reprojected to image pixels via the inverse homography."""
    Hinv = np.linalg.inv(H)
    W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M
    ins, net = court.SINGLES_SIDELINE_INSET_M, court.NET_Y_M
    segs = [((0, 0), (W, 0)), ((0, L), (W, L)), ((0, 0), (0, L)), ((W, 0), (W, L)),
            ((0, net), (W, net)), ((ins, 0), (ins, L)), ((W - ins, 0), (W - ins, L)),
            ((W / 2, 0), (W / 2, L))]

    def px(p):
        v = Hinv @ np.array([p[0], p[1], 1.0])
        return (int(v[0] / v[2]), int(v[1] / v[2]))

    return [(px(a), px(b)) for a, b in segs]


def render_rally(match_id: str, start: int, end: int, out_path, names: dict | None = None) -> str:
    import cv2

    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float64).reshape(3, 3)
    fps = float(m.get("fps", 30.0))
    lines = _court_lines(H)

    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, bbox FROM tracks WHERE match_id=? "
        "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ?",
        [match_id, start, end]).fetch_df()
    con.close()
    by_frame = {f: g for f, g in df.groupby("frame_num")}

    # debounced formation + front slot, per (frame, side)
    rd = roles.roles_df(match_id)
    rd = rd[(rd.frame_num >= start) & (rd.frame_num <= end)]
    form, front = {}, {}
    for side in ("near", "far"):
        s = rd[rd.side == side].sort_values("frame_num")
        fm = roles.hysteresis_formation((s.depth_gap - s.lateral_gap).tolist())
        for fr, f in zip(s.frame_num, fm):
            form[(fr, side)] = f
    for r in rd.itertuples():
        front[(r.frame_num, r.side)] = r.front

    cap = cv2.VideoCapture(str(config.REPO_ROOT / m["video_path"]))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    wpx, hpx = int(cap.get(3)), int(cap.get(4))
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (wpx, hpx))

    for fr in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        for a, b in lines:
            cv2.line(frame, a, b, (0, 170, 0), 1)
        g = by_frame.get(fr)
        if g is not None:
            for r in g.itertuples(index=False):
                pid, (cx, cy, w, h) = r.player_id, r.bbox
                side = "near" if pid in ("near", "near2") else "far"
                role = "front" if front.get((fr, side)) == pid else "back"
                label = f"{names.get(pid, pid) if names else pid} [{role}]"
                col = COL[pid]
                cv2.rectangle(frame, (int(cx - w / 2), int(cy - h / 2)),
                              (int(cx + w / 2), int(cy + h / 2)), col, 2)
                cv2.putText(frame, label, (int(cx - w / 2), int(cy - h / 2) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
        cv2.rectangle(frame, (0, 0), (wpx, 28), (0, 0, 0), -1)
        cv2.putText(frame, f"near: {form.get((fr, 'near'), '-')}    far: {form.get((fr, 'far'), '-')}"
                    f"    frame {fr}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        writer.write(frame)

    cap.release()
    writer.release()
    print(f"wrote {out_path}")
    return str(out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles annotated rally renderer (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("start", type=int)
    ap.add_argument("end", type=int)
    ap.add_argument("-o", "--out", default="data/clips/doubles_rally.mp4")
    ap.add_argument("--set", type=int, default=1, help="use this set's identity roster for names")
    args = ap.parse_args()
    try:
        names = identity.resolve(args.match_id, args.set)
    except SystemExit:
        names = None
    out = config.REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    render_rally(args.match_id, args.start, args.end, out, names)


if __name__ == "__main__":
    main()
