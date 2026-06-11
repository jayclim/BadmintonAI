"""Label-free coach view (Phase 2 integration) — the dashboard with NO ShuttleSet.

Glues the CV chain into stroke_df/rally_df-compatible frames so app.py can render
the full coach view for an unlabeled match:

  strokes rows source='pipeline' (segment.py windows: set_no=0, rally_id=rally_key)
+ scoreboard.events()   — score after every rally, per-rally winner row, set bounds
+ scoreboard.side_map() — per-set row <-> near/far (winner serves next)

Build once per match (slow: the OCR scan seeks ~1 frame/s of video):
    PYTHONPATH=src python -m badminton.pipeline <match_id> --label-free --write
    PYTHONPATH=src python -m badminton.labelfree <match_id> --build
The build snapshots everything derived from the OCR to data/labelfree/<id>.json;
the dashboard only reads the snapshot + the DB.

Conventions (deliberate mirrors of the labeled path):
- frame_num here is the VIDEO frame (offset 0); labeled sdf uses ShuttleSet frames
  (video = ss + 6). Consumers take an offset param for this reason.
- player identity: the scoreboard row that wins the match is 'A' — same as
  ShuttleSet's "A = match winner", so config players[1] keeps naming 'A'.
- events trail their rallies (the overlay updates 2-15+ s late), so each event is
  assigned to the LATEST already-ended unassigned rally; rallies left without an
  event (missed OCR reading or a spurious segment) get winner=None and are simply
  excluded from win/loss stats.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from . import analytics, config, court, db

SNAP_DIR = config.REPO_ROOT / "data" / "labelfree"
CLUTCH_FROM = 18          # keep in sync with insights.CLUTCH_FROM
W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M


def snapshot_path(match_id: str):
    return SNAP_DIR / f"{match_id}.json"


def available(match_id: str) -> bool:
    return snapshot_path(match_id).exists()


# ------------------------------------------------------------------ build

def _pipeline_rallies(con, match_id: str) -> pd.DataFrame:
    """One row per label-free pipeline rally (set_no=0 keyed), ordered by start."""
    df = con.execute(
        "SELECT rally_id AS rally_key, MIN(frame_num) AS f0, MAX(frame_num) AS f1,"
        " COUNT(*) AS shots,"
        " MIN_BY(hitter, ball_round) AS serve_side"
        " FROM strokes WHERE match_id=? AND source='pipeline' AND set_no=0"
        " GROUP BY rally_id ORDER BY f0", [match_id]).df()
    return df


def build(match_id: str, verbose: bool = True, rescan: bool = False) -> dict:
    """Run the OCR, align events to pipeline rallies, snapshot to JSON.
    OCR events are reused from an existing snapshot unless rescan=True (the
    video scan is by far the slow part; alignment logic is cheap to iterate)."""
    from . import scoreboard
    con = db.connect(read_only=True)
    ral = _pipeline_rallies(con, match_id)
    con.close()
    if not len(ral):
        raise RuntimeError(
            f"no label-free pipeline strokes for {match_id} — run "
            f"`python -m badminton.pipeline {match_id} --label-free --write` first")

    ev = None
    if not rescan and snapshot_path(match_id).exists():
        cached = json.loads(snapshot_path(match_id).read_text()).get("events")
        if cached:
            ev = pd.DataFrame(cached).rename(columns={})
            if "jump" not in ev.columns:   # older snapshots: reconstruct
                jumps = []
                prev = None
                for e in ev.itertuples():
                    if prev is None or e.new_set or e.set_no != prev.set_no:
                        jumps.append(None)
                    else:
                        jumps.append(max(e.top - prev.top, e.bot - prev.bot))
                    prev = e
                ev["jump"] = jumps
    if ev is None:
        ev = scoreboard.events(match_id)
    if not len(ev):
        raise RuntimeError("score OCR produced no events for this match")

    # --- assign each score event to the latest already-ended unassigned rally
    assigned: dict[int, dict] = {}        # rally index -> event row
    unassigned = list(ral.index)
    for _, e in ev.iterrows():
        cands = [i for i in unassigned if ral.loc[i, "f1"] <= int(e["frame"])]
        if not cands:
            continue
        i = cands[-1]
        assigned[i] = e
        # earlier unmatched rallies will never get an older event — drop them
        unassigned = [j for j in unassigned if j not in cands]

    # --- which row wins the match -> that row is 'A' (ShuttleSet convention)
    set_final: dict[int, tuple[int, int]] = {}
    for _, e in ev.iterrows():
        set_final[int(e["set_no"])] = (int(e["top"]), int(e["bot"]))
    top_sets = sum(t > b for t, b in set_final.values())
    bot_sets = sum(b > t for t, b in set_final.values())
    if top_sets == bot_sets:              # OCR missed a set end — last set decides
        t, b = set_final[max(set_final)]
        row_a = "top" if t > b else "bot"
    else:
        row_a = "top" if top_sets > bot_sets else "bot"

    all_sets = sorted(set_final)

    # --- per-rally rows: set, scores, winner
    rows = []
    for i in ral.index:
        e = assigned.get(i)
        rows.append(dict(
            rally_key=int(ral.loc[i, "rally_key"]),
            f0=int(ral.loc[i, "f0"]), f1=int(ral.loc[i, "f1"]),
            set_no=int(e["set_no"]) if e is not None else None,
            winner=(None if e is None or e["winner"] is None
                    else ("A" if e["winner"] == row_a else "B")),
            score_a=int(e["top"] if row_a == "top" else e["bot"]) if e is not None else None,
            score_b=int(e["bot"] if row_a == "top" else e["top"]) if e is not None else None,
        ))
    # rallies without an event inherit the set of the next assigned rally
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["set_no"] is None:
            rows[i]["set_no"] = rows[i + 1]["set_no"] if i + 1 < len(rows) \
                else max(set_final)
    # sequential display rally_id per set + forward-filled scores
    counter: dict[int, int] = {}
    prev = {sn: (0, 0) for sn in all_sets + [rows[0]["set_no"]]}
    for r in rows:
        sn = r["set_no"]
        counter[sn] = counter.get(sn, 0) + 1
        r["rally_id"] = counter[sn]
        pa, pb = prev.get(sn, (0, 0))
        r["prev_a"], r["prev_b"] = pa, pb
        if r["score_a"] is None:
            r["score_a"], r["score_b"] = pa, pb
        prev[sn] = (r["score_a"], r["score_b"])

    # --- side of player A per RALLY ("winner serves next" votes, flip-aware).
    # Each winner event constrains which side the winning ROW serves the NEXT
    # rally from. Per set we fit top's side as a step function with at most ONE
    # changepoint — the deciding-game end change when the leader reaches 11.
    votes: dict[int, list[tuple[int, str]]] = {}    # set -> [(rally_id, top_side)]
    for i, e in assigned.items():
        if e["winner"] is None or e.get("jump") != 1:
            continue
        j = i + 1                                    # the rally served next
        if j >= len(rows) or rows[j]["set_no"] != rows[i]["set_no"]:
            continue                                 # set point — next serve is next set
        serve_side = ral.loc[j, "serve_side"]
        if serve_side not in ("near", "far"):
            continue
        top_side = serve_side if e["winner"] == "top" else \
            ("far" if serve_side == "near" else "near")
        votes.setdefault(rows[j]["set_no"], []).append((rows[j]["rally_id"], top_side))

    flipped = {"near": "far", "far": "near"}
    top_fn: dict[int, tuple[str, int | None]] = {}   # set -> (start side, flip rally_id|None)
    sets_in_rows = sorted({r["set_no"] for r in rows})
    for sn in sets_in_rows:
        vs = sorted(votes.get(sn, []))
        if not vs:
            continue
        # The end change at 11 exists ONLY in a deciding game — candidates are
        # restricted to set 3+ (a false flip from vote noise corrupts half a set).
        cands: list[int] = []
        if sn >= 3 and sn == sets_in_rows[-1]:
            cands = [r["rally_id"] for r in rows if r["set_no"] == sn
                     and max(r["prev_a"], r["prev_b"]) == 11]
            if not cands:
                cands = [r["rally_id"] for r in rows if r["set_no"] == sn
                         and max(r["prev_a"], r["prev_b"]) in (10, 12)]
        best = None                                  # (score, has_flip, side, k)
        for side in ("near", "far"):
            score0 = sum((side == s) for _, s in vs)
            if best is None or score0 > best[0]:
                best = (score0, False, side, None)
            for k in cands:
                score = sum(((side if rid < k else flipped[side]) == s) for rid, s in vs)
                if score >= (best[0] + 2 if not best[1] else best[0] + 1):
                    best = (score, True, side, k)
        top_fn[sn] = (best[2], best[3] if best[1] else None)
    # vote-less sets: players swap ends between sets — alternate from a neighbor
    for idx, sn in enumerate(sets_in_rows):
        if sn in top_fn:
            continue
        for d in (-1, 1):
            nb = sets_in_rows[idx + d] if 0 <= idx + d < len(sets_in_rows) else None
            if nb in top_fn:
                start, k = top_fn[nb]
                end_side = flipped[start] if k is not None else start
                top_fn[sn] = (flipped[end_side] if d == -1 else flipped[start], None)
                break

    for r in rows:
        fn = top_fn.get(r["set_no"])
        if fn is None:
            r["side_a"] = None
            continue
        start, k = fn
        top_side = start if (k is None or r["rally_id"] < k) else flipped[start]
        r["side_a"] = top_side if row_a == "top" else flipped[top_side]

    # per-set summary (majority) kept for set-level consumers + the verbose print
    side_a: dict[int, str] = {}
    for sn in sets_in_rows:
        ss = [r["side_a"] for r in rows if r["set_no"] == sn and r["side_a"]]
        if ss:
            side_a[sn] = max(set(ss), key=ss.count)

    snap = dict(match_id=match_id, row_a=row_a,
                side_a={str(sn): s for sn, s in side_a.items()},
                flips={str(sn): k for sn, (_, k) in top_fn.items() if k is not None},
                rallies=rows,
                # raw OCR readings, kept for the dashboard's OCR demo + fast rebuilds
                events=[dict(frame=int(e["frame"]), set_no=int(e["set_no"]),
                             top=int(e["top"]), bot=int(e["bot"]),
                             winner=e["winner"], new_set=bool(e["new_set"]),
                             jump=None if pd.isna(e.get("jump")) else int(e["jump"]))
                        for _, e in ev.iterrows()])
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path(match_id).write_text(json.dumps(snap, indent=1))
    if verbose:
        n_w = sum(r["winner"] is not None for r in rows)
        finals = {sn: max((r["score_a"], r["score_b"]) for r in rows
                          if r["set_no"] == sn) for sn in sorted({r["set_no"] for r in rows})}
        print(f"{match_id}: {len(rows)} rallies, {len(ev)} OCR events, "
              f"{n_w} rally winners assigned; row_a={row_a}; side_a={side_a}")
        print(f"set finals (A-B): {finals}")
        print(f"wrote {snapshot_path(match_id)}")
    return snap


def _load(match_id: str) -> dict:
    return json.loads(snapshot_path(match_id).read_text())


def side_map(match_id: str) -> dict:
    """(set_no, 'A'|'B') -> 'near'|'far', from the snapshot."""
    snap = _load(match_id)
    out = {}
    for sn, side in snap["side_a"].items():
        out[(int(sn), "A")] = side
        out[(int(sn), "B")] = "far" if side == "near" else "near"
    return out


def rally_side_map(match_id: str) -> dict:
    """(set_no, rally_id) -> {'A': side, 'B': side} — rally-level, flip-aware
    (the deciding-game end change at 11 is encoded in the snapshot)."""
    out = {}
    for r in _load(match_id)["rallies"]:
        sa = r.get("side_a")
        if sa:
            out[(int(r["set_no"]), int(r["rally_id"]))] = \
                {"A": sa, "B": "far" if sa == "near" else "near"}
    return out


# ------------------------------------------------------------------ data frames

def stroke_df(match_id: str) -> pd.DataFrame:
    """sdf-compatible frame from pipeline strokes (coords already court metres).
    frame_num is the VIDEO frame; hitter/receiver are mapped to 'A'/'B'."""
    snap = _load(match_id)
    key = {r["rally_key"]: r for r in snap["rallies"]}

    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT rally_id AS rally_key, ball_round, frame_num, hitter AS hitter_side,"
        " receiver AS recv_side, shot_type, shot_type_conf,"
        " hitter_x AS hitter_mx, hitter_y AS hitter_my,"
        " receiver_x AS recv_mx, receiver_y AS recv_my,"
        " landing_x AS land_mx, landing_y AS land_my, hit_x, hit_y"
        " FROM strokes WHERE match_id=? AND source='pipeline' AND set_no=0"
        " ORDER BY frame_num", [match_id]).df()
    con.close()

    df["set_no"] = df["rally_key"].map(lambda k: key[k]["set_no"])
    df["rally_id"] = df["rally_key"].map(lambda k: key[k]["rally_id"])
    df["score_a"] = df["rally_key"].map(lambda k: key[k]["score_a"])
    df["score_b"] = df["rally_key"].map(lambda k: key[k]["score_b"])

    # hitter/receiver -> 'A'/'B' via the per-RALLY side (flip-aware for deciding sets)
    side_a_of = {r["rally_key"]: r.get("side_a") for r in snap["rallies"]}
    def to_player(rk, side):
        sa = side_a_of.get(int(rk))
        if sa is None:
            return "A" if side == "near" else "B"
        return "A" if side == sa else "B"
    df["hitter"] = [to_player(rk, s) for rk, s in zip(df["rally_key"], df["hitter_side"])]
    df["receiver"] = [to_player(rk, s) for rk, s in zip(df["rally_key"], df["recv_side"])]

    df["shot"] = df["shot_type"].fillna("—")
    # labeled-sdf columns that have no label-free source yet
    df["shot_type_raw"] = None
    df["aroundhead"] = False
    df["backhand"] = False
    df["hit_height"] = np.nan
    df["landing_area"] = np.nan
    df["lose_reason"] = None
    df["win_reason"] = None
    df["getpoint_player"] = None
    df["time"] = np.nan
    # normalized orientation: hitter at the bottom (the side IS known per stroke)
    flip = (df["hitter_side"] == "far").to_numpy()
    for mx, my, nx, ny in [("hitter_mx", "hitter_my", "hitter_nx", "hitter_ny"),
                           ("recv_mx", "recv_my", "recv_nx", "recv_ny"),
                           ("land_mx", "land_my", "land_nx", "land_ny")]:
        df[nx] = np.where(flip, W - df[mx], df[mx])
        df[ny] = np.where(flip, L - df[my], df[my])
    return df.sort_values(["set_no", "rally_id", "ball_round"]).reset_index(drop=True)


def _end_category(end_row, winner) -> str:
    """Winner/Net/Out/Error from who hit last + the CV landing point."""
    if winner is None:
        return "—"
    if end_row["hitter"] == winner:
        return "Winner"
    lx, ly = end_row["land_mx"], end_row["land_my"]
    if pd.notna(lx):
        if not (0 <= lx <= W and 0 <= ly <= L):
            return "Out"
        hy = end_row["hitter_my"]
        if pd.notna(hy) and ((hy < court.NET_Y_M) == (ly < court.NET_Y_M)):
            return "Net"          # landed on the hitter's own side
    return "Error"


def rally_df(match_id: str, sdf: pd.DataFrame | None = None) -> pd.DataFrame:
    """rdf-compatible frame; winner/scores come from the OCR snapshot."""
    if sdf is None:
        sdf = stroke_df(match_id)
    snap = _load(match_id)
    key = {r["rally_key"]: r for r in snap["rallies"]}
    fps = float(config.get_match(match_id)["fps"])
    rows = []
    for rk, g in sdf.groupby("rally_key", sort=False):
        g = g.sort_values("ball_round")
        meta = key[int(rk)]
        first, end = g.iloc[0], g.iloc[-1]
        winner = meta["winner"]
        cat = _end_category(end, winner)
        f0, f1 = int(g["frame_num"].min()), int(g["frame_num"].max())
        shots = g["shot"].tolist()
        rows.append(dict(
            set_no=int(meta["set_no"]), rally_id=int(meta["rally_id"]),
            rally_key=int(rk), f0=f0, f1=f1, shots=len(g),
            duration_s=round((f1 - f0) / fps, 1),
            server=first["hitter"],
            serve_type=first["shot"] if first["ball_round"] == 1 else None,
            end_hitter=end["hitter"], end_shot=end["shot"],
            end_round=int(end["ball_round"]), end_backhand=False,
            lose_reason=None, winner=winner, category=cat,
            score_a=meta["score_a"], score_b=meta["score_b"],
            prev_a=meta["prev_a"], prev_b=meta["prev_b"],
            clutch=max(meta["prev_a"], meta["prev_b"]) >= CLUTCH_FROM,
            bucket="short (≤4)" if len(g) <= 4 else ("mid (5–9)" if len(g) <= 9 else "long (10+)"),
            pat2=" → ".join(shots[-2:]) if len(shots) >= 2 else None,
            pat3=" → ".join(shots[-3:]) if len(shots) >= 3 else None,
        ))
    df = pd.DataFrame(rows).sort_values(["set_no", "rally_id"]).reset_index(drop=True)
    return df


# ------------------------------------------------------------------ pressure / movement

def pressure_strokes(sdf: pd.DataFrame, fps: float) -> list[dict]:
    """tactics.pressure_strokes equivalent from label-free metre coords:
    required speed = dist(my contact position, my position at opponent's hit) / dt."""
    out = []
    for _, g in sdf.groupby(["set_no", "rally_id"], sort=False):
        g = g.sort_values("ball_round")
        prev = None
        for _, c in g.iterrows():
            if prev is not None:
                dt = (c["frame_num"] - prev["frame_num"]) / fps
                if dt > 0 and pd.notna(c["hitter_mx"]) and pd.notna(prev["recv_mx"]):
                    spd = float(np.hypot(c["hitter_mx"] - prev["recv_mx"],
                                         c["hitter_my"] - prev["recv_my"]) / dt)
                    out.append(dict(set=int(c["set_no"]), rally=int(c["rally_id"]),
                                    shot_no=int(c["ball_round"]), hitter=c["hitter"],
                                    prev_hitter=prev["hitter"], req_speed=spd,
                                    low_contact=False, prev_shot=prev["shot"]))
            prev = c
    return out


def pressure_summary(sdf: pd.DataFrame, fps: float) -> dict:
    s = pressure_strokes(sdf, fps)
    faced = {"A": [], "B": []}
    applied = {"A": [], "B": []}
    for x in s:
        faced[x["hitter"]].append(x["req_speed"])
        applied[x["prev_hitter"]].append(x["req_speed"])
    return {p: dict(faced=round(float(np.mean(faced[p])), 2) if faced[p] else 0.0,
                    applied=round(float(np.mean(applied[p])), 2) if applied[p] else 0.0,
                    n=len(faced[p])) for p in ("A", "B")}


def pressure_by_shot(sdf: pd.DataFrame, fps: float, min_n: int = 5) -> dict:
    d: dict[str, list] = {}
    for x in pressure_strokes(sdf, fps):
        d.setdefault(x["prev_shot"], []).append(x["req_speed"])
    return {k: round(float(np.mean(v)), 2) for k, v in d.items() if len(v) >= min_n}


def rally_detail(sdf: pd.DataFrame, fps: float, set_no: int, rally_id: int) -> list[dict]:
    """tactics.rally_detail equivalent (no hit-height/zone labels)."""
    g = sdf[(sdf["set_no"] == set_no) & (sdf["rally_id"] == rally_id)] \
        .sort_values("ball_round")
    out, prev = [], None
    for _, c in g.iterrows():
        req = None
        if prev is not None and pd.notna(c["hitter_mx"]) and pd.notna(prev["recv_mx"]):
            dt = (c["frame_num"] - prev["frame_num"]) / fps
            if dt > 0:
                req = round(float(np.hypot(c["hitter_mx"] - prev["recv_mx"],
                                           c["hitter_my"] - prev["recv_my"]) / dt), 1)
        out.append(dict(shot=int(c["ball_round"]), hitter=c["hitter"], type=c["shot"],
                        low_contact=False, zone=None, pressure_mps=req))
        prev = c
    return out


def movement_by_player(match_id: str, rdf: pd.DataFrame, rmap: dict) -> dict:
    """insights.movement_by_player with label-free rally windows (video frames,
    offset 0) and the OCR-derived per-RALLY side map (rally_side_map)."""
    fps = float(config.get_match(match_id)["fps"])
    dist = {"A": 0.0, "B": 0.0}
    secs = {"A": 0.0, "B": 0.0}
    pos = {"A": [], "B": []}
    for r in rdf.itertuples():
        series = analytics.player_series(match_id, int(r.f0), int(r.f1))
        rs = rmap.get((int(r.set_no), int(r.rally_id)), {})
        for side, arr in series.items():
            who = next((p for p in ("A", "B") if rs.get(p) == side), None)
            if who is None or len(arr) < 3:
                continue
            mt = analytics.player_metrics(arr, fps)
            dist[who] += mt["distance_m"]
            secs[who] += mt["duration_s"]
            P = arr[:, 1:3].copy()
            if side == "far":
                P[:, 0], P[:, 1] = W - P[:, 0], L - P[:, 1]
            pos[who].append(P)

    out = {}
    for p in ("A", "B"):
        if not pos[p]:
            continue
        P = np.vstack(pos[p])
        x, y = P[:, 0], P[:, 1]
        hl = court.NET_Y_M
        d_net = np.abs(y - hl)
        front = round(float(np.mean(d_net < hl / 3) * 100))
        back = round(float(np.mean(d_net > 2 * hl / 3) * 100))
        out[p] = dict(distance_m=round(dist[p]), rally_time_s=round(secs[p]),
                      mean_speed=round(dist[p] / secs[p], 2) if secs[p] else 0.0,
                      coverage_m2=round(float(np.pi * 2 * x.std() * 2 * y.std()), 1),
                      recovery_m=round(float(np.hypot(x - W / 2, y - hl / 2).mean()), 2),
                      front_pct=front, mid_pct=100 - front - back, back_pct=back,
                      positions=P)
    return out


# ------------------------------------------------------------------ validation

def validate(match_id: str) -> None:
    """Compare label-free winners / set scores / side map against ShuttleSet
    (only possible on a labeled match — sanity check of the whole chain)."""
    from . import insights
    sdf_lab = insights.stroke_df(match_id)
    rdf_lab = insights.rally_df(match_id, sdf_lab)
    rdf_lf = rally_df(match_id)

    lab_final = rdf_lab.groupby("set_no")[["score_a", "score_b"]].max()
    lf_final = rdf_lf.groupby("set_no")[["score_a", "score_b"]].max()
    print("set finals  labels:", lab_final.to_dict("index"))
    print("set finals  label-free:", lf_final.to_dict("index"))

    # rally winners: align by order within set (keys don't correspond)
    ok = tot = 0
    for sn in sorted(rdf_lab["set_no"].unique()):
        a = rdf_lab[rdf_lab["set_no"] == sn]["winner"].tolist()
        b = rdf_lf[rdf_lf["set_no"] == sn]["winner"].tolist()
        for x, y in zip(a, b):
            if x is not None and y is not None:
                tot += 1
                ok += x == y
    print(f"rally winners (order-aligned): {ok}/{tot} agree "
          f"({ok / tot:.1%})" if tot else "no comparable winners")

    lab_sm = insights.side_map_from(sdf_lab)
    lf_sm = side_map(match_id)
    agree = [lab_sm.get(k) == v for k, v in lf_sm.items() if k in lab_sm]
    print(f"side map (per set): {sum(agree)}/{len(agree)} entries agree")

    # per-rally sides (the 3-set-critical granularity), order-aligned within set
    lab_rm = insights.rally_side_map(sdf_lab)
    lf_rm = rally_side_map(match_id)
    ok = tot = 0
    for sn in sorted(rdf_lab["set_no"].unique()):
        la = [lab_rm.get((sn, int(r))) for r in
              rdf_lab[rdf_lab["set_no"] == sn]["rally_id"]]
        lf = [lf_rm.get((sn, int(r))) for r in
              rdf_lf[rdf_lf["set_no"] == sn]["rally_id"]]
        for x, y in zip(la, lf):
            if x and y:
                tot += 1
                ok += x["A"] == y["A"]
    print(f"per-rally sides (order-aligned): {ok}/{tot} agree"
          + (f" ({ok / tot:.1%})" if tot else ""))
    snap = _load(match_id)
    if snap.get("flips"):
        print(f"deciding-set end-change detected at rally: {snap['flips']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Label-free coach-view snapshot")
    ap.add_argument("match_id")
    ap.add_argument("--build", action="store_true",
                    help="run score OCR + alignment, write the snapshot")
    ap.add_argument("--validate", action="store_true",
                    help="compare against ShuttleSet labels (labeled matches only)")
    args = ap.parse_args()
    if args.build:
        build(args.match_id)
    if args.validate:
        validate(args.match_id)
    if not args.build and not args.validate:
        snap = _load(args.match_id)
        print(f"{args.match_id}: {len(snap['rallies'])} rallies, row_a={snap['row_a']}, "
              f"side_a={snap['side_a']}")
