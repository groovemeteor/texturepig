
# ui/scene/graph_scene.py
from __future__ import annotations
import logging
from typing import Optional, List, Dict

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsScene, QGraphicsItem, QMessageBox

logger = logging.getLogger(__name__)

from texture_pig.ui.nodes.port_item import PortItem
from texture_pig.ui.nodes.edge_item import EdgeItem
from texture_pig.ui.nodes.node_item import NodeItem


class GraphScene(QGraphicsScene):
    def __init__(self, editor: 'GraphEditor'):
        super().__init__(editor)
        self.editor = editor
        self.nodes: List[NodeItem] = []
        self.edges: List[EdgeItem] = []

        # Set a large fixed scene rect to allow panning even when content fits in view
        self.setSceneRect(-10000, -10000, 20000, 20000)

        # Drag connection state
        self.drag_edge: Optional[EdgeItem] = None
        self.drag_from_port: Optional[PortItem] = None
        self.drag_free_end: Optional[str] = None  # 'src' or 'dst'

    # ---------- Edge maintenance ----------
    def _refresh_edge_paths(self):
        for e in self.edges:
            e.update_path()

    def update_edges_for_node(self, node_item: NodeItem):
        for e in self.edges:
            if e.src and e.src.node_item is node_item:
                e.update_path()
            if e.dst and e.dst.node_item is node_item:
                e.update_path()

    # ---------- Nodes ----------
    def add_node_item(self, node_item: NodeItem, pos: QPointF):
        self.addItem(node_item)
        node_item.setPos(pos)
        self.nodes.append(node_item)

        try:
            node_item.layout_ports_and_resize()
        except Exception:
            pass

        # Initial preview render
        self.editor.update_previews_from(node_item)

    def delete_node_item(self, node_item: NodeItem):
        if getattr(node_item, '_is_output_node', False):
            QMessageBox.information(None, 'Output Node', 'The Output node cannot be deleted.')
            return

        # Remove edges involving the node
        for edge in list(self.edges):
            if (edge.src and edge.src.node_item is node_item) or (edge.dst and edge.dst.node_item is node_item):
                self.delete_edge(edge)

        if node_item in self.nodes:
            self.nodes.remove(node_item)
        self.removeItem(node_item)

        # Backend removal
        try:
            self.editor.remove_backend_node(node_item.backend_node)
        except Exception:
            logger.exception("Backend node removal failed")

        # Refresh previews
        if self.nodes:
            self.editor.update_previews_from(self.nodes[0])

    # ---------- Edge lookup / deletion ----------
    def find_edge_for_input_port(self, dst_port: PortItem) -> Optional[EdgeItem]:
        for e in self.edges:
            if e.dst is dst_port:
                return e
        return None

    def delete_edge(self, edge: EdgeItem):
        dst_node_item = edge.dst.node_item if edge.dst else None

        # Clear backend input connection (keep key present)
        if edge.dst is not None:
            dst_node = edge.dst.node_item.backend_node
            in_name = edge.dst.name
            try:
                if hasattr(dst_node, 'inputs'):
                    if in_name in dst_node.inputs:
                        dst_node.inputs[in_name] = None
                    else:
                        key = in_name.lower() if hasattr(in_name, 'lower') else in_name
                        if key in dst_node.inputs:
                            dst_node.inputs[key] = None
                    dst_node.invalidate()
            except Exception:
                pass

        if edge in self.edges:
            self.edges.remove(edge)
        self.removeItem(edge)

        if dst_node_item is not None:
            self.editor.update_previews_from(dst_node_item)

    # ---------- Drag connect ----------
    def _begin_drag_from_output(self, out_port: PortItem):
        self.drag_from_port = out_port
        self.drag_free_end = 'dst'
        self.drag_edge = EdgeItem(src=out_port, dst=None)
        self.addItem(self.drag_edge)

    def _begin_drag_from_input(self, in_port: PortItem):
        existing = self.find_edge_for_input_port(in_port)
        if existing:
            self.delete_edge(existing)
        self.drag_from_port = in_port
        self.drag_free_end = 'src'
        self.drag_edge = EdgeItem(src=None, dst=in_port)
        self.addItem(self.drag_edge)

    def _update_drag(self, scene_pos: QPointF):
        if not self.drag_edge:
            return
        if self.drag_free_end == 'dst':
            self.drag_edge.set_dst_pos(scene_pos)
        else:
            self.drag_edge.set_src_pos(scene_pos)
        self.drag_edge.update_path()

    def _finish_drag(self, target_item: Optional[QGraphicsItem]):
        if not self.drag_edge:
            return

        # Clear all highlights before finishing the drag
        for node in self.nodes:
            for p in list(node.ports_in.values()) + list(node.ports_out.values()):
                p._highlight(False)

        src_port: Optional[PortItem] = None
        dst_port: Optional[PortItem] = None

        if isinstance(target_item, PortItem):
            if self.drag_free_end == 'dst':
                src_port = self.drag_from_port
                dst_port = target_item
            else:
                src_port = target_item
                dst_port = self.drag_from_port

        if src_port and dst_port:
            valid = (
                src_port.is_output and
                not dst_port.is_output and
                src_port.node_item is not dst_port.node_item and
                src_port.is_compatible(dst_port)  # Type check
            )
            if valid:
                old = self.find_edge_for_input_port(dst_port)
                if old:
                    self.delete_edge(old)

                # Replace drag edge with real edge
                self.removeItem(self.drag_edge)
                self.drag_edge = None

                edge = EdgeItem(src_port, dst_port)
                self.edges.append(edge)
                self.addItem(edge)

                # Backend connect (pass source port name for multi-output nodes)
                try:
                    dst_port.node_item.backend_node.connect(
                        dst_port.name,
                        src_port.node_item.backend_node,
                        src_port.name
                    )
                except Exception as e:
                    QMessageBox.warning(None, 'Connection error', str(e))

                self.update_edges_for_node(dst_port.node_item)
                self.editor.update_previews_from(dst_port.node_item)
            else:
                self.removeItem(self.drag_edge)
                self.drag_edge = None
        else:
            self.removeItem(self.drag_edge)
            self.drag_edge = None

        self.drag_from_port = None
        self.drag_free_end = None

    # ---------- Mouse handling ----------
    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())

        if event.button() == Qt.LeftButton and isinstance(item, PortItem):
            if item.is_output:
                self._begin_drag_from_output(item)
            else:
                self._begin_drag_from_input(item)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_edge is not None and event.button() == Qt.LeftButton:
            item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if isinstance(item, PortItem):
                self._finish_drag(item)
            else:
                self._finish_drag(None)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
    
        # Handle manual port highlighting during a drag connection
        if self.drag_edge is not None:
            pos = event.scenePos()
            # Use itemAt to find the specific port under the mouse
            target = self.itemAt(pos, self.views()[0].transform())

            # Reset all ports highlight state
            for node in self.nodes:
                for p in list(node.ports_in.values()) + list(node.ports_out.values()):
                    p._highlight(False)

            # Highlight if hovering over a valid port
            if isinstance(target, PortItem):
                # Basic compatibility check: dragging from output -> target must be input
                is_direction_ok = target.is_output != self.drag_from_port.is_output
                # Don't connect to self
                is_different_node = target.node_item is not self.drag_from_port.node_item
                # Type check: ports must have same type
                is_type_compatible = target.is_compatible(self.drag_from_port)

                if is_direction_ok and is_different_node and is_type_compatible:
                    target._highlight(True)

            # Update the visual drag path
            self._update_drag(pos)
            event.accept()
            return

        super().mouseMoveEvent(event)
