# Third-party licenses & redistribution notes

COURTSIDE's own code is original, MIT-licensed ([`../LICENSE`](../LICENSE)). It depends on third-party models and libraries with the
licenses below. This note exists so the obligations are explicit before anyone commits weights,
redistributes, or deploys the pipeline as a hosted service.

## ⚠️ AGPL-3.0 — Ultralytics YOLO11 (the one with real obligations)

- **Package:** `ultralytics` (YOLO11-Pose) · https://github.com/ultralytics/ultralytics
- **License:** AGPL-3.0.
- **What that means here:**
  - **Weights are NOT committed.** `*.pt` is gitignored; `yolo11{m,x}-pose.pt` are
    auto-downloaded by ultralytics at first use. Keep it that way — committing or otherwise
    redistributing the weights pulls them under AGPL terms.
  - **Network-use clause:** AGPL-3.0 §13 means if you run the Python pipeline as a service users
    interact with over a network, you must offer those users the corresponding source. The
    shipped **web dashboard is static and does not run YOLO at inference** (it serves
    precomputed JSON + clips), so the static site is unaffected — this applies only to hosting
    the CV pipeline itself.
  - For a closed-source or commercially-licensed deployment, Ultralytics sells an Enterprise
    license — that's the migration path. (HANDOFF already notes the longer-term plan to swap
    YOLO-Pose for RTMPose, which is Apache-2.0, to drop this constraint.)

## MIT — vendored models (attribution only)

Both are git-cloned into `third_party/` and keep their upstream `LICENSE` files; preserve those
copyright notices in any redistribution.

- **TrackNetV3** (qaz812345) — `third_party/TrackNetV3/LICENSE` ·
  https://github.com/qaz812345/TrackNetV3 · paper DOI 10.1145/3595916.3626370
- **BST** (Jing-Yuan Chang) — `third_party/BST/LICENSE` · https://arxiv.org/abs/2502.21085
  (CVPRW 2026). Pretrained weights used as-is, zero fine-tuning.

## Dataset

- **ShuttleSet / ShuttleSet22** (CoachAI) · https://github.com/wywyWang/CoachAI-Projects —
  human stroke-level annotations, used as ground truth and as the Tier-1 schema. The
  CoachAI-Projects repo is MIT-licensed (verified 2026-08); cite the ShuttleSet paper in
  any published results.

## Everything else

Standard permissive runtime deps (PyTorch BSD-3, OpenCV Apache-2.0, DuckDB MIT, pandas/NumPy
BSD, scikit-learn BSD, Next.js/React MIT, Tailwind MIT) — no special obligations.
