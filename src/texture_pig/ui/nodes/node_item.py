from __future__ import annotations
import logging
from typing import Dict, Optional

import numpy as np
import cv2
from PIL import Image

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsRectItem, QGraphicsItem, QGraphicsSimpleTextItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QMenu, QMessageBox
)

from texture_pig.ui.utils.qt_helpers import _pil_to_qpixmap, _snap_value, _should_snap
from texture_pig.ui.nodes.port_item import PortItem
from texture_pig.ui.nodes.edge_item import EdgeItem
from texture_pig.ui.commands.undo_commands import MoveNodeCommand, DeleteNodeCommand

# ---- Layout constants (copied here to avoid coupling; keep in sync with editor) ----
TITLE_H = 28
TOP_PAD = 8
PREVIEW_TOP = 36
PREVIEW_PAD = 16
ROW_H = 24
BOTTOM_PAD = 12
LEFT_PAD = 12
RIGHT_PAD = 12
LABEL_LEFT_OFFSET = 14
LABEL_RIGHT_OFFSET = 46

# Default preview fallback
PREVIEW_SIZE_FALLBACK = 256


class NodeItem(QGraphicsRectItem):
    """
    Visual node card with a title, preview, ports & labels.
    """
    def __init__(self, title: str, backend_node, width=300):
        super().__init__(0, 0, width, PREVIEW_TOP + PREVIEW_SIZE_FALLBACK + PREVIEW_PAD + BOTTOM_PAD)

        self.preview_enabled: bool = True
        
        # Use style-friendly color definitions
        self._is_output = (title == "Output" or getattr(backend_node, 'name', '') == 'Output')
        self._card_color = QColor('#505050') if self._is_output else QColor('#2b2b2b')
        self._border_color = QColor('#e0e0e0') if self._is_output else QColor('#555')

        self.setBrush(QBrush(self._card_color))
        self.setPen(QPen(self._border_color, 1))
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)

        # Masked background cache + last preview (PIL) for alpha extraction
        self._bg_pixmap: Optional[QPixmap] = None
        self._last_preview_pil: Optional[Image.Image] = None

        self.title = title
        self.backend_node = backend_node
        self.ports_in: Dict[str, PortItem] = {}
        self.ports_out: Dict[str, PortItem] = {}
        self.exposed_params: set = set()  # Track which params are exposed as scalar inputs

        # Title
        self.title_item = QGraphicsSimpleTextItem(title, self)
        self.title_item.setBrush(QBrush(QColor('#ddd')))
        self.title_item.setPos(LEFT_PAD, TOP_PAD)

        # Eye toggle
        self.preview_toggle = QGraphicsSimpleTextItem("👁", self)
        self.preview_toggle.setBrush(QBrush(QColor('#aaa')))
        self.preview_toggle.setAcceptHoverEvents(True)
        self.preview_toggle.setFlag(QGraphicsItem.ItemIsFocusable, False)
        self.preview_toggle.setCursor(Qt.PointingHandCursor)

        # Preview image
        self.preview_item = QGraphicsPixmapItem(self)
        self.preview_item.setZValue(-0.5)
        self.preview_item.setPos(LEFT_PAD, PREVIEW_TOP)
        self.preview_item.setTransformationMode(Qt.SmoothTransformation)

        # Preview frame
        self.preview_frame = QGraphicsRectItem(self)
        self.preview_frame.setPen(QPen(QColor('#666'), 1))
        self.preview_frame.setBrush(QBrush(Qt.NoBrush))
        self.preview_frame.setZValue(-0.6)

        self.layout_ports_and_resize()
        self._layout_header()

        # Children NOT selectable
        self.title_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.preview_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.preview_frame.setFlag(QGraphicsItem.ItemIsSelectable, False)

        # Ports not selectable
        # (Toggle after init so Scene selection works on the card only)
        # This keeps lasso/rubber-band selection sane.
        for p in self.ports_in.values():
            p.setFlag(QGraphicsItem.ItemIsSelectable, False)
        for p in self.ports_out.values():
            p.setFlag(QGraphicsItem.ItemIsSelectable, False)

    # ---------- Sizing / preview helpers ----------

    def set_card_width(self, width: int):
        """Change the card width while keeping current x, y, and height, then relayout."""
        rect = self.rect()
        self.setRect(rect.x(), rect.y(), int(width), rect.height())
        self.layout_ports_and_resize()

    def set_card_size(self, width: int, height: int):
        """Change both width and height, then relayout."""
        rect = self.rect()
        self.setRect(rect.x(), rect.y(), int(width), int(height))
        self.layout_ports_and_resize()

    def _layout_header(self):
        """Position title and preview eye icon based on current card width."""
        w = int(self.rect().width())
        self.title_item.setPos(LEFT_PAD, TOP_PAD)

        eye_w = self.preview_toggle.boundingRect().width()
        self.preview_toggle.setPos(w - RIGHT_PAD - eye_w, TOP_PAD)

    def _preview_size(self) -> int:
        sc = self.scene()
        if sc and hasattr(sc, 'editor'):
            return int(getattr(sc.editor, 'preview_size', PREVIEW_SIZE_FALLBACK))
        return PREVIEW_SIZE_FALLBACK

    # ---------- Ports ----------

    def add_input(self, name: str, port_type: str = "image", defer_layout: bool = False):
        # PortItem now handles its own label internally
        port = PortItem(self, name, is_output=False, x=0, y=0, port_type=port_type)
        self.ports_in[name] = port
        if not defer_layout:
            self.layout_ports_and_resize()

    def add_output(self, name: str = 'out', port_type: str = "image", defer_layout: bool = False):
        port = PortItem(self, name, is_output=True, x=0, y=0, port_type=port_type)
        self.ports_out[name] = port
        if not defer_layout:
            self.layout_ports_and_resize()

    def expose_param(self, param_name: str):
        """Expose a parameter as a scalar input port."""
        if param_name in self.exposed_params:
            return  # Already exposed
        self.exposed_params.add(param_name)
        self.add_input(param_name, port_type="scalar")

    def unexpose_param(self, param_name: str):
        """Remove a parameter's scalar input port and disconnect any edges."""
        if param_name not in self.exposed_params:
            return  # Not exposed
        self.exposed_params.discard(param_name)

        # Remove the port
        if param_name in self.ports_in:
            port = self.ports_in[param_name]
            # Remove any edge connected to this port
            scene = self.scene()
            if scene and hasattr(scene, 'edges'):
                for edge in list(scene.edges):
                    if edge.dst is port:
                        scene.delete_edge(edge)
            # Remove port from scene
            if port.scene():
                port.scene().removeItem(port)
            del self.ports_in[param_name]
            self.layout_ports_and_resize()

    def is_param_exposed(self, param_name: str) -> bool:
        """Check if a parameter is exposed as a scalar input."""
        return param_name in self.exposed_params

    def layout_ports_and_resize(self):
        """
        Compute and apply the node card height based on current preview visibility & size,
        number of port rows, and fixed paddings. Also repositions ports, preview frame,
        updates dependent edges, rebuilds masked background, and header layout.
        """
        ps = self._preview_size() if self.preview_enabled else 0
        preview_pad = PREVIEW_PAD if (self.preview_enabled and ps > 0) else 0

        n_rows = max(len(self.ports_in), len(self.ports_out))
        ports_h = n_rows * ROW_H

        base_h = PREVIEW_TOP + ps + preview_pad
        min_card_h = max(PREVIEW_TOP, TOP_PAD + TITLE_H + BOTTOM_PAD)
        total_h = max(base_h + ports_h + BOTTOM_PAD, min_card_h)

        w = int(self.rect().width())
        self.setRect(0, 0, w, int(total_h))

        # Preview frame: 0x0 when collapsed
        if ps > 0 and self.preview_enabled:
            self.preview_frame.setRect(LEFT_PAD - 2, PREVIEW_TOP - 2, ps + 4, ps + 4)
        else:
            self.preview_frame.setRect(0, 0, 0, 0)

        ports_y_base = PREVIEW_TOP + ps + preview_pad

        # Inputs (left)
        for i, port in enumerate(self.ports_in.values()):
            y = ports_y_base + i * ROW_H
            port.setPos(LEFT_PAD + 2, y)

        # Outputs (right)
        right_x = w - RIGHT_PAD - 2
        for i, port in enumerate(self.ports_out.values()):
            y = ports_y_base + i * ROW_H
            port.setPos(right_x, y)
        # Update edges for this node
        scene = self.scene()
        if scene and hasattr(scene, 'update_edges_for_node'):
            scene.update_edges_for_node(self)

        self._rebuild_bg_pixmap()
        self._layout_header()

    def update_preview(self, graph=None):
        if not self.preview_enabled:
            return

        # Resolve graph if None
        if graph is None:
            sc = self.scene()
            ed = sc.editor if (sc and hasattr(sc, 'editor')) else None
            graph = getattr(ed, 'graph', None)

        ps = self._preview_size()
        if graph is None:
            pm = QPixmap(ps, ps)
            pm.fill(QColor('#333333'))
            self.preview_item.setPixmap(pm)
            self.preview_item.setScale(1.0)
            self._last_preview_pil = None
            self._rebuild_bg_pixmap()
            return

        try:
            arr = graph.output(self.backend_node, size=ps)  # Expect RGBA in [0..1]
            img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype('uint8'), mode='RGBA')
            self._last_preview_pil = img

            qpix = _pil_to_qpixmap(img)
            self.preview_item.setPixmap(qpix)

            pw = max(1, qpix.width())
            ph = max(1, qpix.height())
            self.preview_item.setScale(min(ps / float(pw), ps / float(ph)))
        except Exception:
            logger.exception("Preview render failed for node=%s",
                              getattr(self.backend_node, 'name', type(self.backend_node).__name__))
            pm = QPixmap(ps, ps)
            pm.fill(QColor('#552222'))
            self.preview_item.setPixmap(pm)
            self.preview_item.setScale(1.0)
            self._last_preview_pil = None

        self._rebuild_bg_pixmap()

    def _update_preview_from_array(self, arr: np.ndarray, is_low_res: bool = False):
        """
        Update preview from a pre-rendered array (used by threaded worker).

        Args:
            arr: RGBA float array in [0..1] range
            is_low_res: If True, this is a quick low-res preview (may be scaled up)
        """
        if not self.preview_enabled:
            return

        ps = self._preview_size()

        try:
            # Convert array to PIL Image
            img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype('uint8'), mode='RGBA')

            # If low-res, scale up to preview size
            if is_low_res and (img.width < ps or img.height < ps):
                # Use cv2.resize (faster than PIL)
                img_arr = np.asarray(img, dtype=np.uint8)
                img_arr = cv2.resize(img_arr, (ps, ps), interpolation=cv2.INTER_LINEAR)
                img = Image.fromarray(img_arr, mode='RGBA')

            self._last_preview_pil = img

            qpix = _pil_to_qpixmap(img)
            self.preview_item.setPixmap(qpix)

            pw = max(1, qpix.width())
            ph = max(1, qpix.height())
            self.preview_item.setScale(min(ps / float(pw), ps / float(ph)))
        except Exception:
            logger.exception("_update_preview_from_array failed")
            pm = QPixmap(ps, ps)
            pm.fill(QColor('#552222'))
            self.preview_item.setPixmap(pm)
            self.preview_item.setScale(1.0)
            self._last_preview_pil = None

        self._rebuild_bg_pixmap()

    def _rebuild_bg_pixmap(self):
        """
        Build a background pixmap for the node card using the preview's alpha
        to mask the background area, allowing the scene grid to show through.
        """
        rect = self.rect()
        w, h = int(rect.width()), int(rect.height())
        if w <= 0 or h <= 0:
            self._bg_pixmap = None
            return

        # Create a solid RGBA image for the card background
        card_rgba = (self._card_color.red(), self._card_color.green(), self._card_color.blue(), 255)
        base = Image.new('RGBA', (w, h), card_rgba)

        # If preview is enabled and we have a valid PIL image, apply its alpha
        if self.preview_enabled and self._last_preview_pil is not None:
            try:
                ps = self._preview_size()
                px, py = int(LEFT_PAD), int(PREVIEW_TOP)

                # Extract and scale the alpha channel from the preview
                # split()[3] is the Alpha channel
                alpha = self._last_preview_pil.split()[3]
                if alpha.size != (ps, ps):
                    # Use cv2.resize (faster than PIL)
                    alpha_arr = np.asarray(alpha, dtype=np.uint8)
                    alpha_arr = cv2.resize(alpha_arr, (ps, ps), interpolation=cv2.INTER_LINEAR)
                    alpha = Image.fromarray(alpha_arr, mode='L')

                # Update the base image's alpha channel in the preview area
                base_a = base.split()[3]
                base_a.paste(alpha, (px, py))
                base.putalpha(base_a)
            except Exception:
                logger.exception("BG mask failed")

        # Convert back to QPixmap for the painter
        self._bg_pixmap = _pil_to_qpixmap(base)
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.rect()
        
        # Draw the card background
        if self._bg_pixmap and not self._bg_pixmap.isNull():
            painter.drawPixmap(rect.topLeft().toPoint(), self._bg_pixmap)
        else:
            painter.fillRect(rect, self._card_color)

        # Border Logic
        pen_color = self._border_color
        if self.isSelected():
            pen_color = QColor('#ffca28') # Highlight Amber
        elif self.isUnderMouse():
            pen_color = pen_color.lighter(160)

        painter.setPen(QPen(pen_color, 2 if self.isSelected() else 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

    def contextMenuEvent(self, event):
        # Right-clicking a node that isn't part of the current selection should act
        # on this node alone, not on whatever was previously selected (Duplicate/
        # Delete below operate on the scene's selected nodes).
        if not self.isSelected():
            scene = self.scene()
            if scene is not None:
                scene.clearSelection()
            self.setSelected(True)

        menu = QMenu()
        if not getattr(self, '_is_output_node', False):
            act_set_out = menu.addAction("Set as Output")
            menu.addSeparator()
            act_dup = menu.addAction("Duplicate")
            act_dup_rewire = menu.addAction("Duplicate & Rewire Downstream")
            menu.addSeparator()
            act_del_node = menu.addAction("Delete Node")
        else:
            act_info = menu.addAction("Output Node (fixed)")

        action = menu.exec(event.screenPos())

        if not getattr(self, '_is_output_node', False):
            if action == act_set_out:
                self.scene().editor._set_output_src(self)
                event.accept()
                return

        if action == act_dup:
            self.scene().editor.duplicate_selected(rewire_downstream=False)
        elif action == act_dup_rewire:
            self.scene().editor.duplicate_selected(rewire_downstream=True)
        elif action == act_del_node:
            self.scene().editor.delete_selected_nodes()

    def itemChange(self, change, value):
        # Snap while the node is being moved
        if change == QGraphicsItem.ItemPositionChange:
            scene = self.scene()
            if scene and hasattr(scene, 'views') and scene.views():
                view = scene.views()[0]
                if _should_snap(view):
                    try:
                        x = value.x()
                        y = value.y()
                        gs = 32
                        sx = _snap_value(x, gs)
                        sy = _snap_value(y, gs)
                        return QPointF(sx, sy)
                    except Exception:
                        pass

        # Update edge paths after move
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene and hasattr(scene, 'update_edges_for_node'):
                scene.update_edges_for_node(self)
        return super().itemChange(change, value)

    def _apply_preview_visibility(self):
        self.preview_item.setVisible(self.preview_enabled)
        self.preview_frame.setVisible(self.preview_enabled)

        if not self.preview_enabled:
            self._last_preview_pil = None
        else:
            sc = self.scene()
            ed = sc.editor if (sc and hasattr(sc, 'editor')) else None
            if ed and hasattr(ed, 'graph'):
                ed.update_previews_from(self)

        self.layout_ports_and_resize()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.preview_toggle.isUnderMouse():
            self.preview_enabled = not self.preview_enabled
            self._apply_preview_visibility()
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            self._move_start = self.pos()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Undoable move on release
        if event.button() == Qt.LeftButton:
            start = getattr(self, '_move_start', None)
            if start is not None:
                end = QPointF(self.pos())
                if end != start:
                    try:
                        editor = self.scene().editor
                        cmd = MoveNodeCommand(editor, self, start, end)
                        editor.undo_stack.push(cmd)
                    except Exception:
                        logger.exception("Move undo push failed")
                self._move_start = None

        super().mouseReleaseEvent(event)