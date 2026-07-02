"""Doubles rally segmentation from 4-player tracks (ISOLATED, Phase 1).

A doubles rally = all four players on the calibrated court; dead-time between points =
the far players walk off court and their tracks vanish. So contiguous runs of
all-4-present frames ARE the candidate rallies.

But "4 tracked people in the court box" is NOT enough on its own: there is no court-line
detector here — every detection is projected through ONE hand-calibrated homography
regardless of where the camera is actually pointing. So intro/crowd/warm-up footage (fans
or knock-up players that happen to project into the court) AND mid-match replays /
celebrations all look like "4 players present" and leak in as fake rallies (~40 of 163 on
wtf_2024_md_sf, scattered across the whole broadcast).

The fix (the `gated` path, default ON): keep a candidate window only if the live BWF score
overlay is on screen during it. Live play always carries the scoreboard graphic; intro,
crowd, replay and celebration B-roll do not. This is the cheap, reliable "is this the play
camera?" signal we already have tooling for (`scoreboard.read_frame`). It needs the video +
the calibrated score box, so it degrades to ungated (keep all candidates) when those are
unavailable. The OCR result is cached per (match, params) in-process AND on disk
(data/cache/doubles_gate_<id>.json), so re-runs are resumable and near-instant.

The scoreboard gate can't catch DEAD-TIME between points, though: the broadcast often
stays on the wide shot with all four players milling about and the graphic still up, so
short between-point fragments pass both tests. Two shuttle-based layers (built on
`strokes.contacts`, the same upgrade path singles took) fix that:

  1. MERGE: fragments hug their parent rally (measured on wtf_2024_md_sf: every fragment
     sits <3 s from a neighbouring window, while real consecutive points are >=5.2 s
     apart, median 18.5 s) — and a mid-rally all-4 dropout longer than max_gap splits one
     real rally into two equally-close windows. Merging windows closer than GAP_MERGE_S
     repairs both.
  2. TRIM: each merged window is cut to its detected contact span (start ~= the serve,
     end ~= the last hit + landing), with the contact list truncated at the first
     >RESTART_GAP inter-contact pause — a dead-shuttle pickup / knock-back after the
     point (singles' "restart truncation", by timing instead of speed). A window with <2
     surviving contacts is DROPPED if the shuttle track was densely visible (we had
     evidence and found no play) and kept untrimmed if not (fail open — nothing to judge
     by, same philosophy as the gate).

Rally windows are also the anchors `identity.reanchor_at_serves` wants.

CLI:  PYTHONPATH=src python -m badminton.doubles.segment <match_id> [--max-gap 20] [--min-len 45]
"""

from __future__ import annotations

import argparse
import json

from .. import config, db
from .track import SLOTS as _SLOTS_BY_HALF

SLOTS = frozenset(s for half in _SLOTS_BY_HALF.values() for s in half)

CACHE_DIR = config.REPO_ROOT / "data" / "cache"

# shuttle-based refinement thresholds (see module docstring; measured on wtf_2024_md_sf)
GAP_MERGE_S = 5.0        # windows closer than this are one rally (+fragment / split halves)
TRIM_PRE, TRIM_POST = 30, 60   # frames kept before the first / after the last contact
RESTART_GAP = 75         # frames between contacts > this = dead-shuttle restart, truncate
MIN_SHUTTLE_VIS = 60     # visible shuttle frames needed to DROP a contact-less window

# Scoreboard-presence gate: sample this many frames per candidate window and keep it only
# if the live score graphic reads in at least MIN_HITS of them. Measured on wtf_2024_md_sf
# the distribution is cleanly bimodal: 43 windows read the graphic in ZERO of 6 samples
# (intro/crowd/replay/celebration B-roll), every other window reads a plausible live score
# in >= 1 sample (incl. short deuce rallies at 23-23 / 26-25 that only catch the overlay
# once). So the safe cut is >= 1 — it removes the pure B-roll without dropping real points.
SCOREBOARD_SAMPLES = 6
SCOREBOARD_MIN_HITS = 1

_GATE_CACHE: dict = {}


def _merge_runs(frames, max_gap: int, min_len: int) -> list[tuple[int, int]]:
    """Contiguous runs of `frames`, bridging gaps <= max_gap (within-rally dropouts),
    keeping only runs spanning >= min_len frames. Pure; no DB."""
    frames = sorted(frames)
    if not frames:
        return []
    runs, start, prev = [], frames[0], frames[0]
    for f in frames[1:]:
        if f - prev <= max_gap:
            prev = f
        else:
            runs.append((start, prev))
            start = prev = f
    runs.append((start, prev))
    return [(a, b) for a, b in runs if b - a + 1 >= min_len]


def _active_frames(match_id: str) -> list[int]:
    """Frames where all four slots are present (real or gap-filled)."""
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT frame_num FROM tracks WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "GROUP BY frame_num HAVING COUNT(DISTINCT player_id)=4 ORDER BY frame_num",
        [match_id]).fetchall()
    con.close()
    return [r[0] for r in rows]


def _disk_cache(name: str) -> dict:
    p = CACHE_DIR / name
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def _disk_save(name: str, obj: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / name).write_text(json.dumps(obj))


