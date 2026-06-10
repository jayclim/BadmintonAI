"""Import ShuttleSet22 set CSVs into the `strokes` table. Phase 0 validation source.

Verified facts (against the Loh Kean Yew vs Lakshya Sen India Open 2022 final):
- Coordinates are RAW BROADCAST PIXELS — no homography is shipped. 30 fps.
- Each stroke has 3 spatial points: hitter feet (player_location), shuttle contact
  (hit), shuttle landing (landing); plus opponent feet (opponent_location).
- `type` is Chinese; collapsed to 10 canonical English classes via the official
  two-step mapping from ShuttleSet22/preprocess_data.py.
- `player` is A/B (A = match winner). We keep A/B here; resolve_near_far() relabels
  to near/far later using the calibrated homography.

Usage:
    python -m badminton.shuttleset india_open_2022_final
"""

from __future__ import annotations

import argparse
import csv
import zlib
from pathlib import Path

from . import config, db

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- official ShuttleSet22 shot-type mapping (preprocess_data.py) -------------------
_COMBINE = {
    "切球": "切球", "過度切球": "切球", "點扣": "殺球", "殺球": "殺球",
    "平球": "平球", "後場抽平球": "平球", "擋小球": "接殺防守", "防守回挑": "接殺防守",
    "防守回抽": "接殺防守", "放小球": "網前球", "勾球": "網前球",
    "推球": "推撲球", "撲球": "推撲球",
}
_CN_EN = {
    "發短球": "short service", "長球": "clear", "推撲球": "push/rush", "殺球": "smash",
    "接殺防守": "defensive shot", "平球": "drive", "網前球": "net shot",
    "挑球": "lob", "切球": "drop", "發長球": "long service",
}


def canonical_shot_type(cn: str | None) -> str | None:
    if not cn:
        return None
    return _CN_EN.get(_COMBINE.get(cn, cn))  # None for 未知球種 / 小平球 etc.


def _f(v: str | None) -> float | None:
    return float(v) if v not in (None, "") else None


def _i(v: str | None) -> int | None:
    return int(float(v)) if v not in (None, "") else None


def _flag(v: str | None) -> bool:
    return v not in (None, "")  # aroundhead/backhand hold '1.0' when true, '' otherwise


def _rows(match_id: str, set_no: int, csv_path: Path, base_id: int):
    for i, r in enumerate(csv.DictReader(csv_path.open(encoding="utf-8"))):
        hitter = r["player"]                      # 'A' | 'B'
        receiver = "B" if hitter == "A" else "A"
        yield {
            "stroke_id": base_id + set_no * 100_000 + i,
            "match_id": match_id,
            "set_no": set_no,
            "rally_id": _i(r["rally"]),
            "ball_round": _i(r["ball_round"]),
            "time": r["time"] or None,
            "frame_num": _i(r["frame_num"]),
            "roundscore_near": _i(r["roundscore_A"]),
            "roundscore_far": _i(r["roundscore_B"]),
            "hitter": hitter,
            "receiver": receiver,
            "server": r["server"] or None,
            "shot_type": canonical_shot_type(r["type"]),
            "shot_type_raw": r["type"] or None,
            "aroundhead": _flag(r["aroundhead"]),
            "backhand": _flag(r["backhand"]),
            "coord_space": "pixel",
            "hitter_x": _f(r["player_location_x"]), "hitter_y": _f(r["player_location_y"]),
            "hitter_area": _i(r["player_location_area"]),
            "receiver_x": _f(r["opponent_location_x"]), "receiver_y": _f(r["opponent_location_y"]),
            "receiver_area": _i(r["opponent_location_area"]),
            "hit_x": _f(r["hit_x"]), "hit_y": _f(r["hit_y"]),
            "hit_area": _i(r["hit_area"]), "hit_height": _f(r["hit_height"]),
            "landing_x": _f(r["landing_x"]), "landing_y": _f(r["landing_y"]),
            "landing_area": _i(r["landing_area"]), "landing_height": _f(r["landing_height"]),
            "lose_reason": r["lose_reason"] or None,
            "win_reason": r["win_reason"] or None,
            "getpoint_player": r["getpoint_player"] or None,
            "flaw": r["flaw"] or None,
            "db": _i(r["db"]),
            "source": "shuttleset",
        }


def import_match(match_id: str) -> int:
    m = config.get_match(match_id)
    ss_dir = REPO_ROOT / "data" / "shuttleset" / match_id
    sets = sorted(ss_dir.glob("set*.csv"))
    if not sets:
        raise SystemExit(f"no set*.csv under {ss_dir}")

    base_id = (zlib.crc32(match_id.encode()) % 1000) * 10_000_000
    records: list[dict] = []
    for path in sets:
        set_no = int(path.stem.replace("set", ""))
        records.extend(_rows(match_id, set_no, path, base_id))

    con = db.connect()
    # ensure the match row exists, then refresh strokes for this match (idempotent)
    con.execute(
        "INSERT INTO matches (match_id, discipline, tournament, fps, camera_view, source) "
        "VALUES (?, ?, ?, ?, 'broadcast', 'shuttleset') ON CONFLICT (match_id) DO NOTHING",
        [match_id, m.get("discipline"), m.get("tournament"), m.get("fps")],
    )
    con.execute("DELETE FROM strokes WHERE match_id = ? AND source = 'shuttleset'", [match_id])

    cols = list(records[0])
    con.executemany(
        f"INSERT INTO strokes ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [[rec[c] for c in cols] for rec in records],
    )
    con.close()
    return len(records)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    args = ap.parse_args()
    n = import_match(args.match_id)
    print(f"imported {n} strokes for {args.match_id}")


if __name__ == "__main__":
    main()
