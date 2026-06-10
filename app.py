"""Badminton coaching dashboard. Run:  PYTHONPATH=src streamlit run app.py

Coach-first pages (sidebar nav): Match story (score worm + auto coach's notes that
deep-link into video) · Points won & lost · Court maps (placement + movement) ·
Patterns & pressure · Film room (filterable rally clips) · Lab (CV diagnostics).

Insight cards carry the rallies that support them, so every claim has a
"Watch" button that jumps to the Film room pre-filtered to the evidence.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import altair as alt
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

from badminton import analytics, clip, commentary, config, court, db, insights, tactics, viz

# Dev convenience: Streamlit hot-reloads only app.py, not imported submodules — so edits
# to badminton/*.py would otherwise be ignored until a full server restart. Reload them
# (leaf deps first) on every rerun so changes are picked up live.
import importlib
for _mod in (config, court, db, viz, analytics, clip, tactics, insights, commentary):
    importlib.reload(_mod)

SS_OFFSET = 6
GREEN, RED = "#2f9e44", "#e03131"
WIN_C, ERR_C, RALLY_C = "#43e08a", "#ff5e57", "#d7e3d7"
PAGES = ["📖 Match story", "🎙️ Commentary", "🎯 Points won & lost", "🗺️ Court maps",
         "🧠 Patterns & pressure", "🎞️ Film room", "🔬 Lab"]
PAGE_FILM = "🎞️ Film room"

st.set_page_config(page_title="Badminton Coach", page_icon="🏸", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Archivo:wght@400;600;700&display=swap');
h1, h2, h3, [data-testid="stMetricValue"] {font-family: 'Barlow Condensed', sans-serif !important;}
[data-testid="stMetricValue"] {font-weight: 600;}
.scoreboard {display:flex; flex-wrap:wrap; gap:.55rem 1.4rem; align-items:baseline;
  padding:.55rem 1rem; border:1px solid rgba(128,128,128,.25); border-radius:.6rem;
  margin-bottom:.6rem; font-family:'Barlow Condensed',sans-serif;}
.scoreboard .pl {font-size:1.45rem; font-weight:700;}
.scoreboard .sets {font-size:1.45rem; font-weight:700; font-variant-numeric:tabular-nums;}
.scoreboard .meta {color:#888; font-family:'Archivo',sans-serif; font-size:.78rem;}
.notetitle {font-weight:700; font-size:1rem; margin-bottom:.15rem;}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ cached data

@st.cache_data(show_spinner=False)
def available_matches():
    con = db.connect(read_only=True)
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT match_id FROM strokes WHERE source='shuttleset' "
        "ORDER BY match_id").fetchall()]
    con.close()
    return ids


@st.cache_data(show_spinner=False)
def get_sdf(mid):
    return insights.stroke_df(mid)


@st.cache_data(show_spinner=False)
def get_rdf(mid):
    return insights.rally_df(mid, insights.stroke_df(mid))


@st.cache_data(show_spinner="Aggregating movement from CV tracks…")
def get_movement(mid):
    return insights.movement_by_player(mid)


@st.cache_data(show_spinner=False)
def get_pressure_summary(mid):
    return tactics.pressure_summary(mid)


@st.cache_data(show_spinner=False)
def get_pressure_by_shot(mid):
    return tactics.pressure_by_shot(mid)


@st.cache_data(show_spinner=False)
def get_notes(mid, pa, pb):
    rdf, sdf = get_rdf(mid), get_sdf(mid)
    return insights.coach_notes(mid, rdf, sdf, {"A": pa, "B": pb})


@st.cache_data(show_spinner="Loading per-frame tracks…")
def get_tracks(mid):
    """frame -> [(player_id, img_x, img_y, court_x, court_y)] — Lab only (big)."""
    con = db.connect(read_only=True)
    tracks = {}
    for f, pid, ix, iy, cx, cy in con.execute(
            "SELECT frame_num,player_id,img_x,img_y,court_x,court_y FROM tracks "
            "WHERE match_id=?", [mid]).fetchall():
        tracks.setdefault(f, []).append((pid, ix, iy, cx, cy))
    con.close()
    return tracks


@st.cache_data(show_spinner="Matching strokes vs ground truth…")
def get_recs(mid):
    """Validation records: each labeled stroke matched to our nearest detection."""
    sdf, tracks = get_sdf(mid), get_tracks(mid)
    recs = []
    for _, r in sdf.iterrows():
        if pd.isna(r["hitter_mx"]):
            continue
        ss_xy = np.array([r["hitter_mx"], r["hitter_my"]])
        cands = [np.array([cx, cy]) for pid, ix, iy, cx, cy
                 in tracks.get(int(r["frame_num"]) + SS_OFFSET, [])]
        err = min((float(np.linalg.norm(c - ss_xy)) for c in cands), default=None)
        recs.append(dict(f=int(r["frame_num"]), rid=int(r["rally_id"]), br=int(r["ball_round"]),
                         sn=int(r["set_no"]), shot=r["shot"], hitter=r["hitter"],
                         half=court.which_half(float(r["hitter_my"])),
                         ss_px=(r["hitter_x"], r["hitter_y"]), ss_xy=ss_xy, err=err,
                         hit_px=(r["hit_x"], r["hit_y"]) if pd.notna(r["hit_x"]) else None,
                         land_px=(r["landing_x"], r["landing_y"]) if pd.notna(r["landing_x"]) else None))
    return recs


# ------------------------------------------------------------------ helpers

def chip(name, color):
    return f"<span style='color:{color};font-weight:700'>{name}</span>"


def small_court(figsize=(2.4, 4.4)):
    fig, ax = plt.subplots(figsize=figsize, dpi=95)
    viz.mpl_court(ax)
    fig.tight_layout(pad=0.2)
    return fig, ax


def go_film(title, keys):
    st.session_state["fr_preset"] = {"title": title,
                                     "keys": sorted({(int(a), int(b)) for a, b in keys})}
    # can't write the radio's key after it's instantiated this run — stage the jump,
    # applied at the top of the next run before the widget is created
    st.session_state["nav_jump"] = PAGE_FILM
    st.rerun()


def end_phrase(r):
    if r["category"] == "Winner":
        return f"{r['end_shot']} winner"
    if r["category"] == "Net":
        return f"{r['end_shot']} into the net"
    if r["category"] == "Out":
        return f"{r['end_shot']} out"
    if r["category"] == "Misjudged":
        return "left it — misjudged"
    return clip.reason_en(r["lose_reason"])


def end_sentence(r):
    if r["winner"] not in ("A", "B"):
        return "outcome not labeled"
    w, l = NAME[r["winner"]], NAME[insights.other(r["winner"])]
    if r["category"] == "Winner":
        return f"**{w}** wins it with a **{r['end_shot']}** winner"
    if r["category"] == "Net":
        return f"**{w}** takes the point — {l}'s {r['end_shot']} goes into the net"
    if r["category"] == "Out":
        return f"**{w}** takes the point — {l}'s {r['end_shot']} lands out"
    if r["category"] == "Misjudged":
        return f"**{w}** takes the point — {l} misjudges the landing"
    return f"**{w}** wins the point ({clip.reason_en(r['lose_reason'])})"


def player_scale():
    return alt.Scale(domain=[PA, PB], range=[COLOR["A"], COLOR["B"]])


# ------------------------------------------------------------------ sidebar / shared state

_ids = available_matches()
if not _ids:
    st.error("No matches in the database yet. Import one with `badminton.shuttleset` first.")
    st.stop()
MATCH = st.sidebar.selectbox(
    "Match", _ids,
    format_func=lambda mid: " vs ".join(config.get_match(mid).get("players", [mid])))

try:
    m = config.get_match(MATCH)
    if "homography" not in m:
        st.info(f"**{' vs '.join(m.get('players', [MATCH]))}** is imported but not calibrated "
                "yet — no homography in `config/matches.yaml`. Finish setup: "
                "`fetch_video` → `calibrate_court` → `scripts/parse_match.py`.")
        st.stop()
    sdf, rdf = get_sdf(MATCH), get_rdf(MATCH)
except Exception as e:
    st.warning("⏳ The database is briefly busy (a detection/import job is writing). "
               "Wait a few seconds and press **R** to rerun.")
    st.caption(str(e))
    st.stop()

# ShuttleSet labels 'A' = match winner (here players[1]); B = players[0].
PA, PB = m["players"][1], m["players"][0]
NAME = {"A": PA, "B": PB}
COLOR = {"A": "#e8590c", "B": "#0c8599"}
SHORT = {p: "".join(w[0] for w in NAME[p].split()) for p in ("A", "B")}
FPS = float(m["fps"])
SMAP = insights.side_map_from(sdf)
PLACE = insights.placement_df(sdf, rdf)

if "nav_jump" in st.session_state:
    st.session_state["page"] = st.session_state.pop("nav_jump")
page = st.sidebar.radio("View", PAGES, key="page", label_visibility="collapsed")
st.sidebar.markdown(f"<small>{chip('●', COLOR['B'])} {PB}<br>"
                    f"{chip('●', COLOR['A'])} {PA}</small>", unsafe_allow_html=True)
st.sidebar.caption(f"📦 {len(sdf):,} labeled strokes · {len(rdf)} rallies cached in DuckDB")

# scoreboard header (every page)
set_scores = rdf.groupby("set_no")[["score_a", "score_b"]].max()
sets_a = " · ".join(f"{r.score_a}–{r.score_b}" for r in set_scores.itertuples())
st.markdown(
    f"<div class='scoreboard'>"
    f"<span class='pl' style='color:{COLOR['A']}'>{PA} 🏆</span>"
    f"<span class='sets'>{sets_a}</span>"
    f"<span class='pl' style='color:{COLOR['B']}'>{PB}</span>"
    f"<span class='meta'>{m['tournament']} · {m.get('round', '')} · "
    f"{rdf['shots'].sum():,} shots · {len(rdf)} rallies</span></div>",
    unsafe_allow_html=True)


# ================================================================== 📖 Match story

def page_story():
    # --- score worm
    d = rdf[rdf["winner"].notna()].copy()
    d["lead"] = d["score_a"] - d["score_b"]
    d["Point"] = d["score_a"] + d["score_b"]
    d["Winner"] = d["winner"].map(NAME)
    d["Score"] = d["score_a"].astype(str) + "–" + d["score_b"].astype(str)
    d["Ended"] = d.apply(end_phrase, axis=1)
    charts = []
    for sn, g in d.groupby("set_no"):
        base = alt.Chart(g).encode(x=alt.X("Point:Q", title=f"Set {sn} — points played"))
        line = base.mark_line(interpolate="step-after", color="#94a3b8", strokeWidth=2).encode(
            y=alt.Y("lead:Q", title=f"← {PB}   ·   {PA} →"))
        pts = base.mark_point(filled=True, size=68, opacity=1).encode(
            y="lead:Q",
            color=alt.Color("Winner:N", scale=player_scale(),
                            legend=alt.Legend(orient="top", title=None)),
            shape=alt.condition(alt.datum.clutch, alt.value("diamond"), alt.value("circle")),
            tooltip=[alt.Tooltip("Score:N"), alt.Tooltip("Winner:N"),
                     alt.Tooltip("Ended:N", title="How it ended"),
                     alt.Tooltip("shots:Q", title="Shots"),
                     alt.Tooltip("duration_s:Q", title="Seconds"),
                     alt.Tooltip("rally_id:Q", title="Rally")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            strokeDash=[4, 3], color="#9ca3af").encode(y="y:Q")
        charts.append((line + pts + zero).properties(height=235, width=430))
    st.markdown(f"#### The match in one picture — who led, point by point "
                f"<small>(♦ = clutch points, {insights.CLUTCH_FROM}+)</small>",
                unsafe_allow_html=True)
    st.altair_chart(alt.hconcat(*charts).resolve_scale(y="shared"))

    # --- headline numbers
    pw = insights.points_won(rdf)
    runs = insights.longest_run(rdf)
    ps = get_pressure_summary(MATCH)
    mov = get_movement(MATCH)
    cols = st.columns(2)
    for col, p in zip(cols, ("B", "A")):
        with col:
            st.markdown(chip(NAME[p], COLOR[p]), unsafe_allow_html=True)
            c = st.columns(5)
            errs_own = pw[insights.other(p)]["opp_out"] + pw[insights.other(p)]["opp_net"] \
                + pw[insights.other(p)]["opp_other"]
            c[0].metric("Points", pw[p]["points"])
            c[1].metric("Winners", pw[p]["winners"])
            c[2].metric("Errors", errs_own)
            c[3].metric("Best run", runs.get(p, 0))
            if p in mov:
                c[4].metric("Ran", f"{mov[p]['distance_m']:,} m")
            else:
                c[4].metric("Pressure", f"{ps[p]['applied']} m/s")
    st.caption("**Errors** = rally-ending mistakes (net / out / misjudged). "
               "**Ran** = total distance covered during rallies, from the CV tracks.")

    # --- coach's notes
    st.markdown("#### 🧑‍🏫 Coach's notes — auto-read from the data")
    st.caption("Every card links to the exact rallies behind it. Click **Watch** to "
               "review them in the Film room.")
    notes = get_notes(MATCH, PA, PB)[:6]
    if not notes:
        st.info("Not enough labeled rallies to generate insights for this match.")
    for row_start in range(0, len(notes), 2):
        cols = st.columns(2)
        for col, (i, n) in zip(cols, list(enumerate(notes))[row_start:row_start + 2]):
            with col, st.container(border=True):
                st.markdown(f"<div class='notetitle'>{n['icon']} {n['title']}</div>",
                            unsafe_allow_html=True)
                st.markdown(n["body"])
                if n["keys"]:
                    if st.button(f"▶ Watch the evidence ({len(set(n['keys']))} rallies)",
                                 key=f"note_{row_start}_{i}"):
                        go_film(n["title"], n["keys"])


# ================================================================== 🎯 Points won & lost

def page_points():
    st.markdown("#### Rally-enders by shot — weapons vs leaks")
    st.caption("Green = outright winners hit with that shot. Red = points thrown away "
               "with it. The biggest red bar is the cheapest place to improve.")
    oc = insights.shot_outcome_counts(rdf)
    cols = st.columns(2)
    for col, p in zip(cols, ("B", "A")):
        with col:
            st.markdown(chip(NAME[p], COLOR[p]), unsafe_allow_html=True)
            mine = oc[oc["player"] == p]
            if mine.empty:
                st.info("No rally-enders.")
                continue
            longd = pd.concat([
                pd.DataFrame({"shot": mine["shot"], "n": mine["winners"], "kind": "winners"}),
                pd.DataFrame({"shot": mine["shot"], "n": -mine["errors"], "kind": "errors"})])
            order = (mine.assign(t=mine["winners"] + mine["errors"])
                     .sort_values("t", ascending=False)["shot"].tolist())
            ch = alt.Chart(longd[longd["n"] != 0]).mark_bar().encode(
                y=alt.Y("shot:N", sort=order, title=None),
                x=alt.X("n:Q", title="← errors · winners →"),
                color=alt.Color("kind:N", scale=alt.Scale(domain=["winners", "errors"],
                                                          range=[GREEN, RED]), legend=None),
                tooltip=["shot:N", "kind:N",
                         alt.Tooltip("n:Q", title="count")]).properties(height=260)
            zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#888").encode(x="x:Q")
            st.altair_chart(ch + zero, width="stretch")

    st.divider()
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("#### Who wins the long rallies?")
        st.caption("Win rate by rally length — patience vs first-strike. A gap here is a "
                   "game plan: shorten or extend points on purpose.")
        lb = insights.length_buckets(rdf)
        lb["Player"] = lb["player"].map(NAME)
        order = ["short (≤4)", "mid (5–9)", "long (10+)"]
        ch = alt.Chart(lb).mark_bar().encode(
            x=alt.X("bucket:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset="Player:N",
            y=alt.Y("win_pct:Q", title="win %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Player:N", scale=player_scale(),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Player:N", "bucket:N", "win_pct:Q", "won:Q",
                     alt.Tooltip("played:Q", title="rallies")]).properties(height=240)
        fifty = alt.Chart(pd.DataFrame({"y": [50]})).mark_rule(
            strokeDash=[4, 3], color="#9ca3af").encode(y="y:Q")
        st.altair_chart(ch + fifty, width="stretch")
    with c2:
        st.markdown("#### How each player's points came")
        pw = insights.points_won(rdf)
        rows = []
        for p in ("B", "A"):
            rows.append({"Player": NAME[p], "Own winners": pw[p]["winners"],
                         "Opponent out": pw[p]["opp_out"], "Opponent net": pw[p]["opp_net"],
                         "Total": pw[p]["points"]})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption("Most points in elite singles come from the opponent's racket — "
                   "forcing errors matters as much as hitting winners.")
        cl = insights.clutch_stats(rdf)
        if cl["A"]["n"]:
            st.markdown(f"**🧊 Clutch points** (either player at {insights.CLUTCH_FROM}+): "
                        f"{chip(PA, COLOR['A'])} {cl['A']['won']} — "
                        f"{cl['B']['won']} {chip(PB, COLOR['B'])} "
                        f"<small>of {cl['A']['n']}</small>", unsafe_allow_html=True)

    st.divider()
    st.markdown("#### Serve & receive")
    sv = insights.serve_stats(rdf)
    cols = st.columns(2)
    for col, p in zip(cols, ("B", "A")):
        s = sv[p]
        with col:
            st.markdown(chip(NAME[p], COLOR[p]), unsafe_allow_html=True)
            c = st.columns(2 + len(s["by_type"]))
            sv_pct = round(100 * s["serve_won"] / s["serve_n"]) if s["serve_n"] else 0
            rc_pct = round(100 * s["recv_won"] / s["recv_n"]) if s["recv_n"] else 0
            c[0].metric("Pts won serving", f"{sv_pct}%", f"{s['serve_won']}/{s['serve_n']}",
                        delta_color="off")
            c[1].metric("Pts won receiving", f"{rc_pct}%", f"{s['recv_won']}/{s['recv_n']}",
                        delta_color="off")
            for j, (t, g) in enumerate(sorted(s["by_type"].items())):
                pct = round(100 * g["won"] / g["n"]) if g["n"] else 0
                c[2 + j].metric(t, f"{pct}%", f"{g['won']}/{g['n']}", delta_color="off")


# ================================================================== 🗺️ Court maps

def page_maps():
    st.markdown("#### Where their shots land")
    st.caption("Each player shown hitting **upward** into the opponent's half (sides are "
               "normalized across sets). ⭐ winners · ✕ rally-ending errors · dots = all "
               "other shots. Filter to a shot type to see placement habits — e.g. where "
               "the smash goes under pressure.")
    fcols = st.columns([3, 2])
    shot_opts = ["All"] + [s for s in insights.SHOT_ORDER if s in set(PLACE["shot"])]
    shot_sel = fcols[0].pills("Shot type", shot_opts, default="All")
    if shot_sel is None:
        shot_sel = "All"
    only_end = fcols[1].segmented_control("Show", ["All shots", "Point-enders only"],
                                          default="All shots")

    cols = st.columns([1, 1, 1.1])
    for col, p in zip(cols, ("B", "A")):
        d = PLACE[PLACE["hitter"] == p]
        if shot_sel != "All":
            d = d[d["shot"] == shot_sel]
        if only_end == "Point-enders only":
            d = d[d["outcome"] != "rally"]
        with col:
            st.markdown(chip(NAME[p], COLOR[p]) + f" <small>· {len(d)} shots</small>",
                        unsafe_allow_html=True)
            fig, ax = small_court()
            base = d[d["outcome"] == "rally"]
            ax.scatter(base["land_nx"], base["land_ny"], s=7, c=RALLY_C, alpha=.5, lw=0)
            err = d[d["outcome"] == "error"]
            ax.scatter(err["land_nx"], err["land_ny"], s=46, c=ERR_C, marker="X",
                       edgecolors="black", linewidths=.4)
            win = d[d["outcome"] == "winner"]
            ax.scatter(win["land_nx"], win["land_ny"], s=95, c=WIN_C, marker="*",
                       edgecolors="black", linewidths=.4)
            ax.annotate(f"{SHORT[p]} hits from here ↑", (court.COURT_WIDTH_M / 2, -0.45),
                        ha="center", fontsize=6.5, color="white")
            st.pyplot(fig)
            plt.close(fig)
    with cols[2]:
        st.markdown("**Reading the maps**")
        st.markdown(
            "- ✕ **above** the far baseline / outside the lines = shots hit long or wide\n"
            "- ✕ **just below the net line** = netted shots\n"
            "- A tight ⭐ cluster shows a go-to finishing zone — both where a player "
            "kills, and where his opponent should not be standing\n"
            "- Compare the two maps for the same shot type to see who has more "
            "placement variety")

    st.divider()
    st.markdown("#### Movement — who did the running")
    mov = get_movement(MATCH)
    if not mov:
        st.info("No continuous tracks yet — run `scripts/parse_match.py` for this match.")
        return
    st.caption("From the CV tracks (validated ±0.57 m), correctly re-attributed per set "
               "as players swap ends. Heatmaps are normalized to each player's own half "
               "(net at the top). **Recovery** = average distance from the ideal base "
               "position — lower is better discipline.")
    cols = st.columns([1, 1, 1.1])
    for col, p in zip(cols, ("B", "A")):
        if p not in mov:
            continue
        mt = mov[p]
        with col:
            st.markdown(chip(NAME[p], COLOR[p]), unsafe_allow_html=True)
            fig, ax = small_court(figsize=(2.1, 2.4))
            P = mt["positions"]
            ax.hist2d(P[:, 0], P[:, 1], bins=(10, 12),
                      range=[[0, court.COURT_WIDTH_M], [0, court.NET_Y_M + 0.5]],
                      cmap="inferno", alpha=.85)
            ax.set_ylim(-0.6, court.NET_Y_M + 0.6)
            st.pyplot(fig)
            plt.close(fig)
            c = st.columns(3)
            c[0].metric("Distance", f"{mt['distance_m']:,} m")
            c[1].metric("Avg speed", f"{mt['mean_speed']} m/s")
            c[2].metric("Recovery", f"{mt['recovery_m']} m")
    with cols[2]:
        st.markdown("**Court-zone time**")
        zone_rows = []
        for p in ("B", "A"):
            if p in mov:
                zone_rows.append({"Player": NAME[p], "Front %": mov[p]["front_pct"],
                                  "Mid %": mov[p]["mid_pct"], "Back %": mov[p]["back_pct"],
                                  "Coverage m²": mov[p]["coverage_m2"]})
        st.dataframe(zone_rows, hide_index=True, width="stretch")
        ps = get_pressure_summary(MATCH)
        st.markdown("**Movement pressure** <small>(required speed to reach shots, "
                    "m/s)</small>", unsafe_allow_html=True)
        st.dataframe([{"Player": NAME[p], "Faced": ps[p]["faced"],
                       "Applied": ps[p]["applied"]} for p in ("B", "A")],
                     hide_index=True, width="stretch")
        st.caption("*Applied > faced* = made the opponent do the scrambling.")


# ================================================================== 🧠 Patterns & pressure

def page_patterns():
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("#### Rally-ending exchanges")
        st.caption("The last shots before the point ended, and who profited. A lopsided "
                   "pattern is a rehearsable situation — drill the response.")
        nlen = st.segmented_control("Pattern length", ["2 shots", "3 shots"],
                                    default="2 shots")
        n = 2 if nlen == "2 shots" else 3
        pats = insights.patterns(rdf, n=n, min_count=3)[:9]
        if not pats:
            st.info("Not enough repeated patterns.")
        hd = st.columns([4, 1, 2, 2, 2])
        for t, col in zip(["**Ending sequence**", "**n**", f"**{SHORT['B']} won**",
                           f"**{SHORT['A']} won**", ""], hd):
            col.markdown(t)
        for i, pt in enumerate(pats):
            cols = st.columns([4, 1, 2, 2, 2])
            cols[0].markdown(pt["pattern"])
            cols[1].markdown(str(pt["n"]))
            cols[2].markdown(chip(str(pt["b_wins"]), COLOR["B"]), unsafe_allow_html=True)
            cols[3].markdown(chip(str(pt["a_wins"]), COLOR["A"]), unsafe_allow_html=True)
            if cols[4].button("▶ Watch", key=f"pat_{n}_{i}"):
                go_film(f"Pattern: {pt['pattern']}", pt["keys"])
    with c2:
        st.markdown("#### Shots that make the opponent scramble")
        st.caption("Average speed the opponent needed to reach the *next* shot (m/s). "
                   "These are the pressure-builders, even when they don't win outright.")
        pbs = get_pressure_by_shot(MATCH)
        d = pd.DataFrame(sorted(pbs.items(), key=lambda kv: -kv[1]),
                         columns=["shot", "mps"])
        ch = alt.Chart(d).mark_bar(color="#5c7cfa").encode(
            y=alt.Y("shot:N", sort="-x", title=None),
            x=alt.X("mps:Q", title="opponent's required speed (m/s)"),
            tooltip=["shot:N", "mps:Q"]).properties(height=250)
        st.altair_chart(ch, width="stretch")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### Forced vs unforced errors")
        st.caption(f"An error is **forced** if the player had to move ≥"
                   f"{insights.FORCED_SPEED} m/s to reach the shot.")
        ep = insights.error_pressure(MATCH, rdf)
        d = pd.DataFrame([{"Player": NAME[p], "kind": k, "n": ep[p][k]}
                          for p in ("B", "A") for k in ("forced", "unforced")])
        ch = alt.Chart(d).mark_bar().encode(
            y=alt.Y("Player:N", title=None),
            x=alt.X("n:Q", title="rally-ending errors"),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["forced", "unforced"],
                                                      range=["#f59f00", RED]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Player:N", "kind:N", "n:Q"]).properties(height=140)
        st.altair_chart(ch, width="stretch")
    with c2:
        st.markdown("#### Backhand vulnerability")
        st.caption("Share of all shots hit backhand vs share of rally-ending errors "
                   "that were backhand. A big gap = a wing to attack (or fix).")
        bh = insights.backhand_stats(sdf, rdf)
        d = pd.DataFrame([{"Player": NAME[p], "metric": lab, "pct": bh[p][k]}
                          for p in ("B", "A")
                          for k, lab in [("usage_pct", "of all shots"),
                                         ("err_pct", "of own errors")]])
        ch = alt.Chart(d).mark_bar().encode(
            y=alt.Y("Player:N", title=None), yOffset="metric:N",
            x=alt.X("pct:Q", title="backhand %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("metric:N", scale=alt.Scale(range=["#868e96", RED]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Player:N", "metric:N", "pct:Q"]).properties(height=160)
        st.altair_chart(ch, width="stretch")
    with c3:
        st.markdown("#### Shot mix")
        st.caption("How each player constructs rallies — share of all shots hit.")
        d = (sdf.groupby(["hitter", "shot"]).size().rename("n").reset_index())
        d["pct"] = d.groupby("hitter")["n"].transform(lambda s: 100 * s / s.sum()).round(1)
        d["Player"] = d["hitter"].map(NAME)
        ch = alt.Chart(d[d["hitter"].isin(["A", "B"])]).mark_bar().encode(
            y=alt.Y("shot:N", sort="-x", title=None), yOffset="Player:N",
            x=alt.X("pct:Q", title="% of own shots"),
            color=alt.Color("Player:N", scale=player_scale(), legend=None),
            tooltip=["Player:N", "shot:N", "pct:Q", "n:Q"]).properties(height=300)
        st.altair_chart(ch, width="stretch")


# ================================================================== 🎞️ Film room

def rally_diagram(sn, rid, f0, f1):
    """Top-down rally map: stroke positions (numbered, player-colored), shuttle paths,
    final landing star, plus faint movement trails from the CV tracks."""
    fig, ax = small_court(figsize=(2.6, 4.7))
    trk = insights.rally_tracks(MATCH, f0, f1)
    for side, g in trk.groupby("player_id"):
        who = next((p for p in ("A", "B") if SMAP.get((sn, p)) == side), None)
        if who is not None:
            ax.plot(g["court_x"], g["court_y"], color=COLOR[who], lw=1.1, alpha=.4)
    g = sdf[(sdf["set_no"] == sn) & (sdf["rally_id"] == rid)].sort_values("ball_round")
    last_br = int(g["ball_round"].max())
    for _, s in g.iterrows():
        if pd.notna(s["hitter_mx"]) and pd.notna(s["land_mx"]):
            ax.plot([s["hitter_mx"], s["land_mx"]], [s["hitter_my"], s["land_my"]],
                    color="white", lw=.7, alpha=.45, ls=":")
        if pd.notna(s["hitter_mx"]):
            ax.scatter([s["hitter_mx"]], [s["hitter_my"]], s=42, c=COLOR[s["hitter"]],
                       edgecolors="black", linewidths=.4, zorder=5)
            ax.annotate(str(int(s["ball_round"])), (s["hitter_mx"], s["hitter_my"]),
                        ha="center", va="center", fontsize=4.6, color="white", zorder=6)
        if int(s["ball_round"]) == last_br and pd.notna(s["land_mx"]):
            ax.scatter([s["land_mx"]], [s["land_my"]], s=130, marker="*", c="#ffd43b",
                       edgecolors="black", linewidths=.5, zorder=7)
    return fig


def page_film():
    preset = st.session_state.get("fr_preset")
    f = rdf.copy()
    if preset:
        c1, c2 = st.columns([5, 1])
        c1.info(f"🎯 Showing the **{len(preset['keys'])} rallies** behind: "
                f"*{preset['title']}*")
        if c2.button("✕ Clear", width="stretch"):
            del st.session_state["fr_preset"]
            st.rerun()
        idx = pd.MultiIndex.from_frame(f[["set_no", "rally_id"]])
        f = f[idx.isin(preset["keys"])]
    else:
        fc = st.columns([1, 2, 2, 2, 2, 2])
        set_sel = fc[0].selectbox("Set", ["All"] + sorted(rdf["set_no"].unique().tolist()))
        win_sel = fc[1].selectbox("Point to", ["Either player", PB, PA])
        cat_sel = fc[2].selectbox("Ended by", ["Anything", "Winner", "Net", "Out", "Misjudged"])
        shot_sel = fc[3].selectbox("Final shot", ["Any"] + sorted(rdf["end_shot"].unique().tolist()))
        len_sel = fc[4].selectbox("Length", ["Any", "short (≤4)", "mid (5–9)", "long (10+)"])
        sort_sel = fc[5].selectbox("Sort", ["Match order", "Longest first", "Most shots",
                                            "Clutch first"])
        if set_sel != "All":
            f = f[f["set_no"] == set_sel]
        if win_sel != "Either player":
            f = f[f["winner"].map(NAME) == win_sel]
        if cat_sel != "Anything":
            f = f[f["category"] == cat_sel]
        if shot_sel != "Any":
            f = f[f["end_shot"] == shot_sel]
        if len_sel != "Any":
            f = f[f["bucket"] == len_sel]
        if sort_sel == "Longest first":
            f = f.sort_values("duration_s", ascending=False)
        elif sort_sel == "Most shots":
            f = f.sort_values("shots", ascending=False)
        elif sort_sel == "Clutch first":
            f = f.sort_values(["clutch", "set_no", "rally_id"],
                              ascending=[False, True, True])

    if f.empty:
        st.info("No rallies match the filters.")
        return

    disp = pd.DataFrame({
        "Set": f["set_no"], "Rally": f["rally_id"],
        "Score": f["score_a"].astype(str) + "–" + f["score_b"].astype(str),
        "Point to": f["winner"].map(NAME).fillna("—"),
        "Shots": f["shots"], "Sec": f["duration_s"],
        "How it ended": f.apply(end_phrase, axis=1),
        "Clutch": np.where(f["clutch"], "🧊", "")})
    left, right = st.columns([2, 3])
    with left:
        st.caption(f"{len(f)} rallies — click one to watch  · score is "
                   f"**{SHORT['A']}–{SHORT['B']}** after the rally")
        ev = st.dataframe(disp, hide_index=True, width="stretch", height=430,
                          on_select="rerun", selection_mode="single-row", key="fr_table")
        rows = ev.selection.rows if ev.selection else []
        r = f.iloc[rows[0] if rows else 0]

    with right:
        st.markdown(f"##### Set {r['set_no']} · Rally {r['rally_id']} — "
                    f"{r['prev_a']}–{r['prev_b']} → **{r['score_a']}–{r['score_b']}** · "
                    f"{r['shots']} shots · {r['duration_s']}s")
        st.markdown(end_sentence(r) + f" · serve: {NAME.get(r['server'], '—')}")
        annotate = st.toggle("Annotated overlay (player boxes + minimap; ~60–90s first time)",
                             key=f"annot_{r['set_no']}_{r['rally_id']}")
        if annotate:
            annot = clip.CLIP_DIR / f"{MATCH}_s{r['set_no']}_r{r['rally_id']}_annot.mp4"
            if not annot.exists():
                with st.spinner("Detecting players + rendering overlay…"):
                    subprocess.run([sys.executable, "-m", "badminton.clip", MATCH,
                                    str(r["set_no"]), str(r["rally_id"]), "--annotate"],
                                   cwd=str(config.REPO_ROOT),
                                   env={**os.environ, "PYTHONPATH": "src"}, check=True)
            st.video(str(annot))
        else:
            with st.spinner("Cutting clip…"):
                st.video(str(clip.clip_rally(MATCH, int(r["set_no"]), int(r["rally_id"]))))

    st.divider()
    d1, d2 = st.columns([1, 2])
    with d1:
        st.caption("Rally map — numbered contact points, ★ final landing, "
                   "faint lines = player movement")
        fig = rally_diagram(int(r["set_no"]), int(r["rally_id"]), int(r["f0"]), int(r["f1"]))
        st.pyplot(fig)
        plt.close(fig)
    with d2:
        st.caption("Shot-by-shot — bar height = how hard the hitter had to scramble "
                   "to reach that shot (required speed, m/s)")
        det = tactics.rally_detail(MATCH, int(r["set_no"]), int(r["rally_id"]))
        dd = pd.DataFrame(det)
        dd["Player"] = dd["hitter"].map(NAME)
        ch = alt.Chart(dd[dd["pressure_mps"].notna()]).mark_bar().encode(
            x=alt.X("shot:O", title="shot #"),
            y=alt.Y("pressure_mps:Q", title="required speed (m/s)"),
            color=alt.Color("Player:N", scale=player_scale(),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["shot:O", "Player:N", "type:N", "pressure_mps:Q"]).properties(height=170)
        st.altair_chart(ch, width="stretch")
        show = dd[["shot", "Player", "type", "pressure_mps", "low_contact"]].rename(
            columns={"shot": "#", "type": "Shot", "pressure_mps": "Pressure (m/s)",
                     "low_contact": "Low contact"})
        st.dataframe(show, hide_index=True, width="stretch", height=200)


# ================================================================== 🔬 Lab

def page_lab():
    st.caption("CV-pipeline diagnostics — accuracy vs ShuttleSet ground truth, raw "
               "position maps, the stroke-level browser, and the full broadcast.")
    recs = get_recs(MATCH)
    tracks = get_tracks(MATCH)
    errs = np.array([r["err"] for r in recs if r["err"] is not None])

    tab_val, tab_stroke, tab_map, tab_video = st.tabs(
        ["📊 Validation", "🔎 Stroke browser", "🗺️ Raw position maps", "🎬 Full video"])

    with tab_val:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Median error", f"{np.median(errs):.2f} m")
        c2.metric("Mean error", f"{errs.mean():.2f} m")
        c3.metric("p90", f"{np.percentile(errs, 90):.2f} m")
        c4.metric("< 0.5 m", f"{np.mean(errs < 0.5) * 100:.0f}%")
        st.caption(f"matched {len(errs)}/{len(recs)} strokes · ground point = "
                   "ankle/bbox blend α=0.65 · frame offset −6")
        left, right = st.columns([3, 2])
        with left:
            fig, ax = plt.subplots(figsize=(4.5, 2.0), dpi=90)
            ax.hist(errs, bins=40, color="#0f766e")
            ax.axvline(float(np.median(errs)), color="orange", ls="--", lw=1)
            ax.set_xlabel("position error (m)", fontsize=8)
            ax.set_ylabel("strokes", fontsize=8)
            ax.tick_params(labelsize=7)
            fig.tight_layout(pad=0.3)
            st.pyplot(fig)
            plt.close(fig)
        with right:
            nh = np.array([r["err"] for r in recs if r["err"] is not None and r["half"] == "near"])
            fh = np.array([r["err"] for r in recs if r["err"] is not None and r["half"] == "far"])
            st.dataframe({"half": ["near", "far"], "n": [len(nh), len(fh)],
                          "median (m)": [round(float(np.median(nh)), 2),
                                         round(float(np.median(fh)), 2)]},
                         hide_index=True, width="stretch")

    with tab_stroke:
        f1, f2, f3, f4 = st.columns([1, 2, 2, 2])
        sets = sorted({r["sn"] for r in recs})
        set_sel = f1.selectbox("Set", ["All"] + sets)
        shot_opts = sorted({r["shot"] for r in recs})
        shot_sel = f2.multiselect("Shot type", shot_opts, default=[])
        hitter_sel = f3.selectbox("Player (hitter)", ["All", PA, PB])
        sort_sel = f4.selectbox("Sort by", ["Chronological", "Largest error", "Smallest error"])

        sel = [i for i, r in enumerate(recs) if r["err"] is not None
               and (set_sel == "All" or r["sn"] == set_sel)
               and (not shot_sel or r["shot"] in shot_sel)
               and (hitter_sel == "All" or NAME.get(r["hitter"]) == hitter_sel)]
        if sort_sel == "Largest error":
            sel.sort(key=lambda i: -recs[i]["err"])
        elif sort_sel == "Smallest error":
            sel.sort(key=lambda i: recs[i]["err"])

        if not sel:
            st.info("No strokes match the filters.")
            return
        st.caption(f"{len(sel)} strokes match · 🟡 ShuttleSet hitter · 🟢 shuttle contact · "
                   "🟣 landing · 🔵/🔴 our detected players")
        pos = st.slider("Browse", 0, len(sel) - 1, 0)
        r = recs[sel[pos]]

        H = np.array(m["homography"], dtype=np.float32).reshape(3, 3)
        cap = cv2.VideoCapture(str(config.REPO_ROOT / m["video_path"]))
        cap.set(cv2.CAP_PROP_POS_FRAMES, r["f"] + SS_OFFSET)
        ok, frame = cap.read()
        cap.release()
        colA, colB = st.columns([3, 1])
        mini = viz.render_court()
        if ok:
            for pid, ix, iy, cx, cy in tracks.get(r["f"] + SS_OFFSET, []):
                c = viz.NEAR_C if pid == "near" else viz.FAR_C
                cv2.circle(frame, (int(ix), int(iy)), 6, c, -1)
                viz.draw_point(mini, cx, cy, c, 6, pid)
            hx, hy = r["ss_px"]
            cv2.drawMarker(frame, (int(hx), int(hy)), viz.SS_C, cv2.MARKER_TILTED_CROSS, 22, 2)
            viz.draw_point(mini, float(r["ss_xy"][0]), float(r["ss_xy"][1]), viz.SS_C, 5, "SS")
            if r["hit_px"]:
                cv2.circle(frame, (int(r["hit_px"][0]), int(r["hit_px"][1])), 6, (80, 220, 80), 2)
            if r["land_px"]:
                cv2.drawMarker(frame, (int(r["land_px"][0]), int(r["land_px"][1])),
                               (220, 80, 220), cv2.MARKER_CROSS, 18, 2)
            colA.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), width=720,
                       caption=f"frame {r['f'] + SS_OFFSET}")
        colB.image(cv2.cvtColor(mini, cv2.COLOR_BGR2RGB))
        colB.metric("This stroke's error", f"{r['err']:.2f} m")
        colB.write(f"**Shot:** {r['shot']}")
        colB.write(f"**Hitter:** {NAME.get(r['hitter'], r['hitter'])}")
        colB.write(f"**Set {r['sn']} · rally {r['rid']} · shot #{r['br']}**")

    with tab_map:
        near = np.array([[cx, cy] for v in tracks.values() for p, ix, iy, cx, cy in v if p == "near"])
        far = np.array([[cx, cy] for v in tracks.values() for p, ix, iy, cx, cy in v if p == "far"])
        c1, c2, _ = st.columns([1, 1, 1])
        with c1:
            st.caption("Detected positions (raw near/far — NOT player-attributed)")
            fig, ax = small_court()
            if len(near):
                ax.scatter(near[:, 0], near[:, 1], s=4, c="#1e90ff", alpha=.35)
            if len(far):
                ax.scatter(far[:, 0], far[:, 1], s=4, c="#ff5a3c", alpha=.35)
            st.pyplot(fig)
            plt.close(fig)
        with c2:
            st.caption("Coverage heatmap (both players)")
            allp = np.vstack([p for p in (near, far) if len(p)])
            fig, ax = small_court()
            ax.hist2d(allp[:, 0], allp[:, 1], bins=(12, 26),
                      range=[[0, court.COURT_WIDTH_M], [0, court.COURT_LENGTH_M]],
                      cmap="inferno", alpha=.75)
            st.pyplot(fig)
            plt.close(fig)

    with tab_video:
        raw = config.REPO_ROOT / m["video_path"]
        if raw.exists():
            st.video(str(raw))
            st.caption("The full broadcast — scrub to any point.")
        else:
            st.info("Download the match video first.")


# ================================================================== 🎙️ Commentary

def page_commentary():
    providers = commentary.available_providers()
    rec = commentary.cached(MATCH)

    def provider_picker(label, key):
        if len(providers) > 1:
            return st.selectbox(label, providers, key=key)
        return providers[0]

    if rec is None:
        st.markdown("#### 🎙️ AI coach's match report")
        st.info("No commentary generated for this match yet. Generation sends the "
                "statistical dossier below (~6 KB, no video) to an LLM once and caches "
                "the report in `data/commentary/`.")
        with st.expander("Preview the dossier that would be sent"):
            st.json(commentary.build_dossier(MATCH))
        if not providers:
            st.warning("No LLM credentials found — put `GEMINI_API_KEY` (or "
                       "`ANTHROPIC_API_KEY`) in the repo-root `.env`, then rerun. "
                       "Terminal alternative:\n\n"
                       f"`PYTHONPATH=src python -m badminton.commentary {MATCH}`")
            return
        prov = provider_picker("Model", "comm_prov_gen")
        if st.button("✨ Generate the match report"):
            with st.spinner("The coach is reviewing the match… (~1 minute)"):
                try:
                    rec = commentary.generate(MATCH, provider=prov)
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    return
        if rec is None:
            return

    c = rec["commentary"]
    st.markdown(f"### {c['headline']}")
    st.markdown(c["match_story"])
    st.markdown("##### ⚡ Turning points")
    for t in c["turning_points"]:
        st.markdown(f"- {t}")

    # one column per player, B left / A right to match the rest of the dashboard
    by_name = {p["name"]: p for p in c["players"]}
    reports = [by_name.get(NAME[k]) for k in ("B", "A")]
    if None in reports:                       # name mismatch fallback: dossier order
        reports = c["players"][:2]
    cols = st.columns(2)
    for col, p in zip(cols, reports):
        key = next((k for k in ("A", "B") if NAME[k] == p["name"]), None)
        with col, st.container(border=True):
            if key is not None:
                st.markdown(f"##### {chip(p['name'], COLOR[key])}", unsafe_allow_html=True)
            else:
                st.markdown(f"##### {p['name']}")
            st.markdown(p["overview"])
            st.markdown("**🗡️ Strengths**")
            for s in p["strengths"]:
                st.markdown(f"- {s}")
            st.markdown("**⚠️ Weaknesses**")
            for w in p["weaknesses"]:
                st.markdown(f"- {w}")
            st.markdown("**🏋️ Training priorities**")
            for t in p["training_priorities"]:
                st.markdown(f"- {t}")
            st.markdown(f"**🎯 How to beat him:** {p['gameplan_against']}")

    u_in, u_out = rec["usage"].get("input_tokens"), rec["usage"].get("output_tokens")
    tok = f" · {u_in:,} in / {u_out:,} out tokens" if u_in is not None else ""
    st.caption(f"Generated {rec['generated_at']} · {rec.get('provider', '?')} "
               f"({rec['model']}){tok}")
    if providers:
        prov = provider_picker("Regenerate with", "comm_prov_regen")
        if st.button("🔁 Regenerate"):
            with st.spinner("Regenerating…"):
                try:
                    commentary.generate(MATCH, provider=prov, force=True)
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    return
            st.rerun()


# ------------------------------------------------------------------ dispatch

PAGE_FN = {"📖 Match story": page_story, "🎙️ Commentary": page_commentary,
           "🎯 Points won & lost": page_points, "🗺️ Court maps": page_maps,
           "🧠 Patterns & pressure": page_patterns, PAGE_FILM: page_film,
           "🔬 Lab": page_lab}
PAGE_FN[page]()
