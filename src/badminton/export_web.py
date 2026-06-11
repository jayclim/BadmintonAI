"""Export precomputed dashboard data for the static web app (web/public/data).

The web app (web/, Next.js static export) renders ONLY what this script emits —
it has no Python, no DB, no video. Everything page-level lives in one JSON per
(match, source); per-rally replay payloads are split into small lazy-loaded files.

Sources: 'labels' (ShuttleSet) and 'ai' (the label-free CV chain: pipeline strokes
+ scoreboard OCR snapshot). All exported frame numbers are VIDEO frames; the
labels source is shifted by +SS_OFFSET here so the frontend never sees offsets.

CLI:
  PYTHONPATH=src python -m badminton.export_web                 # all matches, all sources
  PYTHONPATH=src python -m badminton.export_web --match <id> --skip-slow
`--skip-slow` skips the validation reruns (hit/segment scoring) in showcase.json.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, court, db, hits, insights, labelfree, shotclass, tactics
from .clip import reason_en

OUT_DEFAULT = config.REPO_ROOT / "web" / "public" / "data"
SS_OFFSET = insights.SS_OFFSET
W, L, NET = court.COURT_WIDTH_M, court.COURT_LENGTH_M, court.NET_Y_M
HEAT_BINS = (12, 14)
HEAT_RANGE = [[0.0, W], [0.0, NET + 0.5]]


def _js(o):
    """JSON-safe: numpy scalars -> python, NaN -> None."""
    if isinstance(o, dict):
        return {str(k): _js(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_js(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) or True) and pd.isna(o) else round(float(o), 3)
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


def _end_phrase(r, source: str) -> str:
    if r["category"] == "Winner":
        return f"{r['end_shot']} winner"
    if r["category"] == "Net":
        return f"{r['end_shot']} into the net"
    if r["category"] == "Out":
        return f"{r['end_shot']} out"
    if r["category"] == "Misjudged":
        return "left it — misjudged"
    if r["category"] == "Error":
        return f"{r['end_shot']} error"
    if source == "labels" and r.get("lose_reason"):
        return reason_en(r["lose_reason"])
    return "—"


# ------------------------------------------------------------------ per-source data

def _source_frames(match_id: str, source: str):
    """(sdf, rdf, smap, pressure list, frame->video offset)."""
    if source == "labels":
        sdf = insights.stroke_df(match_id)
        rdf = insights.rally_df(match_id, sdf)
        smap = insights.side_map_from(sdf)
        pressure = tactics.pressure_strokes(match_id)
        return sdf, rdf, smap, pressure, SS_OFFSET
    sdf = labelfree.stroke_df(match_id)
    rdf = labelfree.rally_df(match_id, sdf)
    smap = labelfree.side_map(match_id)
    fps = float(config.get_match(match_id)["fps"])
    pressure = labelfree.pressure_strokes(sdf, fps)
    return sdf, rdf, smap, pressure, 0


def _heat(P: np.ndarray) -> dict:
    h, xe, ye = np.histogram2d(P[:, 0], P[:, 1], bins=HEAT_BINS, range=HEAT_RANGE)
    cells = [[i, j, int(h[i, j])] for i in range(HEAT_BINS[0])
             for j in range(HEAT_BINS[1]) if h[i, j] > 0]
    return dict(nx=HEAT_BINS[0], ny=HEAT_BINS[1],
                x1=HEAT_RANGE[0][1], y1=HEAT_RANGE[1][1], cells=cells)


def _clip_windows(match_id: str) -> list[tuple[int, int, str]]:
    """AI-annotated rally clips on disk: (start, end, relative url). Clip names
    carry their video-frame window so any source's rallies map on by overlap."""
    out = []
    for p in sorted((config.REPO_ROOT / "web" / "public" / "clips" / match_id).glob("f*-*.mp4")):
        a, b = p.stem[1:].split("-")
        out.append((int(a), int(b), f"/clips/{match_id}/{p.name}"))
    return out


