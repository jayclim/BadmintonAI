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
unavailable. The OCR result is cached per (match, params) so the several callers that ask
for `rally_windows` only pay for it once.

Later, shuttle motion + hits can refine the exact start (serve) and end (landing), the same
upgrade path the singles `segment.py` took. Rally windows are also the anchors
`identity.reanchor_at_serves` wants.

CLI:  PYTHONPATH=src python -m badminton.doubles.segment <match_id> [--max-gap 20] [--min-len 45]
"""

from __future__ import annotations

import argparse

from .. import db
from .track import SLOTS as _SLOTS_BY_HALF

SLOTS = frozenset(s for half in _SLOTS_BY_HALF.values() for s in half)

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


def _scoreboard_live_mask(match_id: str, windows, samples: int = SCOREBOARD_SAMPLES) -> list[bool]:
    """Per-window: is the live BWF score overlay on screen? (the "this is the play camera"
    test). Samples `samples` frames per window and reads the scoreboard; a window is live if
    the graphic reads in >= SCOREBOARD_MIN_HITS of them. Returns all-True (no gating) if the
    score box can't be calibrated or the video can't be opened, so a match without usable
    OCR still exports every candidate rather than dropping all of them."""
    import cv2
    import numpy as np

    from .. import config
    from .. import scoreboard as sb
    box = sb.calibrate_box(match_id)
    if box is None:
        return [True] * len(windows)
    tpl = sb._load_templates()
    cap = cv2.VideoCapture(str(config.REPO_ROOT / config.get_match(match_id)["video_path"]))
    if not cap.isOpened():
        return [True] * len(windows)
    mask = []
    for a, b in windows:
        hits = 0
        for f in np.linspace(a, b, samples).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
            ok, fr = cap.read()
            if ok and sb.read_frame(fr, box, tpl):
                hits += 1
        mask.append(hits >= SCOREBOARD_MIN_HITS)
    cap.release()
    return mask


def rally_windows(match_id: str, max_gap: int = 20, min_len: int = 45,
                  gated: bool = True) -> list[tuple[int, int]]:
    """(start_frame, end_frame) per detected rally.

    By default GATED on scoreboard presence (see module docstring): intro/crowd/replay
    footage that tracks 4 people but isn't live play is dropped. Pass gated=False for the
    raw tracks-only candidates. Gating only DROPS windows — kept windows keep identical
    frame bounds — so downstream clip/replay names are stable for the rallies that survive.
    The OCR pass is cached per (match_id, max_gap, min_len) so repeat callers pay once."""
    if not gated:
        return _merge_runs(_active_frames(match_id), max_gap, min_len)
    key = (match_id, max_gap, min_len)
    if key not in _GATE_CACHE:
        raw = _merge_runs(_active_frames(match_id), max_gap, min_len)
        if raw:
            mask = _scoreboard_live_mask(match_id, raw)
            _GATE_CACHE[key] = [w for w, keep in zip(raw, mask) if keep]
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
        print(f"{len(raw)} candidate windows -> {len(w)} live rallies "
              f"({len(raw) - len(w)} dropped as intro/crowd/replay B-roll)")
    print(f"{len(w)} rallies:")
    for i, (a, b) in enumerate(w, 1):
        print(f"  {i:2d}. frames {a}-{b}  ({(b - a + 1) / args.fps:.1f}s)")
    if w:
        tot = sum(b - a + 1 for a, b in w)
        print(f"total rally span: {tot} frames ({tot / args.fps:.1f}s)")


if __name__ == "__main__":
    main()
