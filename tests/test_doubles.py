"""Tests for the isolated doubles core logic — no video, no models, no DB.

Covers the parts most likely to be wrong and impossible to eyeball from a single run:
the SlotAssigner's identity persistence + velocity re-ID, and the role/formation
geometry. The full video pipeline (track.process_video) needs a doubles clip and a
GPU, so it is exercised manually; this locks down the algorithmic core.

Run:  PYTHONPATH=src .venv/bin/python tests/test_doubles.py     (or under pytest)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import court  # noqa: E402
from badminton.doubles import (  # noqa: E402
    control, identity, insights, movement, roles, segment, sets, smooth)
from badminton.doubles.track import REID_RADIUS_M, SlotAssigner, _Det  # noqa: E402

_DUMMY = np.zeros((17, 2)), np.zeros(17), np.zeros(4)  # kxy, kcf, box stand-ins


def det(tid: int, x: float, y: float, area: float = 1.0) -> _Det:
    kxy, kcf, box = _DUMMY
    return _Det(tid, np.array([x, y], float), np.array([0.0, 0.0]), kxy, kcf, box, area)


def test_persistence_survives_position_swap():
    """A slot stays pinned to its track-id even when the two players cross laterally."""
    a = SlotAssigner()
    out0 = a.update(0, [det(10, 2.0, 3.0), det(11, 4.0, 3.0)])
    assert out0["near"].tid == 10 and out0["near2"].tid == 11
    # frame 1: same ids, swapped x positions — identity must follow the id, not the spot
    out1 = a.update(1, [det(10, 4.0, 3.0), det(11, 2.0, 3.0)])
    assert out1["near"].tid == 10 and out1["near2"].tid == 11


def test_velocity_reid_recovers_dropped_id():
    """When ByteTrack drops an id and a NEW id appears near the predicted spot,
    the slot is inherited (this is the occlusion-recovery the doubles papers flag)."""
    a = SlotAssigner()
    a.update(0, [det(10, 1.0, 3.0), det(11, 5.0, 3.0)])      # near=10, near2=11
    a.update(1, [det(10, 2.0, 3.0), det(11, 5.0, 3.0)])      # near velocity = +1 x/frame
    # frame 2: id 10 gone; new id 99 appears at predicted (3,3); 11 persists
    out2 = a.update(2, [det(99, 3.0, 3.0), det(11, 5.0, 3.0)])
    assert out2["near"].tid == 99, "dropped slot should be re-claimed by velocity"
    assert out2["near2"].tid == 11
    assert a.slot_of_tid[99] == "near"


def test_velocity_reid_matches_nearest_slot_no_crossing():
    """Two slots free + two new ids → each maps to its nearest prediction, not crossed."""
    a = SlotAssigner()
    a.update(0, [det(1, 2.0, 2.0), det(2, 4.0, 2.0)])        # near=1, near2=2
    a.update(1, [det(1, 1.0, 2.0), det(2, 5.0, 2.0)])        # 1 drifts left, 2 right
    # both dropped; new ids appear at each predicted spot (near→0, near2→6)
    out = a.update(2, [det(7, 0.2, 2.0), det(8, 5.8, 2.0)])
    assert out["near"].tid == 7 and out["near2"].tid == 8


def test_velocity_reid_routes_to_correct_free_slot():
    """With two slots free, a recovered detection goes to the slot whose PREDICTION it
    matches (within radius) — not to whichever slot happens to be first in fill order."""
    a = SlotAssigner()
    a.update(0, [det(1, 1.0, 3.0), det(2, 5.0, 3.0)])        # near pred→1.0, near2 pred→5.0
    a.update(1, [det(1, 1.0, 3.0), det(2, 5.0, 3.0)])        # both stationary; both persist
    # frame 2: both ids dropped, one new id appears next to near2's prediction (5.0)
    out = a.update(2, [det(9, 4.9, 3.0)])
    assert "near" not in out, "must not cold-fill the first free slot when geometry says near2"
    assert out["near2"].tid == 9


def test_velocity_reid_ignored_beyond_radius():
    """A reappearance far from every prediction is a fresh identity (cold assign), and
    cannot displace a closer in-radius candidate competing for the same single slot."""
    a = SlotAssigner()
    a.update(0, [det(1, 1.0, 3.0), det(2, 5.0, 3.0)])        # near=1 (pred 1.0), near2=2
    a.update(1, [det(1, 1.0, 3.0), det(2, 5.0, 3.0)])
    far = 1.0 + REID_RADIUS_M + 2.0                          # well outside near's radius
    # near2 persists; near is free. Two new ids contend: one in-radius, one far out.
    out = a.update(2, [det(2, 5.0, 3.0, area=3.0),
                       det(7, 1.3, 3.0, area=2.0),           # in radius of near's pred
                       det(8, far, 3.0, area=1.0)])          # out of radius (also area-capped)
    assert out["near"].tid == 7, "in-radius candidate must win the recovered slot"


def test_players_split_across_halves():
    """Detections are routed to near/far slots by court half (net at 6.70 m)."""
    a = SlotAssigner()
    out = a.update(0, [det(1, 2.0, 2.0), det(2, 4.0, 2.0),    # near half (y<6.70)
                       det(3, 2.0, 11.0), det(4, 4.0, 11.0)])  # far half (y>6.70)
    assert {out["near"].tid, out["near2"].tid} == {1, 2}
    assert {out["far"].tid, out["far2"].tid} == {3, 4}


def test_extra_detection_dropped_by_area():
    """A spurious 3rd person on a half is rejected (keep the 2 largest by area)."""
    a = SlotAssigner()
    out = a.update(0, [det(1, 2.0, 3.0, area=10.0), det(2, 4.0, 3.0, area=9.0),
                       det(3, 3.0, 3.0, area=0.1)])           # tiny = line judge / artifact
    assert {out["near"].tid, out["near2"].tid} == {1, 2}
    assert "near" not in {} and len(out) == 2


def _p(pid, x, y):
    return SimpleNamespace(player_id=pid, court_x=x, court_y=y)


def test_roles_attack_formation():
    """Stacked front-to-back (depth gap > lateral) → attack; front is nearer the net."""
    r = roles._pair_roles(_p("near", 3.0, 6.3), _p("near2", 3.4, 3.0))
    assert r["formation"] == "attack"
    assert r["front"] == "near" and r["back"] == "near2"
    assert r["left"] == "near"          # smaller x


def test_roles_defence_formation():
    """Side-by-side (lateral gap >= depth) → defence."""
    r = roles._pair_roles(_p("far", 1.0, 9.0), _p("far2", 5.0, 9.2))
    assert r["formation"] == "defence"


def test_roles_front_is_nearest_net_on_far_side():
    """On the far side (y>6.70) the smaller-y player is the one at the net."""
    r = roles._pair_roles(_p("far", 2.0, 7.0), _p("far2", 4.0, 12.0))
    assert r["front"] == "far" and r["back"] == "far2"


def test_quadrant_of():
    """Service-court quadrant: near/far split at the net (6.70), left/right at x=3.05."""
    assert identity.quadrant_of(1.0, 3.0) == "near_left"
    assert identity.quadrant_of(5.0, 3.0) == "near_right"
    assert identity.quadrant_of(1.0, 10.0) == "far_left"
    assert identity.quadrant_of(5.0, 10.0) == "far_right"


def test_service_courts_parity():
    """Serving rule: even-court player is on the right when the side's score is even."""
    assert identity.service_courts(8, "E", "O") == ("E", "O")    # even -> E right
    assert identity.service_courts(0, "E", "O") == ("E", "O")
    assert identity.service_courts(13, "E", "O") == ("O", "E")   # odd  -> O right
    assert identity.service_courts(9, "E", "O") == ("O", "E")


