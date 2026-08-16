"""Doubles 4-player tracking with stable identity slots (Phase 0, ISOLATED).

Mirrors detect.process_video, but instead of keeping the single largest detection per
court half (singles), it keeps the TOP-2 per half and assigns each a STABLE slot:
  near / near2  (the camera-near pair)   far / far2  (the far pair)
written to the same `tracks` table — `tracks.player_id` already documents near2/far2.

Identity is the hard part of doubles (same uniforms defeat appearance ReID; occlusion
and crossing cause ID switches). Four mechanisms keep a slot pinned to one physical
player across a rally:
  1. Persistence — a YOLO/ByteTrack track-id, once given a slot, keeps it.
  2. Velocity re-ID — when ByteTrack drops an id through occlusion and a new id appears
     near a lost slot's PREDICTED position (last + velocity), the slot is inherited.
     Threshold is in court metres (resolution-independent), gated to short gaps, and
     WIDENS with the distance the slot could plausibly have covered — the players who
     get dropped are the fast ones, so a fixed radius rejects the recoveries that matter.
  3. Optimal assignment — re-ID and cold fill are scored together and solved exactly
     (tiny bipartite match), so a greedy first pick cannot lock in the crossed pairing
     when two team-mates swap sides.
  4. Sticky halves — players cannot cross the net, so a detection is kept on the half its
     track was last on. A lunging far player, with the usual far-court depth error, can
     project to court_y < NET_Y_M; without this it is handed to the near pair's slots.

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
from math import log

import numpy as np

from .. import config, court, db
from ..detect import ground_point  # reuse the singles ground-contact estimator

# Stable slots per court half. Order is the preference order for a fresh assignment.
SLOTS = {"near": ("near", "near2"), "far": ("far", "far2")}

# Velocity re-ID: a dropped slot may be re-claimed by a new detection near its predicted
# position. Court is 6.10 x 13.40 m. The gate is NOT a constant — a player at 5 m/s covers
# 2.5 m over a 15-frame gap, so a fixed 1.5 m rejects exactly the fast movers ByteTrack
# drops. It scales with the travel the slot's own velocity implies.
REID_RADIUS_M = 1.5          # base radius (a stationary slot, or one with no velocity yet)
REID_SLACK = 1.0             # multiplier on the slot's extrapolated travel
REID_MAX_RADIUS_M = 4.0      # ceiling; past this it is a fresh identity, not a recovery
REID_MAX_GAP = 15            # frames; beyond this a slot's prediction is too stale to trust
MAX_SPEED_M_PER_FRAME = 0.35  # ~10 m/s at 30 fps — clamps ground-point jitter, not real running

# Cost of filling a slot with a detection that did NOT re-ID into it (no usable prediction,
# or outside the radius). Strictly worse than any in-radius match so geometry always wins,
# but finite: a leftover detection belongs in a free slot rather than dropped on the floor.
COLD_COST = 100.0
AREA_COST_W = 0.5            # metres-equivalent penalty for a 2x apparent-size mismatch

# Half assignment is sticky — see mechanism 4 in the module docstring.
HALF_FLIP_FRAMES = 5         # consecutive frames on the other side before a half flips
HALF_MEMORY_FRAMES = 600     # forget a track-id unseen this long (ByteTrack reuses ids)


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
    prev_frame: int | None = None
    prev_xy: np.ndarray | None = None
    last_area: float | None = None

    def velocity(self) -> np.ndarray:
        """Court metres PER FRAME from the last two commits (zeros if unknown).

        Dividing by the real frame delta is what makes this correct under --stride and
        across dropped frames; clamping keeps a jittery ground-point estimate from
        throwing the prediction across the court."""
        if (self.last_xy is None or self.prev_xy is None
                or self.last_frame is None or self.prev_frame is None):
            return np.zeros(2)
        dt = self.last_frame - self.prev_frame
        if dt <= 0:
            return np.zeros(2)
        v = (self.last_xy - self.prev_xy) / dt
        speed = float(np.hypot(*v))
        return v * (MAX_SPEED_M_PER_FRAME / speed) if speed > MAX_SPEED_M_PER_FRAME else v

    def predict(self, frame: int) -> np.ndarray | None:
        """Constant-velocity extrapolation to `frame` (court metres), or None if stale.

        Scaled by the ACTUAL gap: a 15-frame gap moves fifteen frames' worth, not one."""
        if self.last_xy is None or self.last_frame is None:
            return None
        gap = frame - self.last_frame
        if gap > REID_MAX_GAP:
            return None
        return self.last_xy + self.velocity() * max(gap, 0)

    def reid_radius(self, frame: int) -> float:
        """How far from its prediction this slot will still claim a detection."""
        if self.last_frame is None:
            return REID_RADIUS_M
        travel = float(np.hypot(*self.velocity())) * max(frame - self.last_frame, 0)
        return min(REID_RADIUS_M + REID_SLACK * travel, REID_MAX_RADIUS_M)

    def commit(self, frame: int, xy: np.ndarray, area: float | None = None) -> None:
        self.prev_frame, self.prev_xy = self.last_frame, self.last_xy
        self.last_frame, self.last_xy = frame, xy
        if area:
            self.last_area = area


