"""Broadcast score-overlay OCR (Phase 2) — scores, sets and rally winners, label-free.

The BWF World Tour graphic is two gray name rows with dark score cells to their
right (completed sets first, CURRENT set points last; digits white, yellow for
the server). Tesseract can't read the ~12 px digits, so we template-match:
digit templates are bootstrapped automatically from a LABELED match (ShuttleSet
gives the exact score after every rally; glyphs harvested where the expected
digit count matches) and stored once in data/scoreboard_digits.npz — the BWF
graphics package is the same across tournaments, so the templates transfer.

Reading the overlay gives, with no ShuttleSet input:
- the score after every rally → per-rally WINNER (which row scored),
- set boundaries (current-points column resets / a cell column is added),
- with segment.py serve sides: the per-set row↔near/far map (winner serves next).

CLI:  PYTHONPATH=src python -m badminton.scoreboard <match_id>            # validate
      PYTHONPATH=src python -m badminton.scoreboard <match_id> --harvest # templates
"""

from __future__ import annotations

import argparse

import cv2
import numpy as np
import pandas as pd

from . import config, hits, insights

TEMPLATES = config.REPO_ROOT / "data" / "scoreboard_digits.npz"
GLYPH_SHAPE = (14, 10)   # all glyph masks normalized to this for matching
STRIP_W = 95             # px of score cells scanned right of the name strip
NUM_GAP = 12             # px gap between glyph clusters = separate numbers
MIN_MATCH = 0.55         # min normalized correlation to accept a digit


# ------------------------------------------------------------- box location

def locate_rows(frame: np.ndarray):
    """(y0, y1, x0, x1) of the gray name-strip box in this frame, or None."""
    reg = frame[5:100, 80:760]
    g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY).astype(np.float32)
    chroma = reg.max(axis=2).astype(int) - reg.min(axis=2).astype(int)
    gray = (g > 140) & (g < 240) & (chroma < 45)
    rowfrac = gray.mean(axis=1)
    ys = np.where(rowfrac > 0.15)[0]
    if len(ys) < 25:
        return None
    y0, y1 = ys.min(), ys.max()
    if not 30 <= y1 - y0 <= 70:
        return None
    colfrac = gray[y0:y1 + 1].mean(axis=0)
    xs = np.where(colfrac > 0.5)[0]
    if len(xs) < 80:
        return None
    runs, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= 4:
            cur.append(x)
        else:
            runs.append(cur)
            cur = [x]
    runs.append(cur)
    best = max(runs, key=len)
    if len(best) < 80:
        return None
    return int(y0) + 5, int(y1) + 5, int(best[0]) + 80, int(best[-1]) + 80


