"""Doubles annotated rally renderer (ISOLATED, Phase 1) — the visual payoff.

Writes an MP4 of a rally with: the reprojected court, the four players boxed + pose
skeletons, labelled with name (per-set roster when known) + front/back role, a banner
showing each side's debounced formation, the machine-read scoreboard score, and — since
`doubles/strokes.py` — the shuttle trail plus a contact ring + shot-type call at each
CV-detected hit, matching the singles `render_overlay` annotations. Shuttle/stroke layers
degrade to absent when the match has no shuttle track or written strokes.

Self-contained per the isolation rule: reads `tracks` + the homography + the doubles
sibling modules, plus low-level `scoreboard` for the OCR score readout. Encodes to a
web-weight 540p H.264 clip (raw mp4v -> ffmpeg libx264), matching render_overlay.

CLI:
  PYTHONPATH=src python -m badminton.doubles.render <match_id> START END [-o out.mp4] [--set N]
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np

from .. import config, court, db
from . import identity, roles

# BGR per slot: near pair green / cyan, far pair yellow / magenta (matches the 2D replay hues)
COL = {"near": (80, 255, 80), "near2": (255, 200, 0),
       "far": (60, 255, 255), "far2": (255, 60, 255)}

TRAIL = 12          # shuttle trail length (frames)
HIT_RING = 10       # frames a contact ring + shot call stays on screen

# COCO-17 skeleton bones (keypoint index pairs) — same as render_overlay.SKELETON
SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]
KP_MIN_CONF = 0.3


def _draw_skeleton(frame, kp51, col) -> None:
    import cv2
    kp = np.asarray(kp51, dtype=np.float32).reshape(17, 3)
    for a, b in SKELETON:
        if kp[a, 2] >= KP_MIN_CONF and kp[b, 2] >= KP_MIN_CONF:
            cv2.line(frame, (int(kp[a, 0]), int(kp[a, 1])),
                     (int(kp[b, 0]), int(kp[b, 1])), col, 2)
    for x, y, c in kp:
        if c >= KP_MIN_CONF:
            cv2.circle(frame, (int(x), int(y)), 3, (255, 255, 255), -1)


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


def _score_events(match_id: str, start: int, end: int, samples: int = 6):
    """Debounced (frame, "top-bot") scoreboard reads across the rally, for a live readout.
    Reuses the singles scoreboard OCR; failures degrade to no score (never crash a render)."""
    try:
        import cv2
        from .. import scoreboard as sb
        box = sb.calibrate_box(match_id)
        if box is None:
            return []
        tpl = sb._load_templates()
        cap = cv2.VideoCapture(str(config.REPO_ROOT / config.get_match(match_id)["video_path"]))
        out = []
        for f in np.linspace(start, end, samples).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
            ok, fr = cap.read()
            r = sb.read_frame(fr, box, tpl) if ok else None
            if r:
                out.append((int(f), f"{r['top'][-1]}-{r['bot'][-1]}"))
        cap.release()
        return out
    except Exception:
        return []


def render_rally(match_id: str, start: int, end: int, out_path,
                 names: dict | None = None, score: str | None = None,
                 out_height: int | None = 540, crf: int = 27) -> str:
    """`score` ("top-bot") is the machine-read scoreboard for the rally; pass it from the
    caller (which already OCRs per-rally scores) to skip the in-render OCR. When None, we
    sample it here. The score is constant within a rally, so one value is shown throughout."""
    import cv2

    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float64).reshape(3, 3)
    fps = float(m.get("fps", 30.0))
    lines = _court_lines(H)

    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, bbox, keypoints FROM tracks WHERE match_id=? "
        "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ?",
        [match_id, start, end]).fetch_df()
    # CV contacts + shot calls (empty pre-strokes); shuttle trail from the shuttle track
    stroke_rows = con.execute(
        "SELECT frame_num, hitter, shot_type, hit_x, hit_y FROM strokes WHERE match_id=? "
        "AND source='pipeline' AND frame_num BETWEEN ? AND ? ORDER BY frame_num",
        [match_id, start, end]).fetchall()
    con.close()
    by_frame = {f: g for f, g in df.groupby("frame_num")}
    try:
        from .. import hits as _hits
        from ..insights import SHOT_DISPLAY    # presentation renames, as in export_web
        shu = _hits.shuttle_series(match_id, start, end)[["img_x", "img_y"]]
        shu = None if shu["img_y"].isna().all() else shu
    except Exception:
        shu, SHOT_DISPLAY = None, {}

    # debounced formation + front slot, per (frame, side) — scoped to the rally window
    rd = roles.roles_df(match_id, start, end)
    form, front = {}, {}
    for side in ("near", "far"):
        s = rd[rd.side == side].sort_values("frame_num")
        fm = roles.hysteresis_formation((s.depth_gap - s.lateral_gap).tolist())
        for fr, f in zip(s.frame_num, fm):
            form[(fr, side)] = f
    for r in rd.itertuples():
        front[(r.frame_num, r.side)] = r.front

    # one stable score for the whole rally: use the caller's value, else OCR it once
    if score is None:
        ev = _score_events(match_id, start, end, samples=3)
        score = ev[-1][1] if ev else None

    cap = cv2.VideoCapture(str(config.REPO_ROOT / m["video_path"]))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    wpx, hpx = int(cap.get(3)), int(cap.get(4))
    raw_out = Path(out_path).with_name("_raw_" + Path(out_path).name)
    writer = cv2.VideoWriter(str(raw_out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (wpx, hpx))

    for fr in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        for a, b in lines:
            cv2.line(frame, a, b, (0, 170, 0), 1)
        g = by_frame.get(fr)
        if g is not None:
            for r in g.itertuples(index=False):
                pid, (cx, cy, w, h), kp = r.player_id, r.bbox, r.keypoints
                side = "near" if pid in ("near", "near2") else "far"
                role = "front" if front.get((fr, side)) == pid else "back"
                label = f"{names.get(pid, pid) if names else pid} [{role}]"
                col = COL[pid]
                cv2.rectangle(frame, (int(cx - w / 2), int(cy - h / 2)),
                              (int(cx + w / 2), int(cy + h / 2)), col, 2)
                if kp is not None:
                    _draw_skeleton(frame, kp, col)
                cv2.putText(frame, label, (int(cx - w / 2), int(cy - h / 2) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
        # shuttle trail (last TRAIL frames, thickening toward the present)
        if shu is not None:
            seg = shu.loc[max(start, fr - TRAIL):fr].dropna()
            pts = seg.to_numpy().astype(int)
            for j in range(1, len(pts)):
                cv2.line(frame, tuple(pts[j - 1]), tuple(pts[j]),
                         (255, 255, 255), 1 + (2 * j) // max(1, len(pts)))
            if len(pts):
                cv2.circle(frame, tuple(pts[-1]), 4, (255, 255, 255), -1)
        # contact ring + shot call at each CV-detected hit (hitter's colour)
        for sf, hitter, shot, hx, hy in stroke_rows:
            if hx is not None and 0 <= fr - sf <= HIT_RING:
                col = COL.get(hitter, (255, 255, 255))
                cv2.circle(frame, (int(hx), int(hy)), 14, col, 2)
                cv2.putText(frame, SHOT_DISPLAY.get(shot, shot), (int(hx) + 18, int(hy) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
        # formation banner (top-left)
        cv2.rectangle(frame, (0, 0), (wpx, 28), (0, 0, 0), -1)
        cv2.putText(frame, f"near: {form.get((fr, 'near'), '-')}    far: {form.get((fr, 'far'), '-')}"
                    f"    frame {fr}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        # machine-read score (top-right), constant through the rally
        if score:
            cv2.rectangle(frame, (wpx - 184, 32), (wpx - 8, 64), (20, 26, 22), -1)
            cv2.putText(frame, f"AI score {score}", (wpx - 176, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 245, 212), 2)
        writer.write(frame)

    cap.release()
    writer.release()

    # transcode to web-weight browser-friendly H.264, drop the raw file
    cmd = ["ffmpeg", "-y", "-i", str(raw_out), "-c:v", "libx264", "-crf", str(crf),
           "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if out_height:
        cmd += ["-vf", f"scale=-2:{out_height}"]
    subprocess.run(cmd + [str(out_path)], check=True, capture_output=True)
    raw_out.unlink(missing_ok=True)
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
