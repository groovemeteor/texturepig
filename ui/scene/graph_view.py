
# ui/scene/graph_view.py
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRectF, QEvent
from PySide6.QtGui import QColor, QPainter, QMouseEvent
from PySide6.QtWidgets import QGraphicsView

from texture_pig.ui.scene.grid_painter import draw_grid


# --- Grid config (scene units) ---
GRID_SPACING      = 32
GRID_COLOR_MAJOR  = QColor(255, 255, 255, 28)   # very dim major lines
GRID_COLOR_MINOR  = QColor(255, 255, 255, 10)   # even dimmer minor lines
GRID_MAJOR_EVERY  = 4


class GraphView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QColor('#1e1e1e'))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFocusPolicy(Qt.StrongFocus)

        # Zoom params
        self._zoom = 1.0
        self._zoom_min = 0.2
        self._zoom_max = 4.0
        self._zoom_step = 1.1

        # Default selection mode; hand tool on middle mouse
        self.setDragMode(QGraphicsView.RubberBandDrag)

    # ---------- Background ----------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        draw_grid(
            painter=painter,
            rect=rect,
            spacing=GRID_SPACING,
            major_every=GRID_MAJOR_EVERY,
            color_minor=GRID_COLOR_MINOR,
            color_major=GRID_COLOR_MAJOR,
        )

    # ---------- Zoom ----------
    def wheelEvent(self, event):
        # Plain wheel or Ctrl+wheel for zoom
        if (event.modifiers() == Qt.NoModifier) or (event.modifiers() & Qt.ControlModifier):
            delta = event.angleDelta().y()
            if delta == 0:
                return
            factor = self._zoom_step if delta > 0 else 1.0 / self._zoom_step
            new_zoom = max(self._zoom_min, min(self._zoom_max, self._zoom * factor))
            factor = new_zoom / self._zoom
            if factor != 1.0:
                self._zoom = new_zoom
                self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0

    def zoom_in(self):
        self._apply_zoom(self._zoom * self._zoom_step)

    def zoom_out(self):
        self._apply_zoom(self._zoom / self._zoom_step)

    def _apply_zoom(self, new_zoom):
        nz = max(self._zoom_min, min(self._zoom_max, new_zoom))
        factor = nz / self._zoom
        if factor != 1.0:
            self._zoom = nz
            self.scale(factor, factor)

    # ---------- Hand tool on middle mouse ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            posF = event.position() if hasattr(event, 'position') else event.pos()
            gposF = event.globalPosition() if hasattr(event, 'globalPosition') else event.globalPos()
            fake = QMouseEvent(
                QEvent.MouseButtonPress, posF, gposF,
                Qt.LeftButton, Qt.LeftButton, event.modifiers()
            )
            super().mousePressEvent(fake)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            posF = event.position() if hasattr(event, 'position') else event.pos()
            gposF = event.globalPosition() if hasattr(event, 'globalPosition') else event.globalPos()
            fake = QMouseEvent(
                QEvent.MouseButtonRelease, posF, gposF,
                Qt.LeftButton, Qt.LeftButton, event.modifiers()
            )
            super().mouseReleaseEvent(fake)
            self.setDragMode(QGraphicsView.RubberBandDrag)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- Keyboard shortcuts ----------
    def keyPressEvent(self, event):
        # SPACE: open Quick Add palette (when the view has focus)
        if event.key() == Qt.Key_Space and (event.modifiers() == Qt.NoModifier):
            if hasattr(self, 'scene') and hasattr(self.scene(), 'editor'):
                self.scene().editor.open_quick_add()
                event.accept()
                return

        if event.key() == Qt.Key_0 and (event.modifiers() & Qt.ControlModifier):
            self.reset_zoom()
            event.accept()
            return
        if (event.modifiers() & Qt.ControlModifier) and event.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_in()
            event.accept()
            return
        if (event.modifiers() & Qt.ControlModifier) and event.key() == Qt.Key_Minus:
            self.zoom_out()
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        # No special space handling anymore
        super().keyReleaseEvent(event)