def export_source(match_id: str, source: str, out: Path) -> dict:
    m = config.get_match(match_id)
    fps = float(m["fps"])
    sdf, rdf, smap, pressure, off = _source_frames(match_id, source)
    names = {"A": m["players"][1], "B": m["players"][0]}

    req = {(x["set"], x["rally"], x["shot_no"]): round(x["req_speed"], 2)
           for x in pressure}

    clips = _clip_windows(match_id)

    def clip_for(f0: int, f1: int) -> str | None:
        best, best_ov = None, 0
        for a, b, url in clips:
            ov = min(f1, b) - max(f0, a)
            if ov > best_ov:
                best, best_ov = url, ov
        return best if best_ov >= 0.6 * (f1 - f0) else None

    rallies = []
    for _, r in rdf.iterrows():
        f0v, f1v = int(r["f0"]) + off, int(r["f1"]) + off
        rallies.append(dict(
            clip=clip_for(f0v, f1v),
            set=int(r["set_no"]), rally=int(r["rally_id"]), f0=f0v, f1=f1v,
            t0=round(f0v / fps, 2), t1=round(f1v / fps, 2),
            shots=int(r["shots"]), durS=float(r["duration_s"]),
            server=r["server"], serveType=r["serve_type"],
            winner=r["winner"] if r["winner"] in ("A", "B") else None,
            endHitter=r["end_hitter"], endShot=r["end_shot"],
            endRound=int(r["end_round"]), category=r["category"],
            endPhrase=_end_phrase(r, source),
            a=int(r["score_a"]), b=int(r["score_b"]),
            pa=int(r["prev_a"]), pb=int(r["prev_b"]),
            clutch=bool(r["clutch"]), bucket=r["bucket"],
            pat2=r["pat2"], pat3=r["pat3"]))

    strokes = []
    for _, s in sdf.iterrows():
        fv = int(s["frame_num"]) + off
        strokes.append(dict(
            set=int(s["set_no"]), rally=int(s["rally_id"]), br=int(s["ball_round"]),
            f=fv, t=round(fv / fps, 2), p=s["hitter"], shot=s["shot"],
            conf=round(float(s["shot_type_conf"]), 2) if "shot_type_conf" in s and pd.notna(s.get("shot_type_conf")) else None,
            hx=s["hitter_mx"], hy=s["hitter_my"],
            lx=s["land_mx"], ly=s["land_my"],
            nx=s["hitter_nx"], ny=s["hitter_ny"],
            lnx=s["land_nx"], lny=s["land_ny"],
            press=req.get((int(s["set_no"]), int(s["rally_id"]), int(s["ball_round"])))))

    # ---- coach analytics: response matrix + opening playbook
    rally_winner = {(int(r["set_no"]), int(r["rally_id"])): r["winner"]
                    for _, r in rdf.iterrows()}

    def response_matrix() -> dict:
        """When the opponent plays X at player P, what does P reply — and how do
        those rallies end up? The scouting 'if-then' table."""
        counts: dict = {"A": {}, "B": {}}
        for (sn, rid), g in sdf.groupby(["set_no", "rally_id"], sort=False):
            g = g.sort_values("ball_round")
            rows_ = list(g.itertuples())
            won = rally_winner.get((int(sn), int(rid)))
            for prev, cur in zip(rows_, rows_[1:]):
                if prev.shot not in insights.SHOT_ORDER or cur.shot not in insights.SHOT_ORDER:
                    continue
                d = counts[cur.hitter].setdefault(prev.shot, {})
                e = d.setdefault(cur.shot, [0, 0, 0])     # n, rallies won, decided
                e[0] += 1
                if won is not None:
                    e[2] += 1
                    e[1] += int(won == cur.hitter)
        out = {}
        for p in ("A", "B"):
            trig = []
            for shot, replies in counts[p].items():
                total = sum(v[0] for v in replies.values())
                if total < 6:
                    continue
                top = sorted(replies.items(), key=lambda kv: -kv[1][0])[:3]
                trig.append(dict(
                    trigger=shot, n=total,
                    replies=[dict(shot=s, n=v[0], pct=round(100 * v[0] / total),
                                  winPct=round(100 * v[1] / v[2]) if v[2] >= 4 else None)
                             for s, v in top]))
            trig.sort(key=lambda t: -t["n"])
            out[p] = trig[:6]
        return out

    def openings() -> dict:
        """Per server: serve type → outcomes + what comes back (and how the
        server fares against each return)."""
        out: dict = {"A": {}, "B": {}}
        for (sn, rid), g in sdf.groupby(["set_no", "rally_id"], sort=False):
            g = g.sort_values("ball_round")
            first = g.iloc[0]
            if int(first["ball_round"]) != 1 or first["shot"] not in insights.SHOT_ORDER:
                continue
            srv, st = first["hitter"], first["shot"]
            won = rally_winner.get((int(sn), int(rid)))
            d = out[srv].setdefault(st, dict(n=0, won=0, decided=0, returns={}))
            d["n"] += 1
            if won is not None:
                d["decided"] += 1
                d["won"] += int(won == srv)
            if len(g) >= 2:
                ret = g.iloc[1]["shot"]
                if ret in insights.SHOT_ORDER:
                    e = d["returns"].setdefault(ret, [0, 0, 0])
                    e[0] += 1
                    if won is not None:
                        e[2] += 1
                        e[1] += int(won == srv)
        for p in ("A", "B"):
            for st, d in out[p].items():
                top = sorted(d["returns"].items(), key=lambda kv: -kv[1][0])[:3]
                d["returns"] = [dict(shot=s, n=v[0],
                                     pct=round(100 * v[0] / max(1, d["n"])),
                                     srvWinPct=round(100 * v[1] / v[2]) if v[2] >= 4 else None)
                                for s, v in top]
                d["winPct"] = round(100 * d["won"] / d["decided"]) if d["decided"] else None
        return out

    # ---- insights bundle (all computed on the source's own frames)
    oc = insights.shot_outcome_counts(rdf)
    notes = insights.coach_notes(match_id, rdf, sdf, names,
                                 pressure=pressure if source == "ai" else None)
    sv = insights.serve_stats(rdf)
    mix = (sdf[sdf["shot"].isin(insights.SHOT_ORDER)]
           .groupby(["hitter", "shot"]).size().rename("n").reset_index())
    mix["pct"] = mix.groupby("hitter")["n"].transform(lambda x: 100 * x / x.sum()).round(1)
    bundle = dict(
        notes=[dict(icon=n["icon"], title=n["title"], body=n["body"],
                    keys=[[int(a), int(b)] for a, b in sorted(set(n["keys"]))])
               for n in notes[:8]],
        pointsWon=insights.points_won(rdf),
        lengthBuckets=insights.length_buckets(rdf).to_dict("records"),
        serveStats=sv,
        clutch=insights.clutch_stats(rdf),
        longestRun=insights.longest_run(rdf),
        patterns2=[{**p, "keys": [[int(a), int(b)] for a, b in p["keys"]]}
                   for p in insights.patterns(rdf, 2, min_count=3)[:9]],
        patterns3=[{**p, "keys": [[int(a), int(b)] for a, b in p["keys"]]}
                   for p in insights.patterns(rdf, 3, min_count=3)[:9]],
        errorPressure=insights.error_pressure(match_id, rdf,
                                              pressure=pressure if source == "ai" else None),
        backhand=insights.backhand_stats(sdf, rdf) if source == "labels" else None,
        shotOutcomes=[dict(p=r["player"], shot=r["shot"], w=int(r["winners"]),
                           e=int(r["errors"])) for _, r in oc.iterrows()
                      if r["shot"] in insights.SHOT_ORDER],
        shotMix=[dict(p=r["hitter"], shot=r["shot"], n=int(r["n"]), pct=float(r["pct"]))
                 for _, r in mix.iterrows() if r["hitter"] in ("A", "B")],
        responseMatrix=response_matrix(),
        openings=openings(),
        pressureByShot=(tactics.pressure_by_shot(match_id) if source == "labels"
                        else labelfree.pressure_by_shot(sdf, fps)),
        pressureSummary=(tactics.pressure_summary(match_id) if source == "labels"
                         else labelfree.pressure_summary(sdf, fps)),
    )

    mov = (insights.movement_by_player(match_id) if source == "labels"
           else labelfree.movement_by_player(match_id, rdf, smap))
    movement = {}
    for p, mt in mov.items():
        movement[p] = dict(distM=mt["distance_m"], secs=mt["rally_time_s"],
                           speed=mt["mean_speed"], cov=mt["coverage_m2"],
                           rec=mt["recovery_m"], front=mt["front_pct"],
                           mid=mt["mid_pct"], back=mt["back_pct"],
                           heat=_heat(mt["positions"]))

    sets = [dict(set=int(sn), a=int(g["score_a"].max()), b=int(g["score_b"].max()))
            for sn, g in rdf.groupby("set_no")]
    pw = bundle["pointsWon"]
    data = dict(
        meta=dict(id=match_id, source=source, players=names,
                  tournament=m.get("tournament"), round=m.get("round"),
                  date=str(m.get("match_date", "")), youtubeId=_yt_id(m.get("video_url")),
                  fps=fps, sets=sets, winner="A",
                  totals=dict(rallies=len(rdf), shots=int(rdf["shots"].sum()),
                              rallySecs=int(rdf["durS"].sum() if "durS" in rdf else rdf["duration_s"].sum()),
                              points={p: pw[p]["points"] for p in ("A", "B")}),
                  smap={f"{sn}": {p: smap.get((sn, p)) for p in ("A", "B")}
                        for sn in sorted({k[0] for k in smap})}),
        rallies=rallies, strokes=strokes, insights=bundle, movement=movement,
        commentary=_commentary(match_id))
    _write(out / match_id / f"{source}.json", data)

    _export_replays(match_id, source, sdf, rdf, smap, off, fps, out)
    return data


