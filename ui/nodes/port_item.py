
# ui/nodes/port_item.py
from __future__ import annotations
from typing import Optional

from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsSimpleTextItem, QGraphicsItem
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtCore import Qt, QPointF


# ---- Port colors (kept local to avoid coupling to the editor) ----
PORT_COLOR_NORMAL = QColor('#444')
PORT_COLOR_HOVER  = QColor('#666')
PORT_COLOR_VALID  = QColor('#4caf50')  # green
PORT_COLOR_INVALID= QColor('#e57373')  # red

# Port type colors
PORT_COLOR_IMAGE = QColor('#888')   # gray for image ports
PORT_COLOR_SCALAR = QColor('#4dd0e1')  # cyan for scalar ports


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node_item, name: str, is_output: bool, x: float, y: float,
                 radius: float = 5.0, port_type: str = "image"):
        # Center the ellipse on (0,0) locally so setPos works intuitively
        super().__init__(-radius, -radius, radius * 2, radius * 2, node_item)

        self.node_item = node_item
        self.name = name
        self.is_output = is_output
        self.radius = radius
        self.port_type = port_type

        # Style - color based on port type
        self._default_color = PORT_COLOR_SCALAR if port_type == "scalar" else PORT_COLOR_IMAGE
        self._hover_color = QColor('#fff')
        self.setBrush(QBrush(self._default_color))
        self.setPen(QPen(QColor('#333'), 1))
        
        self.setAcceptHoverEvents(True)
        # CRITICAL: Ensure ports are NEVER selectable by marquee
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        
        # Ensure ports are always on top of edges for easier interaction
        self.setZValue(10.0)
        
        # Internal Label
        self.label = QGraphicsSimpleTextItem(name, self)
        self.label.setBrush(QBrush(QColor('#bbb')))
        # Position label relative to port
        label_x = -self.label.boundingRect().width() - 10 if is_output else 10
        self.label.setPos(label_x, -radius - 2)

    def scene_center(self) -> QPointF:
        """Returns the center of the port in scene coordinates for edge drawing."""
        return self.mapToScene(QPointF(0, 0))

    def is_compatible(self, other: 'PortItem') -> bool:
        """Check if this port can connect to another port (must have same type)."""
        return self.port_type == other.port_type

    def hoverEnterEvent(self, event):
        self._highlight(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._highlight(False)
        super().hoverLeaveEvent(event)

    def _highlight(self, enabled: bool):
        """Helper to apply the hover/drag glow effect."""
        if enabled:
            self.setBrush(QBrush(self._hover_color))
            self.setPen(QPen(Qt.white, 2)) # Add a white ring
            self.setScale(1.5)             # Make it even larger (1.5x)
        else:
            self.setBrush(QBrush(self._default_color))
            self.setPen(QPen(QColor('#333'), 1))
            self.setScale(1.0)

    # These handle standard mouse-over (no drag)
    def hoverEnterEvent(self, event):
        self._highlight(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._highlight(False)
        super().hoverLeaveEvent(event)

    def dragLeaveEvent(self, event):
        self._highlight(False)
        event.accept()
