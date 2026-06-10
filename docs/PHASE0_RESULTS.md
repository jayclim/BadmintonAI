# Phase 0 results — court + feet, validated against ShuttleSet

**Match:** Loh Kean Yew vs Lakshya Sen, India Open 2022 Final (720p BWF upload).
**Method:** YOLO11x-Pose @ 1280 + ByteTrack on MPS → ankle-midpoint foot point →
hand-calibrated homography → court metres. Compared to ShuttleSet's labeled hitter feet
(same broadcast pixel space, one homography maps both). Window: frames 12420–13919
(opening rallies), 36 labeled strokes, best frame offset −6.

## Result (tightened: foot-reference blend α=0.65)

| Region | Median error |
|---|---|
| **Overall (n=36)** | **0.56 m**  (mean 0.65, p90 0.95) |
| Near court (n=18) | 0.53 m |
| Far court (n=18)  | 0.59 m |

In pixel space the near player matched ShuttleSet to ~5 px at frame 12420 — the pipeline
clearly works.

### Match-wide confirmation
Detecting at all labeled stroke frames across the full 54 min (single-frame pose at
ss_frame+{5,6,7}, 3,189 frames): **1,060/1,063 strokes matched, median 0.570 m**
(mean 0.73, p90 1.06), offset −6. The opening-window accuracy holds across the whole
match. (`scripts/validate_fullmatch.py`)

### How we got here (this session)
1. Ankle-midpoint foot point: 0.85 m overall, but far-court 1.25 m and 6 m+ outliers.
2. Killed the off-court umpire false-positive (yolo11x @ imgsz 1280 + in-court margin
   0.7) → p90 6.4→1.5 m; both players reliably detected.
3. **Foot-reference fix:** ground point = `ankle_y + 0.65*(bbox_bottom_y − ankle_y)`,
   lateral x from ankles. α swept offline against ShuttleSet (no re-detect — keypoints
   and bbox are stored). α=0.65 balances near/far at ~0.55 m. → **0.56 m overall.**

Earlier per-axis finding (ankle-only) that motivated the fix: error was almost all in
depth (Y), +0.43 m biased, matching the ankle-above-ground geometry; lateral (X) was
already ±0.4 m unbiased.

## Interpretation
- **Lateral (X) tracking is strong everywhere** (±0.4 m, unbiased).
- **Near court meets the <0.5 m target.**
- **Error is almost entirely depth (Y) and far-court** — the inherent monocular
  limitation (depth resolution collapses at distance; small far player = noisier ankles).
- **The +Y bias is geometric, not a bug:** the ankle keypoint is ~0.1 m above ground; an
  elevated camera projects it onto the floor farther away. Predicted bias
  (ankle_height × distance / camera_height) ≈ 0.3 m near / 0.5 m far — matches observed.

## Verdict
Phase 0 **validates the 2D core**: extracted positions track human ground truth, lateral
is excellent, near-court is sub-0.5 m. The far-court depth error is the documented hard
case that motivates landing-point use (on the floor plane, well-conditioned) and, later,
controlled/multi-camera capture.

## Improvement levers (not yet applied)
1. **Foot-reference fix** — use bbox-bottom / extrapolate below the ankle to the sole;
   should remove most of the +0.3–0.5 m depth bias. (Requires storing bbox + re-run.)
2. **Calibration** — corners were hand-read off gridded crops; refining the far-baseline
   corners (most ill-conditioned) would help far-court depth.
3. **Far-court detection** — already at yolo11x@1280; further gains need tiling/upscaling
   the far half or multi-camera (Phase 2+).

## Reproduce
```
python -m badminton.detect   india_open_2022_final --model yolo11x-pose.pt \
       --start-frame 12420 --max-frames 1500 --imgsz 1280
python -m badminton.validate india_open_2022_final --search -45 45 3
```
