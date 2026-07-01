"""Export doubles dashboard data for the static web app (ISOLATED, Phase 1).

Mirrors the singles `badminton.export_web`, but for the doubles surface — which is a
SEPARATE web route (`/d/<id>`) reading a SEPARATE manifest (`doubles_index.json`), so the
singles dashboard is untouched and the whole doubles web surface stays deletable. Emits
the tactical layer the singles schema can't express, plus (post `doubles.strokes`) the
stroke-derived shot tables:

  - per-rally formation: attack (front/back stack) vs defence (side-by-side) share,
    rotations (attack<->defence flips) and front-player swaps, per side;
  - a per-side match-span summary (frame-weighted attack share + median gaps);
  - per-named-player front-court share (when a `doubles_identity` roster is set);
  - per-rally 4-player replay tracks (near/near2/far/far2 court-metre paths) + the
    debounced formation timeline, for an animated 2D court in the dashboard.

Everything is rally-scoped (via segment.py) so dead-time between points never pollutes
the numbers. Frame numbers are VIDEO frames (no label offsets exist for doubles).

The isolation rule (see __init__.py): this imports only low-level shared helpers
(config, court, db) plus its own sibling doubles modules — never the singles
`export_web`. The tiny JSON helpers below are re-implemented locally for that reason.

CLI:
  PYTHONPATH=src python -m badminton.doubles.export_web <match_id> [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, court, db
from . import identity as _identity
from . import control, insights, movement, points, roles, segment, sets, shots, validate

OUT_DEFAULT = config.REPO_ROOT / "web" / "public" / "data"
DOUBLES_INDEX = "doubles_index.json"
CLIPS_DIR = config.REPO_ROOT / "web" / "public" / "clips"
SLOTS = ("near", "near2", "far", "far2")


def _js(o):
    """JSON-safe: numpy scalars -> python, NaN -> None (mirrors export_web._js)."""
    if isinstance(o, dict):
        return {str(k): _js(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_js(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if pd.isna(o) else round(float(o), 3)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NA:
        return None
    return o


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_js(obj), separators=(",", ":"), ensure_ascii=False))


def _yt_id(url: str) -> str | None:
    m = re.search(r"(?:youtu\.be/|v=)([\w-]{6,})", url or "")
    return m.group(1) if m else None


# ------------------------------------------------------------------ annotated clips

def _clip_windows(match_id: str) -> list[tuple[int, int, str]]:
    """AI-annotated rally clips on disk: (start, end, relative url). Clip names carry
    their video-frame window so each rally maps on by overlap. Mirrors the singles
    export_web._clip_windows (re-implemented here to keep the isolation rule)."""
    out: list[tuple[int, int, str]] = []
    for p in sorted((CLIPS_DIR / match_id).glob("f*-*.mp4")):
        m = re.match(r"f(\d+)-(\d+)\.mp4$", p.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), f"/clips/{match_id}/{p.name}"))
    return out


def _clip_for(clips: list[tuple[int, int, str]], f0: int, f1: int) -> str | None:
    """The clip whose frame window best overlaps [f0, f1] (>= 60% of the rally), else None."""
    best, best_ov = None, 0
    for a, b, url in clips:
        ov = min(f1, b) - max(f0, a)
        if ov > best_ov:
            best, best_ov = url, ov
    return best if best_ov >= 0.6 * (f1 - f0) else None


# ------------------------------------------------------------------ identity / names

def _slot_names(match_id: str, set_no: int = 1) -> dict[str, str] | None:
    """slot -> athlete name for a set (serve-anchored), or None if no roster is set."""
    try:
        return _identity.resolve(match_id, set_no)
    except SystemExit:
        return None


def _pairs(match_id: str, m: dict, set_no: int = 1) -> dict[str, str]:
    """'near'/'far' -> the pair's display name ("A / B").

    Prefer the per-set `doubles_identity` roster (authoritative side+pair). Fall back to
    the two `players` entries (order not side-resolved, so this is a best-effort label)."""
    roster = (m.get("doubles_identity") or {})
    s = roster.get(set_no, roster.get(str(set_no)))
    if s:
        return {"near": f"{s['near_left']} / {s['near_right']}",
                "far": f"{s['far_left']} / {s['far_right']}"}
    players = m.get("players") or []
    return {"near": players[1] if len(players) > 1 else "Near pair",
            "far": players[0] if players else "Far pair"}


# ------------------------------------------------------------------ teams / set structure

def _teams(match_id: str, m: dict) -> dict[str, str]:
    """Fixed team labels A/B for the whole match. A := the pair that started on the NEAR
    end in set 1, B := the far pair (matching sets.side_pair_map's anchor)."""
    p = _pairs(match_id, m, 1)
    return {"A": p["near"], "B": p["far"]}


def _ocr_scores(match_id: str, windows):
    """Per-rally (start, end, top, bot) scoreboard reads — computed ONCE per export and
    shared by both set detection and the Points view (the cv2 seeks are the slow part)."""
    try:
        return _identity.rally_scores_ocr(match_id, windows)
    except Exception as e:  # OCR/scoreboard failure must not break the whole export
        print(f"  note: scoreboard OCR failed ({e}); treating as a single set, no scores")
        return None


def _rally_sides(windows, scores) -> list[dict]:
    """Per-rally set + which team (A/B) is on near/far, aligned 1:1 to `windows`, from the
    precomputed OCR scores. Falls back to a single set with the set-1 orientation
    (near=A, far=B) so a tracked-but-unread match still exports sensibly."""
    rs = sets.rally_sides(scores) if scores else None
    if rs and len(rs) == len(windows):
        return [{"set": r["set"], "nearPair": r["near_pair"], "farPair": r["far_pair"],
                 "total": r["total"]} for r in rs]
    return [{"set": 1, "nearPair": "A", "farPair": "B", "total": None} for _ in windows]


# ------------------------------------------------------------------ tactics tables

def _rally_table(match_id: str, windows, rsides: list[dict],
                 clips: list, max_gap: int, min_len: int) -> list[dict]:
    """Per rally: frames/time, its real SET, which team is near/far, the annotated-clip url
    (if rendered), and each TEAM's attack share / rotations / front-swaps. The geometric
    near/far stats are mapped to teams A/B via the per-rally side→pair map, so a rally in
    set 2 (ends swapped) credits the right team. `insights.rally_report` shares the windows,
    so its 1-based rally index aligns."""
    rr = insights.rally_report(match_id, max_gap, min_len)
    fps = float(config.get_match(match_id)["fps"])
    out = []
    for i, (a, b) in enumerate(windows, 1):
        rsi = rsides[i - 1]
        row: dict = {"rally": i, "set": rsi["set"], "f0": int(a), "f1": int(b),
                     "t0": round(a / fps, 2), "t1": round(b / fps, 2),
                     "durS": round((b - a + 1) / fps, 2), "frames": int(b - a + 1),
                     "nearPair": rsi["nearPair"], "farPair": rsi["farPair"],
                     "clip": _clip_for(clips, int(a), int(b)),
                     "A": None, "B": None}
        for side, team in (("near", rsi["nearPair"]), ("far", rsi["farPair"])):
            sr = rr[(rr.rally == i) & (rr.side == side)]
            if not sr.empty:
                r0 = sr.iloc[0]
                row[team] = {"attackPct": float(r0["attack_%"]),
                             "rotations": int(r0["rotations"]),
                             "frontSwaps": int(r0["front_swaps"]),
                             "frames": int(r0["frames"])}
        out.append(row)
    return out


def _team_gaps(match_id: str, windows, rsides: list[dict]) -> dict[str, dict[int, list]]:
    """Per team -> {'depth': [...], 'lateral': [...]} of in-rally role-geometry gaps, with
    each rally's near/far rows attributed to the team that occupied that side that rally."""
    rd = roles.roles_df(match_id)
    acc = {"A": {"depth": [], "lateral": []}, "B": {"depth": [], "lateral": []}}
    if rd.empty:
        return acc
    for (a, b), rsi in zip(windows, rsides):
        seg = rd[(rd.frame_num >= a) & (rd.frame_num <= b)]
        for side, team in (("near", rsi["nearPair"]), ("far", rsi["farPair"])):
            g = seg[seg.side == side]
            if not g.empty:
                acc[team]["depth"].extend(g.depth_gap.tolist())
                acc[team]["lateral"].extend(g.lateral_gap.tolist())
    return acc


def _formation_for(rows: list[dict], gaps: dict) -> dict:
    """Per-team formation block from team-keyed rally rows + accumulated gap samples."""
    out = {}
    for team in ("A", "B"):
        sides = [r[team] for r in rows if r.get(team)]
        frames = sum(s["frames"] for s in sides)
        attack = (sum(s["attackPct"] * s["frames"] for s in sides) / frames) if frames else None
        d, lat = gaps[team]["depth"], gaps[team]["lateral"]
        out[team] = {
            "frames": frames,
            "attackPct": round(attack, 1) if attack is not None else None,
            "defencePct": round(100 - attack, 1) if attack is not None else None,
            "rotations": sum(s["rotations"] for s in sides),
            "frontSwaps": sum(s["frontSwaps"] for s in sides),
            "medianDepthGapM": round(float(np.median(d)), 2) if d else None,
            "medianLateralGapM": round(float(np.median(lat)), 2) if lat else None,
        }
    return out


def _formation_summary(match_id: str, windows, rally_rows: list[dict],
                       rsides: list[dict]) -> tuple[dict, list[dict]]:
    """Per-TEAM match-span summary + per-set breakdown. Attack/rotations/front-swaps come
    from the team-keyed rally rows; median depth/lateral gaps from in-rally role geometry
    attributed to the team that held each side that rally."""
    gaps = _team_gaps(match_id, windows, rsides)
    total = _formation_for(rally_rows, gaps)

    by_set = []
    set_nos = sorted({r["set"] for r in rally_rows})
    for sn in set_nos:
        idx = [i for i, r in enumerate(rally_rows) if r["set"] == sn]
        sub_rows = [rally_rows[i] for i in idx]
        sub_win = [windows[i] for i in idx]
        sub_rs = [rsides[i] for i in idx]
        by_set.append({"set": sn,
                       **_formation_for(sub_rows, _team_gaps(match_id, sub_win, sub_rs))})
    return total, by_set


def _player_table(match_id: str, windows, rsides: list[dict]) -> list[dict]:
    """Per named player: front-court share, computed SET-BY-SET and restricted to that set's
    rallies (so a roster only ever names the slots in the set it was anchored on). Only sets
    with a `doubles_identity` roster contribute — others are skipped rather than mislabeled
    by a swapped-end roster. Each row carries its set + the team (A/B) that side belonged to."""
    roster = config.get_match(match_id).get("doubles_identity") or {}
    rd = roles.roles_df(match_id)
    if rd.empty:
        return []
    out = []
    for sn in sorted({r["set"] for r in rsides}):
        if not (roster.get(sn) or roster.get(str(sn))):
            continue
        try:
            slot_name = _identity.resolve(match_id, sn)
        except SystemExit:
            continue
        idx = [i for i, rs in enumerate(rsides) if rs["set"] == sn]
        sub = pd.concat([rd[(rd.frame_num >= windows[i][0]) & (rd.frame_num <= windows[i][1])]
                         for i in idx]) if idx else rd.iloc[0:0]
        smap = sets.side_pair_map(sn)
        for side, slots in (("near", ("near", "near2")), ("far", ("far", "far2"))):
            s = sub[sub.side == side]
            if s.empty:
                continue
            n = len(s)
            for slot in slots:
                out.append({"name": slot_name.get(slot, slot), "slot": slot,
                            "side": side, "set": sn, "team": smap[side],
                            "frontPct": round(100 * float((s.front == slot).mean())),
                            "frames": int(n)})
    return out


def _movement_table(match_id: str, fps: float, teams: dict,
                    rally_full: list[dict]) -> list[dict]:
    """Per-PLAYER movement (FOUR per set): distance/speed/coverage, front/mid/back, and a
    positional heatmap, each far-side player mirrored onto one near half so all four are
    comparable. Keyed by (set, team, within-pair index) so it's correct through the
    end-swaps; set-1 entries carry the real athlete name (roster-anchored), other sets
    carry name=None (the web shows the pair name + P1/P2 — the team is always known, only
    the within-pair identity isn't)."""
    team_names = _identity.team_slot_names(match_id)   # (team, idx) -> name, or None
    # name is the exact roster athlete for set 1, None otherwise — the web renders the
    # honest fallback (pair name + P1/P2) rather than guessing which member is which.
    return movement.player_movement(match_id, fps, rally_full, team_names)


# ------------------------------------------------------------------ formation flow

def _flow_table(match_id: str, fps: float, rsides: list[dict],
                max_gap: int, min_len: int) -> dict:
    """Per-TEAM formation-flow aggregates + per-rally attack/defence segments. The geometric
    near/far segments are credited to the team that held that side each rally (so the flow
    survives end-swaps). `insights.formation_flow` shares the windows, so rally index aligns."""
    flow = insights.formation_flow(match_id, max_gap, min_len)
    agg = {t: {"attack_first": 0, "defence_first": 0, "rallies": 0, "a2d": 0, "d2a": 0,
               "rotations": 0, "attack_frames": 0, "total_frames": 0, "holds": []}
           for t in ("A", "B")}
    out_rallies = []
    for r in flow["rallies"]:
        a, b = r["f0"], r["f1"]
        rsi = rsides[r["rally"] - 1] if r["rally"] - 1 < len(rsides) else {"set": 1, "nearPair": "A", "farPair": "B"}
        out_rallies.append({"rally": r["rally"], "set": rsi["set"], "f0": a, "f1": b,
                            "durS": round((b - a + 1) / fps, 1),
                            "nearPair": rsi["nearPair"], "farPair": rsi["farPair"],
                            "near": r["near"], "far": r["far"]})
        for side, team in (("near", rsi["nearPair"]), ("far", rsi["farPair"])):
            segs = r[side]
            if not segs:
                continue
            g = agg[team]
            g["rallies"] += 1
            g["attack_first" if segs[0][2] == "attack" else "defence_first"] += 1
            for s0, s1, lab in segs:
                dur = s1 - s0 + 1
                g["total_frames"] += dur
                if lab == "attack":
                    g["attack_frames"] += dur
                    g["holds"].append(dur)
            for x, y in zip(segs, segs[1:]):
                g["a2d"] += x[2] == "attack" and y[2] == "defence"
                g["d2a"] += x[2] == "defence" and y[2] == "attack"
            g["rotations"] += len(segs) - 1
    teams = {}
    for team in ("A", "B"):
        g = agg[team]
        n = g["rallies"]
        mins = g["total_frames"] / fps / 60 if g["total_frames"] else 0
        holds = g["holds"]
        teams[team] = {
            "rallies": n,
            "attackFirst": g["attack_first"], "defenceFirst": g["defence_first"],
            "attackFirstPct": round(100 * g["attack_first"] / n) if n else None,
            "attackPct": round(100 * g["attack_frames"] / g["total_frames"]) if g["total_frames"] else None,
            "attackHoldMedS": round(float(np.median(holds)) / fps, 1) if holds else None,
            "rotPerRally": round(g["rotations"] / n, 1) if n else None,
            "rotPerMin": round(g["rotations"] / mins, 1) if mins else None,
            "a2d": g["a2d"], "d2a": g["d2a"],
        }
    return {"A": teams["A"], "B": teams["B"], "rallies": out_rallies}


# ------------------------------------------------------------------ court control

def _control_table(match_id: str, windows, rsides: list[dict], teams: dict) -> dict:
    """Per-TEAM court control (Voronoi dominant region), attributed via the per-rally
    side→team map. Reports the bias-cancelled index (raw control has a static far-side
    floor — see control.py) plus a set-1 control MAP (near=A) as the 'control surface'."""
    frac, _, _, _ = control.control_series(match_id, windows=windows)
    base = control.match_baseline(frac)                # near% baseline (static bias floor)
    rallies, accum = [], {"A": [], "B": []}
    for i, (a, b) in enumerate(windows, 1):
        vals = [v for f, v in frac.items() if a <= f <= b]
        if not vals:
            continue
        near = 100 * float(np.mean(vals))
        rsi = rsides[i - 1]
        accum[rsi["nearPair"]].append((near, len(vals)))
        accum[rsi["farPair"]].append((100 - near, len(vals)))
        rallies.append({"rally": i, "set": rsi["set"], "f0": int(a), "f1": int(b),
                        "nearPair": rsi["nearPair"], "farPair": rsi["farPair"],
                        "nearControlPct": round(near), "nearIndex": round(near - base, 1)})
    summary = {}
    for t in ("A", "B"):
        s = accum[t]
        fr = sum(n for _, n in s)
        summary[t] = round(sum(c * n for c, n in s) / fr, 1) if fr else None

    cmap = None
    set1 = [w for w, rs in zip(windows, rsides) if rs["set"] == 1]
    if set1:
        _, grid, n1, _ = control.control_series(match_id, windows=set1)
        if n1:
            cmap = {"step": control.GRID_STEP, "w": court.COURT_WIDTH_M, "l": court.COURT_LENGTH_M,
                    "nearTeam": teams["A"], "farTeam": teams["B"],
                    "grid": [[round(float(v), 3) for v in row] for row in grid]}
    return {"baseline": round(base, 1), "summary": summary, "rallies": rallies, "map": cmap}


# ------------------------------------------------------------------ per-rally replay

def _export_replay(match_id: str, rally_no: int, a: int, b: int, fps: float,
                   teams: dict, rsi: dict, rd: pd.DataFrame, out: Path,
                   strokes: list | None = None) -> None:
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks WHERE match_id=? "
        "AND player_id IN ('near','near2','far','far2') AND frame_num BETWEEN ? AND ? "
        "ORDER BY frame_num", [match_id, a, b]).fetchall()
    con.close()
    tracks: dict[str, list] = {s: [] for s in SLOTS}
    for f, pid, x, y in rows:
        if pid in tracks:
            tracks[pid].append([int(f), round(float(x), 2), round(float(y), 2)])

    seg = rd[(rd.frame_num >= a) & (rd.frame_num <= b)]
    form = {side: insights._form_segments(seg[seg.side == side]) for side in ("near", "far")}

    # which team is on each side this rally → the web colours dots by team, not court side
    pairs = {"near": teams[rsi["nearPair"]], "far": teams[rsi["farPair"]]}
    _write(out / match_id / "dreplay" / f"r{rally_no}.json", dict(
        fps=fps, f0=int(a), f1=int(b), rally=rally_no, set=rsi["set"],
        nearPair=rsi["nearPair"], farPair=rsi["farPair"],
        pairs=pairs, names=None, tracks=tracks, form=form, strokes=strokes or []))


