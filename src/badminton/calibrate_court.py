"""Interactive court calibration. Phase 0 step 3.

Opens a frame, you click the 4 OUTER (doubles) court corners in this order:
    1) near-left   2) near-right   3) far-right   4) far-left
("near" = baseline closest to camera; left/right from the camera's view.)

Computes the image->court homography and saves corners + H into config/matches.yaml.

Usage:
    python -m badminton.calibrate_court <match_id> --frame data/raw/frame.png

Run this in your own terminal (needs a GUI window). Tip: prefix with `!` in Claude Code.
Controls:  left-click = place corner   u = undo   r = reset   enter = confirm   q = quit
"""

from __future__ import annotations

import argparse

import numpy as np

from . import config, court


def pick_corners(frame_path: str) -> np.ndarray:
    import cv2

    img = cv2.imread(frame_path)
    if img is None:
        raise SystemExit(f"could not read {frame_path}")
    pts: list[tuple[int, int]] = []
    win = "calibrate court — click 4 outer corners (near-L, near-R, far-R, far-L)"

    def redraw() -> None:
        disp = img.copy()
        for i, (x, y) in enumerate(pts):
            cv2.circle(disp, (x, y), 6, (0, 255, 255), -1)
            cv2.putText(disp, f"{i+1}:{court.CORNER_LABELS[i]}", (x + 8, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        if len(pts) > 1:
            cv2.polylines(disp, [np.array(pts)], len(pts) == 4, (0, 200, 0), 2)
        cv2.imshow(win, disp)

    def on_mouse(event: int, x: int, y: int, *_: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))
            redraw()

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    redraw()
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k == ord("u") and pts:
            pts.pop(); redraw()
        elif k == ord("r"):
            pts.clear(); redraw()
        elif k == ord("q"):
            cv2.destroyAllWindows(); raise SystemExit("cancelled")
        elif k in (13, 10) and len(pts) == 4:  # enter
            break
    cv2.destroyAllWindows()
    return np.array(pts, dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--frame", required=True, help="path to a clean wide-shot frame")
    args = ap.parse_args()

    corners = pick_corners(args.frame)
    H = court.compute_homography(corners)

    # Sanity: corners should map back to the known court metres.
    mapped = court.image_to_court(corners, H)
    err = np.linalg.norm(mapped - court.COURT_CORNERS_M, axis=1).max()
    print("corner reprojection (should be ~0):")
    for lbl, m in zip(court.CORNER_LABELS, mapped):
        print(f"  {lbl:>10}: ({m[0]:.2f}, {m[1]:.2f}) m")
    print(f"max corner error: {err:.4f} m")

    config.update_match(args.match_id, {
        "court_corners_px": corners.tolist(),
        "homography": H.flatten().tolist(),
    })
    print(f"saved homography for {args.match_id} -> config/matches.yaml")


if __name__ == "__main__":
    main()