def test_identity_seed_inversion():
    """A clean serve anchor (4 slots in 4 distinct quadrants) maps each slot to its name."""
    slot_quad = {"near": "near_left", "near2": "near_right",
                 "far": "far_right", "far2": "far_left"}
    quad_names = {"near_left": "A", "near_right": "B", "far_left": "C", "far_right": "D"}
    assert len(set(slot_quad.values())) == 4                 # the anchor is unambiguous
    slot_name = {s: quad_names[q] for s, q in slot_quad.items()}
    assert slot_name == {"near": "A", "near2": "B", "far": "D", "far2": "C"}


def test_smooth_lerp_midpoint():
    """Interpolation helpers: midpoint and None-guarding."""
    assert smooth._lerp(0.0, 10.0, 0.5) == 5.0
    assert smooth._lerp(2.0, 6.0, 0.25) == 3.0
    assert smooth._lerp(None, 6.0, 0.5) is None
    assert smooth._lerp_seq([0, 0, 2, 4], [4, 8, 2, 0], 0.5) == [2, 4, 2, 2]
    assert smooth._lerp_seq(None, [1, 2], 0.5) is None


def test_segment_splits_on_long_gap():
    """Runs split when the gap exceeds max_gap; sub-min-len fragments are dropped."""
    frames = [1, 2, 3, 10, 11, 12, 13, 100]
    assert segment._merge_runs(frames, max_gap=2, min_len=3) == [(1, 3), (10, 13)]


