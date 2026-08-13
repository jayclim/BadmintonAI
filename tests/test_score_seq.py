"""Tests for badminton.score_seq — the rule-constrained score decoder.

Two layers:
  1. pure unit tests of each rule (no data needed);
  2. an END-TO-END accuracy test against ground truth, which runs anywhere: both
     inputs are checked into the repo (`data/labelfree/<id>.json` holds the raw OCR
     event stream, `data/shuttleset/<id>/set*.csv` holds the human labels), so no
     video, no DuckDB and no model weights are involved.

Run:  PYTHONPATH=src python tests/test_score_seq.py
"""

import csv
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import score_seq  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The four labeled singles matches, with the true scoreline (winner's score first
# per ShuttleSet's A = match winner convention).
LABELED = ["india_open_2022_final", "denmark_open_2022_sf",
           "all_england_2022_sf", "all_england_2022_ws_final"]


def _reads(match_id):
    """Raw per-event scoreboard readings from the checked-in OCR snapshot."""
    snap = json.loads((ROOT / "data" / "labelfree" / f"{match_id}.json").read_text())
    return ([(int(e["set_no"]), int(e["top"]), int(e["bot"]), i)
             for i, e in enumerate(snap["events"])], snap["row_a"])


def _truth(match_id):
    """{set_no: (A, B)} final scores from the ShuttleSet labels."""
    out = {}
    for p in sorted(glob.glob(str(ROOT / "data" / "shuttleset" / match_id / "set*.csv"))):
        sn = int(os.path.basename(p)[3:-4])
        last = list(csv.DictReader(open(p)))[-1]
        out[sn] = (int(last["roundscore_A"]), int(last["roundscore_B"]))
    return out


# ------------------------------------------------------------------ unit tests

def test_is_final():
    assert score_seq.is_final(21, 17)
    assert score_seq.is_final(21, 19)
    assert not score_seq.is_final(21, 20)      # must be won by two
    assert score_seq.is_final(22, 20)
    assert score_seq.is_final(30, 29)          # the cap wins by one
    assert not score_seq.is_final(20, 17)
    assert not score_seq.is_final(19, 19)
    print("ok  is_final")


def test_repair_drops_the_0_8_spike():
    # the template matcher's signature failure: a single sample reads 0 as 8
    reads = [(1, 2, 0, "a"), (1, 3, 8, "b"), (1, 3, 0, "c"), (1, 3, 1, "d")]
    out = score_seq.repair(reads)
    assert [(x, y) for _, x, y, _ in out] == [(2, 0), (3, 0), (3, 1)], out
    print("ok  repair drops the 0/8 spike")


def test_repair_keeps_a_legal_path_untouched():
    reads = [(1, 1, 0, 0), (1, 1, 1, 1), (1, 2, 1, 2)]
    assert score_seq.repair(reads) == reads
    print("ok  repair is a no-op on a legal path")


def test_repair_resets_between_games():
    # a new game legitimately goes 21-17 -> 1-0; that is not a regression
    reads = [(1, 21, 17, 0), (2, 1, 0, 1), (2, 1, 1, 2)]
    assert score_seq.repair(reads) == reads
    print("ok  repair resets at a game boundary")


def test_expand_splits_a_skipped_reading():
    # 1-0 -> 3-0 is TWO rallies the OCR read once, not one rally worth two points
    reads = [(1, 1, 0, "a"), (1, 3, 0, "b")]
    out = score_seq.expand(reads)
    assert [(x, y, who) for _, x, y, who, _, _ in out] == \
        [(1, 0, "x"), (2, 0, "x"), (3, 0, "x")], out
    assert [ref for *_, ref, _ in out] == ["a", None, "b"]   # only reads are anchored
    assert [s for *_, s in out] == [False, True, False]
    print("ok  expand splits a skipped reading into its rallies")


def test_expand_splits_a_two_sided_jump():
    reads = [(1, 1, 0, "a"), (1, 2, 1, "b")]
    out = score_seq.expand(reads)
    assert [(x, y) for _, x, y, *_ in out] == [(1, 0), (1, 1), (2, 1)], out
    print("ok  expand splits a two-sided jump")


def test_expand_counts_a_games_first_reading_from_zero():
    # the first reading of a game is itself a jump from 0-0: 2-1 means 3 rallies
    out = score_seq.expand([(1, 2, 1, "a")])
    assert [(x, y) for _, x, y, *_ in out] == [(0, 1), (1, 1), (2, 1)], out
    print("ok  expand counts a game's first reading from 0-0")


def test_complete_finishes_a_cut_away_game():
    pts = [(1, 19, 17, "x", 0, False), (1, 20, 17, "x", 1, False)]
    out = score_seq.complete(pts)
    assert score_seq.set_finals(out) == {1: (21, 17)}
    assert out[-1][5] is True                 # marked as reconstructed
    print("ok  complete finishes a cut-away game")


def test_complete_respects_win_by_two():
    out = score_seq.complete([(1, 20, 20, "x", 0, False), (1, 21, 20, "x", 1, False)])
    assert score_seq.set_finals(out) == {1: (22, 20)}
    print("ok  complete respects win-by-two")


def test_complete_refuses_to_invent_a_whole_game():
    # OCR died at 5-3: finishing that would fabricate 16 points, so leave it alone
    pts = [(1, 5, 3, "x", 0, False)]
    assert score_seq.complete(pts) == pts
    print("ok  complete refuses to invent a whole game")


def test_complete_leaves_a_finished_game_alone():
    pts = [(1, 21, 17, "x", 0, False)]
    assert score_seq.complete(pts) == pts
    print("ok  complete leaves a finished game alone")


def test_sets_won():
    log = score_seq.point_log([(1, 21, 17, 0), (2, 15, 21, 1), (3, 21, 19, 2)])
    assert score_seq.sets_won(log) == (2, 1)
    print("ok  sets_won")


def test_serve_court_parity():
    # near server to the RIGHT of the far receiver => near server's right court => even
    assert score_seq.serve_court_parity(4.0, 2.0, server_near=True) is True
    assert score_seq.serve_court_parity(2.0, 4.0, server_near=True) is False
    # a far server faces the camera, so the sense flips
    assert score_seq.serve_court_parity(4.0, 2.0, server_near=False) is False
    assert score_seq.serve_court_parity(2.0, 4.0, server_near=False) is True
    # too close to call — abstain rather than guess
    assert score_seq.serve_court_parity(3.1, 3.0, server_near=True) is None
    print("ok  serve_court_parity")


# --------------------------------------------------------- end-to-end accuracy

def test_decoded_scorelines_match_ground_truth():
    """Every labeled match's scoreline must come out EXACTLY right.

    This is the regression that motivated the module: using the raw OCR readings
    as-is, 0 of these 4 matches had every set final correct (the broadcast cuts
    away on set point, so the winning reading is never sampled)."""
    bad = []
    for mid in LABELED:
        reads, row_a = _reads(mid)
        finals = score_seq.set_finals(score_seq.point_log(reads))
        got = {sn: ((t, b) if row_a == "top" else (b, t)) for sn, (t, b) in finals.items()}
        want = _truth(mid)
        if got != want:
            bad.append(f"{mid}: got {got} want {want}")
        else:
            line = " ".join(f"{a}-{b}" for _, (a, b) in sorted(got.items()))
            print(f"ok  {mid:<28} {line}")
    assert not bad, "scoreline mismatches:\n  " + "\n  ".join(bad)


def test_every_decoded_game_is_a_legal_point_path():
    """The decoded log must be a legal badminton score path: +1 to exactly one
    side per entry, and every finished game a legal final."""
    for mid in LABELED:
        reads, _ = _reads(mid)
        log = score_seq.point_log(reads)
        prev = {}
        for sn, x, y, who, _ref, _s in log:
            px, py = prev.get(sn, (0, 0))
            assert (x - px, y - py) in ((1, 0), (0, 1)), \
                f"{mid} set {sn}: ({px},{py}) -> ({x},{y}) is not a single point"
            assert who == ("x" if x > px else "y"), f"{mid}: scorer disagrees with the score"
            prev[sn] = (x, y)
        for sn, (x, y) in score_seq.set_finals(log).items():
            assert score_seq.is_final(x, y), f"{mid} set {sn}: {x}-{y} is not a legal final"
    print("ok  every decoded game is a legal point path")


def test_decoder_recovers_the_dropped_points():
    """The decoded log must contain one entry per point actually played."""
    for mid in LABELED:
        reads, _ = _reads(mid)
        log = score_seq.point_log(reads)
        want = sum(a + b for a, b in _truth(mid).values())
        assert len(log) == want, f"{mid}: decoded {len(log)} points, {want} were played"
        raw = len(reads)
        print(f"ok  {mid:<28} {raw} raw readings -> {len(log)} points (all {want} recovered)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\n{len(fns)}/{len(fns)} passed")