def _commentary(match_id: str):
    d = config.REPO_ROOT / "data" / "commentary"
    cands = sorted(d.glob(f"{match_id}.*.json"), key=lambda p: p.stat().st_mtime)
    if not cands:
        return None
    rec = json.loads(cands[-1].read_text())
    return dict(commentary=rec["commentary"], model=rec.get("model"),
                provider=rec.get("provider"), generatedAt=rec.get("generated_at"))


# ------------------------------------------------------------------ replay payloads

def _export_replays(match_id, source, sdf, rdf, smap, off, fps, out: Path):
    con = db.connect(read_only=True)
    sh_off = hits.shuttle_offset(match_id)
    lab = None
    if source == "ai":   # reference hit frames from labels, when the match has them
        try:
            lab = insights.stroke_df(match_id)
        except Exception:
            lab = None

    for _, r in rdf.iterrows():
        sn, rid = int(r["set_no"]), int(r["rally_id"])
        f0, f1 = int(r["f0"]) + off - 15, int(r["f1"]) + off + 45
        tr = con.execute(
            "SELECT frame_num, player_id, court_x, court_y FROM tracks "
            "WHERE match_id=? AND frame_num BETWEEN ? AND ? ORDER BY frame_num",
            [match_id, f0, f1]).fetchall()
        players = {"near": [], "far": []}
        for f, p, x, y in tr:
            if p in players:
                players[p].append([int(f), round(float(x), 2), round(float(y), 2)])
        sh = con.execute(
            "SELECT frame_num, img_x, img_y FROM shuttle WHERE match_id=? AND visible "
            "AND frame_num BETWEEN ? AND ? ORDER BY frame_num",
            [match_id, f0, f1]).fetchall()

        g = sdf[(sdf["set_no"] == sn) & (sdf["rally_id"] == rid)].sort_values("ball_round")
        hits_l, arcs = [], []
        for _, s in g.iterrows():
            fv = int(s["frame_num"]) + off
            hits_l.append(dict(f=fv, p=s["hitter"], shot=s["shot"],
                               conf=(round(float(s["shot_type_conf"]), 2)
                                     if "shot_type_conf" in s and pd.notna(s.get("shot_type_conf")) else None)))
            if pd.notna(s["hitter_mx"]) and pd.notna(s["land_mx"]):
                arcs.append(dict(f=fv, x0=round(float(s["hitter_mx"]), 2),
                                 y0=round(float(s["hitter_my"]), 2),
                                 x1=round(float(s["land_mx"]), 2),
                                 y1=round(float(s["land_my"]), 2)))
        land = None
        last = g.iloc[-1]
        if pd.notna(last["land_mx"]):
            land = dict(x=round(float(last["land_mx"]), 2), y=round(float(last["land_my"]), 2))

        ref = []
        if lab is not None:
            lg = lab[(lab["frame_num"] + sh_off >= f0) & (lab["frame_num"] + sh_off <= f1)]
            ref = [dict(f=int(x["frame_num"]) + sh_off, shot=x["shot"])
                   for _, x in lg.iterrows()]

        payload = dict(fps=fps, f0=f0, f1=f1,
                       smap={p: smap.get((sn, p)) for p in ("A", "B")},
                       near=players["near"], far=players["far"],
                       shuttle=[[int(f), round(float(x), 1), round(float(y), 1)]
                                for f, x, y in sh],
                       hits=hits_l, refHits=ref, arcs=arcs, land=land)
        _write(out / match_id / "replay" / source / f"s{sn}r{rid}.json", payload)
    con.close()