def test_segment_bridges_short_dropouts():
    """Gaps <= max_gap are bridged into one rally (within-rally far dropout)."""
    assert segment._merge_runs([1, 2, 5, 8], max_gap=3, min_len=1) == [(1, 8)]


def test_segment_min_len_filters_noise():
    """A short flicker that never reaches min_len is not a rally."""
    assert segment._merge_runs([1, 2, 3], max_gap=2, min_len=5) == []
    assert segment._merge_runs([], max_gap=20, min_len=45) == []


def test_hysteresis_suppresses_flicker():
    """A margin flickering inside the band holds state (no false rotations)."""
    flick = [0.1, -0.1, 0.2, -0.2, 0.1]          # all within ±0.4
    assert insights._count_switches(roles.hysteresis_formation(flick, band=0.4)) == 0


def test_hysteresis_keeps_real_switch():
    """A margin that clearly crosses the band still registers the rotation."""
    seq = roles.hysteresis_formation([1.0, 1.0, -1.0, -1.0], band=0.4)
    assert seq == ["attack", "attack", "defence", "defence"]
    assert insights._count_switches(seq) == 1


def test_hysteresis_generic_labels():
    """Generic Schmitt trigger used for the front-player debounce (labels a/b)."""
    assert roles.hysteresis([1.0, 1.0, -1.0, -1.0], "a", "b", 0.4) == ["a", "a", "b", "b"]
    # front flicker within the band must not register a swap
    assert insights._count_switches(roles.hysteresis([0.1, -0.2, 0.1], "a", "b", 0.5)) == 0


def test_count_switches():
    """Rotation counting = adjacent changes in a formation/front sequence."""
    assert insights._count_switches(["attack", "attack", "defence", "attack"]) == 2
    assert insights._count_switches(["near", "near", "near"]) == 0
    assert insights._count_switches([]) == 0
    assert insights._count_switches(["a", "b", "a", "b"]) == 3


def _set_totals(end_a, end_b):
    """Synthetic per-rally totals for one game ending end_a-end_b (1 point added/rally)."""
    return list(range(1, end_a + end_b + 1))


def test_assign_sets_three_game_match():
    """Set boundaries from score-total resets across a real 3-game line (17-21/21-16/27-25)."""
    totals = _set_totals(17, 21) + _set_totals(21, 16) + _set_totals(27, 25)
    s = sets.assign_sets(totals)
    assert s[0] == 1 and s[-1] == 3
    # the first rally of game 2 is right after the 38-total game-1 finale
    assert s[len(_set_totals(17, 21))] == 2
    assert s[len(_set_totals(17, 21)) + len(_set_totals(21, 16))] == 3
    assert max(s) == 3