# ------------------------------------------------------------------ coach notes

def _coach_notes(teams: dict, formation: dict, flow: dict, players: list) -> list[dict]:
    """Rule-based, doubles-tailored scouting notes from the already-computed per-TEAM
    tactics (no extra DB work). Honest and small: each note states a measured tendency a
    coach would act on. `kind` colours it (good/watch/info) in the web."""
    notes: list[dict] = []

    def note(kind, head, body):
        notes.append({"kind": kind, "head": head, "body": body})

    fa, fb = flow["A"], flow["B"]

    # 1) attack control — who seizes and holds the offence
    if fa["attackPct"] is not None and fb["attackPct"] is not None:
        dom, oth = ("A", "B") if fa["attackPct"] >= fb["attackPct"] else ("B", "A")
        d, o = flow[dom], flow[oth]
        gap = abs(fa["attackPct"] - fb["attackPct"])
        if gap >= 12:
            note("watch", "Attack control is lopsided",
                 f"{teams[dom]} held the attacking formation {d['attackPct']}% of tracked "
                 f"frames vs {o['attackPct']}% for {teams[oth]}"
                 + (f", and seized it first in {d['attackFirstPct']}% of rallies" if d.get("attackFirstPct") is not None else "")
                 + f". {teams[oth]} need to win the first exchange to get off defence.")
        else:
            note("info", "Attack was evenly contested",
                 f"Both pairs held the offence a similar share of the time "
                 f"({teams['A']} {fa['attackPct']}% · {teams['B']} {fb['attackPct']}%).")

    # 2) attack hold length — sustaining vs trading the offence
    for team in ("A", "B"):
        h = flow[team].get("attackHoldMedS")
        if h is not None and flow[team]["rallies"] >= 3:
            if h >= 2.5:
                note("good", f"{teams[team]} sustain the attack",
                     f"Median {h:.1f}s of continuous attacking before being rotated off — "
                     f"they keep the pressure on rather than trading it back.")
            elif h <= 1.5:
                note("watch", f"{teams[team]} lose the attack quickly",
                     f"Median attack lasts only {h:.1f}s before they're forced back to "
                     f"defence — the rear player isn't getting time to step in.")

    # 3) net hunter — clearest front-court specialist (within a roster-named set)
    if players:
        top = max(players, key=lambda p: p["frontPct"])
        if top["frontPct"] >= 60:
            mate = next((p for p in players if p.get("set") == top.get("set")
                         and p["side"] == top["side"] and p["slot"] != top["slot"]), None)
            tail = f" — {mate['name']} mostly covers the rear" if mate else ""
            note("info", f"{top['name']} hunts the net",
                 f"At the front for {top['frontPct']:.0f}% of set-{top['set']} in-rally frames{tail}. "
                 f"A defined front/back split is harder to break down than a 50/50 pair.")

    # 4) rotation discipline — flips per minute
    for team in ("A", "B"):
        r = flow[team].get("rotPerMin")
        if r is not None and r >= 22 and flow[team]["rallies"] >= 3:
            note("watch", f"{teams[team]} rotate a lot",
                 f"{r:.0f} formation flips per minute — frequent attack⇄defence churn can "
                 f"mean they're being pulled around rather than dictating.")

    return notes


