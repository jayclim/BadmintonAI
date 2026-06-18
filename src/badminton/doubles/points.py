"""Doubles points / momentum from scoreboard OCR (ISOLATED, Phase 1, pure).

The singles "Points" view is shot-based (winners/errors per shot); doubles has no strokes
yet, so its Points view is the SCORE story instead — the per-set trajectory (a "worm"),
who won each rally, momentum runs, and win-rate by rally length. Everything is derived
from data we already read: per-rally scoreboard scores + the set/side structure.

Key fact about the BWF graphic on this broadcast (verified, see docs/DOUBLES.md): the two
score rows are FIXED BY TEAM, not by court side — the name strip doesn't move when the
pairs change ends. So the top row is one team's score all match and the bottom the other,
and mapping rows->teams needs a single anchor (`top_team`, default 'A', overridable in
matches.yaml as `scoreboard_top_team`). The per-rally near/far team map is NOT needed for
scores (only the order-invariant total is, and that's used for set detection in sets.py).

`build()` is PURE (takes the precomputed (start,end,top,bot) rally scores + the rally-side
structure, returns the web payload) so it unit-tests without a video or DB. The exporter
computes the OCR scores ONCE and feeds both this and `sets.rally_sides`.

CLI:  PYTHONPATH=src python -m badminton.doubles.points <match_id>
"""

from __future__ import annotations

import argparse

# rally-length buckets in SECONDS (doubles rallies are short; no shot counts without strokes)
SHORT_S, MID_S = 6.0, 12.0


def _bucket(dur_s: float) -> str:
    if dur_s <= SHORT_S:
        return "short"
    if dur_s <= MID_S:
        return "mid"
    return "long"


def clean_set_scores(rows: list[dict]) -> list[dict]:
    """Reduce one set's per-rally (rally, a, b) reads to a clean, monotonic point log.

    `rows`: ordered [{rally, a, b}] where a/b are team A/B scoreboard scores (a/b may be
    None on an OCR miss). Tracks-only segmentation slightly over-segments and the OCR drops
    reads, so we keep only rallies whose readable score is a single-team +1 step over the
    last accepted score (the real point). Duplicates (replays, dead-time windows) and
    regressions/garbage are dropped. Returns [{rally, a, b, winner}] at each scored point."""
    out: list[dict] = []
    la, lb = 0, 0
    for r in rows:
        a, b = r["a"], r["b"]
        if a is None or b is None:
            continue
        da, db = a - la, b - lb
        # exactly one team advanced by one (clean point); tolerate a jump after OCR gaps by
        # accepting any forward move where total increased and neither score went backwards
        if a >= la and b >= lb and (a + b) > (la + lb):
            winner = "A" if da >= db else "B"
            out.append({"rally": r["rally"], "a": int(a), "b": int(b), "winner": winner})
            la, lb = a, b
    return out


def _longest_run(points: list[dict], team: str) -> int:
    best = cur = 0
    for p in points:
        cur = cur + 1 if p["winner"] == team else 0
        best = max(best, cur)
    return best


def build(rally_scores: list[tuple], rsides: list[dict], fps: float,
          top_team: str = "A") -> dict:
    """Assemble the Points payload.

    rally_scores: ordered (start, end, top, bot) per rally (top/bot = raw scoreboard rows).
    rsides:       aligned 1:1 — each {set, ...} (from sets.rally_sides); gives the set number.
    top_team:     which fixed team the TOP scoreboard row belongs to ('A' or 'B')."""
    a_is_top = top_team == "A"
    n_sets = max((r["set"] for r in rsides), default=0)

    sets_out: list[dict] = []
    length_wins = {"A": {"short": 0, "mid": 0, "long": 0},
                   "B": {"short": 0, "mid": 0, "long": 0}}
    runs = {"A": 0, "B": 0}
    rally_winner: dict[int, str] = {}

    for sn in range(1, n_sets + 1):
        rows = []
        for i, ((a, b, top, bot), rs) in enumerate(zip(rally_scores, rsides), 1):
            if rs["set"] != sn:
                continue
            ta = top if a_is_top else bot
            tb = bot if a_is_top else top
            rows.append({"rally": i, "a": ta, "b": tb,
                         "durS": round((b - a + 1) / fps, 2)})
        pts = clean_set_scores(rows)
        # attach duration to each accepted point for length-bucketed win rates + deep links
        dur_by_rally = {r["rally"]: r["durS"] for r in rows}
        for p in pts:
            rally_winner[p["rally"]] = p["winner"]
            length_wins[p["winner"]][_bucket(dur_by_rally.get(p["rally"], 0.0))] += 1
        runs["A"] = max(runs["A"], _longest_run(pts, "A"))
        runs["B"] = max(runs["B"], _longest_run(pts, "B"))
        final = {"a": pts[-1]["a"], "b": pts[-1]["b"]} if pts else {"a": 0, "b": 0}
        winner = ("A" if final["a"] > final["b"] else "B") if pts else None
        sets_out.append({"set": sn, "points": pts, "final": final, "winner": winner})

    return {"topTeam": top_team, "sets": sets_out, "lengthWins": length_wins,
            "runs": runs, "rallyWinner": {str(k): v for k, v in rally_winner.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles points / momentum (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    from .. import config
    from . import identity, segment, sets
    m = config.get_match(args.match_id)
    fps = float(m["fps"])
    top_team = m.get("scoreboard_top_team", "A")
    windows = segment.rally_windows(args.match_id, args.max_gap, args.min_len)
    rally_scores = identity.rally_scores_ocr(args.match_id, windows)
    rsides = sets.rally_sides(rally_scores)
    p = build(rally_scores, rsides, fps, top_team)
    for s in p["sets"]:
        f = s["final"]
        print(f"set {s['set']}: {len(s['points'])} pts, final A {f['a']}-{f['b']} B "
              f"(winner {s['winner']})")
    print("runs:", p["runs"], "length wins:", p["lengthWins"])


if __name__ == "__main__":
    main()