def test_assign_sets_tolerates_dropped_reads():
    """A None (unreadable) rally inherits the running set and never invents a boundary."""
    totals = [1, 2, None, 4, 38, 1, 2]          # one reset after the 38
    s = sets.assign_sets(totals)
    assert s == [1, 1, 1, 1, 1, 2, 2]
    # an 8->0 misread mid-game (e.g. 18->10) must NOT trigger a reset (10 > SET_RESET_MAX)
    assert sets.assign_sets([16, 18, 10, 19]) == [1, 1, 1, 1]


def test_side_pair_map_end_swaps():
    """Ends swap each game; the deciding game swaps once more at 11."""
    assert sets.side_pair_map(1) == {"near": "A", "far": "B"}
    assert sets.side_pair_map(2) == {"near": "B", "far": "A"}
    assert sets.side_pair_map(3) == {"near": "A", "far": "B"}          # before 11
    assert sets.side_pair_map(3, post_deciding_swap=True) == {"near": "B", "far": "A"}
    # only the deciding (3rd) game has the mid-set swap
    assert sets.side_pair_map(2, post_deciding_swap=True) == {"near": "B", "far": "A"}


def test_deciding_swap_frame_at_eleven():
    """The mid-game change of ends is located at the rally where a side first hits 11."""
    rows = [(0, 99, 5, 3), (100, 199, 9, 8), (200, 299, 11, 9), (300, 399, 12, 10)]
    assert sets.deciding_swap_frame(rows) == 199 + 100  # end frame of the 11-9 rally (299)
    assert sets.deciding_swap_frame([(0, 50, 3, 4)]) is None


def test_rally_sides_full_structure():
    """End-to-end pure assembly: each rally tagged with set + which pair is near/far.
    Each game must end high (>=18 total) before the next resets — as in real play."""
    rs = [(0, 99, 19, 21),                             # game 1 ends high (total 40)
          (100, 199, 1, 0), (200, 299, 19, 21),        # game 2: reset -> climbs high
          (300, 399, 0, 1),                            # game 3: reset
          (400, 499, 11, 5),                           # game 3 hits 11 -> swap after f499
          (500, 599, 12, 5)]                           # game 3 post-swap
    out = sets.rally_sides(rs)
    setseq = [r["set"] for r in out]
    assert setseq == [1, 2, 2, 3, 3, 3]
    assert out[0]["near_pair"] == "A" and out[0]["far_pair"] == "B"   # game 1
    assert out[1]["near_pair"] == "B"                                  # game 2 swapped
    assert out[3]["near_pair"] == "A"                                  # game 3 pre-11
    assert out[5]["near_pair"] == "B"                                  # game 3 post-11 swap


def test_coach_notes_lopsided_attack():
    """Coach notes flag a clearly lopsided attack share, naming the dominant TEAM."""
    from badminton.doubles import export_web
    teams = {"A": "A / B", "B": "C / D"}
    flow = {
        "A": {"attackPct": 30, "attackFirstPct": 20, "attackHoldMedS": 1.2,
              "rotPerMin": 12, "rallies": 5},
        "B": {"attackPct": 80, "attackFirstPct": 100, "attackHoldMedS": 3.1,
              "rotPerMin": 14, "rallies": 5},
    }
    notes = export_web._coach_notes(teams, {}, flow, [])
    assert any(n["kind"] == "watch" and "lopsided" in n["head"].lower() for n in notes)
    lop = next(n for n in notes if "lopsided" in n["head"].lower())
    assert "C / D" in lop["body"]                    # names the dominant team
    # team B sustains attack (>=2.5s) AND team A loses it fast (<=1.5s)
    assert any(n["kind"] == "good" and "C / D" in n["head"] for n in notes)
    assert any(n["kind"] == "watch" and "quickly" in n["head"].lower() for n in notes)


