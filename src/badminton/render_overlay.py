"""Render an annotated overlay video for a frame range: player boxes + foot dots,
a live top-down minimap, and ShuttleSet labels overlaid for comparison.

Needs CONTINUOUS tracks over the range (run `detect.py` on that window first).

    python -m badminton.render_overlay india_open_2022_final --start 12420 --end 13620
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import config, court, db, viz

SS_OFFSET = 6  # our_frame = ss_frame + 6 (validated)

# COCO-17 skeleton bones (keypoint index pairs)
SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10),          # arms
            (5, 6), (5, 11), (6, 12), (11, 12),       # torso
            (11, 13), (13, 15), (12, 14), (14, 16),   # legs
            (0, 5), (0, 6)]                            # head -> shoulders
KP_MIN_CONF = 0.3


def draw_skeleton(frame: np.ndarray, kp51: list[float], col: tuple) -> None:
    kp = np.asarray(kp51, dtype=np.float32).reshape(17, 3)
    for a, b in SKELETON:
        if kp[a, 2] >= KP_MIN_CONF and kp[b, 2] >= KP_MIN_CONF:
            cv2.line(frame, (int(kp[a, 0]), int(kp[a, 1])),
                     (int(kp[b, 0]), int(kp[b, 1])), col, 2)
    for x, y, c in kp:
        if c >= KP_MIN_CONF:
            cv2.circle(frame, (int(x), int(y)), 3, (255, 255, 255), -1)


def _nearest_call(shot_calls: dict[int, tuple], hf: int, tol: int = 4):
    """Pipeline stroke frames and detect_hits frames can differ by a frame or two."""
    for d in range(tol + 1):
        for f in (hf - d, hf + d):
            if f in shot_calls:
                return shot_calls[f]
    return None


def render(match_id: str, start: int, end: int, out_path: Path,
           fps: float = 30.0, ss_linger: int = 10,
           ai_only: bool = False, out_height: int | None = None,
           crf: int = 23) -> Path:
    """ai_only=True renders the label-free showcase: no ShuttleSet layer, BST shot
    labels at detected hits (from source='pipeline' strokes) and the OCR-read score.
    out_height downsizes the encode (e.g. 540) for web-weight clips."""
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    video = config.REPO_ROOT / m["video_path"]

    con = db.connect(read_only=True)
    tracks: dict[int, list] = {}
    for f, pid, ix, iy, cx, cy, box, kp in con.execute(
        "SELECT frame_num,player_id,img_x,img_y,court_x,court_y,bbox,keypoints FROM tracks "
        "WHERE match_id=? AND frame_num BETWEEN ? AND ?", [match_id, start, end]).fetchall():
        tracks.setdefault(f, []).append((pid, ix, iy, cx, cy, box, kp))
    ss: dict[int, tuple] = {}
    if not ai_only:
        for f, hx, hy, st, raw in con.execute(
            "SELECT frame_num,hitter_x,hitter_y,shot_type,shot_type_raw FROM strokes "
            "WHERE match_id=? AND source='shuttleset' AND hitter_x IS NOT NULL "
            "AND frame_num BETWEEN ? AND ?", [match_id, start - 30, end]).fetchall():
            ss[f + SS_OFFSET] = (hx, hy, st, raw)
    # label-free layer: BST shot calls at detected hit frames + OCR score readout
    shot_calls: dict[int, tuple] = {}
    for f, st, conf in con.execute(
        "SELECT frame_num,shot_type,shot_type_conf FROM strokes "
        "WHERE match_id=? AND source='pipeline' AND set_no=0 "
        "AND frame_num BETWEEN ? AND ?", [match_id, start - 10, end]).fetchall():
        shot_calls[f] = (st, conf)
    score_events: list[tuple] = []   # (frame, "a–b") from the OCR snapshot
    if ai_only:
        try:
            import json
            from . import labelfree
            snap = json.loads(labelfree.snapshot_path(match_id).read_text())
            row_a = snap["row_a"]
            score_events = sorted(
                (int(e["frame"]),
                 f"{e['top' if row_a == 'top' else 'bot']}-{e['bot' if row_a == 'top' else 'top']}")
                for e in snap.get("events", []))
        except Exception:
            pass
    shuttle: dict[int, tuple] = {}
    for f, sx, sy in con.execute(
        "SELECT frame_num,img_x,img_y FROM shuttle WHERE match_id=? AND visible "
        "AND frame_num BETWEEN ? AND ?", [match_id, start - 15, end]).fetchall():
        shuttle[f] = (sx, sy)
    con.close()

    hit_events: dict[int, dict] = {}
    if shuttle:
        from . import hits as hits_mod
        for h in hits_mod.detect_hits(match_id, start, end):
            hit_events[h["frame"]] = h

    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    W, Hh = int(cap.get(3)), int(cap.get(4))
    cw, ch = viz.court_size()
    raw_out = out_path.with_name("_raw_" + out_path.name)
    writer = cv2.VideoWriter(str(raw_out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, Hh))

    last_ss, ss_age = None, 999
    for fr in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        mini = viz.render_court()
        for pid, ix, iy, cx, cy, box, kp in tracks.get(fr, []):
            col = viz.NEAR_C if pid == "near" else viz.FAR_C
            bx, by, bw, bh = box
            cv2.rectangle(frame, (int(bx - bw / 2), int(by - bh / 2)),
                          (int(bx + bw / 2), int(by + bh / 2)), col, 2)
            if kp is not None:
                draw_skeleton(frame, kp, col)
            cv2.circle(frame, (int(ix), int(iy)), 5, col, -1)
            cv2.putText(frame, pid, (int(bx - bw / 2), int(by - bh / 2) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
            viz.draw_point(mini, cx, cy, col, 6, pid)

        # shuttle comet trail (fading) + current position + hit flashes
        if shuttle:
            TRAIL = 12
            for g in range(fr - TRAIL, fr + 1):
                if g not in shuttle:
                    continue
                fade = max(0.15, 1.0 - (fr - g) / TRAIL)
                col = (int(90 * fade), int(255 * fade), int(255 * fade))   # BGR yellow
                cv2.circle(frame, (int(shuttle[g][0]), int(shuttle[g][1])),
                           max(2, int(6 * fade)), col, -1)
            for hf, h in hit_events.items():
                age = fr - hf
                if 0 <= age <= 6:
                    cv2.circle(frame, (int(h["x"]), int(h["y"])),
                               12 + age * 4, (110, 255, 105), 2)
                # BST shot call lingers longer than the flash so it's readable
                call = _nearest_call(shot_calls, hf)
                if call and 0 <= age <= 24:
                    st, conf = call
                    label = f"{st}" + (f" {conf:.0%}" if conf is not None else "")
                    cv2.putText(frame, label, (int(h["x"]) + 18, int(h["y"]) - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 245, 212), 2)
                elif not call and 0 <= age <= 3:
                    cv2.putText(frame, "HIT", (int(h["x"]) + 18, int(h["y"]) - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (110, 255, 105), 2)

        if fr in ss:
            last_ss, ss_age = ss[fr], 0
        if last_ss is not None and ss_age <= ss_linger:
            hx, hy, st, raw = last_ss
            cv2.drawMarker(frame, (int(hx), int(hy)), viz.SS_C,
                           cv2.MARKER_TILTED_CROSS, 20, 2)
            cv2.putText(frame, f"SS: {st or raw}", (int(hx) + 10, int(hy) + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, viz.SS_C, 2)
            sc = court.image_to_court(np.array([[hx, hy]], np.float32), H)[0]
            viz.draw_point(mini, float(sc[0]), float(sc[1]), viz.SS_C, 5)
        ss_age += 1

        x0, y0 = W - cw - 12, 12
        frame[y0:y0 + ch, x0:x0 + cw] = mini
        cv2.rectangle(frame, (x0 - 1, y0 - 1), (x0 + cw, y0 + ch), (255, 255, 255), 1)
        legend = [("near", viz.NEAR_C), ("far", viz.FAR_C),
                  ("shuttle", (90, 255, 255))]
        if not ai_only:
            legend.insert(2, ("ShuttleSet", viz.SS_C))
        for i, (txt, col) in enumerate(legend):
            cv2.putText(frame, txt, (x0, y0 + ch + 16 + i * 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
        if score_events:
            cur = None
            for ef, s in score_events:
                if ef <= fr:
                    cur = s
                else:
                    break
            if cur:
                cv2.rectangle(frame, (10, 10), (190, 44), (20, 26, 22), -1)
                cv2.putText(frame, f"AI score {cur}", (18, 33),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.62, (60, 245, 212), 2)
        cv2.putText(frame, f"frame {fr}", (12, Hh - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(frame)

    cap.release()
    writer.release()

    # transcode to browser-friendly H.264 (Streamlit/QuickTime), drop the raw file
    cmd = ["ffmpeg", "-y", "-i", str(raw_out), "-c:v", "libx264",
           "-crf", str(crf), "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if out_height:
        cmd += ["-vf", f"scale=-2:{out_height}"]
    subprocess.run(cmd + [str(out_path)], check=True, capture_output=True)
    raw_out.unlink(missing_ok=True)
    print(f"wrote {out_path}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("-o", "--out", default="data/raw/overlay.mp4")
    args = ap.parse_args()
    render(args.match_id, args.start, args.end, config.REPO_ROOT / args.out)


if __name__ == "__main__":
    main()
