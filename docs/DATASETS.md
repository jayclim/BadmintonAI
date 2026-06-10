# Annotated badminton datasets

Practical caveat: BWF broadcast footage is copyrighted, so most datasets ship
**annotations + video IDs/timestamps**, not raw video — you reconstruct frames by
downloading the matches yourself.

## Directly downloadable (GitHub)
- **ShuttleSet** (KDD'23) — stroke-level: 18 shot types, hit + landing locations, both
  players' court positions per stroke. 104 sets / 3,685 rallies / **36,492 strokes** / 44
  matches (2018–21). MIT license. Repo: `github.com/wywyWang/CoachAI-Projects` (incl.
  ShuttleSet22 extension). arXiv 2306.04948. **← our Tier-1 backbone.**
- **Shuttlecock Trajectory Dataset** (TrackNet/V2) — per-frame shuttle (x,y)+visibility,
  26 videos / 78,200 frames / 1280×720@30fps.
- **TrackNetV3** — pretrained shuttle tracker + code (97.5% acc). `github.com/qaz812345/TrackNetV3`.
- **MonoTrack** — full monocular pipeline: court detect, MMPose, modified TrackNet, HitNet
  (hit detection), GRU 3D reconstruction. `github.com/jhwang7628/monotrack`, arXiv 2204.01899.
- **SoloShuttlePose** — runnable end-to-end court+pose+shuttle. `github.com/sunwuzhou03/SoloShuttlePose`.

## Request from authors
- **BadmintonDB** — manually labeled shuttle positions, rally-segmented (23 train + 3 test).
- **VideoBadminton** (arXiv 2403.12385) — action clips + pose. Camera spec: ~2m behind
  baseline, ~4.5m high, 30° tilt (our capture reference).
- **FineBadminton** (ACM MM'25, arXiv 2508.07554) — 3-level hierarchy incl. Decision
  Evaluation; closest to the "why was the point lost" goal. finebadminton.github.io/FineBadminton.
- **BFMD** (arXiv 2603.25533) — 20+ hrs, 19 full matches singles+doubles, 16,751 hit
  events w/ shot captions, shuttle trajectories, pose.