def test_coach_notes_even_attack_no_false_alarm():
    """A balanced attack share yields the neutral 'evenly contested' note, not a warning."""
    from badminton.doubles import export_web
    teams = {"A": "A / B", "B": "C / D"}
    flow = {
        "A": {"attackPct": 52, "attackFirstPct": 50, "attackHoldMedS": 2.0,
              "rotPerMin": 10, "rallies": 5},
        "B": {"attackPct": 48, "attackFirstPct": 50, "attackHoldMedS": 2.0,
              "rotPerMin": 10, "rallies": 5},
    }
    notes = export_web._coach_notes(teams, {}, flow, [])
    assert any("evenly contested" in n["head"].lower() for n in notes)
    assert not any("lopsided" in n["head"].lower() for n in notes)


def test_form_segments_runlength():
    """Formation flow: debounced attack/defence runs, sorted, with clean empty handling."""
    import pandas as pd
    # margin = depth_gap - lateral_gap; +ve clears the band → attack, −ve → defence
    df = pd.DataFrame({"frame_num": [10, 11, 12, 13, 14],
                       "depth_gap": [2.0, 2.0, 2.0, 0.0, 0.0],
                       "lateral_gap": [0.0, 0.0, 0.0, 2.0, 2.0]})
    assert insights._form_segments(df) == [[10, 12, "attack"], [13, 14, "defence"]]
    assert insights._form_segments(df.iloc[::-1]) == [[10, 12, "attack"], [13, 14, "defence"]]
    assert insights._form_segments(df.iloc[0:0]) == []


def test_movement_near_slot_passthrough():
    """Near slots already live on the near half — normalisation must leave them untouched."""
    P = np.array([[1.0, 2.0], [4.0, 5.5]])
    assert np.allclose(movement._to_near_half(P, "near"), P)
    assert np.allclose(movement._to_near_half(P, "near2"), P)


def test_movement_far_slot_mirrors_onto_near_half():
    """Far slots flip across centre (x->W-x, y->L-y) so a far net-player lands NEAR the net."""
    W, L, NET = movement.W, movement.L, movement.NET
    far_at_net = np.array([[1.0, NET + 0.3]])             # just over the net, far side
    out = movement._to_near_half(far_at_net, "far")
    assert np.allclose(out, [[W - 1.0, L - (NET + 0.3)]])
    assert abs(out[0, 1] - NET) < 0.5                     # mirrored y sits close to the net
    # a far baseline player maps to small y (own baseline → REAR), not negative/out of court
    base = movement._to_near_half(np.array([[3.0, L - 0.2]]), "far2")
    assert 0.0 <= base[0, 1] <= NET / 3                   # deep = REAR band


def test_movement_reach_and_grid_constants():
    """Court-control grid spans one half and the reach is a sane racket+lunge radius."""
    nx, ny = movement.CTRL_GRID
    assert nx > 0 and ny > 0
    assert 1.0 <= movement.REACH_M <= 2.5            # racket + lunge, not a teleport
    # the grid's y extent is the half court (cell centres live in (0, NET))
    ys = (np.arange(ny) + 0.5) / ny * movement.NET
    assert ys.min() > 0 and ys.max() < movement.NET


def test_movement_heat_shape_and_binning():
    """_heat matches the singles HeatMap contract (bins/extent) and counts every point."""
    P = np.array([[0.1, 0.1], [0.2, 0.2], [movement.W - 0.1, movement.NET]])
    h = movement._heat(P)
    assert (h["nx"], h["ny"]) == movement.HEAT_BINS
    assert h["x1"] == movement.W and h["y1"] == movement.NET + 0.5
    assert sum(c[2] for c in h["cells"]) == len(P)        # no point dropped
    assert all(0 <= i < h["nx"] and 0 <= j < h["ny"] for i, j, _ in h["cells"])


