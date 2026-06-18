"""Doubles multi-set structure: set boundaries + side↔pair mapping (ISOLATED, Phase 1).

A full broadcast is several games (sets). Two things change across sets and BOTH must be
handled or the per-pair stats get attributed to the wrong team:

  1. The score resets each set (0-0 again).
  2. The two pairs SWAP ENDS between games — and once more, mid-game, when a side first
     reaches 11 in the DECIDING game. So which physical pair occupies the geometric
     near/far court slots flips on a known, deterministic schedule.

Set boundaries come from the scoreboard OCR: the per-rally score TOTAL (top+bot) climbs
within a game and collapses to ~0 at the next game's first rally. The total is invariant
to which scoreboard row is which, so it survives the end-swap and the OCR's only
systematic confusion (8↔0). Side↔pair is then pure bookkeeping off the set-1 anchor —
no extra OCR, no per-set roster needed: pair A := whoever started on the near end in
set 1, pair B := the far pair; each game transition swaps ends, the deciding-game 11
adds one more swap.

The functions here are PURE (take scores, return structure) so they unit-test without a
video or DB; `analyze()` ties them to `identity.rally_scores_ocr` + `segment`.

CLI:  PYTHONPATH=src python -m badminton.doubles.sets <match_id>
"""

from __future__ import annotations

import argparse

SET_END_MIN = 18        # a game-ending rally total is at least this (21, or higher on deuce)
SET_RESET_MAX = 5       # the next game's opening rallies total at most this
DECIDING_SWAP_AT = 11   # change ends in the deciding game when a side first reaches this


def assign_sets(totals: list[int | None]) -> list[int]:
    """Set number (1-based) for each rally, from per-rally score totals in order.

    A new set starts at a clean RESET: the previous readable total was game-ending
    (>= SET_END_MIN) and the current one is an opening total (<= SET_RESET_MAX). Rallies
    with an unreadable total (None) inherit the running set and don't update the baseline,
    so a single dropped read never invents or misses a boundary."""
    out: list[int] = []
    cur, prev = 1, None
    for t in totals:
        if t is not None and prev is not None and prev >= SET_END_MIN and t <= SET_RESET_MAX:
            cur += 1
        out.append(cur)
        if t is not None:
            prev = t
    return out


def deciding_swap_frame(set_rows) -> int | None:
    """Frame after which the deciding-game mid-set end-change applies, or None.

    set_rows: ordered (start, end, top, bot) for the DECIDING set's rallies. The swap
    happens at the changeover right after the rally in which a side first reaches 11."""
    for a, b, top, bot in set_rows:
        if top is not None and bot is not None and max(top, bot) >= DECIDING_SWAP_AT:
            return int(b)
    return None


def side_pair_map(set_no: int, post_deciding_swap: bool = False) -> dict[str, str]:
    """{'near': pair, 'far': pair} where pair is 'A' (set-1 near pair) or 'B' (set-1 far
    pair). Ends swap once per game transition; the deciding game adds one swap at 11."""
    swaps = set_no - 1
    if set_no >= 3 and post_deciding_swap:
        swaps += 1
    near = "A" if swaps % 2 == 0 else "B"
    return {"near": near, "far": "B" if near == "A" else "A"}


def rally_sides(rally_scores, n_sets_expected: int | None = None) -> list[dict]:
    """Per-rally set + side↔pair structure, the single source of truth the exporter uses.

    rally_scores: ordered (start, end, top, bot) per rally (top/bot = raw scoreboard rows;
    their order is fixed across the match, only the SUM is used for set detection). Returns
    one dict per rally: {start, end, set, total, near_pair, far_pair}."""
    totals = [None if (t is None or b is None) else int(t) + int(b)
              for (_, _, t, b) in rally_scores]
    set_no = assign_sets(totals)
    n_sets = max(set_no) if set_no else 0

    # deciding-game mid-set swap, only if a deciding (3rd+) set actually exists
    swap_frame = None
    if n_sets >= 3:
        deciding = max(set_no)
        rows = [rally_scores[i] for i in range(len(rally_scores)) if set_no[i] == deciding]
        swap_frame = deciding_swap_frame(rows)

    out = []
    for (a, b, top, bot), sn, tot in zip(rally_scores, set_no, totals):
        post = bool(swap_frame is not None and sn == max(set_no) and a >= swap_frame)
        m = side_pair_map(sn, post)
        out.append({"start": int(a), "end": int(b), "set": sn, "total": tot,
                    "near_pair": m["near"], "far_pair": m["far"]})
    return out


def analyze(match_id: str, max_gap: int = 20, min_len: int = 45,
            windows=None) -> list[dict]:
    """Full-match per-rally set/side structure from tracks + scoreboard OCR.

    Only the SUM (set boundaries) and MAX (deciding-game 11) of the two scoreboard rows
    are used — both order-invariant — so the row→side convention is irrelevant here; the
    default `rally_scores_ocr` mapping returns the two row scores unchanged in positions
    3/4, which is all `rally_sides` needs. Pass `windows` to reuse the exporter's rally
    segmentation (so the result aligns 1:1) instead of recomputing it."""
    from . import identity, segment
    if windows is None:
        windows = segment.rally_windows(match_id, max_gap, min_len)
    scores = identity.rally_scores_ocr(match_id, windows)
    return rally_sides(scores)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles set boundaries + side↔pair (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    rs = analyze(args.match_id, args.max_gap, args.min_len)
    if not rs:
        print("no rallies — run doubles.track first")
        return
    n_sets = max(r["set"] for r in rs)
    print(f"{len(rs)} rallies across {n_sets} set(s):")
    for r in rs:
        print(f"  r set{r['set']} f{r['start']}-{r['end']} total={r['total']} "
              f"near={r['near_pair']} far={r['far_pair']}")


if __name__ == "__main__":
    main()
