"""Doubles persistent identity — OPTIONAL layer over the geometric roles (ISOLATED).

`roles.py` is identity-free and robust (pure geometry, survives ID swaps). This module
adds the opt-in piece: mapping the geometric slots (near/near2/far/far2) to NAMED
players, seeded MANUALLY per set. Exactly what a future self-uploader fills in.

Why per set: the two pairs swap ends between sets, so identity is defined per set.

Why a serve anchor: doubles serving rules put the four players in known service-court
quadrants at the serve (server's court by score parity, receiver diagonal). So labelling
the four quadrants once, at a set's first serve, pins names to slots; names then carry by
slot through the set. Re-anchoring at EVERY serve from the per-rally score (scoreboard
OCR) is the robust upgrade — it auto-corrects the rare mid-rally slot swaps — and is left
as a hook (`reanchor_at_serves`) until score OCR is wired for doubles.

Roster lives in matches.yaml under `doubles_identity` (a self-uploader just edits this):

    doubles_identity:
      1:                       # set number (ends swap → set 2 near/far names swap)
        anchor_frame: 27050    # a frame at/just after the set's first serve (all 4 on court)
        near_left:  Goh Sze Fei
        near_right: Nur Izzuddin
        far_left:   Fajar Alfian
        far_right:  Muhammad Rian Ardianto

CLI:  PYTHONPATH=src python -m badminton.doubles.identity <match_id> [--set N]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import config, court, db

QUADRANTS = ("near_left", "near_right", "far_left", "far_right")
SLOTS = ("near", "near2", "far", "far2")


def quadrant_of(x: float, y: float) -> str:
    """Service-court quadrant of a court-metre point (near/far by net, left/right by x)."""
    ns = "near" if y < court.NET_Y_M else "far"
    lr = "left" if x < court.COURT_WIDTH_M / 2 else "right"
    return f"{ns}_{lr}"


def _anchor_rows(match_id: str, anchor_frame: int, search: int = 5):
    """The 4 slot rows at the tracked frame nearest `anchor_frame` that has all 4 slots
    sitting in 4 DISTINCT quadrants (i.e. a genuine serve stance, not a mid-rally cross)."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') "
        "AND frame_num BETWEEN ? AND ? ",
        [match_id, anchor_frame - search * 30, anchor_frame + search * 30]).fetch_df()
    con.close()
    if df.empty:
        raise SystemExit(f"no tracks near frame {anchor_frame} — run doubles.track first")
    # prefer the frame closest to the anchor that is unambiguous (4 slots, 4 quadrants)
    for f in sorted(df.frame_num.unique(), key=lambda f: abs(f - anchor_frame)):
        g = df[df.frame_num == f]
        if set(g.player_id) >= set(SLOTS):
            quad = {r.player_id: quadrant_of(r.court_x, r.court_y) for r in g.itertuples()}
            if len(set(quad.values())) == 4:
                return f, quad
    raise SystemExit(
        f"no frame near {anchor_frame} has all 4 players in 4 distinct service quadrants — "
        "pick an anchor at a clean serve (players in their service courts)")


def resolve(match_id: str, set_no: int = 1) -> dict[str, str]:
    """slot -> player name for a set, from the manual roster + serve-quadrant anchor."""
    roster = config.get_match(match_id).get("doubles_identity") or {}
    s = roster.get(set_no, roster.get(str(set_no)))
    if not s:
        raise SystemExit(f"no doubles_identity for set {set_no} in matches.yaml (see docs/DOUBLES.md)")
    quad_names = {q: s[q] for q in QUADRANTS}
    used_frame, slot_quad = _anchor_rows(match_id, int(s["anchor_frame"]))
    if used_frame != int(s["anchor_frame"]):
        print(f"note: anchored at nearest clean serve frame {used_frame}")
    return {slot: quad_names[q] for slot, q in slot_quad.items()}