def calibrate_box(match_id: str, n: int = 120):
    """Median box geometry over sampled frames (the graphic is static)."""
    video = str(config.REPO_ROOT / config.get_match(match_id)["video_path"])
    cap = cv2.VideoCapture(video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    boxes = []
    for f in np.linspace(total * 0.1, total * 0.9, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, fr = cap.read()
        if ok:
            b = locate_rows(fr)
            if b:
                boxes.append(b)
    cap.release()
    if len(boxes) < n * 0.25:
        return None
    return tuple(int(np.median([b[i] for b in boxes])) for i in range(4))


# ----------------------------------------------------------- glyph extraction

def _row_glyphs(strip: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Bright digit glyphs on dark cell background in one row strip."""
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).astype(int)
    bgr = strip.astype(int)
    chroma = bgr.max(axis=2) - bgr.min(axis=2)
    white = (g > 150) & (chroma < 70)
    yellow = (g > 110) & (bgr[:, :, 2] > 140) & (bgr[:, :, 1] > 140) \
        & (bgr[:, :, 0] < 120)
    mask = (white | yellow).astype(np.uint8)
    nlab, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    H = mask.shape[0]
    out = []
    for i in range(1, nlab):
        x, y, w, h, area = stats[i]
        if not (H * 0.45 <= h <= H * 0.9) or not (4 <= w <= 16) or area < 12:
            continue
        # digits sit on a dark cell; logo/feather edges don't
        x0, x1 = max(0, x - 2), min(strip.shape[1], x + w + 2)
        y0, y1 = max(0, y - 1), min(H, y + h + 1)
        around = g[y0:y1, x0:x1][lab[y0:y1, x0:x1] != i]
        if len(around) == 0 or np.median(around) > 100:
            continue
        out.append((int(x), (lab[y : y + h, x : x + w] == i).astype(np.uint8)))
    out.sort(key=lambda t: t[0])
    return out


def row_strips(frame: np.ndarray, box) -> dict[str, np.ndarray]:
    y0, y1, x0, x1 = box
    h2 = (y1 - y0) // 2
    return {"top": frame[y0 : y0 + h2 + 1, x1 + 1 : x1 + STRIP_W],
            "bot": frame[y1 - h2 : y1 + 1, x1 + 1 : x1 + STRIP_W]}


def _norm_glyph(mask: np.ndarray) -> np.ndarray:
    return cv2.resize(mask.astype(np.float32), GLYPH_SHAPE[::-1],
                      interpolation=cv2.INTER_AREA)


def _group_numbers(glyphs: list[tuple[int, np.ndarray]]) -> list[list]:
    """Cluster x-sorted glyphs into numbers (cells) split at gaps > NUM_GAP."""
    if not glyphs:
        return []
    groups = [[glyphs[0]]]
    for x, m in glyphs[1:]:
        px, pm = groups[-1][-1]
        if x - (px + pm.shape[1]) > NUM_GAP:
            groups.append([(x, m)])
        else:
            groups[-1].append((x, m))
    return groups


# ------------------------------------------------------- template bootstrap

def harvest_templates(match_id: str, verbose: bool = True) -> dict:
    """Build digit templates from a LABELED match: at each rally end the score
    is known; harvest rows whose glyph count matches the expected digits."""
    sdf = insights.stroke_df(match_id)
    off = hits.shuttle_offset(match_id)
    box = calibrate_box(match_id)
    if box is None:
        raise RuntimeError("score box not found")

    # expected score AFTER each rally, per ShuttleSet row identity (A/B)
    last = sdf.sort_values(["set_no", "rally_id", "ball_round"]) \
        .groupby(["set_no", "rally_id"]).last().reset_index()
    video = str(config.REPO_ROOT / config.get_match(match_id)["video_path"])
    cap = cv2.VideoCapture(video)

    # row -> A/B is unknown a priori; collect candidate assignments both ways
    # and keep the one that harvests consistently (right one matches ~every
    # rally, wrong one almost never matches the expected digit counts).
    buckets = {k: {d: [] for d in range(10)} for k in ("AB", "BA")}
    n_used = {"AB": 0, "BA": 0}
    set_scores: dict[int, list] = {}
    # sample just BEFORE the NEXT rally's serve: the overlay updates 2-5 s
    # after a rally (sampling too early harvests off-by-one digit labels —
    # this contaminated 5/7/8 on the first attempt), but it is always final
    # before the next serve
    nxt = (last["frame_num"].astype(int) + off).shift(-1)
    for (_, r), nf in zip(last.iterrows(), nxt):
        sn = int(r["set_no"])
        a, b = int(r["score_a"]), int(r["score_b"])
        set_scores.setdefault(sn, []).append((a, b))
        end_f = int(r["frame_num"]) + off
        f = int(min(nf - 45, end_f + 240)) if pd.notna(nf) else end_f + 150
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, fr = cap.read()
        if not ok:
            continue
        strips = row_strips(fr, box)
        done = [(s_, scores[-1]) for s_, scores in set_scores.items() if s_ < sn]
        for key, (top_pts, bot_pts) in (("AB", (a, b)), ("BA", (b, a))):
            expect = {"top": [], "bot": []}
            for s_, (fa, fb) in done:
                expect["top"].append(fa if key == "AB" else fb)
                expect["bot"].append(fb if key == "AB" else fa)
            expect["top"].append(top_pts)
            expect["bot"].append(bot_pts)
            ok_rows = 0
            assign = []
            for row in ("top", "bot"):
                groups = _group_numbers(_row_glyphs(strips[row]))
                want = ["".join(str(d) for d in str(n)) for n in expect[row]]
                if len(groups) != len(want) or any(
                        len(g) != len(w) for g, w in zip(groups, want)):
                    break
                for g, w in zip(groups, want):
                    for (x, m), ch in zip(g, w):
                        assign.append((int(ch), m))
                ok_rows += 1
            if ok_rows == 2:
                n_used[key] += 1
                for d, m in assign:
                    buckets[key][d].append(_norm_glyph(m))
    cap.release()

    key = "AB" if n_used["AB"] >= n_used["BA"] else "BA"
    if verbose:
        print(f"harvest: row order {key}, {n_used[key]} rallies usable "
              f"(other order: {n_used['AB' if key == 'BA' else 'BA']})")
    tpl = {}
    for d in range(10):
        if buckets[key][d]:
            tpl[str(d)] = np.mean(buckets[key][d], axis=0)
    counts = {d: len(buckets[key][d]) for d in range(10)}
    if verbose:
        print("glyphs per digit:", counts)
    missing = [d for d in range(10) if str(d) not in tpl]
    if missing:
        print(f"WARNING: no examples for digits {missing}")
    np.savez(TEMPLATES, **tpl)
    if verbose:
        print(f"wrote {TEMPLATES}")
    return tpl


# ------------------------------------------------------------- reading

def _load_templates() -> dict[str, np.ndarray]:
    z = np.load(TEMPLATES)
    return {k: z[k] for k in z.files}


def _classify(mask: np.ndarray, tpl: dict[str, np.ndarray]) -> str | None:
    v = _norm_glyph(mask).ravel()
    v = v - v.mean()
    nv = np.linalg.norm(v)
    if nv == 0:
        return None
    best, best_c = None, MIN_MATCH
    for ch, t in tpl.items():
        u = t.ravel() - t.mean()
        c = float(np.dot(u, v) / (np.linalg.norm(u) * nv + 1e-9))
        if c > best_c:
            best, best_c = ch, c
    return best


def read_frame(frame: np.ndarray, box, tpl) -> dict | None:
    """{'top': [nums...], 'bot': [nums...]} (cells left→right) or None."""
    out = {}
    for row, strip in row_strips(frame, box).items():
        nums = []
        for group in _group_numbers(_row_glyphs(strip)):
            digits = [_classify(m, tpl) for _, m in group]
            if any(d is None for d in digits):
                return None
            nums.append(int("".join(digits)))
        out[row] = nums
    if not out["top"] or not out["bot"] or len(out["top"]) != len(out["bot"]):
        return None
    return out


def timeline(match_id: str, step: int = 30, verbose: bool = True) -> pd.DataFrame:
    """Sampled score readings over the whole match (NaN where unreadable)."""
    box = calibrate_box(match_id)
    if box is None:
        raise RuntimeError("score box not found")
    tpl = _load_templates()
    video = str(config.REPO_ROOT / config.get_match(match_id)["video_path"])
    cap = cv2.VideoCapture(video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rows = []
    for f in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, fr = cap.read()
        if not ok:
            break
        r = read_frame(fr, box, tpl)
        if r is None:
            continue
        rows.append(dict(frame=f, n_cells=len(r["top"]),
                         top=r["top"][-1], bot=r["bot"][-1],
                         top_all=r["top"], bot_all=r["bot"]))
    cap.release()
    df = pd.DataFrame(rows)
    if verbose:
        print(f"timeline: {len(df)} readable samples / {total // step}")
    return df


# ------------------------------------------------------------- score events

def events(match_id: str, step: int = 30, tl: pd.DataFrame | None = None
           ) -> pd.DataFrame:
    """Score-change events from the sampled timeline.

    A reading is accepted only when two consecutive samples agree (kills
    one-frame misreads). Events carry the frame of FIRST appearance, the new
    (top, bot) points, the set number (1 + completed-set cells) and the winner
    row ('top'/'bot') when exactly one side gained points. The overlay can
    update 15+ s late (hidden behind replays), so events are aligned to
    rallies by ORDER, not by fixed windows."""
    if tl is None:
        tl = timeline(match_id, step=step, verbose=False)
    ev = []
    prev = None          # accepted (n_cells, top, bot)
    pend = None          # candidate awaiting confirmation
    for r in tl.itertuples():
        cur = (int(r.n_cells), int(r.top), int(r.bot))
        if prev is not None and cur == (prev[0], prev[1], prev[2]):
            pend = None
            continue
        if pend is not None and cur == pend[0]:
            nc, t, b = cur
            new_set = prev is not None and (
                nc > prev[0] or (t < prev[1] and b < prev[2]))
            if prev is None or new_set:
                winner = None
            else:
                dt_, db_ = t - prev[1], b - prev[2]
                winner = "top" if dt_ > 0 and db_ == 0 else \
                         "bot" if db_ > 0 and dt_ == 0 else None
            ev.append(dict(frame=int(pend[1]), set_no=nc, top=t, bot=b,
                           new_set=bool(new_set), winner=winner,
                           jump=None if prev is None or new_set
                           else max(t - prev[1], b - prev[2])))
            prev = cur
            pend = None
        else:
            pend = (cur, r.frame)
    return pd.DataFrame(ev)


def side_map(match_id: str, ev: pd.DataFrame | None = None,
             seg: pd.DataFrame | None = None) -> dict:
    """{(set_no, 'top'|'bot') -> 'near'|'far'}, fully label-free.

    The rally WINNER serves the next rally; OCR says which ROW won, the
    segmenter + wrist attribution say which SIDE serves next. Each
    (winner event, next segment) pair is one vote; majority per set absorbs
    late overlay updates and attribution errors."""
    from . import segment
    if ev is None:
        ev = events(match_id)
    if seg is None:
        seg = segment.segments(match_id)
    votes: dict[tuple, dict] = {}
    for i, e in ev.iterrows():
        if e["winner"] is None or e["jump"] != 1 or e["new_set"]:
            continue
        # last event of its set = set point; the next serve is next set's
        if i + 1 < len(ev) and bool(ev.iloc[i + 1]["new_set"]):
            continue
        nxt = seg[seg["start"] > int(e["frame"])]
        if not len(nxt) or nxt.iloc[0]["serve_player"] not in ("near", "far"):
            continue
        key = (int(e["set_no"]), e["winner"])
        votes.setdefault(key, {"near": 0, "far": 0})
        votes[key][nxt.iloc[0]["serve_player"]] += 1

    out = {}
    for sn in sorted({k[0] for k in votes}):
        t = votes.get((sn, "top"), {"near": 0, "far": 0})
        b = votes.get((sn, "bot"), {"near": 0, "far": 0})
        # joint assignment: top and bot are on opposite sides
        score_tn = t["near"] + b["far"]
        score_tf = t["far"] + b["near"]
        if score_tn == score_tf:
            continue
        top_side = "near" if score_tn > score_tf else "far"
        out[(sn, "top")] = top_side
        out[(sn, "bot")] = "far" if top_side == "near" else "near"
    return out


# --------------------------------------------------------------- validation

def validate(match_id: str, step: int = 30) -> dict:
    """Score the OCR event trajectory against ShuttleSet roundscores."""
    sdf = insights.stroke_df(match_id)
    last = sdf.sort_values(["set_no", "rally_id", "ball_round"]) \
        .groupby(["set_no", "rally_id"]).last().reset_index()
    ev = events(match_id, step=step)

    # label trajectory per set, in rally order; OCR rows may be A/B or B/A —
    # resolve by which mapping explains more events
    for key in ("AB", "BA"):
        evi = 0
        hit = winner_n = 0
        for _, r in last.iterrows():
            a, b = int(r["score_a"]), int(r["score_b"])
            t, bt = (a, b) if key == "AB" else (b, a)
            # find this score in the remaining events (in order, same set —
            # score pairs recur across sets and one sampling gap would
            # otherwise desync the whole match); a miss does NOT consume
            for j in range(evi, len(ev)):
                e = ev.iloc[j]
                if int(e["set_no"]) != int(r["set_no"]):
                    continue
                if int(e["top"]) == t and int(e["bot"]) == bt:
                    hit += 1
                    if e["winner"] is not None and e["jump"] == 1:
                        winner_n += 1
                    evi = j + 1
                    break
        if hit > len(last) * 0.5:
            break
    n = len(last)
    print(f"OCR events: {len(ev)} | label rallies {n} | trajectory matched "
          f"{hit} ({hit / n:.1%}) with row order {key}; "
          f"{winner_n} have an unambiguous +1 winner")

    # side map: OCR rows are (top,bot); labels are (A,B) — key maps them
    derived = side_map(match_id, ev=ev)
    lab_map = insights.side_map_from(sdf)
    row_of = {"A": "top" if key == "AB" else "bot",
              "B": "bot" if key == "AB" else "top"}
    sm_ok = sm_bad = 0
    for (sn, ab), side in lab_map.items():
        got = derived.get((int(sn), row_of[ab]))
        if got is None:
            continue
        sm_ok += got == side
        sm_bad += got != side
    print(f"side map: {sm_ok}/{sm_ok + sm_bad} (set,player) entries correct, "
          f"{len(lab_map) - sm_ok - sm_bad} undecided")
    return dict(n=n, n_events=len(ev), matched=hit, row_order=key,
                winner_events=winner_n, side_ok=sm_ok, side_bad=sm_bad)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score overlay OCR")
    ap.add_argument("match_id")
    ap.add_argument("--harvest", action="store_true",
                    help="(re)build digit templates from this labeled match")
    args = ap.parse_args()
    if args.harvest:
        harvest_templates(args.match_id)
    else:
        validate(args.match_id)