# ------------------------------------------------------------------ showcase

def _tracking_validation(match_id: str) -> dict:
    """Median position error vs labeled hitter positions (the Phase-0 number)."""
    sdf = insights.stroke_df(match_id)
    con = db.connect(read_only=True)
    frames = tuple(int(f) + SS_OFFSET for f in sdf["frame_num"].unique().tolist())
    rows = con.execute(
        f"SELECT frame_num, court_x, court_y FROM tracks WHERE match_id=? "
        f"AND frame_num IN {frames}", [match_id]).fetchall()
    con.close()
    by_f: dict[int, list] = {}
    for f, x, y in rows:
        by_f.setdefault(int(f), []).append((float(x), float(y)))
    errs, halves = [], []
    for _, r in sdf.iterrows():
        if pd.isna(r["hitter_mx"]):
            continue
        cands = by_f.get(int(r["frame_num"]) + SS_OFFSET, [])
        if not cands:
            continue
        e = min(np.hypot(x - r["hitter_mx"], y - r["hitter_my"]) for x, y in cands)
        errs.append(float(e))
        halves.append(court.which_half(float(r["hitter_my"])))
    errs = np.array(errs)
    h = np.array(halves)
    return dict(medianM=round(float(np.median(errs)), 3),
                p90M=round(float(np.percentile(errs, 90)), 3), n=len(errs),
                nearM=round(float(np.median(errs[h == "near"])), 3),
                farM=round(float(np.median(errs[h == "far"])), 3))