def _best_matching(costs: dict[tuple[int, int], float],
                   n_dets: int, n_slots: int) -> list[tuple[int, int]]:
    """Exact minimum-cost bipartite matching for the tiny (<=2x2) doubles case.

    Brute force over every matching — seven of them at 2x2 — which is both optimal and
    cheaper than taking a scipy dependency. Prefers the LARGEST matching, then the
    cheapest: leaving a real player unslotted is worse than an imperfect pairing."""
    best_key: tuple[int, float] | None = None
    best: list[tuple[int, int]] = []

    def rec(i: int, used: frozenset[int], pairs: list[tuple[int, int]], total: float) -> None:
        nonlocal best_key, best
        if i == n_dets:
            key = (-len(pairs), total)
            if best_key is None or key < best_key:
                best_key, best = key, list(pairs)
            return
        for j in range(n_slots):
            if j not in used and (i, j) in costs:
                pairs.append((i, j))
                rec(i + 1, used | {j}, pairs, total + costs[(i, j)])
                pairs.pop()
        rec(i + 1, used, pairs, total)          # or detection i takes no slot at all

    rec(0, frozenset(), [], 0.0)
    return best


class SlotAssigner:
    """Maps per-frame detections to stable slots (near/near2, far/far2).

    Keeps slots pinned via ByteTrack ids (persistence), recovers dropped ids by velocity
    (re-ID over a gap-scaled radius), resolves the two together as one optimal assignment,
    and holds each track to its own half of the net. Stateful across frames — one instance
    per tracking run. See the module docstring for why each mechanism exists."""

    def __init__(self) -> None:
        self.slot_of_tid: dict[int, str] = {}
        self.half_of_tid: dict[int, str] = {}
        self.state: dict[str, _SlotState] = {s: _SlotState() for h in SLOTS for s in SLOTS[h]}
        self._disagree: dict[int, int] = {}     # consecutive frames a tid looked cross-net
        self._seen: dict[int, int] = {}         # tid -> last frame seen
        self._last_prune = 0

    def _half_for(self, frame: int, d: _Det) -> str:
        """Which half's slots this detection competes for — sticky across frames.

        A track keeps the half it was last on. Nobody crosses the net mid-rally, so a
        one-frame flip is projection error on a lunge, not a crossing. A SUSTAINED flip
        is a real change of ends (or a reused track-id), and re-anchors."""
        obs = court.which_half(float(d.cxy[1]))
        self._seen[d.tid] = frame
        prev = self.half_of_tid.get(d.tid)
        if prev is None or prev == obs:
            self._disagree[d.tid] = 0
            self.half_of_tid[d.tid] = obs
            return obs
        self._disagree[d.tid] = n = self._disagree.get(d.tid, 0) + 1
        if n < HALF_FLIP_FRAMES:
            return prev
        self._disagree[d.tid] = 0
        self.half_of_tid[d.tid] = obs
        self.slot_of_tid.pop(d.tid, None)       # its old slot is on the other half now
        return obs

    def _prune(self, frame: int) -> None:
        """Forget track-ids unseen for a while: ByteTrack reuses ids, and a stale half
        would strand a brand-new player on the wrong side of the net."""
        if frame - self._last_prune < HALF_MEMORY_FRAMES:
            return
        self._last_prune = frame
        for tid in [t for t, f in self._seen.items() if frame - f > HALF_MEMORY_FRAMES]:
            for m in (self._seen, self.half_of_tid, self._disagree, self.slot_of_tid):
                m.pop(tid, None)

    def _cost(self, frame: int, d: _Det, slot: str) -> float:
        """Assignment cost in court metres. An in-radius re-ID scores by distance to the
        slot's prediction; everything else pays COLD_COST, so geometry always wins first
        and cold fill only breaks ties among detections nothing claimed."""
        st = self.state[slot]
        pen = AREA_COST_W * abs(log(d.area / st.last_area)) if st.last_area and d.area > 0 else 0.0
        pred = st.predict(frame)
        if pred is None:
            return COLD_COST + pen
        dist = float(np.hypot(*(d.cxy - pred)))
        return (dist if dist <= st.reid_radius(frame) else COLD_COST + dist) + pen

    def update(self, frame: int, dets: list[_Det]) -> dict[str, _Det]:
        out: dict[str, _Det] = {}
        by_half: dict[str, list[_Det]] = {"near": [], "far": []}
        for d in dets:
            by_half[self._half_for(frame, d)].append(d)
        self._prune(frame)

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

            # pass 2 — velocity re-ID and cold fill, solved together as ONE optimal
            # assignment. Scoring them jointly is what fixes the crossing case: a greedy
            # nearest-first pass commits to its best single pair and can strand the other
            # detection on the wrong slot, which pins the swap in for the rest of the rally.
            free = [s for s in slots if s not in taken]
            costs = {(i, j): self._cost(frame, d, s)
                     for i, d in enumerate(leftover) for j, s in enumerate(free)}
            for i, j in _best_matching(costs, len(leftover), len(free)):
                out[free[j]] = leftover[i]
                self.slot_of_tid[leftover[i].tid] = free[j]

        for s, d in out.items():
            self.state[s].commit(frame, d.cxy, d.area)
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
