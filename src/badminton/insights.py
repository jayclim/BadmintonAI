"""Coach-facing derived datasets + rule-based auto insights (no Streamlit here).

Built on the ShuttleSet stroke labels (whole match) + the validated CV tracks.
The dashboard (app.py) only renders what this module computes.

Conventions
- ShuttleSet players are 'A'/'B' with A = the match winner; the dashboard maps
  these to display names. Everything in this module stays in A/B.
- Players SWAP COURT ENDS between sets. side_map() resolves (set_no, player) ->
  'near'/'far' from the labeled hitter positions, so per-frame track data
  (keyed near/far) can be attributed to the right PLAYER. Aggregating raw
  near/far across sets mixes the two players — don't.
- *_mx/_my columns are court METRES (homography-converted from ShuttleSet px).
  *_nx/_ny are NORMALIZED metres: flipped per set so the acting player is
  always on the near half (bottom), comparable across sets and players.
- roundscore_near/far columns hold ShuttleSet roundscore_A/B (importer reuses
  the columns); they are the score AFTER the rally. Rally winner is derived
  from the score delta (more complete than getpoint_player).
- Limitation: a deciding-set mid-game end change (at 11) is not modeled; the
  side map is per set. Fine for sets 1-2; revisit for 3-set matches.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import analytics, config, court, db, tactics

SS_OFFSET = 6                # video_frame = shuttleset_frame + 6 (validated)
FORCED_SPEED = 2.5           # m/s required speed above which an error counts as "forced"
CLUTCH_FROM = 18             # a rally is "clutch" once either player has >= this score

# rally-ending error classification from ShuttleSet lose_reason (Chinese)
_END_CAT = {"出界": "Out", "掛網": "Net", "未過網": "Net", "落點判斷失誤": "Misjudged"}

# Canonical class strings as stored in the DB (ShuttleSet import + pipeline rows
# + shotclass.CLASSES all key off these — do NOT rename here).
SHOT_ORDER = ["short service", "long service", "clear", "drive", "drop", "lob",
              "net shot", "smash", "push/rush", "defensive shot"]

# Coach-facing display names (modern terminology), applied at presentation
# boundaries (export_web) — internal data keeps the canonical strings above.
SHOT_DISPLAY = {"short service": "short serve", "long service": "high serve",
                "lob": "lift", "push/rush": "push", "defensive shot": "block"}

# prose variant (plural forms too) + helpers for the presentation boundaries
SHOT_DISPLAY_PROSE = {**SHOT_DISPLAY,
                      "lobs": "lifts", "defensive shots": "blocks",
                      "push/rushes": "pushes",
                      "short services": "short serves", "long services": "high serves"}
_DISP_RE = re.compile(r"\b(?:%s)\b" % "|".join(
    re.escape(k) for k in sorted(SHOT_DISPLAY_PROSE, key=len, reverse=True)))


def shot_display_text(s: str) -> str:
    """Canonical class names -> display terms inside a sentence (word-boundaried,
    so e.g. 'global' or 'service points' are untouched)."""
    return _DISP_RE.sub(lambda m: SHOT_DISPLAY_PROSE[m.group(0)], s)


def shot_display_deep(o, rename_keys: bool = False):
    """shot_display_text over every string in a nested structure; rename_keys also
    rewrites dict keys (LLM dossier — shot names appear as keys there)."""
    if isinstance(o, dict):
        return {(shot_display_text(k) if rename_keys and isinstance(k, str) else k):
                shot_display_deep(v, rename_keys) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [shot_display_deep(v, rename_keys) for v in o]
    return shot_display_text(o) if isinstance(o, str) else o


def other(p: str) -> str:
    return "B" if p == "A" else "A"


def _H_fps(match_id):
    m = config.get_match(match_id)
    H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
    return H, float(m["fps"])


def _px_to_m(df: pd.DataFrame, H, pairs) -> None:
    """Convert pixel coord column pairs to court-metre columns in place."""
    for cx, cy, mx, my in pairs:
        xy = df[[cx, cy]].to_numpy(dtype=np.float64)
        out = np.full_like(xy, np.nan)
        ok = ~np.isnan(xy).any(axis=1)
        if ok.any():
            out[ok] = court.image_to_court(xy[ok].astype(np.float32), H)
        df[mx], df[my] = out[:, 0], out[:, 1]


def stroke_df(match_id: str) -> pd.DataFrame:
    """One row per labeled stroke, with court-metre and normalized coordinates."""
    H, _ = _H_fps(match_id)
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT set_no, rally_id, ball_round, frame_num, time, hitter, receiver, server,"
        " shot_type, shot_type_raw, aroundhead, backhand, hit_height, landing_area,"
        " hitter_x, hitter_y, receiver_x, receiver_y, hit_x, hit_y, landing_x, landing_y,"
        " roundscore_near AS score_a, roundscore_far AS score_b,"
        " lose_reason, win_reason, getpoint_player"
        " FROM strokes WHERE match_id=? AND source='shuttleset'"
        " ORDER BY set_no, rally_id, ball_round", [match_id]).df()
    con.close()

    df["shot"] = df["shot_type"].fillna(df["shot_type_raw"]).fillna("—")
    _px_to_m(df, H, [("hitter_x", "hitter_y", "hitter_mx", "hitter_my"),
                     ("receiver_x", "receiver_y", "recv_mx", "recv_my"),
                     ("landing_x", "landing_y", "land_mx", "land_my")])

    # normalized orientation: flip rows where the HITTER was on the far half that set,
    # so every stroke is "hitter at the bottom, hitting up"
    smap = side_map_from(df)
    flip = df.apply(lambda r: smap.get((r.set_no, r.hitter)) == "far", axis=1).to_numpy()
    W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M
    for mx, my, nx, ny in [("hitter_mx", "hitter_my", "hitter_nx", "hitter_ny"),
                           ("recv_mx", "recv_my", "recv_nx", "recv_ny"),
                           ("land_mx", "land_my", "land_nx", "land_ny")]:
        df[nx] = np.where(flip, W - df[mx], df[mx])
        df[ny] = np.where(flip, L - df[my], df[my])
    return df


def side_map_from(sdf: pd.DataFrame) -> dict:
    """(set_no, 'A'|'B') -> 'near'|'far', from mean labeled hitter depth per set."""
    out = {}
    for (sn, h), g in sdf.dropna(subset=["hitter_my"]).groupby(["set_no", "hitter"]):
        out[(int(sn), h)] = "near" if g["hitter_my"].mean() < court.NET_Y_M else "far"
    return out


def side_map(match_id: str) -> dict:
    return side_map_from(stroke_df(match_id))


def rally_df(match_id: str, sdf: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per rally: boundaries, score context, winner, how it ended, patterns."""
    if sdf is None:
        sdf = stroke_df(match_id)
    _, fps = _H_fps(match_id)
    rows, prev = [], {}
    for (sn, rid), g in sdf.groupby(["set_no", "rally_id"], sort=True):
        g = g.sort_values("ball_round")
        first, end = g.iloc[0], g.iloc[-1]
        a, b = int(g["score_a"].max()), int(g["score_b"].max())
        pa, pb = prev.get(sn, (0, 0))
        if a == pa + 1 and b == pb:
            winner = "A"
        elif b == pb + 1 and a == pa:
            winner = "B"
        else:  # score glitch — fall back to the human label
            winner = end["getpoint_player"] if end["getpoint_player"] in ("A", "B") else None
        prev[sn] = (a, b)

        if winner is None:
            cat = "—"
        elif end["hitter"] == winner:
            cat = "Winner"
        else:
            cat = _END_CAT.get(end["lose_reason"], "Error")

        f0, f1 = int(g["frame_num"].min()), int(g["frame_num"].max())
        shots = g["shot"].tolist()
        rows.append(dict(
            set_no=int(sn), rally_id=int(rid), f0=f0, f1=f1, shots=len(g),
            duration_s=round((f1 - f0) / fps, 1),
            server=first["hitter"],
            serve_type=first["shot"] if first["ball_round"] == 1 else None,
            end_hitter=end["hitter"], end_shot=end["shot"],
            end_round=int(end["ball_round"]), end_backhand=bool(end["backhand"]),
            lose_reason=end["lose_reason"], winner=winner, category=cat,
            score_a=a, score_b=b, prev_a=pa, prev_b=pb,
            clutch=max(pa, pb) >= CLUTCH_FROM,
            bucket="short (≤4)" if len(g) <= 4 else ("mid (5–9)" if len(g) <= 9 else "long (10+)"),
            pat2=" → ".join(shots[-2:]) if len(shots) >= 2 else None,
            pat3=" → ".join(shots[-3:]) if len(shots) >= 3 else None,
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- outcome stats

def shot_outcome_counts(rdf: pd.DataFrame) -> pd.DataFrame:
    """Rally-ending shots: winners and errors per (player, shot type)."""
    d = rdf[rdf["winner"].notna() & (rdf["category"] != "—")]
    rows = []
    for (p, shot), g in d.groupby(["end_hitter", "end_shot"]):
        rows.append(dict(player=p, shot=shot,
                         winners=int((g["category"] == "Winner").sum()),
                         errors=int((g["category"] != "Winner").sum())))
    return pd.DataFrame(rows)


def points_won(rdf: pd.DataFrame) -> dict:
    """Per player: total points + how they were won (own winner vs opponent error type)."""
    out = {}
    for p in ("A", "B"):
        won = rdf[rdf["winner"] == p]
        own = int((won["end_hitter"] == p).sum())          # rally ended on p's winner
        opp_err = won[won["end_hitter"] != p]
        out[p] = dict(points=len(won), winners=own,
                      opp_out=int((opp_err["category"] == "Out").sum()),
                      opp_net=int((opp_err["category"] == "Net").sum()),
                      opp_other=int((~opp_err["category"].isin(["Out", "Net"])).sum()))
    return out


def length_buckets(rdf: pd.DataFrame) -> pd.DataFrame:
    """Win rate per rally-length bucket per player."""
    d = rdf[rdf["winner"].notna()]
    rows = []
    for bucket, g in d.groupby("bucket"):
        for p in ("A", "B"):
            rows.append(dict(bucket=bucket, player=p, played=len(g),
                             won=int((g["winner"] == p).sum()),
                             win_pct=round(100 * (g["winner"] == p).mean())))
    return pd.DataFrame(rows)


def serve_stats(rdf: pd.DataFrame) -> dict:
    """Per player: points won when serving / receiving, and per serve type."""
    d = rdf[rdf["winner"].notna()]
    out = {}
    for p in ("A", "B"):
        sv, rc = d[d["server"] == p], d[d["server"] != p]
        by_type = {}
        for t, g in sv.groupby("serve_type"):
            by_type[t] = dict(n=len(g), won=int((g["winner"] == p).sum()))
        out[p] = dict(serve_n=len(sv), serve_won=int((sv["winner"] == p).sum()),
                      recv_n=len(rc), recv_won=int((rc["winner"] == p).sum()),
                      by_type=by_type)
    return out


def clutch_stats(rdf: pd.DataFrame) -> dict:
    d = rdf[rdf["clutch"] & rdf["winner"].notna()]
    return {p: dict(n=len(d), won=int((d["winner"] == p).sum())) for p in ("A", "B")}


def longest_run(rdf: pd.DataFrame) -> dict:
    """Longest consecutive-points streak per player (whole match)."""
    best, cur, last = {"A": 0, "B": 0}, 0, None
    for w in rdf.sort_values(["set_no", "rally_id"])["winner"]:
        if w is None or (isinstance(w, float) and np.isnan(w)):
            continue
        cur = cur + 1 if w == last else 1
        last = w
        best[w] = max(best[w], cur)
    return best


def patterns(rdf: pd.DataFrame, n: int = 2, min_count: int = 2) -> list[dict]:
    """Rally-ending shot sequences: who they favor + the supporting rallies."""
    col = "pat2" if n == 2 else "pat3"
    d = rdf[rdf[col].notna() & rdf["winner"].notna()]
    out = []
    for pat, g in d.groupby(col):
        if len(g) < min_count:
            continue
        out.append(dict(pattern=pat, n=len(g),
                        a_wins=int((g["winner"] == "A").sum()),
                        b_wins=int((g["winner"] == "B").sum()),
                        keys=list(zip(g["set_no"], g["rally_id"]))))
    out.sort(key=lambda x: -x["n"])
    return out


def error_pressure(match_id: str, rdf: pd.DataFrame,
                   hi: float = FORCED_SPEED,
                   pressure: list[dict] | None = None) -> dict:
    """Split each player's rally-ending errors into forced (had to scramble) vs
    unforced (comfortable position, < hi m/s required speed).
    `pressure` overrides the labeled tactics.pressure_strokes (label-free path)."""
    req = {(x["set"], x["rally"], x["shot_no"]): x["req_speed"]
           for x in (pressure if pressure is not None
                     else tactics.pressure_strokes(match_id))}
    out = {p: dict(forced=0, unforced=0, unknown=0, errors=0) for p in ("A", "B")}
    errs = rdf[rdf["winner"].notna() & (rdf["category"] != "Winner") & (rdf["category"] != "—")]
    for _, r in errs.iterrows():
        p = r["end_hitter"]
        if p not in out:
            continue
        out[p]["errors"] += 1
        spd = req.get((r["set_no"], r["rally_id"], r["end_round"]))
        if spd is None:
            out[p]["unknown"] += 1
        elif spd >= hi:
            out[p]["forced"] += 1
        else:
            out[p]["unforced"] += 1
    return out


def backhand_stats(sdf: pd.DataFrame, rdf: pd.DataFrame) -> dict:
    """Backhand usage share vs backhand share of rally-ending errors, per player."""
    out = {}
    errs = rdf[rdf["winner"].notna() & ~rdf["category"].isin(["Winner", "—"])]
    for p in ("A", "B"):
        mine = sdf[sdf["hitter"] == p]
        my_errs = errs[errs["end_hitter"] == p]
        out[p] = dict(usage_pct=round(100 * mine["backhand"].mean()) if len(mine) else 0,
                      err_pct=round(100 * my_errs["end_backhand"].mean()) if len(my_errs) else 0,
                      n_err=len(my_errs))
    return out


def placement_df(sdf: pd.DataFrame, rdf: pd.DataFrame) -> pd.DataFrame:
    """Strokes with landing coords + outcome tag ('winner'/'error' for rally-enders,
    'rally' otherwise) — feeds the shot placement maps."""
    m = sdf.merge(rdf[["set_no", "rally_id", "end_round", "winner", "category"]],
                  on=["set_no", "rally_id"], how="left")
    is_end = (m["ball_round"] == m["end_round"]) & m["winner"].notna() & (m["category"] != "—")
    m["outcome"] = np.where(is_end & (m["hitter"] == m["winner"]), "winner",
                            np.where(is_end, "error", "rally"))
    return m[m["land_nx"].notna()]


# ---------------------------------------------------------------- movement (side-swap aware)

def movement_by_player(match_id: str) -> dict:
    """Whole-match movement per PLAYER ('A'/'B'), aggregated rally-by-rally with the
    per-set near/far mapping applied (sides swap between sets). Positions are
    returned NORMALIZED (player always on the near half)."""
    sdf = stroke_df(match_id)
    smap = side_map_from(sdf)
    _, fps = _H_fps(match_id)
    W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M

    spans = sdf.groupby(["set_no", "rally_id"])["frame_num"].agg(["min", "max"])
    dist = {"A": 0.0, "B": 0.0}
    secs = {"A": 0.0, "B": 0.0}
    pos = {"A": [], "B": []}
    for (sn, _), (f0, f1) in spans.iterrows():
        series = analytics.player_series(match_id, int(f0) + SS_OFFSET, int(f1) + SS_OFFSET)
        for side, arr in series.items():
            who = next((p for p in ("A", "B") if smap.get((int(sn), p)) == side), None)
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


def rally_tracks(match_id: str, f0: int, f1: int) -> pd.DataFrame:
    """Per-frame court positions for one rally window (ShuttleSet frame numbers)."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, player_id, court_x, court_y FROM tracks"
        " WHERE match_id=? AND frame_num BETWEEN ? AND ? ORDER BY frame_num",
        [match_id, f0 + SS_OFFSET, f1 + SS_OFFSET]).df()
    con.close()
    return df


# ---------------------------------------------------------------- coach's notes

def _pct(won, n):
    return round(100 * won / n) if n else 0


def coach_notes(match_id: str, rdf: pd.DataFrame, sdf: pd.DataFrame,
                names: dict, pressure: list[dict] | None = None) -> list[dict]:
    """Rule-based, data-backed insight cards. Each note carries the rallies that
    support it so the dashboard can deep-link straight into the Film room.
    Returns dicts: icon, title, body, keys (list of (set_no, rally_id)), score.
    `pressure` swaps the labeled pressure model for the label-free one."""
    notes = []
    oc = shot_outcome_counts(rdf)
    finished = rdf[rdf["winner"].notna() & (rdf["category"] != "—")]

    def keys_for(player, shot, won: bool):
        d = finished[(finished["end_hitter"] == player) & (finished["end_shot"] == shot)]
        d = d[(d["category"] == "Winner")] if won else d[d["category"] != "Winner"]
        return list(zip(d["set_no"], d["rally_id"]))

    for p in ("A", "B"):
        mine = oc[oc["player"] == p]
        nm = names[p]
        # 1) biggest weapon
        if len(mine) and mine["winners"].max() >= 4:
            r = mine.loc[mine["winners"].idxmax()]
            total = int(mine["winners"].sum())
            notes.append(dict(icon="🗡️", score=r["winners"] * 1.5,
                              title=f"{nm}'s {r['shot']} was his biggest weapon",
                              body=f"{r['winners']} of his {total} outright winners came from the "
                                   f"{r['shot']}. Expect it — and train the counter.",
                              keys=keys_for(p, r["shot"], won=True)))
        # 2) biggest leak
        if len(mine) and mine["errors"].max() >= 4:
            r = mine.loc[mine["errors"].idxmax()]
            d = finished[(finished["end_hitter"] == p) & (finished["end_shot"] == r["shot"])
                         & (finished["category"] != "Winner")]
            net, out_ = int((d["category"] == "Net").sum()), int((d["category"] == "Out").sum())
            notes.append(dict(icon="⚠️", score=r["errors"] * 1.6,
                              title=f"{nm} bled points on the {r['shot']}",
                              body=f"{r['errors']} points lost to {r['shot']} errors "
                                   f"({net} into the net, {out_} out). The single biggest fix available.",
                              keys=keys_for(p, r["shot"], won=False)))

    # 3) forced vs unforced errors
    ep = error_pressure(match_id, rdf, pressure=pressure)
    for p in ("A", "B"):
        e = ep[p]
        known = e["forced"] + e["unforced"]
        if known >= 8:
            unf = _pct(e["unforced"], known)
            if unf >= 60:
                body = (f"{e['unforced']} of his {known} pressure-rated errors came from a "
                        f"comfortable position (<{FORCED_SPEED} m/s required movement). "
                        "These are free points to claw back — focus errors, not fitness.")
                title = f"{names[p]}'s errors were mostly unforced ({unf}%)"
            elif unf <= 40:
                body = (f"{e['forced']} of {known} errors came while scrambling at "
                        f"≥{FORCED_SPEED} m/s — his opponent earned them with placement. "
                        "Work on earlier recovery to the base.")
                title = f"{names[p]} was forced into his errors ({100 - unf}%)"
            else:
                continue
            errs = finished[(finished["end_hitter"] == p) & (finished["category"] != "Winner")]
            notes.append(dict(icon="🎚️", score=abs(unf - 50) / 8 + 3, title=title, body=body,
                              keys=list(zip(errs["set_no"], errs["rally_id"]))))

    # 4) most damaging 2-shot pattern
    pats = patterns(rdf, n=2, min_count=3)
    for pt in pats[:6]:
        lean = max(pt["a_wins"], pt["b_wins"]) / pt["n"]
        if pt["n"] >= 4 and lean >= 0.75:
            fav = "A" if pt["a_wins"] >= pt["b_wins"] else "B"
            notes.append(dict(icon="🔁", score=pt["n"] * lean,
                              title=f"The “{pt['pattern']}” exchange favored {names[fav]}",
                              body=f"This ending sequence appeared {pt['n']} times and "
                                   f"{names[fav]} took {max(pt['a_wins'], pt['b_wins'])} of them. "
                                   "Recognize the setup shot and break the pattern early.",
                              keys=pt["keys"]))
            break

    # 5) rally-length edge
    lb = length_buckets(rdf)
    for p in ("A", "B"):
        mine = lb[lb["player"] == p].set_index("bucket")
        if {"short (≤4)", "long (10+)"} <= set(mine.index):
            s, lg = mine.loc["short (≤4)"], mine.loc["long (10+)"]
            if s["played"] >= 8 and lg["played"] >= 8 and abs(int(s["win_pct"]) - int(lg["win_pct"])) >= 20:
                better = "short" if s["win_pct"] > lg["win_pct"] else "long"
                d = finished[finished["bucket"] == ("short (≤4)" if better == "short" else "long (10+)")]
                notes.append(dict(icon="⏱️", score=abs(int(s["win_pct"]) - int(lg["win_pct"])) / 4,
                                  title=f"{names[p]} thrived in {better} rallies",
                                  body=f"He won {s['win_pct']}% of short rallies (≤4 shots) vs "
                                       f"{lg['win_pct']}% of long ones (10+). "
                                       + ("Force quick exchanges against him — or extend them yourself."
                                          if better == "short" else
                                          "Keep the shuttle alive against him only if you can match his legs."),
                                  keys=list(zip(d["set_no"], d["rally_id"]))))

    # 6) serve edge
    sv = serve_stats(rdf)
    for p in ("A", "B"):
        s = sv[p]
        if s["serve_n"] >= 15:
            pct = _pct(s["serve_won"], s["serve_n"])
            if pct <= 42 or pct >= 58:
                d = finished[finished["server"] == p]
                verdict = "a genuine edge" if pct >= 58 else "a liability"
                notes.append(dict(icon="🎯", score=abs(pct - 50) / 5 + 1,
                                  title=f"Serving was {verdict} for {names[p]}",
                                  body=f"He won {pct}% of his {s['serve_n']} service points "
                                       f"(vs {_pct(s['recv_won'], s['recv_n'])}% when receiving).",
                                  keys=list(zip(d["set_no"], d["rally_id"]))))

    # 7) clutch
    cl = clutch_stats(rdf)
    n_cl = cl["A"]["n"]
    if n_cl >= 6 and abs(cl["A"]["won"] - cl["B"]["won"]) >= max(2, n_cl // 4):
        p = "A" if cl["A"]["won"] > cl["B"]["won"] else "B"
        d = rdf[rdf["clutch"] & rdf["winner"].notna()]
        notes.append(dict(icon="🧊", score=abs(cl["A"]["won"] - cl["B"]["won"]) + 2,
                          title=f"{names[p]} owned the big points",
                          body=f"From {CLUTCH_FROM}+ in a game, {names[p]} took "
                               f"{cl[p]['won']} of the {n_cl} points. Composure under "
                               "pressure decided the tight stretches.",
                          keys=list(zip(d["set_no"], d["rally_id"]))))

    # 8) backhand leak
    bh = backhand_stats(sdf, rdf)
    for p in ("A", "B"):
        b = bh[p]
        if b["n_err"] >= 10 and b["err_pct"] - b["usage_pct"] >= 12:
            d = finished[(finished["end_hitter"] == p) & finished["end_backhand"]
                         & (finished["category"] != "Winner")]
            notes.append(dict(icon="🫲", score=(b["err_pct"] - b["usage_pct"]) / 4 + 2,
                              title=f"{names[p]}'s backhand cracked under fire",
                              body=f"Backhands were {b['usage_pct']}% of his shots but "
                                   f"{b['err_pct']}% of his rally-ending errors. Attack that wing.",
                              keys=list(zip(d["set_no"], d["rally_id"]))))

    notes.sort(key=lambda x: -x["score"])
    return notes