def _scoreboard_live_mask(match_id: str, windows, samples: int = SCOREBOARD_SAMPLES) -> list[bool]:
    """Per-window: is the live BWF score overlay on screen? (the "this is the play camera"
    test). Samples `samples` frames per window and reads the scoreboard; a window is live if
    the graphic reads in >= SCOREBOARD_MIN_HITS of them. Returns all-True (no gating) if the
    score box can't be calibrated or the video can't be opened, so a match without usable
    OCR still exports every candidate rather than dropping all of them.

    Results are cached on disk per raw window (the raw candidates only change if the
    tracks change), so an interrupted run resumes where it left off and a repeat run
    skips the cv2 seeks entirely."""
    import cv2
    import numpy as np

    from .. import scoreboard as sb
    cache_name = f"doubles_gate_{match_id}.json"
    cache = _disk_cache(cache_name)
    todo = [w for w in windows if f"{w[0]}-{w[1]}" not in cache]
    if todo:
        box = sb.calibrate_box(match_id)
        if box is None:
            return [True] * len(windows)
        tpl = sb._load_templates()
        cap = cv2.VideoCapture(str(config.REPO_ROOT / config.get_match(match_id)["video_path"]))
        if not cap.isOpened():
            return [True] * len(windows)
        for i, (a, b) in enumerate(todo, 1):
            print(f"\r  scoreboard gate {i}/{len(todo)} (cached {len(windows) - len(todo)})",
                  end="", flush=True)
            hits = 0
            for f in np.linspace(a, b, samples).astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
                ok, fr = cap.read()
                if ok and sb.read_frame(fr, box, tpl):
                    hits += 1
            cache[f"{a}-{b}"] = hits >= SCOREBOARD_MIN_HITS
            _disk_save(cache_name, cache)
        cap.release()
        print()
    return [cache[f"{a}-{b}"] for a, b in windows]


def _merge_close(windows, fps: float = 30.0, gap_s: float = GAP_MERGE_S) -> list[tuple[int, int]]:
    """Merge windows whose gap is < gap_s: a dead-time fragment reunites with its parent
    rally, and a rally split by a long all-4 dropout is repaired. Pure; no DB."""
    if not windows:
        return []
    out = [list(windows[0])]
    for a, b in windows[1:]:
        if a - out[-1][1] <= gap_s * fps:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(int(a), int(b)) for a, b in out]


def _truncate_restarts(cs: list[dict]) -> list[dict]:
    """Cut the contact list at the first >RESTART_GAP pause: contacts after it are the
    dead-shuttle pickup / knock-back once the point is over, not play. Pure."""
    keep = cs[:1]
    for prev, c in zip(cs, cs[1:]):
        if c["frame"] - prev["frame"] > RESTART_GAP:
            break
        keep.append(c)
    return keep


def _contact_trim(match_id: str, windows) -> list[tuple[int, int] | None]:
    """Trim each window to its detected shuttle-contact span (None = drop the window).
    <2 surviving contacts: drop when the shuttle track was densely visible (evidence of
    no play), keep untrimmed when it wasn't (nothing to judge by — fail open)."""
    from .. import hits as _hits          # low-level shared helper (shuttle series)
    from . import strokes                 # lazy: strokes imports segment
    out: list[tuple[int, int] | None] = []
    for i, (a, b) in enumerate(windows, 1):
        print(f"\r  contact trim {i}/{len(windows)}", end="", flush=True)
        cs = _truncate_restarts(strokes.enforce_alternation(strokes.contacts(match_id, a, b)))
        if len(cs) >= 2:
            out.append((max(a, cs[0]["frame"] - TRIM_PRE), min(b, cs[-1]["frame"] + TRIM_POST)))
        else:
            s = _hits.shuttle_series(match_id, a, b)
            vis = int(s["img_y"].notna().sum()) if len(s) else 0
            out.append(None if vis >= MIN_SHUTTLE_VIS else (a, b))
    print()
    return out


def rally_windows(match_id: str, max_gap: int = 20, min_len: int = 45,
                  gated: bool = True) -> list[tuple[int, int]]:
    """(start_frame, end_frame) per detected rally.

    By default GATED on scoreboard presence, then MERGED (fragments/split halves) and
    contact-TRIMMED to the shuttle's play span (see module docstring). Pass gated=False
    for the raw tracks-only candidates. The whole refinement is cached per
    (match_id, max_gap, min_len) in-process, and its slow OCR layer on disk."""
    if not gated:
        return _merge_runs(_active_frames(match_id), max_gap, min_len)
    key = (match_id, max_gap, min_len)
    if key not in _GATE_CACHE:
        raw = _merge_runs(_active_frames(match_id), max_gap, min_len)
        if raw:
            mask = _scoreboard_live_mask(match_id, raw)
            live = _merge_close([w for w, keep in zip(raw, mask) if keep])
            _GATE_CACHE[key] = [w for w in _contact_trim(match_id, live) if w is not None]
        else:
            _GATE_CACHE[key] = raw
    return _GATE_CACHE[key]


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles rally segmentation from tracks (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=20, help="bridge within-rally dropouts up to N frames")
    ap.add_argument("--min-len", type=int, default=45, help="discard runs shorter than N frames")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--no-gate", action="store_true",
                    help="skip the scoreboard-presence gate (show raw tracks-only candidates)")
    args = ap.parse_args()
    raw = rally_windows(args.match_id, args.max_gap, args.min_len, gated=False)
    w = raw if args.no_gate else rally_windows(args.match_id, args.max_gap, args.min_len)
    if not args.no_gate:
        print(f"{len(raw)} candidate windows -> {len(w)} rallies "
              f"(B-roll gated + fragments merged + contact-trimmed)")
    print(f"{len(w)} rallies:")
    for i, (a, b) in enumerate(w, 1):
        print(f"  {i:2d}. frames {a}-{b}  ({(b - a + 1) / args.fps:.1f}s)")
    if w:
        tot = sum(b - a + 1 for a, b in w)
        print(f"total rally span: {tot} frames ({tot / args.fps:.1f}s)")


if __name__ == "__main__":
    main()
