# ui/palette/gradient_editor.py
"""
Visual gradient bar editor with draggable color stops.
Supports RGBA colors and integrates with undo/redo system.
"""
from __future__ import annotations
from typing import List, Tuple, Optional

from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QLinearGradient, QPen, QBrush,
    QPainterPath, QPixmap, QMouseEvent, QPaintEvent
)
from PySide6.QtWidgets import QWidget, QColorDialog


def _checkerboard(size: int = 8) -> QPixmap:
    """Create a checkerboard pattern for transparency preview."""
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    c1 = QColor(180, 180, 180)
    c2 = QColor(220, 220, 220)
    p.fillRect(0, 0, size, size, c1)
    p.fillRect(size, 0, size, size, c2)
    p.fillRect(0, size, size, size, c2)
    p.fillRect(size, size, size, size, c1)
    p.end()
    return pix


class GradientStopEditor(QWidget):
    """
    Visual gradient bar editor with draggable color stops.

    Interactions:
    - Click on gradient bar: Add new stop at that position
    - Click on handle: Select stop
    - Drag handle: Reposition stop
    - Double-click handle: Open color picker
    - Right-click handle: Delete stop (if more than 2)

    Signals:
        stopsChanged(tuple): Emitted when stops change, with immutable tuple data
    """
    stopsChanged = Signal(object)  # tuple of (pos, (R, G, B, A))

    def __init__(self, stops: tuple = None, parent: QWidget = None, debounce_ms: int = 60):
        super().__init__(parent)

        # Default to black-to-white gradient
        if stops is None:
            stops = ((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))

        self._stops: List[Tuple[float, Tuple[float, float, float, float]]] = [
            (float(pos), tuple(float(c) for c in color))
            for pos, color in stops
        ]
        self._selected_index: Optional[int] = None
        self._dragging: bool = False
        self._drag_start_x: float = 0.0
        self._drag_moved: bool = False  # Track if actual movement occurred

        # Debouncer for smooth dragging
        self._debouncer = QTimer(self)
        self._debouncer.setSingleShot(True)
        self._debouncer.timeout.connect(self._emit_stops)
        self._debounce_ms = debounce_ms

        # UI dimensions
        self._bar_height = 24
        self._handle_size = 10
        self._padding = 6  # Left/right padding for handles at edges

        self.setMinimumHeight(self._bar_height + self._handle_size + 8)
        self.setMinimumWidth(150)
        self.setMouseTracking(True)

        # Checkerboard for alpha preview
        self._checker = _checkerboard(6)

    # ---------- Public API ----------

    def get_stops(self) -> tuple:
        """Return stops as immutable tuple for undo/redo."""
        return tuple((pos, tuple(color)) for pos, color in self._stops)

    def set_stops(self, stops: tuple, block_signal: bool = False):
        """Set stops from tuple (used by undo/redo)."""
        self._stops = [
            (float(pos), tuple(float(c) for c in color))
            for pos, color in stops
        ]
        self._selected_index = None
        self.update()
        if not block_signal:
            self._emit_stops_immediate()

    # ---------- Coordinate Conversion ----------

    def _pos_to_x(self, pos: float) -> float:
        """Convert gradient position [0,1] to widget x coordinate."""
        usable_width = self.width() - 2 * self._padding
        return self._padding + pos * usable_width

    def _x_to_pos(self, x: float) -> float:
        """Convert widget x coordinate to gradient position [0,1]."""
        usable_width = self.width() - 2 * self._padding
        pos = (x - self._padding) / max(usable_width, 1)
        return max(0.0, min(1.0, pos))

    # ---------- Painting ----------

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bar_rect = QRectF(
            self._padding, 0,
            self.width() - 2 * self._padding,
            self._bar_height
        )

        # Draw checkerboard background
        painter.save()
        painter.setClipRect(bar_rect)
        brush = QBrush(self._checker)
        painter.fillRect(bar_rect, brush)
        painter.restore()

        # Draw gradient bar
        self._draw_gradient_bar(painter, bar_rect)

        # Draw border
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawRect(bar_rect)

        # Draw stop handles
        for i, (pos, color) in enumerate(self._stops):
            self._draw_stop_handle(painter, i, pos, color, selected=(i == self._selected_index))

        painter.end()

    def _draw_gradient_bar(self, painter: QPainter, rect: QRectF):
        """Draw the gradient using QLinearGradient."""
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)

        for pos, (r, g, b, a) in self._stops:
            gradient.setColorAt(pos, QColor.fromRgbF(r, g, b, a))

        painter.fillRect(rect, gradient)

    def _draw_stop_handle(self, painter: QPainter, index: int, pos: float,
                          color: Tuple[float, float, float, float], selected: bool = False):
        """Draw a triangular handle below the bar."""
        x = self._pos_to_x(pos)
        y = self._bar_height + 2

        r, g, b, a = color
        fill_color = QColor.fromRgbF(r, g, b, 1.0)  # Solid fill (ignore alpha for handle)

        # Triangle pointing up
        half_w = self._handle_size / 2
        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x - half_w, y + self._handle_size)
        path.lineTo(x + half_w, y + self._handle_size)
        path.closeSubpath()

        # Draw checkerboard inside handle if alpha < 1
        if a < 0.99:
            painter.save()
            painter.setClipPath(path)
            brush = QBrush(self._checker)
            painter.fillPath(path, brush)
            painter.restore()

        # Fill with color (respects alpha)
        painter.fillPath(path, QColor.fromRgbF(r, g, b, a))

        # Outline
        if selected:
            painter.setPen(QPen(QColor(255, 200, 0), 2))
        else:
            painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.drawPath(path)

    # ---------- Hit Testing ----------

    def _hit_test_handle(self, point: QPointF) -> Optional[int]:
        """Return index of handle at point, or None."""
        y = self._bar_height + 2
        half_w = self._handle_size / 2 + 2  # Small tolerance

        for i, (pos, _) in enumerate(self._stops):
            hx = self._pos_to_x(pos)
            if (abs(point.x() - hx) <= half_w and
                    y <= point.y() <= y + self._handle_size + 2):
                return i
        return None

    def _hit_test_bar(self, point: QPointF) -> bool:
        """Return True if point is inside gradient bar."""
        bar_rect = QRectF(
            self._padding, 0,
            self.width() - 2 * self._padding,
            self._bar_height
        )
        return bar_rect.contains(point)

    # ---------- Mouse Events ----------

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()

        if event.button() == Qt.LeftButton:
            handle_idx = self._hit_test_handle(pos)

            if handle_idx is not None:
                # Select and start dragging
                self._selected_index = handle_idx
                self._dragging = True
                self._drag_start_x = pos.x()
                self._drag_moved = False  # Reset movement flag
                self.update()
            elif self._hit_test_bar(pos):
                # Add new stop
                self._add_stop_at(self._x_to_pos(pos.x()))

        elif event.button() == Qt.RightButton:
            # Right-click to delete stop
            handle_idx = self._hit_test_handle(pos)
            if handle_idx is not None and len(self._stops) > 2:
                self._remove_stop(handle_idx)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._selected_index is not None:
            new_pos = self._x_to_pos(event.position().x())

            # Update stop position
            color = self._stops[self._selected_index][1]
            self._stops[self._selected_index] = (new_pos, color)

            # Re-sort and update selection
            self._sort_stops_and_update_selection()

            self._drag_moved = True  # Mark that actual movement occurred
            self.update()
            self._debounce_emit()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            # Only emit if actual movement occurred (allows double-click to work)
            if self._drag_moved:
                self._emit_stops_immediate()
            self._drag_moved = False

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Double-click on handle to edit color."""
        handle_idx = self._hit_test_handle(event.position())
        if handle_idx is not None:
            self._open_color_picker(handle_idx)

    # ---------- Stop Management ----------

    def _add_stop_at(self, pos: float):
        """Add a new stop at position, interpolating color from neighbors."""
        pos = max(0.0, min(1.0, pos))

        # Find color by interpolating between surrounding stops
        color = self._interpolate_color_at(pos)

        self._stops.append((pos, color))
        self._stops.sort(key=lambda s: s[0])

        # Select the new stop
        for i, (p, _) in enumerate(self._stops):
            if abs(p - pos) < 1e-6:
                self._selected_index = i
                break

        self.update()
        self._emit_stops_immediate()

    def _remove_stop(self, index: int):
        """Remove stop at index (if more than 2 stops remain)."""
        if len(self._stops) <= 2:
            return

        del self._stops[index]

        # Adjust selection
        if self._selected_index is not None:
            if self._selected_index == index:
                self._selected_index = None
            elif self._selected_index > index:
                self._selected_index -= 1

        self.update()
        self._emit_stops_immediate()

    def _interpolate_color_at(self, pos: float) -> Tuple[float, float, float, float]:
        """Interpolate color at position from surrounding stops."""
        if not self._stops:
            return (0.5, 0.5, 0.5, 1.0)

        # Find surrounding stops
        prev_stop = self._stops[0]
        next_stop = self._stops[-1]

        for i, (p, c) in enumerate(self._stops):
            if p <= pos:
                prev_stop = (p, c)
            if p >= pos:
                next_stop = (p, c)
                break

        p0, c0 = prev_stop
        p1, c1 = next_stop

        if abs(p1 - p0) < 1e-8:
            return c0

        t = (pos - p0) / (p1 - p0)
        return tuple(
            (1.0 - t) * c0[i] + t * c1[i]
            for i in range(4)
        )

    def _sort_stops_and_update_selection(self):
        """Sort stops by position and track selected stop."""
        if self._selected_index is None:
            self._stops.sort(key=lambda s: s[0])
            return

        # Remember selected stop's identity
        selected_stop = self._stops[self._selected_index]

        self._stops.sort(key=lambda s: s[0])

        # Find new index of selected stop
        for i, stop in enumerate(self._stops):
            if stop is selected_stop:
                self._selected_index = i
                break

    def _open_color_picker(self, index: int):
        """Open color dialog to edit stop's color."""
        pos, (r, g, b, a) = self._stops[index]

        current_color = QColor.fromRgbF(r, g, b, a)

        dlg = QColorDialog(current_color, self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)

        if dlg.exec():
            new_color = dlg.selectedColor()
            new_rgba = (
                new_color.redF(),
                new_color.greenF(),
                new_color.blueF(),
                new_color.alphaF()
            )
            self._stops[index] = (pos, new_rgba)
            self.update()
            self._emit_stops_immediate()

    # ---------- Signal Emission ----------

    def _emit_stops(self):
        """Emit stopsChanged signal with immutable tuple."""
        self.stopsChanged.emit(self.get_stops())

    def _emit_stops_immediate(self):
        """Emit immediately (for final actions like mouse release, dialog)."""
        self._debouncer.stop()
        self._emit_stops()

    def _debounce_emit(self):
        """Debounce emissions for smooth dragging."""
        if self._debounce_ms <= 0:
            self._emit_stops()
        else:
            self._debouncer.start(self._debounce_ms)
