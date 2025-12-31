
# ui/nodes/edge_item.py
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPen, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import QGraphicsPathItem, QMenu

from .port_item import PortItem

# Edge colors based on port type
EDGE_COLOR_IMAGE = QColor('#999')
EDGE_COLOR_SCALAR = QColor('#4dd0e1')


class EdgeItem(QGraphicsPathItem):
    def __init__(self, src: Optional[PortItem], dst: Optional[PortItem]):
        super().__init__()
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, False)

        self.src: Optional[PortItem] = src
        self.dst: Optional[PortItem] = dst
        self.src_pos: Optional[QPointF] = None
        self.dst_pos: Optional[QPointF] = None

        # Determine edge color based on port type
        port_type = src.port_type if src else (dst.port_type if dst else "image")
        edge_color = EDGE_COLOR_SCALAR if port_type == "scalar" else EDGE_COLOR_IMAGE

        self._normal_pen = QPen(edge_color, 2)
        self._hover_pen  = QPen(edge_color.lighter(130), 2)
        self._sel_pen    = QPen(QColor('#ccc'), 3)
        self.update_path()

    # ---- Endpoints can be ports or raw positions during drag ----
    def set_src_port(self, port: Optional[PortItem]):
        self.src = port
        self.src_pos = None

    def set_dst_port(self, port: Optional[PortItem]):
        self.dst = port
        self.dst_pos = None

    def set_src_pos(self, pos: QPointF):
        self.src = None
        self.src_pos = QPointF(pos)

    def set_dst_pos(self, pos: QPointF):
        self.dst = None
        self.dst_pos = QPointF(pos)

    def _p1(self) -> QPointF:
        return self.src.scene_center() if self.src is not None else (self.src_pos or QPointF(0, 0))

    def _p2(self) -> QPointF:
        return self.dst.scene_center() if self.dst is not None else (self.dst_pos or QPointF(0, 0))

    def update_path(self):
        p1 = self._p1()
        p2 = self._p2()
        
        path = QPainterPath(p1)
        
        # Improved cubic tangent logic
        # dx is the horizontal distance between ports, but capped to a minimum
        # to prevent "flat" lines when nodes are stacked vertically.
        dist = abs(p2.x() - p1.x())
        dx = max(dist * 0.5, 50.0) 
        
        path.cubicTo(
            QPointF(p1.x() + dx, p1.y()), 
            QPointF(p2.x() - dx, p2.y()), 
            p2
        )
        
        self.setPath(path)
        self._apply_pen()

    def shape(self) -> QPainterPath:
        """
        Return a wider path for mouse interaction. 
        This makes it MUCH easier to click/select the edge.
        """
        path = self.path()
        stroker = QPainterPathStroker()
        stroker.setWidth(20) # 20px wide invisible hit-box
        return stroker.createStroke(path)

    def _apply_pen(self):
        # ... existing code ...
        self._sel_pen    = QPen(QColor('#ffca28'), 3) # Use a highlight color (Amber)
        
        pen = self._normal_pen
        if self.isSelected():
            pen = self._sel_pen
        elif self.isUnderMouse():
            pen = self._hover_pen
            
        self.setPen(pen)

    def hoverEnterEvent(self, event):
        self._apply_pen()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._apply_pen()
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        act_del = menu.addAction("Delete Link")
        action = menu.exec(event.screenPos())
        if action == act_del:
            sc = self.scene()
            if hasattr(sc, 'delete_edge'):
                sc.delete_edge(self)
        event.accept()
