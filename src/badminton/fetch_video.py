"""Download a match video (yt-dlp) and pull frames. Phase 0 step 2.

Usage:
    python -m badminton.fetch_video <match_id> --url https://youtu.be/XXXX
    python -m badminton.fetch_video <match_id> --frame-at 00:12:30 -o frame.png
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from . import config

REPO_ROOT = Path(__file__).resolve().parents[2]


def download(match_id: str, url: str | None = None) -> Path:
    m = config.get_match(match_id)
    url = url or m.get("video_url")
    if not url:
        raise SystemExit(
            f"No video_url for {match_id!r}. ShuttleSet ships annotations, not video.\n"
            f"Find the BWF/YouTube URL of this match and pass --url, or set it in matches.yaml."
        )
    out = REPO_ROOT / m["video_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    # Prefer mp4; keep original fps. (Re-encodes can shift frame count vs ShuttleSet —
    # we verify alignment downstream.)
    subprocess.run(
        ["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
         "--merge-output-format", "mp4", "-o", str(out), url],
        check=True,
    )
    config.update_match(match_id, {"video_url": url, "fps": probe_fps(out)})
    return out


def probe_fps(video_path: Path | str) -> float:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return round(float(fps), 6)


def grab_frame(video_path: Path | str, timestamp: str, out_path: Path | str) -> Path:
    """Extract a single frame at HH:MM:SS using ffmpeg."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", timestamp, "-i", str(video_path),
         "-frames:v", "1", str(out_path)],
        check=True,
    )
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--url", default=None)
    ap.add_argument("--frame-at", default=None, help="HH:MM:SS — extract one frame")
    ap.add_argument("-o", "--out", default="data/raw/frame.png")
    args = ap.parse_args()

    m = config.get_match(args.match_id)
    if args.frame_at:
        video = REPO_ROOT / m["video_path"]
        grab_frame(video, args.frame_at, args.out)
        print(f"frame -> {args.out}")
    else:
        path = download(args.match_id, args.url)
        print(f"video -> {path}  (fps={probe_fps(path)})")


if __name__ == "__main__":
    main()