def test_points_clean_drops_dupes_and_regressions():
    """Score cleaning keeps only real forward points: over-segmented duplicates (same score
    twice) and OCR garbage (a backwards or unreadable read) are dropped, and the winner is
    the team whose score advanced."""
    from badminton.doubles import points
    rows = [
        {"rally": 1, "a": 1, "b": 0},   # A scores
        {"rally": 2, "a": 1, "b": 0},   # duplicate (over-segmented) — drop
        {"rally": 3, "a": 1, "b": 1},   # B scores
        {"rally": 4, "a": None, "b": None},  # OCR miss — drop
        {"rally": 5, "a": 0, "b": 0},   # regression (garbage) — drop
        {"rally": 6, "a": 2, "b": 1},   # A scores
    ]
    pts = points.clean_set_scores(rows)
    assert [(p["rally"], p["a"], p["b"], p["winner"]) for p in pts] == [
        (1, 1, 0, "A"), (3, 1, 1, "B"), (6, 2, 1, "A")]


def test_points_build_maps_rows_to_teams_and_detects_winner():
    """build(): top/bot rows map to teams A/B via top_team; final + set winner are derived
    from the accepted trajectory, and a longest-run is counted."""
    from badminton.doubles import points
    # one set: A pulls ahead 3-1. rally_scores = (start,end,top,bot); top_team='A' → a=top.
    rally_scores = [(0, 9, 1, 0), (10, 19, 2, 0), (20, 29, 2, 1), (30, 39, 3, 1)]
    rsides = [{"set": 1} for _ in rally_scores]
    out = points.build(rally_scores, rsides, fps=30.0, top_team="A")
    s = out["sets"][0]
    assert s["final"] == {"a": 3, "b": 1} and s["winner"] == "A"
    assert out["runs"]["A"] == 2          # A won rallies 1,2 back to back (then B, then A)
    # flipping top_team swaps the rows: now bottom row is team A
    flipped = points.build(rally_scores, rsides, fps=30.0, top_team="B")
    assert flipped["sets"][0]["final"] == {"a": 1, "b": 3} and flipped["sets"][0]["winner"] == "B"


def test_control_symmetric_is_half():
    """Mirror-image positions about the net → ~50/50 court control."""
    gx, gy = control._grid()
    L = court.COURT_LENGTH_M
    pos = {"near": (2.0, 5.0), "near2": (4.0, 5.0),
           "far": (2.0, L - 5.0), "far2": (4.0, L - 5.0)}
    assert abs(control.near_control_mask(pos, gx, gy).mean() - 0.5) < 0.03


def test_control_attacking_team_exceeds_half():
    """Near pair up at the net, far pair pinned deep → near controls > half the court."""
    gx, gy = control._grid()
    L = court.COURT_LENGTH_M
    pos = {"near": (2.5, 6.4), "near2": (3.5, 5.8),
           "far": (2.5, L - 0.9), "far2": (3.5, L - 0.9)}
    assert control.near_control_mask(pos, gx, gy).mean() > 0.55


def test_segment_merge_close_windows():
    """Fragments within GAP_MERGE_S of a neighbour reunite; distant windows don't."""
    ws = [(0, 300), (330, 400), (1000, 1600), (1650, 1700), (3000, 3300)]
    merged = segment._merge_close(ws, fps=30.0, gap_s=5.0)  # 1-1.6s gaps merge, 43s doesn't
    assert merged == [(0, 400), (1000, 1700), (3000, 3300)], merged


def test_segment_restart_truncation():
    """Contacts after a >RESTART_GAP pause are the dead-shuttle pickup — cut there."""
    cs = [{"frame": f} for f in (100, 130, 155, 190, 330, 350)]  # 140f pause after 190
    kept = segment._truncate_restarts(cs)
    assert [c["frame"] for c in kept] == [100, 130, 155, 190], kept
    assert segment._truncate_restarts(cs[:1]) == cs[:1]  # single contact passes through
    assert segment._truncate_restarts([]) == []


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
