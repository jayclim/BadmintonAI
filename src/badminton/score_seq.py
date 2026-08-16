"""Score-sequence decoding — turn noisy scoreboard reads into a legal point log.

A badminton score is not free-form data: it is a monotone path through a small,
rule-constrained state space. Exactly ONE side gains exactly ONE point per rally,
a game ends at `TARGET` with a `WIN_BY` margin (hard cap `CAP`), and the score
never goes backwards inside a game. Reading the broadcast overlay per rally and
using each reading *as-is* throws all of that structure away, so a single dropped
or misread sample corrupts everything downstream:

  * the OCR misses the reading a replay covered  -> that rally's point vanishes and
    every later rally in the set is attributed the PREVIOUS rally's score;
  * the template matcher confuses 0 and 8        -> a one-sample spike (0 -> 8 -> 1);
  * the broadcast cuts to the crowd on set point -> the set final is never observed,
    so a 21-17 set is reported as 19-17.

This module puts the rules back. It is PURE (no DB, no video, no pandas, no I/O),
operates on plain tuples, and is shared by BOTH disciplines — the singles
label-free chain (`labelfree.build`) and the doubles points view
(`doubles.points`) — the same way `court`/`config` are shared low-level helpers.

    reads (per rally, may be None)
      -> repair()    drop transient misreads, keep the monotone path
      -> expand()    split multi-point jumps into ONE point each (the OCR skipped
                     readings, not the rally: 4-4 -> 6-4 is two rallies, not one)
      -> complete()  finish a set the broadcast cut away from, using the rules
      -> point log   one entry per point: score after it + who scored it

`point_log()` runs the three in order. `set_finals()` reads the finals off the log.

Measured on the four labeled singles matches (`tests/test_score_seq.py` asserts
this against the checked-in OCR snapshots + ShuttleSet ground truth): the raw
readings reproduce 0/4 correct scorelines; the decoded point log reproduces 4/4.
"""

from __future__ import annotations

# Laws of badminton scoring (BWF rules 7.1-7.4), rally-point era.
TARGET = 21     # a game is to 21 points ...
WIN_BY = 2      # ... but must be won by two ...
CAP = 30        # ... except at 29-29, where the 30th point wins.


def is_final(x: int, y: int) -> bool:
    """True if (x, y) is a legal END-OF-GAME score."""
    return (max(x, y) >= TARGET and abs(x - y) >= WIN_BY) or max(x, y) >= CAP


def _legal_step(prev: tuple[int, int], cur: tuple[int, int]) -> bool:
    """True if `cur` can follow `prev` within one game (never backwards, and at
    least one point was scored). Multi-point jumps ARE legal here — they mean the
    OCR skipped readings, and `expand` splits them back into single rallies."""
    dx, dy = cur[0] - prev[0], cur[1] - prev[1]
    return dx >= 0 and dy >= 0 and dx + dy >= 1


def repair(reads):
    """Drop unreadable and self-contradicting samples, keeping the monotone path.

    `reads`: ordered [(set_no, x, y, ref)]; x/y None where the OCR failed, `ref` is
    an opaque caller handle (a rally index, a frame, ...) carried through untouched.

    A score that goes BACKWARDS is impossible inside a game, so one of the two
    samples is a misread. We prefer to blame the EARLIER one when dropping it makes
    the sequence legal again — that is the signature of the template matcher's 0/8
    confusion, which spikes for a single reading (0 -> 8 -> 1) rather than persisting.
    """
    out: list[tuple] = []
    for sn, x, y, ref in reads:
        if x is None or y is None:
            continue
        if not out or out[-1][0] != sn:          # first readable sample of a game
            out.append((sn, x, y, ref))
            continue
        if _legal_step((out[-1][1], out[-1][2]), (x, y)):
            out.append((sn, x, y, ref))
            continue
        # illegal: is the PREVIOUS sample the spike?
        if len(out) >= 2 and out[-2][0] == sn and \
                _legal_step((out[-2][1], out[-2][2]), (x, y)):
            out[-1] = (sn, x, y, ref)            # replace the spike
        # else: this sample is the spike — drop it
    return out


