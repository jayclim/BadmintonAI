"""Court geometry, coordinate frame, and homography helpers.

Canonical coordinate frame (metres), locked in docs/DESIGN.md:
    origin (0, 0) at one outer court corner,
    X across the 6.10 m width   -> X in [0, 6.10],
    Y along the 13.40 m length  -> Y in [0, 13.40],
    net at Y = 6.70 m.
All downstream data (homography output, ShuttleSet import) normalizes to this frame.
"""

from __future__ import annotations

import numpy as np

# Official BWF dimensions (outer doubles boundary).
COURT_WIDTH_M = 6.10
COURT_LENGTH_M = 13.40
NET_Y_M = COURT_LENGTH_M / 2.0  # 6.70

# Singles sidelines are inset from the doubles outer line by this much.
SINGLES_SIDELINE_INSET_M = 0.46  # doubles width 6.10 -> singles width 5.18

# The 4 outer (doubles) corners, in the canonical frame, in a FIXED order.
# calibrate_court.py must collect the image-pixel corners in this same order.
#   0: near-left, 1: near-right, 2: far-right, 3: far-left
# ("near" = baseline closest to camera = Y=0 side; left/right from camera view)
COURT_CORNERS_M = np.array(
    [
        [0.0,          0.0],            # 0 near-left
        [COURT_WIDTH_M, 0.0],          # 1 near-right
        [COURT_WIDTH_M, COURT_LENGTH_M],  # 2 far-right
        [0.0,          COURT_LENGTH_M],   # 3 far-left
    ],
    dtype=np.float32,
)

CORNER_LABELS = ["near-left", "near-right", "far-right", "far-left"]


def compute_homography(corners_px: np.ndarray) -> np.ndarray:
    """Image-pixel court corners (4x2, in COURT_CORNERS_M order) -> 3x3 homography
    mapping image pixels to court metres."""
    import cv2

    src = np.asarray(corners_px, dtype=np.float32).reshape(4, 2)
    return cv2.getPerspectiveTransform(src, COURT_CORNERS_M)


def image_to_court(points_px: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Apply homography H to image-pixel points (N,2) -> court metres (N,2)."""
    import cv2

    pts = np.asarray(points_px, dtype=np.float32).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(pts, np.asarray(H, dtype=np.float32))
    return out.reshape(-1, 2)


def which_half(court_y: float) -> str:
    """Singles ID trick: assign 'near' / 'far' by court half (net at NET_Y_M)."""
    return "near" if court_y < NET_Y_M else "far"


def in_court(xy, margin: float = 0.0) -> bool:
    """True if a court-metre point is inside the court (+ margin for lunges).
    Rejects off-court people (umpire, line judges, coaches)."""
    x, y = float(xy[0]), float(xy[1])
    return (-margin <= x <= COURT_WIDTH_M + margin
            and -margin <= y <= COURT_LENGTH_M + margin)


# TODO(Phase 1): implement ShuttleSet's 16-grid `area` scheme
# (9 zones inside the singles court + 7 outside) for tactical phrasing.
def court_area(court_x: float, court_y: float) -> int | None:
    raise NotImplementedError("16-grid area mapping — define against ShuttleSet's layout")