# ------------------------------------------------------------------ per-match

def _shots_table(match_id: str, pts: dict | None) -> dict | None:
    """Stroke-derived shot tactics per team A/B: mix, response matrix, per-player mix,
    serve/receive point splits and finishing shots (the last two join the strokes to the
    OCR rally winners in `pts`). The shot DISPLAY renames (lift/serve/push/block) are
    applied HERE — the presentation boundary — off the singles SHOT_DISPLAY map; the
    DB/strokes keep canonical strings. None pre-strokes."""
    from ..insights import SHOT_DISPLAY
    ts = shots.team_strokes(match_id)
    if ts.empty:
        return None
    disp = lambda s: SHOT_DISPLAY.get(s, s)

    def rows(counter):
        tot = sum(counter.values()) or 1
        return [{"shot": disp(k), "n": int(v), "pct": round(100 * v / tot)}
                for k, v in counter.most_common()]

    mix = {t: rows(c) for t, c in shots.shot_mix(match_id, ts).items()}
    responses = {}
    for team, mat in shots.response_matrix(match_id, ts).items():
        responses[team] = [
            {"vs": disp(opp), "total": int(sum(ans.values())), "answers": rows(ans)}
            for opp, ans in sorted(mat.items(), key=lambda kv: -sum(kv[1].values()))]

    # server per rally comes from the SCORE (winner serves next), not the strokes —
    # the contact detector can't see the far-side serve (window-edge extremum)
    winners = {int(k): v for k, v in (pts or {}).get("rallyWinner", {}).items()}
    srv = shots.rally_server((pts or {}).get("sets") or [])

    # per player, keyed (set, team, idx) like movement — name only in the set-1 roster set
    team_names = _identity.team_slot_names(match_id) or {}
    players = [{"set": p["set"], "team": p["team"], "idx": p["idx"],
                "name": team_names.get((p["team"], p["idx"])) if p["set"] == 1 else None,
                "serves": p["serves"], "top": rows(p["shots"])}
               for p in shots.player_mix(match_id, ts, srv)]

    fin = shots.finishers(ts, winners)
    return {"mix": mix, "responses": responses, "players": players,
            "serveReceive": shots.serve_receive(winners, srv) if srv else None,
            "finishers": {"won": {t: rows(c) for t, c in fin["won"].items()},
                          "lost": {t: rows(c) for t, c in fin["lost"].items()}}
                         if winners else None,
            "rallyFinish": {str(r): {"shot": disp(v["shot"]), "team": v["team"]}
                            for r, v in fin["rallyFinish"].items()}}