def _agreement(match_id: str) -> dict:
    """DB pipeline strokes vs labels: coverage / hitter / shot + confusion."""
    con = db.connect(read_only=True)
    df = con.execute(
        "SELECT frame_num, hitter, shot_type FROM strokes "
        "WHERE match_id=? AND source='pipeline' AND set_no=0 ORDER BY frame_num",
        [match_id]).df()
    con.close()
    sdf = insights.stroke_df(match_id)
    smap = insights.side_map_from(sdf)
    off = hits.shuttle_offset(match_id)
    of = df["frame_num"].to_numpy()
    used = np.zeros(len(df), bool)
    n_match = hit_ok = shot_ok = shot_n = 0
    conf: dict[tuple, int] = {}
    for _, lab in sdf.iterrows():
        lf = int(lab["frame_num"]) + off
        cands = [(abs(int(of[j]) - lf), j) for j in range(len(df))
                 if not used[j] and abs(int(of[j]) - lf) <= 6]
        if not cands:
            continue
        _, j = min(cands)
        used[j] = True
        n_match += 1
        mine = df.iloc[j]
        lab_side = smap.get((int(lab["set_no"]), lab["hitter"]))
        hit_ok += int(lab_side == mine["hitter"])
        if lab["shot"] in shotclass.CLASSES:
            shot_n += 1
            shot_ok += int(mine["shot_type"] == lab["shot"])
            k = (lab["shot"], mine["shot_type"])
            conf[k] = conf.get(k, 0) + 1
    rec = {}
    for (l, p), n in conf.items():
        rec.setdefault(l, [0, 0])
        rec[l][1] += n
        if l == p:
            rec[l][0] += n
    return dict(
        nLabel=len(sdf), nPipeline=len(df), nMatched=n_match,
        coverage=round(n_match / len(sdf), 4),
        hitterAcc=round(hit_ok / n_match, 4) if n_match else None,
        shotAcc=round(shot_ok / shot_n, 4) if shot_n else None,
        e2e=round(shot_ok / len(sdf), 4),
        confusion=[dict(label=l, pred=p, n=n) for (l, p), n in sorted(conf.items())],
        recall=[dict(shot=l, recall=round(ok / tot, 3), n=tot)
                for l, (ok, tot) in sorted(rec.items())])