def team_slot_names(match_id: str) -> dict[tuple[str, int], str] | None:
    """Map (team, within-pair index 0/1) -> athlete name, for the WHOLE match.

    Identity that survives the set end-swaps has to be keyed by TEAM, not by the
    geometric court slot (which holds a different pair each game). We only have an exact
    roster for set 1 (the serve-quadrant anchor), and that's enough to NAME the teams:
    team A := the set-1 near pair, team B := the far pair (the same anchor sets.py uses).
    Within a pair the two members are indexed 0/1 by their set-1 tracker slots
    (A0=near, A1=near2, B0=far, B1=far2).

    Returns None when no set-1 roster is configured — callers then fall back to the pair
    display name + a P1/P2 index, which is honest (the team is always known; only the
    within-pair split is). We deliberately do NOT guess which physical player is which in
    later sets, since the pairs swap ends and only set 1 is anchored."""
    try:
        slot_name = resolve(match_id, 1)
    except SystemExit:
        return None
    return {("A", 0): slot_name.get("near"), ("A", 1): slot_name.get("near2"),
            ("B", 0): slot_name.get("far"), ("B", 1): slot_name.get("far2")}


def names_df(match_id: str, set_no: int = 1) -> pd.DataFrame:
    """All tracked rows for the match with a `name` column (names carried by slot).
    NOTE: carry-by-slot is only as good as slot persistence — serve re-anchoring (below)
    is what makes this robust to the occasional slot swap."""
    slot_name = resolve(match_id, set_no)
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks "
        "WHERE match_id=? AND player_id IN ('near','near2','far','far2') ORDER BY frame_num",
        [match_id]).fetch_df()
    con.close()
    df["name"] = df.player_id.map(slot_name)
    return df


def service_courts(side_score: int, even_player: str, odd_player: str) -> tuple[str, str]:
    """(right_court_player, left_court_player) for a side, from its score parity.

    Doubles serving-rule invariant: within a game a side's `even_player` stands in the
    RIGHT service court when the side's score is even, the LEFT when odd (and vice-versa
    for the partner). That fixed parity-court is what lets a single per-set seed name
    both players at every serve, regardless of how they rotated mid-rally."""
    return (even_player, odd_player) if side_score % 2 == 0 else (odd_player, even_player)


def _side_names(match_id: str, set_no: int) -> dict[str, set]:
    roster = config.get_match(match_id).get("doubles_identity") or {}
    s = roster.get(set_no, roster.get(str(set_no)))
    if not s:
        raise SystemExit(f"no doubles_identity for set {set_no} in matches.yaml")
    return {"near": {s["near_left"], s["near_right"]}, "far": {s["far_left"], s["far_right"]}}


def reanchor_at_serves(match_id: str, rally_scores, even_court: dict[str, str],
                       set_no: int = 1) -> list[tuple[int, int, dict[str, str]]]:
    """Per-rally slot->name, re-derived each rally from the serving-rule parity — so a
    slot swap during the previous rally's dead-time is corrected at the next serve.

    rally_scores: iterable of (start_frame, end_frame, near_score, far_score).
    even_court:   {'near': name, 'far': name} — each side's even-court (right-on-even)
                  player; the partner is the side's other roster name. (Production seeds
                  this from the set's first serve; scores come from scoreboard OCR.)

    For each rally: parity -> which named player is in the right vs left service court per
    side; then assign that side's two slots to those names by court_x at the rally's first
    all-4 frame. Returns (start, end, {slot: name}) per rally."""
    names = _side_names(match_id, set_no)
    con = db.connect(read_only=True)
    out = []
    for start, end, near_score, far_score in rally_scores:
        df = con.execute(
            "SELECT frame_num, player_id, court_x FROM tracks WHERE match_id=? "
            "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ? "
            "ORDER BY frame_num", [match_id, start, end]).fetch_df()
        rally_map: dict[str, str] = {}
        for f in df.frame_num.unique():
            g = df[df.frame_num == f]
            if set(g.player_id) >= {"near", "near2", "far", "far2"}:
                pos = dict(zip(g.player_id, g.court_x))
                for side, slots, score in (("near", ("near", "near2"), near_score),
                                           ("far", ("far", "far2"), far_score)):
                    even = even_court[side]
                    odd = (names[side] - {even}).pop()
                    right_name, left_name = service_courts(score, even, odd)
                    s0, s1 = slots
                    # larger court_x = right service court (camera view)
                    if pos[s0] >= pos[s1]:
                        rally_map[s0], rally_map[s1] = right_name, left_name
                    else:
                        rally_map[s0], rally_map[s1] = left_name, right_name
                break
        out.append((start, end, rally_map))
    con.close()
    return out


