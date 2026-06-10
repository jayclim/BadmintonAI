"""Rally auto-clipping. Phase 1.

ShuttleSet provides stroke frames for EVERY rally across the whole match, so we can cut
any rally straight from the raw video — no detection needed. This is how you watch any
part of the game, rally by rally, instead of just the annotated demo clip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config, db

SS_OFFSET = 6  # video_frame = ss_frame + 6 (validated)
CLIP_DIR = config.REPO_ROOT / "data" / "clips"

# ShuttleSet rally-outcome reasons (Chinese) -> English
REASON_EN = {
    "出界": "hit out (long/wide)",
    "對手落地致勝": "beaten by a winner",
    "掛網": "into the net",
    "未過網": "didn't clear the net",
    "落點判斷失誤": "misjudged the landing",
    "對手出界": "opponent hit out",
    "落地致勝": "winner — landed in",
    "對手掛網": "opponent netted it",
    "對手未過網": "opponent didn't clear net",
    "對手落點判斷失誤": "opponent misjudged landing",
}


def reason_en(cn: str | None) -> str:
    return REASON_EN.get(cn, cn or "—")


def list_rallies(match_id: str) -> list[dict]:
    """Every rally with its shot count, winner and end reason (whole match)."""
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT set_no, rally_id, COUNT(*) AS shots, MIN(frame_num) AS f0, MAX(frame_num) AS f1, "
        "MAX(getpoint_player) AS winner, MAX(lose_reason) AS lose, MAX(win_reason) AS win "
        "FROM strokes WHERE match_id=? AND source='shuttleset' "
        "GROUP BY set_no, rally_id ORDER BY set_no, rally_id", [match_id]).fetchall()
    con.close()
    return [dict(set_no=r[0], rally_id=r[1], shots=r[2], f0=r[3], f1=r[4],
                 winner=r[5], lose=r[6], win=r[7]) for r in rows]


def clip_rally(match_id: str, set_no: int, rally_id: int,
               pre: int = 90, post: int = 60) -> Path:
    """Cut one rally from the raw video (cached). pre/post = padding frames."""
    m = config.get_match(match_id)
    fps = float(m["fps"])
    video = config.REPO_ROOT / m["video_path"]
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    out = CLIP_DIR / f"{match_id}_s{set_no}_r{rally_id}.mp4"
    if out.exists():
        return out

    con = db.connect(read_only=True)
    fs = [r[0] for r in con.execute(
        "SELECT frame_num FROM strokes WHERE match_id=? AND source='shuttleset' "
        "AND set_no=? AND rally_id=? ORDER BY frame_num",
        [match_id, set_no, rally_id]).fetchall()]
    con.close()
    if not fs:
        raise ValueError(f"no strokes for set {set_no} rally {rally_id}")

    f0 = max(0, min(fs) + SS_OFFSET - pre)
    f1 = max(fs) + SS_OFFSET + post
    t0, dur = f0 / fps, (f1 - f0) / fps
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t0:.3f}", "-i", str(video), "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-an", str(out)],
        check=True, capture_output=True)
    return out


def annotated_rally(match_id: str, set_no: int, rally_id: int,
                    pre: int = 60, post: int = 45,
                    model: str = "yolo11x-pose.pt", imgsz: int = 1280) -> Path:
    """Detect just this rally (continuous) and render the annotated overlay (cached).
    Runs detection — call from a SUBPROCESS, not inside the read-only dashboard process."""
    from . import detect, render_overlay
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    out = CLIP_DIR / f"{match_id}_s{set_no}_r{rally_id}_annot.mp4"
    if out.exists():
        return out

    con = db.connect(read_only=True)
    fs = [r[0] for r in con.execute(
        "SELECT frame_num FROM strokes WHERE match_id=? AND source='shuttleset' "
        "AND set_no=? AND rally_id=? ORDER BY frame_num",
        [match_id, set_no, rally_id]).fetchall()]
    if not fs:
        con.close()
        raise ValueError(f"no strokes for set {set_no} rally {rally_id}")
    f0 = max(0, min(fs) + SS_OFFSET - pre)
    f1 = max(fs) + SS_OFFSET + post
    covered = con.execute("SELECT COUNT(*) FROM tracks WHERE match_id=? AND frame_num>=? "
                          "AND frame_num<?", [match_id, f0, f1]).fetchone()[0]
    con.close()
    # skip detection if the rally is already densely parsed (full-match parse done)
    if covered < (f1 - f0) * 0.8:
        detect.process_video(match_id, model, start_frame=f0, max_frames=f1 - f0, imgsz=imgsz)
    render_overlay.render(match_id, f0, f1, out)
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("set_no", type=int)
    ap.add_argument("rally_id", type=int)
    ap.add_argument("--annotate", action="store_true",
                    help="detect + render the annotated overlay (slower)")
    args = ap.parse_args()
    if args.annotate:
        print(annotated_rally(args.match_id, args.set_no, args.rally_id))
    else:
        print(clip_rally(args.match_id, args.set_no, args.rally_id))


if __name__ == "__main__":
    main()
