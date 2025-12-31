# ui/preview/large_preview.py
from __future__ import annotations
from typing import Optional
import time

import numpy as np
from PIL import Image

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QPainter, QColor, QPixmap, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QDockWidget, QApplication
)

from texture_pig.ui.utils.qt_helpers import _pil_to_qpixmap


class _RenderWorker(QObject):
    """Background worker for full-resolution preview rendering."""
    finished = Signal(object, int)  # (numpy array or None, render_id)

    def __init__(self, graph, backend_node, size: int, render_id: int):
        super().__init__()
        self.graph = graph
        self.backend_node = backend_node
        self.size = size
        self.render_id = render_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            self.finished.emit(None, self.render_id)
            return
        try:
            arr = self.graph.output(self.backend_node, size=int(self.size))
            if not self._cancelled:
                self.finished.emit(arr, self.render_id)
            else:
                self.finished.emit(None, self.render_id)
        except Exception as e:
            print(f"[RenderWorker] Error: {e}")
            self.finished.emit(None, self.render_id)


class LargePreviewPanel(QWidget):
    """
    High-resolution preview of the currently selected node.
    Always renders at the current Graph.size (Output Size).
    Zoom mode is persistent across node selection: 'fit', 'full', or 'custom'.
    """
    def __init__(self, editor: 'GraphEditor'):
        super().__init__(editor)
        self.editor = editor
        self.current_node_item: Optional['NodeItem'] = None

        # Persistent zoom mode ('fit' or 'full' or 'custom')
        self.zoom_mode: str = 'full'  # default to 100% unless the user presses Fit

        # Auto state - when True, auto-refresh is enabled (default OFF to avoid lag during load)
        self.auto_enabled: bool = False

        # Progressive rendering state
        self._render_thread: Optional[QThread] = None
        self._render_worker: Optional[_RenderWorker] = None
        self._render_id: int = 0  # Incremented for each render to track stale results
        self._is_rendering: bool = False
        self._render_start_time: float = 0.0

        # --- UI ---
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        ctrl = QWidget(self)
        hl = QHBoxLayout(ctrl)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        self.btn_fit = QPushButton("Fit", self)
        self.btn_100 = QPushButton("Full", self)  # 100% / 1:1
        self.btn_zoom_in = QPushButton("+", self)
        self.btn_zoom_out = QPushButton("-", self)
        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setMinimumWidth(56)
        self.btn_auto = QPushButton("Auto", self)
        self.btn_auto.setCheckable(True)
        self.btn_auto.setChecked(False)  # Default to auto OFF to avoid lag during load
        self.btn_auto.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: #999999;
            }
            QPushButton:checked {
                background-color: #cc4444;
                color: white;
                font-weight: bold;
            }
        """)
        self.btn_refresh = QPushButton("Refresh", self)

        hl.addStretch(1)
        hl.addWidget(self.btn_fit)
        hl.addWidget(self.btn_100)
        hl.addWidget(self.btn_zoom_out)
        hl.addWidget(self.btn_zoom_in)
        hl.addWidget(self.zoom_label)
        hl.addWidget(self.btn_auto)
        hl.addWidget(self.btn_refresh)
        outer.addWidget(ctrl)

        # Graphics view for zoom/pan
        self.scene = QGraphicsScene(self)
        self._setup_checkerboard()

        self.view = _PreviewView(self)  # subclass to catch wheel zoom
        self.view.setScene(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing, False)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        
        # Ensure the view doesn't block the scene's checkerboard
        self.view.setBackgroundBrush(Qt.NoBrush)
        
        # Prevent scrollbars from popping up and jumping during zoom
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self.pix_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pix_item)
        outer.addWidget(self.view, stretch=1)

        # --- Signals ---
        self.btn_fit.clicked.connect(self._on_fit_clicked)
        self.btn_100.clicked.connect(self._on_full_clicked)
        self.btn_zoom_in.clicked.connect(lambda: self._apply_zoom(1.1))
        self.btn_zoom_out.clicked.connect(lambda: self._apply_zoom(1.0 / 1.1))
        self.btn_auto.toggled.connect(self._on_auto_toggled)
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)

    def _setup_checkerboard(self):
        """Creates a repeating checkerboard pattern for the background."""
        tile_size = 32
        pix = QPixmap(tile_size * 2, tile_size * 2)
        pix.fill(QColor('#1a1a1a'))
        painter = QPainter(pix)
        painter.fillRect(0, 0, tile_size, tile_size, QColor('#222222'))
        painter.fillRect(tile_size, tile_size, tile_size, tile_size, QColor('#222222'))
        painter.end()
        self.scene.setBackgroundBrush(QBrush(pix))

    # ---------- Public API ----------
    def set_node_item(self, node_item: Optional['NodeItem']):
        self.current_node_item = node_item
        if self.auto_enabled:
            self.render()

    def render(self):
        """Render the selected node with progressive refinement."""
        nitem = self.current_node_item
        if not nitem:
            self.pix_item.setPixmap(QPixmap())
            self._update_zoom_label()
            self._clear_status()
            return

        size = self._desired_render_size()
        if size <= 0:
            return

        # Cancel any pending render
        self._cancel_pending_render()

        # Show status and start timing
        self._is_rendering = True
        self._render_start_time = time.time()
        self._show_status(f"Rendering preview at {size}x{size}...")

        # For small sizes, just render directly (progressive not needed)
        if size <= 256:
            self._render_direct(nitem, size)
            return

        # Progressive rendering: first show low-res preview quickly
        preview_size = max(64, size // 4)  # 1/4 resolution for quick preview
        try:
            arr_preview = self.editor.graph.output(nitem.backend_node, size=int(preview_size))
            # Upscale to target size for display
            img_preview = Image.fromarray((np.clip(arr_preview, 0, 1) * 255 + 0.5).astype('uint8'), mode='RGBA')
            img_preview = img_preview.resize((size, size), Image.NEAREST)
            qpix = _pil_to_qpixmap(img_preview)
            self.pix_item.setPixmap(qpix)
            self.pix_item.setOffset(0, 0)
            self._apply_zoom_mode()
            self._update_zoom_label()
            QApplication.processEvents()  # Show the preview immediately
        except Exception as e:
            print(f"[LargePreview] Low-res preview failed: {e}")

        # Start background thread for full resolution
        self._render_id += 1
        current_render_id = self._render_id

        self._render_thread = QThread(self)
        self._render_worker = _RenderWorker(
            self.editor.graph, nitem.backend_node, size, current_render_id
        )
        self._render_worker.moveToThread(self._render_thread)
        self._render_thread.started.connect(self._render_worker.run)
        self._render_worker.finished.connect(self._on_render_finished)
        self._render_worker.finished.connect(self._render_thread.quit)
        self._render_thread.start()

    def _render_direct(self, nitem, size: int):
        """Direct synchronous render for small sizes."""
        try:
            arr = self.editor.graph.output(nitem.backend_node, size=int(size))
            img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype('uint8'), mode='RGBA')
            qpix = _pil_to_qpixmap(img)
            self.pix_item.setPixmap(qpix)
            self.pix_item.setOffset(0, 0)
            self._apply_zoom_mode()
            self._update_zoom_label()
        except Exception as e:
            w = h = int(self._fallback_side())
            pm = QPixmap(w, h)
            pm.fill(QColor('#552222'))
            self.pix_item.setPixmap(pm)
            print("[LargePreview] Render failed:", e)
            self._apply_zoom_mode()
            self._update_zoom_label()
        finally:
            self._is_rendering = False
            elapsed = time.time() - self._render_start_time
            self._show_status(f"Preview rendered in {elapsed:.2f}s", timeout=2000)

    def _on_render_finished(self, arr, render_id: int):
        """Handle completion of background render."""
        # Ignore stale results
        if render_id != self._render_id:
            return

        self._is_rendering = False
        elapsed = time.time() - self._render_start_time

        if arr is None:
            self._show_status("Preview render cancelled", timeout=2000)
            return

        try:
            img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype('uint8'), mode='RGBA')
            qpix = _pil_to_qpixmap(img)
            self.pix_item.setPixmap(qpix)
            self.pix_item.setOffset(0, 0)
            self._apply_zoom_mode()
            self._update_zoom_label()
            self._show_status(f"Preview rendered in {elapsed:.2f}s", timeout=2000)
        except Exception as e:
            print(f"[LargePreview] Failed to display render result: {e}")
            self._show_status("Preview render failed", timeout=2000)

    def _cancel_pending_render(self):
        """Cancel any pending background render."""
        if self._render_worker:
            self._render_worker.cancel()
        if self._render_thread and self._render_thread.isRunning():
            self._render_thread.quit()
            self._render_thread.wait(100)
        self._render_worker = None
        self._render_thread = None

    def _show_status(self, message: str, timeout: int = 0):
        """Show message in status bar."""
        try:
            self.editor.statusBar().showMessage(message, timeout)
        except Exception:
            pass

    def _clear_status(self):
        """Clear status bar message."""
        try:
            self.editor.statusBar().clearMessage()
        except Exception:
            pass

    def refresh_if_tracking(self, node_item: Optional['NodeItem']):
        """Call when the selected node changes or its downstream updates."""
        if not self.auto_enabled:
            return
        if node_item is None:
            return
        if self.current_node_item is node_item:
            self.render()

    def on_graph_size_changed(self):
        """Always re-render at the new Graph.size if a node is selected."""
        if not self.auto_enabled:
            return
        if self.current_node_item is not None:
            self.render()

    # ---------- Helpers ----------
    def _desired_render_size(self) -> int:
        try:
            return int(self.editor.graph.size)
        except Exception:
            return 512

    def _fallback_side(self) -> int:
        vp = self.view.viewport().size()
        side = max(64, min(vp.width(), vp.height()))
        return int(side)

    # Apply persistent zoom mode
    def _apply_zoom_mode(self):
        if self.zoom_mode == 'fit':
            self.view.fitInView(self.pix_item, Qt.KeepAspectRatio)
        elif self.zoom_mode == 'full':
            self.view.resetTransform()
        else:
            # 'custom' uses whatever transform is currently set
            pass

    def _on_fit_clicked(self):
        self.zoom_mode = 'fit'
        self.view.fitInView(self.pix_item, Qt.KeepAspectRatio)
        self._update_zoom_label()

    def _on_full_clicked(self):
        self.zoom_mode = 'full'
        self.view.resetTransform()
        self._update_zoom_label()

    def _on_auto_toggled(self, checked: bool):
        self.auto_enabled = checked
        if checked:
            self.render()

    def _on_refresh_clicked(self):
        """Manual refresh - always works regardless of pause state."""
        self.render()

    def _apply_zoom(self, factor: float):
        # Zooming via +/- puts us in 'custom' mode
        self.view.scale(factor, factor)
        self.zoom_mode = 'custom'
        self._update_zoom_label()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # If we are in 'fit' mode, refit on resize to keep it fitting.
        if self.zoom_mode == 'fit':
            self.view.fitInView(self.pix_item, Qt.KeepAspectRatio)
        # Update label regardless
        self._update_zoom_label()

    def _current_scale_factor(self) -> float:
        try:
            return float(self.view.transform().m11())
        except Exception:
            return 1.0

    def _update_zoom_label(self):
        scale = self._current_scale_factor()
        pct = int(round(scale * 100))
        self.zoom_label.setText(f"{pct}%")

    def cleanup(self):
        """Cancel any pending renders and cleanup threads."""
        self._cancel_pending_render()


class _PreviewView(QGraphicsView):
    """Helper view to catch wheel zoom and mark zoom_mode='custom'."""
    def __init__(self, owner_panel: LargePreviewPanel):
        super().__init__(owner_panel)
        self._owner = owner_panel

    def wheelEvent(self, event):
        # Calculate zoom factor
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        # Apply scale
        self.scale(zoom_factor, zoom_factor)
        
        # Mark as custom zoom and update UI
        self._owner.zoom_mode = 'custom'
        self._owner._update_zoom_label()
        
        # Accept the event to prevent default scrolling behavior
        event.accept()


class LargePreviewDock(QDockWidget):
    def __init__(self, editor: 'GraphEditor'):
        super().__init__('Output Preview', editor)
        self.panel = LargePreviewPanel(editor)
        self.setWidget(self.panel)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)

    def set_node_item(self, node_item: Optional['NodeItem']):
        # Preserve your existing behavior: only track the Output node
        out_item = getattr(self.panel.editor, 'output_node_item', None)
        if node_item is None or node_item is out_item:
            self.panel.set_node_item(node_item)

    def refresh_if_tracking(self, node_item: Optional['NodeItem']):
        out_item = getattr(self.panel.editor, 'output_node_item', None)
        if out_item is not None and node_item is out_item:
            self.panel.refresh_if_tracking(node_item)

    def on_graph_size_changed(self):
        self.panel.on_graph_size_changed()
