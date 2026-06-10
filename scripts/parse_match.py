"""Parse the full match into CONTINUOUS tracks, in checkpointed chunks.

After this finishes, every rally's annotated overlay renders instantly (no per-rally
detection), and the Analytics tab spans the whole match.

Runs in chunks: each chunk is written to the DB on completion, so progress survives a
crash and the dashboard can read between chunks. Re-run with --resume to skip done chunks.

    python scripts/parse_match.py                       # default: yolo11m@1280, whole match
    python scripts/parse_match.py --model yolo11x-pose.pt   # max accuracy (slower)
    python scripts/parse_match.py --stride 2 --resume       # faster, continue a prior run
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import db, detect  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--match", default="india_open_2022_final")
ap.add_argument("--model", default="yolo11m-pose.pt")
ap.add_argument("--imgsz", type=int, default=1280)
ap.add_argument("--start", type=int, default=12420)     # first labeled frame
ap.add_argument("--end", type=int, default=110085)      # last labeled frame
ap.add_argument("--chunk", type=int, default=4000)      # frames processed per checkpoint
ap.add_argument("--stride", type=int, default=1)
ap.add_argument("--resume", action="store_true")
args = ap.parse_args()


def covered(cs, ce):
    con = db.connect(read_only=True)
    n = con.execute("SELECT COUNT(*) FROM tracks WHERE match_id=? AND frame_num>=? AND frame_num<?",
                    [args.match, cs, ce]).fetchone()[0]
    con.close()
    return n


t0 = time.time()
span = args.end - args.start
step = args.chunk * args.stride
for cs in range(args.start, args.end, step):
    ce = min(cs + step, args.end)
    n_proc = (ce - cs) // args.stride
    if args.resume and covered(cs, ce) >= n_proc * 1.4:   # ~1.6 rows/frame when fully parsed
        print(f"skip {cs}-{ce} (already parsed)", flush=True)
        continue
    detect.process_video(args.match, args.model, start_frame=cs, max_frames=n_proc,
                         imgsz=args.imgsz, stride=args.stride)
    pct = (ce - args.start) / span * 100
    print(f"[{pct:4.0f}%] {cs}-{ce} · elapsed {(time.time() - t0) / 60:.1f} min", flush=True)

print(f"DONE — full match parsed in {(time.time() - t0) / 60:.1f} min")