def _ocr_demo(match_id: str, out: Path, n_crops: int = 6) -> dict:
    """Scoreboard crops with their machine readings + the OCR event series."""
    import cv2
    from . import scoreboard
    snap = json.loads(labelfree.snapshot_path(match_id).read_text())
    events = snap.get("events", [])
    crops = []
    box = scoreboard.calibrate_box(match_id, n=40)
    if box is not None and events:
        video = str(config.REPO_ROOT / config.get_match(match_id)["video_path"])
        cap = cv2.VideoCapture(video)
        pick = events[:: max(1, len(events) // n_crops)][:n_crops]
        y0, y1, x0, x1 = box
        for e in pick:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(e["frame"]))
            ok, fr = cap.read()
            if not ok:
                continue
            crop = fr[max(0, y0 - 4): y1 + 5, max(0, x0 - 4): x1 + scoreboard.STRIP_W + 6]
            crop = cv2.resize(crop, (crop.shape[1] * 2, crop.shape[0] * 2),
                              interpolation=cv2.INTER_NEAREST)
            name = f"f{e['frame']}.jpg"
            p = out / match_id / "ocr" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(p), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
            crops.append(dict(frame=e["frame"], img=f"ocr/{name}",
                              top=e["top"], bot=e["bot"], set=e["set_no"]))
        cap.release()
    return dict(events=events, rowA=snap.get("row_a"), sideA=snap.get("side_a"),
                crops=crops)


def export_showcase(match_id: str, out: Path, skip_slow: bool = False) -> None:
    from . import segment
    sc: dict = dict(heldOut=match_id == "denmark_open_2022_sf")
    sc["tracking"] = _tracking_validation(match_id)
    sc["agreement"] = _agreement(match_id)
    sc["ocr"] = _ocr_demo(match_id, out)
    if skip_slow:  # keep previously computed slow validations rather than dropping them
        prev_p = out / match_id / "showcase.json"
        if prev_p.exists():
            prev = json.loads(prev_p.read_text())
            for k in ("hits", "segmentation"):
                if k in prev:
                    sc[k] = prev[k]
    if not skip_slow:
        hv = hits.validate(match_id, verbose=False)
        sc["hits"] = dict(f1=hv["f1"], precision=hv["precision"], recall=hv["recall"],
                          attribution=hv["attribution_acc"],
                          landingMedM=hv["landing_median_m"],
                          landingP90M=hv["landing_p90_m"], nLabel=hv["n_label"])
        sv = segment.validate(match_id, verbose=False)
        sc["segmentation"] = dict(recall=sv["recall"], precision=sv["precision"],
                                  f1=sv["f1"], nLabel=sv["n_label"], nDet=sv["n_detected"])
    _write(out / match_id / "showcase.json", sc)


# ------------------------------------------------------------------ index + main

def export_match(match_id: str, out: Path, skip_slow: bool = False) -> dict:
    sources = []
    entry: dict = {}
    for source in ("labels", "ai"):
        try:
            if source == "ai" and not labelfree.available(match_id):
                continue
            data = export_source(match_id, source, out)
            sources.append(source)
            if source == "labels" or not entry:
                m = data["meta"]
                entry = dict(id=match_id, players=m["players"], tournament=m["tournament"],
                             round=m["round"], date=m["date"], youtubeId=m["youtubeId"],
                             sets=[[s["a"], s["b"]] for s in m["sets"]],
                             rallies=m["totals"]["rallies"], shots=m["totals"]["shots"])
        except Exception as e:
            print(f"  !! {match_id}/{source}: {e}")
    if "labels" in sources:
        export_showcase(match_id, out, skip_slow=skip_slow)
    entry["sources"] = sources
    return entry


def main() -> None:
    ap = argparse.ArgumentParser(description="Export web dashboard data")
    ap.add_argument("--match", default=None)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--skip-slow", action="store_true",
                    help="skip hit/segmentation validation reruns in showcase.json")
    args = ap.parse_args()
    out = Path(args.out)

    con = db.connect(read_only=True)
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT match_id FROM strokes ORDER BY match_id").fetchall()]
    con.close()
    if args.match:
        ids = [args.match]

    entries = []
    for mid in ids:
        print(f"== {mid}")
        entries.append(export_match(mid, out, skip_slow=args.skip_slow))
    _write(out / "index.json", dict(matches=entries))
    print(f"wrote {out / 'index.json'} ({len(entries)} matches)")


if __name__ == "__main__":
    main()