def _rally_strokes(match_id: str) -> dict[int, list]:
    """rally_id -> ordered [frame, slot, display shot] for the per-rally replay payloads."""
    from ..insights import SHOT_DISPLAY
    con = db.connect(read_only=True)
    rows = con.execute(
        "SELECT rally_id, frame_num, hitter, shot_type FROM strokes "
        "WHERE match_id=? AND source='pipeline' ORDER BY frame_num", [match_id]).fetchall()
    con.close()
    out: dict[int, list] = {}
    for rid, f, hitter, shot in rows:
        out.setdefault(int(rid), []).append([int(f), hitter, SHOT_DISPLAY.get(shot, shot)])
    return out


def export_match(match_id: str, out: Path, set_no: int = 1,
                 max_gap: int = 20, min_len: int = 45) -> dict | None:
    m = config.get_match(match_id)
    if m.get("discipline") != "doubles":
        print(f"  !! {match_id}: discipline={m.get('discipline')!r}, not doubles — skipping")
        return None
    fps = float(m["fps"])
    windows = segment.rally_windows(match_id, max_gap, min_len)
    if not windows:
        print(f"  !! {match_id}: no rallies (run doubles.track first) — skipping")
        return None

    pairs = _pairs(match_id, m, set_no)            # set-1 orientation (near=A, far=B)
    teams = _teams(match_id, m)                     # fixed A/B labels for the whole match
    scores = _ocr_scores(match_id, windows)         # (start,end,top,bot) per rally — OCR ONCE
    rsides = _rally_sides(windows, scores)          # per-rally set + which team is near/far
    clips = _clip_windows(match_id)                 # annotated rally clips on disk (if rendered)
    rally_full = [{"start": int(a), "end": int(b), "set": rs["set"],
                   "near_pair": rs["nearPair"], "far_pair": rs["farPair"]}
                  for (a, b), rs in zip(windows, rsides)]

    rally_rows = _rally_table(match_id, windows, rsides, clips, max_gap, min_len)
    formation, formation_by_set = _formation_summary(match_id, windows, rally_rows, rsides)
    players = _player_table(match_id, windows, rsides)
    movements = _movement_table(match_id, fps, teams, rally_full)
    flow = _flow_table(match_id, fps, rsides, max_gap, min_len)
    control_tbl = _control_table(match_id, windows, rsides, teams)
    showcase = validate.showcase(match_id, fps, max_gap, min_len, None)
    notes = _coach_notes(teams, formation, flow, players)
    # Points / momentum from the scoreboard scores (rows are fixed by team; top_team anchors it)
    pts = points.build(scores, sets.rally_sides(scores), fps,
                       m.get("scoreboard_top_team", "A")) if scores else None
    total_frames = sum(r["frames"] for r in rally_rows)

    n_sets = max((r["set"] for r in rally_rows), default=1)
    set_totals = [{"set": sn,
                   "rallies": sum(1 for r in rally_rows if r["set"] == sn),
                   "frames": sum(r["frames"] for r in rally_rows if r["set"] == sn)}
                  for sn in range(1, n_sets + 1)]

    meta = dict(
        id=match_id, discipline="doubles", pairs=pairs, teams=teams,
        tournament=m.get("tournament"), round=m.get("round"),
        date=str(m.get("match_date", "")), youtubeId=_yt_id(m.get("video_url")),
        result=m.get("result"), fps=fps, nSets=n_sets, sets=set_totals,
        totals=dict(rallies=len(windows), frames=total_frames,
                    rallySecs=round(total_frames / fps, 1)),
        span=dict(f0=int(windows[0][0]), f1=int(windows[-1][1])),
    )
    _write(out / match_id / "doubles.json",
           dict(meta=meta, rallies=rally_rows, formation=formation,
                formationBySet=formation_by_set, players=players,
                movement=movements, flow=flow, control=control_tbl, points=pts,
                showcase=showcase, notes=notes, shots=_shots_table(match_id, pts)))

    rd = roles.roles_df(match_id)
    rally_strokes = _rally_strokes(match_id)
    for i, (a, b) in enumerate(windows, 1):
        _export_replay(match_id, i, a, b, fps, teams, rsides[i - 1], rd, out,
                       rally_strokes.get(i))

    return dict(id=match_id, discipline="doubles",
                pairs={"near": teams["A"], "far": teams["B"]},  # index keeps {near,far} shape
                tournament=m.get("tournament"), round=m.get("round"),
                date=str(m.get("match_date", "")), youtubeId=_yt_id(m.get("video_url")),
                result=m.get("result"), rallies=len(windows), nSets=n_sets)


def _merge_index(out: Path, entry: dict) -> None:
    """Upsert one match into doubles_index.json without disturbing other entries."""
    path = out / DOUBLES_INDEX
    matches = []
    if path.exists():
        try:
            matches = json.loads(path.read_text()).get("matches", [])
        except json.JSONDecodeError:
            matches = []
    matches = [x for x in matches if x.get("id") != entry["id"]] + [entry]
    matches.sort(key=lambda x: x.get("date", ""))
    _write(path, dict(matches=matches))


def main() -> None:
    ap = argparse.ArgumentParser(description="Export doubles dashboard data (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--set", type=int, default=1)
    ap.add_argument("--max-gap", type=int, default=20)
    ap.add_argument("--min-len", type=int, default=45)
    args = ap.parse_args()
    out = Path(args.out)
    entry = export_match(args.match_id, out, args.set, args.max_gap, args.min_len)
    if entry is None:
        return
    _merge_index(out, entry)
    print(f"wrote {out / args.match_id / 'doubles.json'} "
          f"({entry['rallies']} rallies) + {out / DOUBLES_INDEX}")


if __name__ == "__main__":
    main()
