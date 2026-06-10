# Design — Badminton CV Match Tracker & Tactical Analytics

## 1. Goal & scope

End-to-end system that converts badminton video into structured tactical data, then into:
1. a **coach-facing analytics dashboard** (positions, coverage, movement, rally clips), and
2. later, **natural-language tactical commentary/advice** ("you lost three points caught
   flat-footed after your cross-court drop").

**Sequencing decisions (locked):**
- Capture: broadcast now → *user-controlled single-camera capture* later. Controlled
  capture makes court calibration a one-time step (huge simplification).
- Product: analytics dashboard first → commentary/advice later.
- Discipline: singles first → doubles later.

## 2. The 2D-vs-3D fork (the decision that shapes everything)

- **Players live on the floor plane** → a court homography maps pixels → real court
  metres cleanly. Position, coverage, speed, recovery distance are all reliable from a
  single feed. **This is the solid core.**
- **The shuttle is inherently 3D** and a single image can't recover its height without
  physics priors. So true shuttle speed / apex / contact-height are *hard* and deferred.
  - BUT shuttle **landing points are on the floor plane**, so even pure-2D shuttle
    detection + the homography yields accurate landing coordinates cheaply.

**Strategy:** build the player-centric 2D product first; treat full 3D shuttle as a later
phase (monocular physics fitting, à la MonoTrack; stereo as a "pro" tier).

## 3. Architecture (modular pipeline, not monolithic)

```
Video ──┬─► Court mapping (homography, calibrate once)
        ├─► Player pipeline (detect → track → pose → feet→court coords)
        └─► Shuttle engine (DEFERRED: TrackNetV3 2D → MonoTrack 3D)
                       │
                       ▼
        Spatial-temporal sync → Tier-2 tracks → reduce to Tier-1 strokes
                       │
                       ▼
        Analytics dashboard  ──►  Commentary/advice (LLM over Tier-1)
```

## 4. Tooling choices (with trade-offs)

| Stage | Pick for v1 | Why / migrate to | Watch-out |
|---|---|---|---|
| Detection + pose | **YOLO11-Pose** | fastest to prototype → **RTMPose** (Apache-2.0) before productizing | Ultralytics is **AGPL-3.0** (commercial risk) |
| Player ID tracking | **ByteTrack** + "which court half" rule | singles has 1 player/half → near-free ID | doubles needs **BoT-SORT + ReID** |
| Court → coords | manual `cv2.getPerspectiveTransform` | controlled capture = calibrate once | broadcast cuts/zooms break a fixed matrix |
| Data layer | **Polars + DuckDB/Parquet** | SQL analytics, no server, event schema | — |
| Overlays | **supervision** + OpenCV | don't reinvent annotation drawing | — |
| Dashboard | **Streamlit** | ship analytics in weeks → **React+FastAPI** | Streamlit weak at frame-accurate video UX |
| Clipping | **ffmpeg-python** | fast, keyframe-accurate; moviepy only for compositing | — |
| Annotation | **CVAT** | video/keypoint labeling; the real cost is labels | — |
| Shuttle (deferred) | TrackNetV3 → MonoTrack | 2D then monocular 3D; stereo = pro tier | — |
| Commentary (deferred) | **Claude** over Tier-1 events | Opus for narratives, Haiku for bulk tagging | quality bounded by event-extraction quality |

## 5. Phased plan

- **Phase 0 — Court + feet (the proof):** static wide clip → homography → YOLO11-Pose →
  animated top-down dot map. Success = dots faithfully track the players on the 2D map.
- **Phase 1 — Player analytics:** heatmaps, distance, speed, recovery metrics; rally
  segmentation + auto-clips. **First shippable tool.**
- **Phase 2 — Shuttle in 2D:** TrackNetV3 + Kalman gap-fill → rally start/end + landing points.
- **Phase 3 — Shot classification:** pose + contact + shuttle screen-motion → 18 shot
  types. Heuristics first, learned model once labels exist.
- **Phase 4 — Tactical/causal commentary:** the "why was the point lost" engine. Research-grade.

**Parallel track (decoupled from CV):** build Phases 3–4's logic on **ShuttleSet now**,
since it already provides labeled strokes + player positions. The dashboard/commentary
can be demoed before the vision pipeline produces a single frame.

## 6. Capture spec (for controlled-capture users)
Prescribed position: **elevated, centered, behind one baseline.** Real-world reference
from the VideoBadminton dataset: **~2 m behind baseline, ~4.5 m high, ~30° tilt.**

## 7. Open questions before building — see end of SCHEMA.md / project notes.
