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

from badminton.doubles import identity, insights, roles, segment, smooth  # noqa: E402
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
