"""Shuttle tracking via TrackNetV3 (vendored at third_party/TrackNetV3) → `shuttle` table.

We run the upstream predict.py UNMODIFIED via runpy, after monkeypatching:
- Tensor.cuda / Module.cuda → .to(mps|cpu)   (their code hardcodes .cuda())
- torch.load → map_location='cpu', weights_only=False  (ckpts saved on CUDA, torch 1.10)

Their pipeline: 8-frame sliding window heatmap UNet (with median-background as an extra
input channel) → temporal ensemble → InpaintNet rectifies occluded segments from the
trajectory itself. Output CSV: Frame, X, Y, Visibility (pixels in source resolution;
X=Y=0 means "not visible"). We import that into DuckDB keyed (match_id, frame_num),
with interpolated=True for the rows InpaintNet repaired (visible but heatmap missed).

CLI:
  PYTHONPATH=src python -m badminton.shuttle <match_id>             # full match (hours)
  PYTHONPATH=src python -m badminton.shuttle <match_id> --clip data/clips/..._s1_r1.mp4 \
      --start-frame F      # one clip, frame_num offset by F (smoke tests / per-rally runs)
"""

from __future__ import annotations

import argparse
import csv
import runpy
import sys
from pathlib import Path

from . import config, db

TRACKNET_DIR = config.REPO_ROOT / "third_party" / "TrackNetV3"
CKPT_TRACKNET = TRACKNET_DIR / "ckpts" / "TrackNet_best.pt"
CKPT_INPAINT = TRACKNET_DIR / "ckpts" / "InpaintNet_best.pt"
PRED_DIR = config.REPO_ROOT / "data" / "shuttle_pred"


def _patch_torch():
    """Make TrackNetV3's hardcoded .cuda()/torch.load work on MPS/CPU."""
    import torch

    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    torch.Tensor.cuda = lambda self, *a, **k: self.to(dev)
    torch.nn.Module.cuda = lambda self, *a, **k: self.to(dev)
    _load = torch.load

    def load(*a, **k):
        k.setdefault("map_location", "cpu")
        k["weights_only"] = False
        return _load(*a, **k)

    torch.load = load
    return dev


def run_tracknet(video_file: Path, save_dir: Path, eval_mode: str = "weight",
                 large_video: bool = True, batch_size: int = 8) -> Path:
    """Run upstream predict.py on a video; returns the prediction CSV path."""
    video_file = video_file.resolve()       # we chdir below — relative paths would break
    save_dir = save_dir.resolve()
    save_dir.mkdir(parents=True, exist_ok=True)
    dev = _patch_torch()
    print(f"[shuttle] TrackNetV3 on {video_file.name} (device={dev}, mode={eval_mode})")

    argv = ["predict.py",
            "--video_file", str(video_file),
            "--tracknet_file", str(CKPT_TRACKNET),
            "--inpaintnet_file", str(CKPT_INPAINT),
            "--save_dir", str(save_dir),
            "--eval_mode", eval_mode,
            "--batch_size", str(batch_size)]
    if large_video:
        argv.append("--large_video")

    old_argv, old_path, old_cwd = sys.argv, list(sys.path), Path.cwd()
    try:
        sys.argv = argv
        sys.path.insert(0, str(TRACKNET_DIR))
        import os
        os.chdir(TRACKNET_DIR)          # their utils assume repo-relative paths
        runpy.run_path(str(TRACKNET_DIR / "predict.py"), run_name="__main__")
    finally:
        sys.argv, sys.path = old_argv, old_path
        import os
        os.chdir(old_cwd)
    return save_dir / f"{video_file.stem}_ball.csv"


def import_csv(match_id: str, csv_file: Path, frame_offset: int = 0,
               replace_window: tuple[int, int] | None = None) -> int:
    """Load a TrackNetV3 prediction CSV into the shuttle table.

    frame_offset shifts CSV frame indices into full-video frame numbers (for clips).
    Rows in the target frame range are replaced (re-runs are idempotent).
    """
    rows = []
    with open(csv_file) as f:
        for r in csv.DictReader(f):
            fn = int(r["Frame"]) + frame_offset
            x, y, vis = float(r["X"]), float(r["Y"]), int(r["Visibility"])
            rows.append((match_id, fn, x if vis else None, y if vis else None, bool(vis)))
    if not rows:
        return 0

    lo, hi = replace_window or (rows[0][1], rows[-1][1])
    con = db.connect()
    try:
        con.execute("DELETE FROM shuttle WHERE match_id=? AND frame_num BETWEEN ? AND ?",
                    [match_id, lo, hi])
        con.executemany(
            "INSERT INTO shuttle (match_id, frame_num, img_x, img_y, visible) "
            "VALUES (?, ?, ?, ?, ?)", rows)
    finally:
        con.close()
    return len(rows)


def cut_exact(match_id: str, f0: int, f1: int) -> Path:
    """Write a frame-accurate clip [f0, f1] from the match video via cv2 (ffmpeg -ss
    seeks by time and can land frames off; we seek by exact frame index)."""
    import cv2
    m = config.get_match(match_id)
    video = config.REPO_ROOT / m["video_path"]
    out = PRED_DIR / match_id / f"win_{f0}_{f1}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                         cap.get(cv2.CAP_PROP_FPS), (w, h))
    for _ in range(f1 - f0 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        vw.write(frame)
    cap.release()
    vw.release()
    return out


def track_video(match_id: str, clip: Path | None = None, frame_offset: int = 0,
                eval_mode: str = "weight") -> int:
    """Track one video (full match or clip) and persist to the shuttle table."""
    if clip is None:
        m = config.get_match(match_id)
        video = config.REPO_ROOT / m["video_path"]
        large = True
    else:
        video, large = clip, False
    out_csv = run_tracknet(video, PRED_DIR / match_id, eval_mode=eval_mode,
                           large_video=large)
    n = import_csv(match_id, out_csv, frame_offset=frame_offset)
    print(f"[shuttle] imported {n:,} frames into shuttle table ({match_id})")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="TrackNetV3 shuttle tracking → DuckDB")
    ap.add_argument("match_id")
    ap.add_argument("--clip", type=Path, default=None,
                    help="track a clip instead of the full match video")
    ap.add_argument("--start-frame", type=int, default=0,
                    help="full-video frame number of the clip's first frame")
    ap.add_argument("--window", type=int, nargs=2, metavar=("F0", "F1"), default=None,
                    help="track exact video frames [F0, F1] (frame-accurate cv2 cut)")
    ap.add_argument("--eval-mode", default="weight",
                    choices=["nonoverlap", "average", "weight"],
                    help="temporal ensemble mode (nonoverlap = 8x faster, less accurate)")
    args = ap.parse_args()
    if args.window:
        f0, f1 = args.window
        tmp = cut_exact(args.match_id, f0, f1)
        track_video(args.match_id, clip=tmp, frame_offset=f0, eval_mode=args.eval_mode)
    else:
        track_video(args.match_id, clip=args.clip, frame_offset=args.start_frame,
                    eval_mode=args.eval_mode)
