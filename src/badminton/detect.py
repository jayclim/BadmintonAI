"""Player detection + pose + tracking -> per-frame court positions. Phase 0 step 4-5.

YOLO11-Pose (COCO 17 keypoints) + ByteTrack. The foot point (ankle midpoint) is
mapped through the calibrated homography to court metres and written to `tracks`.
Singles simplification: keep the 2 players, label near/far by court half.

Requires: ultralytics, supervision, a downloaded video, and a calibrated homography
(run fetch_video.py + calibrate_court.py first).

Usage:
    python -m badminton.detect india_open_2022_final [--model yolo11x-pose.pt] [--max-frames N]
"""

from __future__ import annotations

import argparse

import numpy as np

from . import config, court, db

# COCO-17 ankle keypoint indices
L_ANKLE, R_ANKLE = 15, 16


def ankle_x(kpts_xy: np.ndarray, kpts_conf: np.ndarray, min_conf: float = 0.3):
    """Lateral foot position = mean of visible ankles' x (fallback: more confident one)."""
    la, ra = kpts_conf[L_ANKLE], kpts_conf[R_ANKLE]
    if la >= min_conf and ra >= min_conf:
        return float((kpts_xy[L_ANKLE, 0] + kpts_xy[R_ANKLE, 0]) / 2)
    if max(la, ra) >= min_conf:
        return float(kpts_xy[L_ANKLE if la >= ra else R_ANKLE, 0])
    return None


# Ground-point blend: y = ankle_y + FOOT_BLEND*(bbox_bottom_y - ankle_y).
# 0 = ankle midpoint (sits ~0.1 m above ground → +depth bias),
# 1 = bbox bottom (overshoots below the feet for large near players).
# 0.65 minimizes validation error against ShuttleSet (near & far balanced ~0.55 m).
FOOT_BLEND = 0.65


def ground_point(box_xywh: np.ndarray, kxy: np.ndarray, kcf: np.ndarray,
                 blend: float = FOOT_BLEND):
    """Ground-contact pixel: lateral x from the ankles (accurate during lunges),
    vertical y blended between ankle and bbox bottom (see FOOT_BLEND)."""
    cx, cy, w, h = (float(v) for v in box_xywh)
    bbox_bottom = cy + h / 2.0
    ys = [kxy[idx, 1] for idx in (L_ANKLE, R_ANKLE) if kcf[idx] >= 0.3]
    ankle_y = float(np.mean(ys)) if ys else bbox_bottom
    ax = ankle_x(kxy, kcf)
    return np.array([ax if ax is not None else cx,
                     ankle_y + blend * (bbox_bottom - ankle_y)])


