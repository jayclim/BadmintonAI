"""Export doubles dashboard data for the static web app (ISOLATED, Phase 1).

Mirrors the singles `badminton.export_web`, but for the doubles surface — which is a
SEPARATE web route (`/d/<id>`) reading a SEPARATE manifest (`doubles_index.json`), so the
singles dashboard is untouched and the whole doubles web surface stays deletable. Doubles
has no strokes/shuttle yet, so there is nothing shot-level to emit; what we DO have is the
tactical layer the singles schema can't express:

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
from . import insights, roles, segment

OUT_DEFAULT = config.REPO_ROOT / "web" / "public" / "data"
DOUBLES_INDEX = "doubles_index.json"
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


# ------------------------------------------------------------------ tactics tables

def _rally_table(match_id: str, windows, max_gap: int, min_len: int) -> list[dict]:
    """Per rally: frames/time + each side's attack share, rotations, front-swaps.

    `insights.rally_report` is computed on the SAME windows (same max_gap/min_len), so
    its 1-based `rally` index lines up with `windows[rally-1]`."""
    rr = insights.rally_report(match_id, max_gap, min_len)
    fps = float(config.get_match(match_id)["fps"])
    out = []
    for i, (a, b) in enumerate(windows, 1):
        row: dict = {"rally": i, "set": 1, "f0": int(a), "f1": int(b),
                     "t0": round(a / fps, 2), "t1": round(b / fps, 2),
                     "durS": round((b - a + 1) / fps, 2), "frames": int(b - a + 1)}
        for side in ("near", "far"):
            sr = rr[(rr.rally == i) & (rr.side == side)]
            if sr.empty:
                row[side] = None
            else:
                r0 = sr.iloc[0]
                row[side] = {"attackPct": float(r0["attack_%"]),
                             "rotations": int(r0["rotations"]),
                             "frontSwaps": int(r0["front_swaps"]),
                             "frames": int(r0["frames"])}
        out.append(row)
    return out


def _formation_summary(match_id: str, windows, rally_rows: list[dict]) -> dict:
    """Per-side match-span summary: frame-weighted attack share, summed rotations/
    front-swaps (from the rally rows), and median depth/lateral gaps over in-rally
    frames only (so dead-time geometry never leaks in)."""
    rd = roles.roles_df(match_id)
    in_rally = pd.concat([rd[(rd.frame_num >= a) & (rd.frame_num <= b)] for a, b in windows]) \
        if windows and not rd.empty else rd.iloc[0:0]
    out = {}
    for side in ("near", "far"):
        sides = [r[side] for r in rally_rows if r.get(side)]
        frames = sum(s["frames"] for s in sides)
        attack = (sum(s["attackPct"] * s["frames"] for s in sides) / frames) if frames else None
        g = in_rally[in_rally.side == side]
        out[side] = {
            "frames": frames,
            "attackPct": round(attack, 1) if attack is not None else None,
            "defencePct": round(100 - attack, 1) if attack is not None else None,
            "rotations": sum(s["rotations"] for s in sides),
            "frontSwaps": sum(s["frontSwaps"] for s in sides),
            "medianDepthGapM": round(float(np.median(g.depth_gap)), 2) if not g.empty else None,
            "medianLateralGapM": round(float(np.median(g.lateral_gap)), 2) if not g.empty else None,
        }
    return out


def _player_table(match_id: str, set_no: int, max_gap: int, min_len: int) -> list[dict]:
    """Per named player: front-court share + which side, when a roster is set."""
    pr = insights.player_report(match_id, set_no, max_gap, min_len)
    if pr is None or pr.empty:
        return []
    side_of = {"near": "near", "near2": "near", "far": "far", "far2": "far"}
    return [{"name": r["player"], "slot": r["slot"], "side": side_of[r["slot"]],
             "frontPct": float(r["front_%"]), "frames": int(r["frames"])}
            for _, r in pr.iterrows()]


# ------------------------------------------------------------------ per-rally replay

def _form_segments(rd_side: pd.DataFrame) -> list[list]:
    """Run-length [startFrame, endFrame, 'attack'|'defence'] of the DEBOUNCED formation
    (Schmitt-triggered, matching roles/render) for one side over its sorted rows."""
    s = rd_side.sort_values("frame_num")
    if s.empty:
        return []
    labels = roles.hysteresis_formation((s.depth_gap - s.lateral_gap).tolist())
    frames = s.frame_num.tolist()
    segs, start, cur, prev = [], frames[0], labels[0], frames[0]
    for f, lab in zip(frames[1:], labels[1:]):
        if lab != cur:
            segs.append([int(start), int(prev), cur])
            start, cur = f, lab
        prev = f
    segs.append([int(start), int(frames[-1]), cur])
    return segs


def _export_replay(match_id: str, rally_no: int, a: int, b: int, fps: float,
                   pairs: dict, names: dict | None, rd: pd.DataFrame, out: Path) -> None:
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
    form = {side: _form_segments(seg[seg.side == side]) for side in ("near", "far")}

    _write(out / match_id / "dreplay" / f"r{rally_no}.json", dict(
        fps=fps, f0=int(a), f1=int(b), rally=rally_no, set=1,
        pairs=pairs, names=names, tracks=tracks, form=form))


# ------------------------------------------------------------------ per-match

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

    pairs = _pairs(match_id, m, set_no)
    names = _slot_names(match_id, set_no)
    rally_rows = _rally_table(match_id, windows, max_gap, min_len)
    formation = _formation_summary(match_id, windows, rally_rows)
    players = _player_table(match_id, set_no, max_gap, min_len)
    total_frames = sum(r["frames"] for r in rally_rows)

    meta = dict(
        id=match_id, discipline="doubles", pairs=pairs, names=names,
        tournament=m.get("tournament"), round=m.get("round"),
        date=str(m.get("match_date", "")), youtubeId=_yt_id(m.get("video_url")),
        result=m.get("result"), fps=fps,
        totals=dict(rallies=len(windows), frames=total_frames,
                    rallySecs=round(total_frames / fps, 1)),
        span=dict(f0=int(windows[0][0]), f1=int(windows[-1][1]), set=set_no),
    )
    _write(out / match_id / "doubles.json",
           dict(meta=meta, rallies=rally_rows, formation=formation, players=players))

    rd = roles.roles_df(match_id)
    for i, (a, b) in enumerate(windows, 1):
        _export_replay(match_id, i, a, b, fps, pairs, names, rd, out)

    return dict(id=match_id, discipline="doubles", pairs=pairs,
                tournament=m.get("tournament"), round=m.get("round"),
                date=str(m.get("match_date", "")), youtubeId=_yt_id(m.get("video_url")),
                result=m.get("result"), rallies=len(windows))


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
