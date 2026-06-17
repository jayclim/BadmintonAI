"""Doubles 4-player tracking with stable identity slots (Phase 0, ISOLATED).

Mirrors detect.process_video, but instead of keeping the single largest detection per
court half (singles), it keeps the TOP-2 per half and assigns each a STABLE slot:
  near / near2  (the camera-near pair)   far / far2  (the far pair)
written to the same `tracks` table — `tracks.player_id` already documents near2/far2.

Identity is the hard part of doubles (same uniforms defeat appearance ReID; occlusion
and crossing cause ID switches). Two mechanisms keep a slot pinned to one physical
player across a rally:
  1. Persistence — a YOLO/ByteTrack track-id, once given a slot, keeps it.
  2. Velocity re-ID — when ByteTrack drops an id through occlusion and a new id appears
     near a lost slot's PREDICTED position (last + velocity), the slot is inherited.
     Threshold is in court metres (resolution-independent), gated to short gaps.

Slot labels are arbitrary persistence tags, NOT tactical meaning. Front/back, left/
right and formation are derived per-frame in badminton.doubles.roles and do not care
which physical player is 'near' vs 'near2'. (Anchoring slots to true players at the
serve — service court is fixed by score parity — is a later refinement; see roles.py.)

CLI:
  PYTHONPATH=src python -m badminton.doubles.track <match_id> \
      [--model yolo11x-pose.pt] [--start-frame F] [--max-frames N] [--stride S]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np

from .. import config, court, db
from ..detect import ground_point  # reuse the singles ground-contact estimator

# Stable slots per court half. Order is the preference order for a fresh assignment.
SLOTS = {"near": ("near", "near2"), "far": ("far", "far2")}

# Velocity re-ID: a dropped slot may be re-claimed by a new detection within this many
# court metres of its predicted position. Court is 6.10 x 13.40 m; 1.5 m comfortably
# covers a player's travel over the <~10 frame gaps ByteTrack typically loses.
REID_RADIUS_M = 1.5
REID_MAX_GAP = 15            # frames; beyond this a slot's prediction is too stale to trust


@dataclass(eq=False)  # identity equality: holds numpy arrays, and `in`/`remove` below
class _Det:            # must match by object identity, not elementwise array compare
    tid: int
    cxy: np.ndarray          # court metres (x, y)
    fp: np.ndarray           # ground-contact pixel
    kxy: np.ndarray
    kcf: np.ndarray
    box: np.ndarray
    area: float


@dataclass
class _SlotState:
    last_frame: int | None = None
    last_xy: np.ndarray | None = None
    prev_xy: np.ndarray | None = None

    def predict(self, frame: int) -> np.ndarray | None:
        """Constant-velocity extrapolation to `frame` (court metres), or None if stale."""
        if self.last_xy is None or self.last_frame is None:
            return None
        if frame - self.last_frame > REID_MAX_GAP:
            return None
        if self.prev_xy is None:
            return self.last_xy
        return self.last_xy + (self.last_xy - self.prev_xy)

    def commit(self, frame: int, xy: np.ndarray) -> None:
        self.prev_xy = self.last_xy
        self.last_xy = xy
        self.last_frame = frame


class SlotAssigner:
    """Maps per-frame detections to stable slots (near/near2, far/far2).

    Keeps slots pinned via ByteTrack ids (persistence) and recovers dropped ids by
    velocity (re-ID). Stateful across frames — one instance per tracking run."""

    def __init__(self) -> None:
        self.slot_of_tid: dict[int, str] = {}
        self.state: dict[str, _SlotState] = {s: _SlotState() for h in SLOTS for s in SLOTS[h]}

    def update(self, frame: int, dets: list[_Det]) -> dict[str, _Det]:
        out: dict[str, _Det] = {}
        by_half: dict[str, list[_Det]] = {"near": [], "far": []}
        for d in dets:
            by_half[court.which_half(float(d.cxy[1]))].append(d)

        for half, slots in SLOTS.items():
            # at most 2 real players per half; drop spurious extras by smallest area
            cands = sorted(by_half[half], key=lambda d: -d.area)[:2]
            taken: set[str] = set()
            leftover: list[_Det] = []

            # pass 1 — persistence: a det whose tid already owns a slot on this half keeps it
            for d in cands:
                s = self.slot_of_tid.get(d.tid)
                if s in slots and s not in taken:
                    out[s] = d
                    taken.add(s)
                else:
                    leftover.append(d)

            # pass 2 — velocity re-ID: match leftover dets to free slots by predicted pos
            free = [s for s in slots if s not in taken]
            pairs = []
            for d in leftover:
                for s in free:
                    pred = self.state[s].predict(frame)
                    if pred is not None:
                        dist = float(np.hypot(*(d.cxy - pred)))
                        if dist <= REID_RADIUS_M:
                            pairs.append((dist, d, s))
            for _, d, s in sorted(pairs, key=lambda p: p[0]):
                if d in leftover and s in free:
                    out[s] = d
                    taken.add(s); free.remove(s); leftover.remove(d)
                    self.slot_of_tid[d.tid] = s

            # pass 3 — cold assignment: remaining dets fill remaining slots (rally start / lost)
            for d, s in zip(leftover, free):
                out[s] = d
                self.slot_of_tid[d.tid] = s

        for s, d in out.items():
            self.state[s].commit(frame, d.cxy)
        return out


def _ensure_match_row(con, match_id: str, m: dict) -> None:
    """Insert a minimal `matches` row from config if absent. The ShuttleSet importer
    is the only other thing that creates one, so a label-free (non-ShuttleSet) match
    like a doubles broadcast would otherwise trip the tracks→matches foreign key."""
    if con.execute("SELECT 1 FROM matches WHERE match_id=?", [match_id]).fetchone():
        return
    con.execute(
        "INSERT INTO matches (match_id, discipline, player_near, player_far, tournament, "
        "match_date, video_url, fps, camera_view, homography, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [match_id, m.get("discipline"), m.get("player_near"), m.get("player_far"),
         m.get("tournament"), str(m["match_date"]) if m.get("match_date") else None,
         m.get("video_url"), m.get("fps"), "broadcast", m.get("homography"), "pipeline"])


def _detections(res, H: np.ndarray, margin: float) -> list[_Det]:
    """In-court people for one frame as _Det (rejects umpire/coaches via in_court)."""
    if res.keypoints is None or res.boxes is None or res.boxes.id is None:
        return []
    kxy = res.keypoints.xy.cpu().numpy()
    kcf = res.keypoints.conf.cpu().numpy()
    boxes = res.boxes.xywh.cpu().numpy()
    tids = res.boxes.id.cpu().numpy().astype(int)
    out: list[_Det] = []
    for i in range(len(tids)):
        fp = ground_point(boxes[i], kxy[i], kcf[i])
        cxy = court.image_to_court(fp.reshape(1, 2), H)[0]
        if not court.in_court(cxy, margin=margin):
            continue
        out.append(_Det(int(tids[i]), cxy, fp, kxy[i], kcf[i], boxes[i],
                        float(boxes[i, 2] * boxes[i, 3])))
    return out


def process_video(match_id: str, model_name: str = "yolo11x-pose.pt",
                  start_frame: int = 0, max_frames: int | None = None,
                  device: str = "mps", imgsz: int = 1280, margin: float = 0.7,
                  stride: int = 1, conf: float = 0.25) -> int:
    import cv2
    from ultralytics import YOLO

    m = config.get_match(match_id)
    if m.get("discipline") not in (None, "doubles"):
        print(f"warning: {match_id} discipline={m.get('discipline')!r}; "
              "doubles tracker keeps 2 players/half regardless")
    if not m.get("homography"):
        raise SystemExit(f"no homography for {match_id} — run calibrate_court.py first")
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    video = config.REPO_ROOT / m["video_path"]

    model = YOLO(model_name)
    span = max_frames * stride if max_frames else 2**31
    assigner = SlotAssigner()

    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    rows: list[list] = []
    n_frames = 0
    frame_idx = start_frame
    while max_frames is None or n_frames < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        res = model.track(frame, persist=True, tracker="bytetrack.yaml",
                          imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
        n_frames += 1
        cur_frame = frame_idx
        frame_idx += 1
        for _ in range(stride - 1):
            if not cap.grab():
                break
            frame_idx += 1

        dets = _detections(res, H, margin)
        for pid, d in assigner.update(cur_frame, dets).items():
            kp51 = np.concatenate([d.kxy, d.kcf[:, None]], axis=1).flatten().tolist()
            rows.append([
                match_id, cur_frame, pid,
                float(d.cxy[0]), float(d.cxy[1]), float(d.fp[0]), float(d.fp[1]),
                d.box.tolist(), kp51, float(d.kcf.mean()),
            ])

    cap.release()
    con = db.connect()
    _ensure_match_row(con, match_id, m)        # tracks FK needs a matches row (label-free path)
    con.execute("DELETE FROM tracks WHERE match_id=? AND frame_num>=? AND frame_num<?",
                [match_id, start_frame, start_frame + span])
    if rows:
        con.executemany(
            "INSERT INTO tracks (match_id, frame_num, player_id, court_x, court_y, "
            "img_x, img_y, bbox, keypoints, pose_conf) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    con.close()
    print(f"processed {n_frames} frames -> {len(rows)} track rows "
          f"({len(rows) / n_frames:.2f}/frame)" if n_frames else "no frames")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles 4-player tracker (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--model", default="yolo11x-pose.pt")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--margin", type=float, default=0.7)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--conf", type=float, default=0.25, help="detection conf (lower = more far-side recall)")
    args = ap.parse_args()
    process_video(args.match_id, args.model, args.start_frame, args.max_frames,
                  args.device, args.imgsz, args.margin, args.stride, args.conf)


if __name__ == "__main__":
    main()
