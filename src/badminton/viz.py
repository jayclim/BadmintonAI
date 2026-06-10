"""Top-down court rendering + colors shared by the overlay video and the dashboard."""

from __future__ import annotations

import cv2
import numpy as np

from . import court as C

SCALE = 34   # px per metre (minimap)
PAD = 22

# BGR colors (cv2)
NEAR_C = (255, 140, 0)    # near player — blue/cyan
FAR_C = (0, 90, 255)      # far player — orange/red
SS_C = (0, 235, 235)      # ShuttleSet label — yellow

_LINES = None  # cached metre-space line segments


def _segments():
    global _LINES
    if _LINES is not None:
        return _LINES
    W, L, net, ins = C.COURT_WIDTH_M, C.COURT_LENGTH_M, C.NET_Y_M, C.SINGLES_SIDELINE_INSET_M
    _LINES = [
        ((0, 0), (W, 0)), ((0, L), (W, L)), ((0, 0), (0, L)), ((W, 0), (W, L)),  # outer
        ((ins, 0), (ins, L)), ((W - ins, 0), (W - ins, L)),                       # singles sidelines
        ((0, net - 1.98), (W, net - 1.98)), ((0, net + 1.98), (W, net + 1.98)),   # short service
        ((0, 0.76), (W, 0.76)), ((0, L - 0.76), (W, L - 0.76)),                   # doubles long service
        ((W / 2, 0), (W / 2, net - 1.98)), ((W / 2, net + 1.98), (W / 2, L)),     # center line
    ]
    return _LINES


def court_size() -> tuple[int, int]:
    return (int(C.COURT_WIDTH_M * SCALE + 2 * PAD),
            int(C.COURT_LENGTH_M * SCALE + 2 * PAD))


def to_px(x: float, y: float) -> tuple[int, int]:
    """Court metres -> minimap pixel (near baseline y=0 at the bottom)."""
    return (int(round(PAD + x * SCALE)),
            int(round(PAD + (C.COURT_LENGTH_M - y) * SCALE)))


def render_court() -> np.ndarray:
    w, h = court_size()
    img = np.full((h, w, 3), (60, 110, 60), np.uint8)
    for (x1, y1), (x2, y2) in _segments():
        cv2.line(img, to_px(x1, y1), to_px(x2, y2), (235, 235, 235), 1, cv2.LINE_AA)
    cv2.line(img, to_px(0, C.NET_Y_M), to_px(C.COURT_WIDTH_M, C.NET_Y_M),
             (255, 255, 255), 2, cv2.LINE_AA)
    return img


def draw_point(img, x: float, y: float, color, r: int = 5, label: str | None = None):
    p = to_px(x, y)
    cv2.circle(img, p, r, color, -1, cv2.LINE_AA)
    cv2.circle(img, p, r, (0, 0, 0), 1, cv2.LINE_AA)
    if label:
        cv2.putText(img, label, (p[0] + 6, p[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
    return img


def mpl_court(ax):
    """Draw the court into a matplotlib axis (metre coordinates) for the dashboard."""
    from matplotlib.patches import Rectangle
    W, L, net = C.COURT_WIDTH_M, C.COURT_LENGTH_M, C.NET_Y_M
    # axis('off') below hides the axes facecolor patch — paint the floor explicitly
    ax.add_patch(Rectangle((-0.6, -0.6), W + 1.2, L + 1.2,
                           facecolor=(0.27, 0.45, 0.27), edgecolor="none", zorder=0))
    for (x1, y1), (x2, y2) in _segments():
        ax.plot([x1, x2], [y1, y2], color="white", lw=1)
    ax.plot([0, W], [net, net], color="yellow", lw=2)
    ax.set_xlim(-0.6, W + 0.6)
    ax.set_ylim(-0.6, L + 0.6)
    ax.set_aspect("equal")
    ax.axis("off")
