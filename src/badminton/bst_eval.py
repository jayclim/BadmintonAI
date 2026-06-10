"""Evaluate the pretrained BST-0 stroke classifier on OUR pipeline data.

Adapter: for each labeled stroke, build the exact inputs BST trained on —
a ±0.5 s window around contact (video frame = SS frame − 1, gotcha 9) with
- joints: tracks keypoints (17 COCO), per-frame bbox-normalized (their scheme:
  offset by bbox top-left, scaled by bbox diagonal; zeros = missing),
  m-order [Top(far), Bottom(near)], + bones (19 COCO pairs) → JnB (t, 2, 36, 2)
- shuttle: TrackNetV3 track / (1280, 720); invisible → 0
fed to BST_0 (weights: third_party/BST/bst_weights/bst_0_JnB_bone_merged.pt,
25 merged classes = unknown + Top_/Bottom_ × 12 CN types).

Scored against ShuttleSet labels at three levels: side (Top/Bottom), shot class
(mapped to our 10 canonical EN via shuttleset.canonical_shot_type), and joint.

CLI:  PYTHONPATH=src python -m badminton.bst_eval <match_id>
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import torch

from . import config, db, insights, shuttleset

BST_DIR = config.REPO_ROOT / "third_party" / "BST" / "stroke_classification"
WEIGHTS = config.REPO_ROOT / "third_party" / "BST" / "bst_weights" / "bst_0_JnB_bone_merged.pt"
sys.path.insert(0, str(BST_DIR))

from model.bst import BST_0                                    # noqa: E402
from preparing_data.shuttleset_dataset import (                # noqa: E402
    create_bones, get_bone_pairs, get_merged_stroke_types, make_seq_len_same)

SEQ_LEN, HALF = 30, 15
VID_W, VID_H = 1280.0, 720.0
PAIRS = get_bone_pairs()
CLASSES = get_merged_stroke_types()           # ['未知球種'] + Top_x*12 + Bottom_x*12


def _normalize_joints(j: np.ndarray, bb: np.ndarray) -> np.ndarray:
    """Their scheme: offset by bbox top-left, scale by bbox diagonal. j: (m,17,2),
    bb: (m,4) corners (x1,y1,x2,y2). Zeros stay zero (= missing)."""
    dist = np.linalg.norm(bb[:, 2:] - bb[:, :2], axis=-1, keepdims=True)
    dist = np.where(dist > 0, dist, 1.0)
    out = np.zeros_like(j)
    for d in (0, 1):
        v = j[:, :, d]
        out[:, :, d] = np.where(v != 0.0, (v - bb[:, None, d]) / dist, 0.0)
    return out


def build_inputs(match_id: str):
    """(JnB, shuttle, video_len, labels) for every labeled stroke with a known class."""
    sdf = insights.stroke_df(match_id)
    smap = insights.side_map_from(sdf)
    con = db.connect(read_only=True)

    JnBs, shuttles, labels = [], [], []
    for _, s in sdf.iterrows():
        en = s["shot"] if s["shot"] in shuttleset._CN_EN.values() else None
        side = smap.get((int(s["set_no"]), s["hitter"]))   # 'near' | 'far'
        if en is None or side is None:
            continue
        c = int(s["frame_num"]) - 1
        f0, f1 = c - HALF, c + HALF

        joints = np.zeros((f1 - f0 + 1, 2, 17, 2), np.float32)
        bbox = np.zeros((f1 - f0 + 1, 2, 4), np.float32)
        for f, pid, kps, bb in con.execute(
                "SELECT frame_num, player_id, keypoints, bbox FROM tracks "
                "WHERE match_id=? AND frame_num BETWEEN ? AND ?",
                [match_id, f0, f1]).fetchall():
            m = 0 if pid == "far" else 1                   # Top before Bottom
            t = int(f) - f0
            if kps is not None:
                k = np.asarray(kps, np.float32).reshape(17, 3)
                joints[t, m] = k[:, :2]
            if bb is not None:
                x, y, w, h = bb                            # ours: center x,y,w,h
                bbox[t, m] = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)

        sh = np.zeros((f1 - f0 + 1, 2), np.float32)
        for f, sx, sy in con.execute(
                "SELECT frame_num, img_x, img_y FROM shuttle WHERE match_id=? "
                "AND visible AND frame_num BETWEEN ? AND ?",
                [match_id, f0, f1]).fetchall():
            sh[int(f) - f0] = (sx / VID_W, sy / VID_H)

        jn = np.stack([_normalize_joints(joints[t], bbox[t])
                       for t in range(len(joints))])
        pos_dummy = np.zeros((len(jn), 2, 2), np.float32)
        jn, _, sh, _ = make_seq_len_same(SEQ_LEN, jn, pos_dummy, sh)
        bones = create_bones(jn, PAIRS)
        JnBs.append(np.concatenate((jn, bones), axis=-2))   # (t, 2, 36, 2)
        shuttles.append(sh)
        labels.append(("Top_" if side == "far" else "Bottom_", en))
    con.close()
    return (np.stack(JnBs).astype(np.float32),
            np.stack(shuttles).astype(np.float32), labels)


def evaluate(match_id: str, batch: int = 256) -> dict:
    JnB, sh, labels = build_inputs(match_id)
    net = BST_0(in_dim=(17 + len(PAIRS)) * 2, n_class=len(CLASSES),
                seq_len=SEQ_LEN, depth_tem=2, depth_inter=1)
    net.load_state_dict(torch.load(WEIGHTS, map_location="cpu", weights_only=False))
    net.eval()

    preds = []
    with torch.no_grad():
        for i in range(0, len(JnB), batch):
            x = torch.from_numpy(JnB[i:i + batch])
            x = x.view(*x.shape[:-2], -1)                  # (b, t, 2, 72)
            s = torch.from_numpy(sh[i:i + batch])
            vl = torch.full((len(x),), SEQ_LEN, dtype=torch.long)
            preds.append(net(x, s, vl).argmax(1))
    preds = torch.cat(preds).numpy()

    side_ok = cls_ok = joint_ok = known = 0
    for p, (side, en) in zip(preds, labels):
        name = CLASSES[p]
        if name == "未知球種":
            continue
        known += 1
        p_side = "Top_" if name.startswith("Top_") else "Bottom_"
        p_en = shuttleset.canonical_shot_type(name.split("_", 1)[1])
        side_ok += p_side == side
        cls_ok += p_en == en
        joint_ok += (p_side == side) and (p_en == en)
    n = len(labels)
    out = dict(n=n, predicted_known=known,
               side_acc=round(side_ok / known, 4) if known else None,
               class_acc=round(cls_ok / known, 4) if known else None,
               joint_acc=round(joint_ok / known, 4) if known else None,
               end_to_end_class=round(cls_ok / n, 4))
    print(f"strokes: {n} · predicted a known class for {known}")
    print(f"side (Top/Bottom): {out['side_acc']:.1%}  ·  shot class (10 EN): "
          f"{out['class_acc']:.1%}  ·  joint: {out['joint_acc']:.1%}")
    print(f"end-to-end class accuracy over all strokes: {out['end_to_end_class']:.1%}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pretrained BST-0 on our CV inputs")
    ap.add_argument("match_id")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()
    evaluate(args.match_id, batch=args.batch)
