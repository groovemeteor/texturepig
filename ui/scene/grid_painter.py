
# ui/scene/grid_painter.py
from __future__ import annotations
from typing import Any

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPen


def draw_grid(
    painter: Any,
    rect: QRectF,
    spacing: int,
    major_every: int,
    color_minor,
    color_major,
) -> None:
    """
    Draw a subtle grid in scene space.
    - painter: QPainter already set up by QGraphicsView.drawBackground
    - rect: visible scene rect
    - spacing: pixel spacing between minor lines (scene units)
    - major_every: draw a major line every N minor lines
    - color_minor / color_major: QColor instances
    """
    # Determine visible scene rect
    left   = int(np.floor(rect.left()))
    right  = int(np.ceil(rect.right()))
    top    = int(np.floor(rect.top()))
    bottom = int(np.ceil(rect.bottom()))

    s = max(1, int(spacing))
    me = max(1, int(major_every))

    # Starting positions snapped to grid
    first_x = (left // s) * s
    first_y = (top  // s) * s

    # Cosmetic pens so lines stay thin with zoom
    p_minor = QPen(color_minor, 0)
    p_major = QPen(color_major, 0)

    # Vertical lines
    x = first_x
    while x <= right:
        idx = (x // s)
        painter.setPen(p_major if (idx % me == 0) else p_minor)
        painter.drawLine(x, top, x, bottom)
        x += s

    # Horizontal lines
    y = first_y
    while y <= bottom:
        idx = (y // s)
        painter.setPen(p_major if (idx % me == 0) else p_minor)
        painter.drawLine(left, y, right, y)
        y += s