def rally_scores_ocr(match_id: str, windows, samples: int = 9, row_side=None):
    """Per-rally (start, end, near_score, far_score) via scoreboard OCR, majority-voted
    over `samples` frames per window (kills single-frame misreads). The re-anchor only
    uses score PARITY, so the OCR's one systematic confusion (8<->0, same parity) is
    harmless. `row_side` maps scoreboard rows to court sides (default top->near, bot->far;
    a future match/set with ends swapped would flip this — derive from side_map/roster).

    Reads are cached on disk per window (data/cache/), saved as it goes — an interrupted
    run resumes where it stopped, and a repeat run skips the cv2 seeks entirely."""
    import cv2
    from collections import Counter

    from .. import scoreboard as sb
    from . import segment
    row_side = row_side or {"top": "near", "bot": "far"}
    box = sb.calibrate_box(match_id)
    if box is None:
        raise SystemExit("score box not found")
    tpl = sb._load_templates()
    cache_name = f"doubles_scores_{match_id}.json"
    cache = segment._disk_cache(cache_name)
    cap = cv2.VideoCapture(str(config.REPO_ROOT / config.get_match(match_id)["video_path"]))
    out, n_new = [], 0
    for i, (a, b) in enumerate(windows, 1):
        key = f"{a}-{b}"
        if key not in cache:
            n_new += 1
            print(f"\r  score OCR {i}/{len(windows)} (cached {i - n_new})", end="", flush=True)
            tops, bots = [], []
            for f in np.linspace(a, b, samples).astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
                ok, fr = cap.read()
                r = sb.read_frame(fr, box, tpl) if ok else None
                if r:
                    tops.append(r["top"][-1])
                    bots.append(r["bot"][-1])
            cache[key] = [Counter(tops).most_common(1)[0][0] if tops else None,
                          Counter(bots).most_common(1)[0][0] if bots else None]
            segment._disk_save(cache_name, cache)
        top, bot = cache[key]
        if top is None or bot is None:
            out.append((a, b, None, None))
            continue
        out.append((a, b, top if row_side["top"] == "near" else bot,
                    bot if row_side["bot"] == "far" else top))
    if n_new:
        print()
    cap.release()
    return out


def auto_reanchor(match_id: str, even_court: dict[str, str], set_no: int = 1,
                  max_gap: int = 20, min_len: int = 45):
    """Fully-automatic serve re-anchor: segment rallies -> OCR per-rally scores -> parity
    re-anchor. Rallies with unreadable scores are skipped."""
    from . import segment
    windows = segment.rally_windows(match_id, max_gap, min_len)
    scores = [s for s in rally_scores_ocr(match_id, windows) if s[2] is not None]
    return reanchor_at_serves(match_id, scores, even_court, set_no)


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles persistent identity (isolated, opt-in)")
    ap.add_argument("match_id")
    ap.add_argument("--set", type=int, default=1)
    args = ap.parse_args()
    slot_name = resolve(args.match_id, args.set)
    print(f"set {args.set} slot -> player:")
    for slot in SLOTS:
        print(f"  {slot:6s} -> {slot_name.get(slot, '?')}")
    df = names_df(args.match_id, args.set)
    print(f"\nnamed {len(df):,} track rows across {df.frame_num.nunique():,} frames")


if __name__ == "__main__":
    main()