def expand(reads):
    """One entry per POINT. Multi-point jumps become several single-point entries.

    A jump of n points means the OCR missed n-1 readings, NOT that one rally was
    worth n points — the rallies happened, we just never read the overlay during
    them. Returns [(set_no, x, y, scorer, ref, synth)] where (x, y) is the score
    AFTER that point, `scorer` is 'x' or 'y', and `synth` marks the reconstructed
    entries (their `ref` is None — they have no observed reading behind them).

    Within one jump the ORDER of the points is not recoverable from the score
    alone (4-4 -> 5-5 could be either way round); the totals are exact regardless,
    and the y-side points are emitted first by convention.
    """
    out: list[tuple] = []
    for sn, x, y, ref in reads:
        px, py = (0, 0) if not out or out[-1][0] != sn else (out[-1][1], out[-1][2])
        dx, dy = x - px, y - py
        if dx + dy <= 1:                         # already a single point
            out.append((sn, x, y, "x" if dx else "y", ref, False))
            continue
        cx, cy = px, py
        steps: list[tuple[int, int, str]] = []
        for _ in range(dy):
            cy += 1
            steps.append((cx, cy, "y"))
        for _ in range(dx):
            cx += 1
            steps.append((cx, cy, "x"))
        for i, (sx, sy, who) in enumerate(steps, 1):
            last = i == len(steps)               # only the last one was observed
            out.append((sn, sx, sy, who, ref if last else None, not last))
    return out


def complete(points, max_fill: int = 3):
    """Finish any game the broadcast cut away from, using the scoring rules.

    Broadcasts cut to the crowd on set point, so the winning reading is routinely
    never shown: the OCR's last sample of a game is 20-17 for a 21-17 set. The
    rules make the missing tail deterministic — the LEADER takes points until the
    game is legally over. Capped at `max_fill` points so a genuinely truncated
    scan (OCR died at 5-3) is left alone instead of being invented; if the game
    still isn't finishable within the cap, nothing is added.
    """
    by_set: dict[int, list] = {}
    for p in points:
        by_set.setdefault(p[0], []).append(p)
    out: list[tuple] = []
    for sn in sorted(by_set):
        rows = list(by_set[sn])
        x, y = rows[-1][1], rows[-1][2]
        if not is_final(x, y) and x != y:        # a tie tells us nothing about who wins
            who = "x" if x > y else "y"
            added = []
            while not is_final(x, y) and len(added) < max_fill:
                if who == "x":
                    x += 1
                else:
                    y += 1
                added.append((sn, x, y, who, None, True))
            if is_final(x, y):
                rows += added
        out += rows
    return out


def point_log(reads, max_fill: int = 3):
    """repair -> expand -> complete. The rally-by-rally point log of the match."""
    return complete(expand(repair(reads)), max_fill=max_fill)


def set_finals(points) -> dict[int, tuple[int, int]]:
    """{set_no: (x, y)} — the final score of each game in a point log."""
    out: dict[int, tuple[int, int]] = {}
    for sn, x, y, *_ in points:
        out[sn] = (x, y)
    return out


def sets_won(points) -> tuple[int, int]:
    """(x games, y games) from a point log, counting only LEGALLY finished games."""
    fx = fy = 0
    for x, y in set_finals(points).values():
        if not is_final(x, y):
            continue
        fx += x > y
        fy += y > x
    return fx, fy


# --------------------------------------------------------------- serve geometry

def serve_court_parity(server_x: float, receiver_x: float, server_near: bool,
                       min_sep_m: float = 0.5) -> bool | None:
    """Is the SERVER's score even? True/False, or None when the geometry is unclear.

    Rule 9.1.1-9.1.6: a player serves from their RIGHT service court when their own
    score is even and from the left when it is odd, and the receiver stands in the
    diagonally opposite court. That makes the serve stance a free, OCR-independent
    parity bit on the server's score — one extra observation per rally, from pure
    geometry, for cross-checking or replacing a failed scoreboard reading.

    Comparing the server against the CENTRE LINE is too fragile: servers hug the
    line, so the call comes down to ~10 cm and loses to homography error (74% on
    india_open against ShuttleSet). Comparing the server against the RECEIVER uses
    the full diagonal instead — a 1.5-3 m separation — and cancels any shared
    lateral bias in the homography: 96.3% across the four labeled matches, 97.6%
    on the calls where the two are at least `min_sep_m` apart.

    `server_x` / `receiver_x` are court metres; `server_near` says which half the
    server is in (near = small court_y, the camera side).
    """
    dx = server_x - receiver_x
    if abs(dx) < min_sep_m:
        return None                              # too close to call — abstain
    # The near player faces up-screen, so their right service court is screen-right
    # (larger x); the far player faces the camera, so theirs is screen-left.
    on_right = dx > 0 if server_near else dx < 0
    return on_right
