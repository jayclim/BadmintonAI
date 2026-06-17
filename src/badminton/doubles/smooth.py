"""Doubles temporal gap-fill — interpolate short slot dropouts (ISOLATED, Phase 1).

The 4-player tracker loses the small far-side players for brief spells (occlusion, a
missed detection): measured far-side recall during rallies ~73%, with most gaps only
1-2 frames. This pass linearly interpolates a slot's court/image position, bbox and
keypoints across gaps up to `max_gap` frames between two REAL detections of THAT slot,
and writes the filled rows back into `tracks` so every downstream consumer (roles,
identity, future hits attribution) benefits — not just an in-memory view.

Markers / safety:
- Filled rows carry pose_conf = INTERP_CONF (-1.0), a sentinel no other code reads, so
  the pass is idempotent (re-run clears prior fills first) and reversible
  (DELETE FROM tracks WHERE pose_conf < 0).
- Only fills the open interval between two real detections of the same slot, never across
  a gap > max_gap (a long gap means the player genuinely left / a real swap, not a
  dropout), and never extrapolates past the slot's first/last real frame.

Assumes the tracker ran at stride 1 (the default); at higher stride a "gap" is normal
spacing, so don't gap-fill strided runs.

CLI:  PYTHONPATH=src python -m badminton.doubles.smooth <match_id> [--max-gap 5]
"""

from __future__ import annotations

import argparse

from .. import db
from .track import SLOTS as _SLOTS_BY_HALF

INTERP_CONF = -1.0
SLOTS = tuple(s for half in _SLOTS_BY_HALF.values() for s in half)


def _lerp(a, b, t):
    return None if a is None or b is None else a + (b - a) * t


def _lerp_seq(a, b, t):
    return None if a is None or b is None else [av + (bv - av) * t for av, bv in zip(a, b)]


def fill_gaps(match_id: str, max_gap: int = 5) -> int:
    """Interpolate dropouts up to `max_gap` frames for each slot. Returns rows inserted."""
    con = db.connect()
    con.execute("DELETE FROM tracks WHERE match_id=? AND pose_conf < 0", [match_id])  # idempotent
    rows_out: list[list] = []
    for slot in SLOTS:
        real = con.execute(
            "SELECT frame_num, court_x, court_y, img_x, img_y, bbox, keypoints FROM tracks "
            "WHERE match_id=? AND player_id=? AND pose_conf >= 0 ORDER BY frame_num",
            [match_id, slot]).fetchall()
        for (fa, *a), (fb, *b) in zip(real, real[1:]):
            gap = fb - fa
            if gap <= 1 or gap > max_gap + 1:           # consecutive, or too long to trust
                continue
            cxa, cya, ixa, iya, bba, kpa = a
            cxb, cyb, ixb, iyb, bbb, kpb = b
            for f in range(fa + 1, fb):
                t = (f - fa) / gap
                rows_out.append([
                    match_id, f, slot,
                    _lerp(cxa, cxb, t), _lerp(cya, cyb, t),
                    _lerp(ixa, ixb, t), _lerp(iya, iyb, t),
                    _lerp_seq(bba, bbb, t), _lerp_seq(kpa, kpb, t), INTERP_CONF,
                ])
    if rows_out:
        con.executemany(
            "INSERT INTO tracks (match_id, frame_num, player_id, court_x, court_y, "
            "img_x, img_y, bbox, keypoints, pose_conf) VALUES (?,?,?,?,?,?,?,?,?,?)", rows_out)
    con.close()
    print(f"filled {len(rows_out)} interpolated rows (max_gap={max_gap})")
    return len(rows_out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles temporal gap-fill (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=5, help="longest dropout (frames) to fill")
    args = ap.parse_args()
    fill_gaps(args.match_id, args.max_gap)


if __name__ == "__main__":
    main()
