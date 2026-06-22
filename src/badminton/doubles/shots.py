"""Doubles stroke-derived tactics, keyed per fixed team A/B (ISOLATED, Phase 2).

Unblocked by `doubles/strokes.py` — the first doubles features that need real shot
data (CLAUDE.md said not to fake these until 4-slot hit attribution was real; it now is).

Two views the formation layer can't express:
  - shot_mix: what each team hits (shot-type distribution), per set and overall;
  - response_matrix: given the opponent's shot X, what the team answers with (X → Y),
    the doubles analogue of the singles "vs X he plays Y" matrix.

Team-keying is the whole subtlety (see sets.py): the pairs SWAP ENDS between games, so a
court side ('near'/'far') is NOT a stable team. `sets.analyze` maps each rally's near/far
court to the fixed pair A/B; every stroke is attributed to A or B through that map, so the
numbers follow a pair across the end-swaps instead of mixing the two teams.

Shot strings stay canonical here; the lift/serve/push/block display renames live in
`insights.SHOT_DISPLAY` and are applied only at the presentation boundary (web exporter).

CLI:  PYTHONPATH=src python -m badminton.doubles.shots <match_id> [--set N]
"""

from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd

from .. import db
from . import segment, sets

SIDE = {"near": "near", "near2": "near", "far": "far", "far2": "far"}


def team_strokes(match_id: str) -> pd.DataFrame:
    """Pipeline strokes for the match with fixed team (A/B) + set attached.

    rally_id is the 1-based index into segment.rally_windows — the SAME enumeration
    sets.analyze aligns to — so the rally→(set, side→pair) map joins by (rally_id - 1)."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT rally_id, ball_round, hitter, receiver, shot_type, shot_type_conf "
        "FROM strokes WHERE match_id=? AND source='pipeline' "
        "ORDER BY rally_id, ball_round", [match_id]).df()
    con.close()
    if df.empty:
        return df
    windows = segment.rally_windows(match_id)
    rs = sets.analyze(match_id, windows=windows)        # 1:1 with windows
    side = df["hitter"].map(SIDE)
    df["side"] = side
    df["set"] = df["rally_id"].map(lambda r: rs[r - 1]["set"] if 1 <= r <= len(rs) else None)
    df["team"] = [rs[r - 1]["near_pair" if s == "near" else "far_pair"]
                  if 1 <= r <= len(rs) else None
                  for r, s in zip(df["rally_id"], side)]
    return df


def shot_mix(match_id: str, ts: pd.DataFrame | None = None) -> dict:
    """{team: {shot_type: count}} over all sets. Serves included — they're real strokes."""
    ts = team_strokes(match_id) if ts is None else ts
    return {t: Counter(g["shot_type"]) for t, g in ts.groupby("team") if t}


def response_matrix(match_id: str, ts: pd.DataFrame | None = None) -> dict:
    """{team: {opponent_shot_X: {team_shot_Y: count}}}: how a team answers each shot.

    A response is a stroke whose immediately preceding stroke (same rally, ball_round-1)
    was hit by the OTHER team. Cross-rally and same-team consecutive pairs are skipped."""
    ts = team_strokes(match_id) if ts is None else ts
    out: dict = {}
    for _, g in ts.sort_values(["rally_id", "ball_round"]).groupby("rally_id"):
        rows = list(g.itertuples())
        for prev, cur in zip(rows, rows[1:]):
            if cur.ball_round != prev.ball_round + 1 or cur.team == prev.team \
                    or not cur.team or not prev.team:
                continue
            out.setdefault(cur.team, {}).setdefault(prev.shot_type, Counter())[cur.shot_type] += 1
    return out


def _top(counter: Counter, n: int = 3) -> str:
    tot = sum(counter.values()) or 1
    return ", ".join(f"{k} {100 * v // tot}%" for k, v in counter.most_common(n))


def main() -> None:
    ap = argparse.ArgumentParser(description="Doubles stroke-derived tactics (team A/B)")
    ap.add_argument("match_id", nargs="?", default="wtf_2024_md_sf")
    ap.add_argument("--set", type=int, default=None, help="restrict to one set")
    args = ap.parse_args()

    ts = team_strokes(args.match_id)
    if ts.empty:
        print("no pipeline strokes — run doubles.strokes --write first")
        return
    if args.set is not None:
        ts = ts[ts["set"] == args.set]
    from ..insights import SHOT_DISPLAY
    disp = lambda s: SHOT_DISPLAY.get(s, s)

    print(f"=== shot mix per team{'' if args.set is None else f' (set {args.set})'} ===")
    for team, c in sorted(shot_mix(args.match_id, ts).items()):
        tot = sum(c.values())
        mix = ", ".join(f"{disp(k)} {100 * v // tot}%" for k, v in c.most_common(6))
        print(f"  Team {team} ({tot} shots): {mix}")

    print("\n=== response matrix (vs opponent's shot → team answers) ===")
    for team, mat in sorted(response_matrix(args.match_id, ts).items()):
        print(f"  Team {team}:")
        for opp, answers in sorted(mat.items(), key=lambda kv: -sum(kv[1].values()))[:5]:
            print(f"    vs {disp(opp):14s} -> {_top(Counter({disp(k): v for k, v in answers.items()}))}")


def demo() -> None:
    """Self-check: every stroke maps to a team, both teams appear, totals reconcile."""
    ts = team_strokes("wtf_2024_md_sf")
    assert not ts.empty, "no strokes — run doubles.strokes --write"
    assert ts["team"].isin(["A", "B"]).all(), "some strokes unmapped to a team"
    mix = shot_mix("wtf_2024_md_sf", ts)
    assert set(mix) == {"A", "B"}, f"expected teams A,B got {set(mix)}"
    assert sum(sum(c.values()) for c in mix.values()) == len(ts), "shot_mix lost strokes"
    rm = response_matrix("wtf_2024_md_sf", ts)
    assert rm and all(rm.values()), "empty response matrix"
    print(f"[demo] {len(ts)} strokes, teams {dict((t, int((ts.team == t).sum())) for t in 'AB')}, "
          f"{ts['set'].nunique()} sets — OK")


if __name__ == "__main__":
    main()