def process_video(match_id: str, model_name: str = "yolo11x-pose.pt",
                  start_frame: int = 0, max_frames: int | None = None,
                  device: str = "mps", imgsz: int = 1280, margin: float = 0.7,
                  stride: int = 1) -> int:
    import cv2
    from ultralytics import YOLO

    m = config.get_match(match_id)
    if not m.get("homography"):
        raise SystemExit(f"no homography for {match_id} — run calibrate_court.py first")
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    video = config.REPO_ROOT / m["video_path"]

    model = YOLO(model_name)
    span = max_frames * stride if max_frames else 2**31  # frames this run will (re)compute

    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    rows: list[list] = []
    n_frames = 0
    frame_idx = start_frame
    while max_frames is None or n_frames < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        # per-frame track with persist=True keeps ByteTrack state across the window
        res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                          imgsz=imgsz, device=device, verbose=False)[0]
        n_frames += 1
        cur_frame = frame_idx
        frame_idx += 1
        for _ in range(stride - 1):       # skip frames without decoding (10/15fps is plenty for movement)
            if not cap.grab():
                break
            frame_idx += 1
        if res.keypoints is None or res.boxes is None or res.boxes.id is None:
            continue
        kxy = res.keypoints.xy.cpu().numpy()        # (P,17,2) image px
        kcf = res.keypoints.conf.cpu().numpy()      # (P,17)
        boxes = res.boxes.xywh.cpu().numpy()        # (P,4)
        tids = res.boxes.id.cpu().numpy().astype(int)

        # keep only on-court people (rejects umpire/line judges/coaches), then
        # take the largest detection per court half — singles = 1 near + 1 far.
        best: dict[str, tuple] = {}
        for i in range(len(tids)):
            fp = ground_point(boxes[i], kxy[i], kcf[i])
            cxy = court.image_to_court(fp.reshape(1, 2), H)[0]
            if not court.in_court(cxy, margin=margin):
                continue
            area = float(boxes[i, 2] * boxes[i, 3])
            pid = court.which_half(float(cxy[1]))
            if pid not in best or area > best[pid][0]:
                best[pid] = (area, cxy, fp, kxy[i], kcf[i], boxes[i])

        for pid, (_, cxy, fp, kpx, kcf_i, box) in best.items():
            kp51 = np.concatenate([kpx, kcf_i[:, None]], axis=1).flatten().tolist()
            rows.append([
                match_id, cur_frame, pid,
                float(cxy[0]), float(cxy[1]), float(fp[0]), float(fp[1]),
                box.tolist(), kp51, float(kcf_i.mean()),
            ])

    cap.release()
    # take the write lock only now (seconds), so the dashboard can read during the run
    con = db.connect()
    con.execute("DELETE FROM tracks WHERE match_id=? AND frame_num>=? AND frame_num<?",
                [match_id, start_frame, start_frame + span])
    if rows:
        con.executemany(
            "INSERT INTO tracks (match_id, frame_num, player_id, court_x, court_y, "
            "img_x, img_y, bbox, keypoints, pose_conf) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    con.close()
    print(f"processed {n_frames} frames -> {len(rows)} track rows")
    return len(rows)


def process_frames(match_id: str, frames: list[int], model_name: str = "yolo11x-pose.pt",
                   device: str = "mps", imgsz: int = 1280, margin: float = 0.7) -> int:
    """Single-frame pose on an explicit (sorted) frame list — for match-wide validation
    at the labeled stroke frames. No tracking; consecutive frames avoid re-seeking."""
    import cv2
    from ultralytics import YOLO

    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    model = YOLO(model_name)
    cap = cv2.VideoCapture(str(config.REPO_ROOT / m["video_path"]))

    rows: list[list] = []
    prev = None
    for fr in frames:
        if fr != (prev + 1 if prev is not None else None):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fr)
        prev = fr
        ok, frame = cap.read()
        if not ok:
            continue
        res = model.predict(frame, imgsz=imgsz, device=device, verbose=False)[0]
        if res.keypoints is None or res.boxes is None:
            continue
        kxy = res.keypoints.xy.cpu().numpy()
        kcf = res.keypoints.conf.cpu().numpy()
        boxes = res.boxes.xywh.cpu().numpy()
        best: dict[str, tuple] = {}
        for i in range(len(boxes)):
            fp = ground_point(boxes[i], kxy[i], kcf[i])
            cxy = court.image_to_court(fp.reshape(1, 2), H)[0]
            if not court.in_court(cxy, margin=margin):
                continue
            area = float(boxes[i, 2] * boxes[i, 3])
            pid = court.which_half(float(cxy[1]))
            if pid not in best or area > best[pid][0]:
                best[pid] = (area, cxy, fp, kxy[i], kcf[i], boxes[i])
        for pid, (_, cxy, fp, kpx, kcf_i, box) in best.items():
            kp51 = np.concatenate([kpx, kcf_i[:, None]], axis=1).flatten().tolist()
            rows.append([match_id, fr, pid, float(cxy[0]), float(cxy[1]),
                         float(fp[0]), float(fp[1]), box.tolist(), kp51, float(kcf_i.mean())])
    cap.release()
    con = db.connect()                       # brief write lock at the end only
    con.execute("DELETE FROM tracks WHERE match_id = ?", [match_id])
    if rows:
        con.executemany(
            "INSERT INTO tracks (match_id, frame_num, player_id, court_x, court_y, "
            "img_x, img_y, bbox, keypoints, pose_conf) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    print(f"processed {len(frames)} frames -> {len(rows)} track rows")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--model", default="yolo11x-pose.pt")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--margin", type=float, default=0.7)
    ap.add_argument("--stride", type=int, default=1)
    args = ap.parse_args()
    process_video(args.match_id, args.model, args.start_frame, args.max_frames,
                  args.device, args.imgsz, args.margin, args.stride)


if __name__ == "__main__":
    main()
