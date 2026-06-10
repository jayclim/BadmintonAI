"""Shot-type classification from stroke GEOMETRY (no pose, no video).

Goal: establish how far positions + timing alone go on ShuttleSet's 10 canonical
classes, using exactly the features the CV pipeline will eventually produce on its
own (hitter/opponent court positions, landing position, flight time, rally position).
This is the deployable baseline; BST (pose+trajectory transformer) is the upgrade path.

Feature sets:
- "cv"     — only what Phase-2 CV can emit: normalized court coords (hitter always at
             bottom), landing coords, dt to previous/next hit, ball_round, derived
             deltas/speed. NaNs (rally-enders have no next hit) handled natively by
             HistGradientBoosting.
- "cv+lab" — adds labeled hit_height (high/low contact) + backhand/aroundhead flags;
             an UPPER bound for when CV learns to estimate contact height later.

Eval protocol: cross-match (train on one match, test on the other) — different players,
tournament, camera — plus a pooled 5-fold CV for reference.

CLI:  PYTHONPATH=src python -m badminton.shotclass            # train + report
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import insights

CLASSES = insights.SHOT_ORDER

CV_FEATURES = ["hitter_nx", "hitter_ny", "recv_nx", "recv_ny", "land_nx", "land_ny",
               "ball_round", "dt_prev", "dt_next", "depth_delta", "lat_delta",
               "speed_proxy", "opp_depth_delta", "contact_rel_px"]
LAB_FEATURES = ["low_contact", "backhand", "aroundhead"]


def build_features(match_id: str, feet_landing: bool = False) -> pd.DataFrame:
    """One row per labeled stroke with geometry features + shot label.

    feet_landing=True swaps the landing convention to match the CV pipeline:
    landing of stroke i := the NEXT stroke's hitter position (feet, on the floor
    plane) instead of the mid-air landing click; final strokes keep the labeled
    floor landing. Train with this when classifying pipeline-built strokes.
    """
    sdf = insights.stroke_df(match_id).copy()
    sdf = sdf.sort_values(["set_no", "rally_id", "ball_round"])
    g = sdf.groupby(["set_no", "rally_id"])
    sdf["dt_prev"] = g["frame_num"].diff()
    sdf["dt_next"] = -g["frame_num"].diff(-1)

    if feet_landing:
        from . import court
        nx_next = g["hitter_mx"].shift(-1)
        ny_next = g["hitter_my"].shift(-1)
        last = nx_next.isna()
        sdf["land_mx"] = np.where(last, sdf["land_mx"], nx_next)
        sdf["land_my"] = np.where(last, sdf["land_my"], ny_next)
        smap = insights.side_map_from(sdf)
        flip = sdf.apply(lambda r: smap.get((r.set_no, r.hitter)) == "far",
                         axis=1).to_numpy()
        W, L = court.COURT_WIDTH_M, court.COURT_LENGTH_M
        sdf["land_nx"] = np.where(flip, W - sdf["land_mx"], sdf["land_mx"])
        sdf["land_ny"] = np.where(flip, L - sdf["land_my"], sdf["land_my"])

    sdf["depth_delta"] = sdf["land_ny"] - sdf["hitter_ny"]    # how far up-court it goes
    sdf["lat_delta"] = (sdf["land_nx"] - sdf["hitter_nx"]).abs()
    dist = np.hypot(sdf["land_nx"] - sdf["hitter_nx"], sdf["land_ny"] - sdf["hitter_ny"])
    sdf["speed_proxy"] = dist / sdf["dt_next"]                # court-m per frame
    sdf["opp_depth_delta"] = sdf["land_ny"] - sdf["recv_ny"]  # landing vs opponent depth

    # contact height proxy: shuttle-at-contact vs hitter feet, image px (negative =
    # above the feet; both the labels and the CV pipeline can compute this)
    sdf["contact_rel_px"] = sdf["hit_y"] - sdf["hitter_y"]

    sdf["low_contact"] = (sdf["hit_height"] == 2).astype(float)
    sdf["backhand"] = sdf["backhand"].astype(float)
    sdf["aroundhead"] = sdf["aroundhead"].astype(float)

    sdf["match_id"] = match_id
    keep = sdf["shot"].isin(CLASSES)
    cols = list(dict.fromkeys(["match_id", "set_no", "rally_id", "ball_round", "shot"]
                              + CV_FEATURES + LAB_FEATURES))
    return sdf.loc[keep, cols]


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                          max_leaf_nodes=31, random_state=0)


def evaluate(feature_set: str = "cv") -> dict:
    """Cross-match + pooled-CV accuracy; returns the fitted pooled model + reports."""
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from sklearn.model_selection import cross_val_score

    cols = CV_FEATURES + (LAB_FEATURES if feature_set == "cv+lab" else [])
    matches = ["india_open_2022_final", "denmark_open_2022_sf"]
    dfs = {m: build_features(m) for m in matches}
    out = {"feature_set": feature_set, "cross_match": {}}

    for train_m, test_m in [(matches[0], matches[1]), (matches[1], matches[0])]:
        tr, te = dfs[train_m], dfs[test_m]
        clf = _model().fit(tr[cols], tr["shot"])
        pred = clf.predict(te[cols])
        acc = accuracy_score(te["shot"], pred)
        out["cross_match"][f"{train_m} → {test_m}"] = {
            "accuracy": round(float(acc), 4),
            "n_test": len(te),
            "report": classification_report(te["shot"], pred, zero_division=0),
            "confusion": confusion_matrix(te["shot"], pred,
                                          labels=sorted(te["shot"].unique())),
            "labels": sorted(te["shot"].unique()),
        }

    pooled = pd.concat(dfs.values(), ignore_index=True)
    scores = cross_val_score(_model(), pooled[cols], pooled["shot"], cv=5)
    out["pooled_cv_acc"] = round(float(scores.mean()), 4)
    out["pooled_model"] = _model().fit(pooled[cols], pooled["shot"])
    out["class_counts"] = pooled["shot"].value_counts().to_dict()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Geometry-only shot classifier baseline")
    ap.add_argument("--features", choices=["cv", "cv+lab"], default="cv")
    args = ap.parse_args()

    res = evaluate(args.features)
    print(f"=== feature set: {res['feature_set']} ===")
    print("class counts:", res["class_counts"])
    for name, r in res["cross_match"].items():
        print(f"\n--- {name}  (n={r['n_test']})  accuracy {r['accuracy']:.1%} ---")
        print(r["report"])
    print(f"pooled 5-fold CV accuracy: {res['pooled_cv_acc']:.1%}")
