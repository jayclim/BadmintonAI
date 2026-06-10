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


def render(match_id: str, start: int, end: int, out_path: Path,
           fps: float = 30.0, ss_linger: int = 10) -> Path:
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    video = config.REPO_ROOT / m["video_path"]

    con = db.connect(read_only=True)
    tracks: dict[int, list] = {}
    for f, pid, ix, iy, cx, cy, box in con.execute(
        "SELECT frame_num,player_id,img_x,img_y,court_x,court_y,bbox FROM tracks "
        "WHERE match_id=? AND frame_num BETWEEN ? AND ?", [match_id, start, end]).fetchall():
        tracks.setdefault(f, []).append((pid, ix, iy, cx, cy, box))
    ss: dict[int, tuple] = {}
    for f, hx, hy, st, raw in con.execute(
        "SELECT frame_num,hitter_x,hitter_y,shot_type,shot_type_raw FROM strokes "
        "WHERE match_id=? AND source='shuttleset' AND hitter_x IS NOT NULL "
        "AND frame_num BETWEEN ? AND ?", [match_id, start - 30, end]).fetchall():
        ss[f + SS_OFFSET] = (hx, hy, st, raw)
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
        for pid, ix, iy, cx, cy, box in tracks.get(fr, []):
            col = viz.NEAR_C if pid == "near" else viz.FAR_C
            bx, by, bw, bh = box
            cv2.rectangle(frame, (int(bx - bw / 2), int(by - bh / 2)),
                          (int(bx + bw / 2), int(by + bh / 2)), col, 2)
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
                    if age <= 3:
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
        for i, (txt, col) in enumerate([("near", viz.NEAR_C), ("far", viz.FAR_C),
                                        ("ShuttleSet", viz.SS_C),
                                        ("shuttle", (90, 255, 255))]):
            cv2.putText(frame, txt, (x0, y0 + ch + 16 + i * 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
        cv2.putText(frame, f"frame {fr}", (12, Hh - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(frame)

    cap.release()
    writer.release()

    # transcode to browser-friendly H.264 (Streamlit/QuickTime), drop the raw file
    subprocess.run(["ffmpeg", "-y", "-i", str(raw_out), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
                   check=True, capture_output=True)
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
