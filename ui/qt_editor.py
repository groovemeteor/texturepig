from __future__ import annotations
from typing import Dict, Optional, List
import inspect

from shiboken6 import isValid
from PIL import Image
import json
import numpy as np

from PySide6.QtCore import Qt, QPointF, QSize, QEvent, QRectF, QTimer, QThread
from PySide6.QtGui import (
    QBrush, QColor, QPen, QPainterPath, QPixmap, QPainter,
    QKeySequence, QShortcut, QMouseEvent, QCursor, QIcon,
    QFontMetrics, QAction, QUndoStack
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsSimpleTextItem, QGraphicsEllipseItem, QVBoxLayout, QPushButton,
    QDockWidget, QFormLayout, QDoubleSpinBox, QLabel, QSpinBox, QFileDialog,
    QMessageBox, QHBoxLayout, QComboBox, QCheckBox, QMenu, QSlider,
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QAbstractItemView,
    QGridLayout, QToolButton, QSizePolicy, QProgressDialog
)

# ---- Backend nodes ----
from texture_pig.nodes.core import Graph, Constant
from texture_pig.nodes.scalar import Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp
from texture_pig.nodes.generators import (
    GradientRadial, GradientLinear, GradientReflected, GradientAngle,
    PerlinNoise, WorleyNoise
)
from texture_pig.nodes.shapes import Circle, Rectangle, Triangle, Line, Stripes, HexGrid
from texture_pig.nodes.blends import Blend, Lerp
from texture_pig.nodes.outline import Outline
from texture_pig.nodes.filters import GaussianBlur, Transform, Invert, Levels, Combine, Split
from texture_pig.nodes.layout import Grid, RadialGrid, Mirror
from texture_pig.nodes.image_source import ImageNode
from texture_pig.nodes.utils import resolve_qt_resource_or_fs, register_qt_resources, load_stylesheet_with_fallback
from texture_pig.nodes.output import Output

from texture_pig.ui.nodes.node_item import NodeItem
from texture_pig.ui.nodes.edge_item import EdgeItem
from texture_pig.ui.nodes.port_item import PortItem
from texture_pig.ui.scene.graph_scene import GraphScene
from texture_pig.ui.scene.graph_view import GraphView
from texture_pig.ui.preview.large_preview import LargePreviewDock
from texture_pig.ui.preview.preview_worker import PreviewWorkerPool, TaskPriority
from texture_pig.ui.inspector.inspector import Inspector
from texture_pig.ui.utils.actions import setup_editor_actions

# ---- Utilities ----
from texture_pig.ui.utils.qt_helpers import _pil_to_qpixmap
from texture_pig.ui.utils.editor_helpers import (
    shorten_label, compute_edit_menu_min_width, default_card_width
)
from texture_pig.ui.palette.quick_add import QuickAddDialog
from texture_pig.ui.utils.loader import GraphLoadWorker
from texture_pig.ui.utils.editor_helpers import normalize_params
from texture_pig.ui.commands.undo_commands import DeleteNodeCommand, DeleteNodesCommand

try:
    from texture_pig.ui import icons_rc
    print("[Resources] icons_rc imported.")
except Exception:
    pass  # Fallback to filesystem icons via resolve_qt_resource_or_fs()

# Constants
PREVIEW_SIZE = 256
OUTPUT_SIZE = 512
LEFT_PAD = 12
RIGHT_PAD = 12
SQUARE_SIZE_CHOICES = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192]

NODE_REGISTRY = {
    'Output': Output, 'Constant': Constant, 'Float': Float, 'Int': Int,
    'ScalarAdd': ScalarAdd, 'ScalarSub': ScalarSub, 'ScalarMul': ScalarMul, 'ScalarDiv': ScalarDiv, 'ScalarClamp': ScalarClamp,
    'GradientLinear': GradientLinear,
    'GradientRadial': GradientRadial, 'GradientReflected': GradientReflected,
    'GradientAngle': GradientAngle, 'PerlinNoise': PerlinNoise, 'WorleyNoise': WorleyNoise,
    'Circle': Circle, 'Rectangle': Rectangle, 'Triangle': Triangle, 'Line': Line,
    'Stripes': Stripes, 'Blend': Blend, 'GaussianBlur': GaussianBlur, 'Transform': Transform,
    'Invert': Invert, 'Levels': Levels, 'Combine': Combine, 'Split': Split, 'Grid': Grid,
    'RadialGrid': RadialGrid, 'Mirror': Mirror, 'HexGrid': HexGrid, 'ImageNode': ImageNode,
    'Outline': Outline, 'Lerp': Lerp
}

class GraphEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Texture Pig')
        self.resize(1800, 900)

        # Core Graph State
        self.graph = Graph(size=OUTPUT_SIZE)
        self.scene = GraphScene(self)
        self.view = GraphView(self.scene)
        self.setCentralWidget(self.view)
        self.preview_size = PREVIEW_SIZE
        self.undo_stack = QUndoStack(self)
        self.actions = setup_editor_actions(self)

        # Export State
        self.last_export_path: Optional[str] = None
        self.confirm_overwrite_on_reexport: bool = True

        # Threaded Preview Worker Pool
        self.preview_worker = PreviewWorkerPool(self, max_threads=4)

        # Async Load State
        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[GraphLoadWorker] = None
        self._load_id_to_item: Dict[int, NodeItem] = {}
        self._load_nodes_done = 0
        self._load_edges_done = 0
        self._load_total_nodes = 0
        self._load_total_edges = 0
        self._load_total = 0

        # UI Initialization
        self._setup_docks()
        self.scene.selectionChanged.connect(self._on_selection)
        self._create_output_node()

    def _setup_docks(self):
        self._build_palette_dock()
        self._build_inspector_dock()
        
        self.large_preview = LargePreviewDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.large_preview)

        self._build_export_dock()
        self._build_resolution_dock()

    # ---------- Dock Builders ----------
    def _build_export_dock(self):
        dock = QDockWidget('Export', self)
        widget = QWidget()
        layout = QHBoxLayout(widget)

        btn_export = QPushButton('Export PNG')
        btn_export.clicked.connect(self.export_selected)

        self.btn_reexport = QPushButton('Re-Export')
        self.btn_reexport.setToolTip("Export again to the last saved file path")
        self.btn_reexport.clicked.connect(self.reexport_output)
        self.btn_reexport.setEnabled(False)

        self.lbl_last_export = QLabel("Last: (none)")

        for w in [btn_export, self.btn_reexport, self.lbl_last_export]:
            layout.addWidget(w)
        layout.addStretch(1)

        dock.setWidget(widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_resolution_dock(self):
        dock = QDockWidget('Resolution', self)
        widget = QWidget()
        layout = QFormLayout(widget)

        # Output Size
        self.output_size_combo = QComboBox()
        for s in SQUARE_SIZE_CHOICES:
            self.output_size_combo.addItem(str(s), s)
        
        cur_out = getattr(self.graph, 'size', OUTPUT_SIZE)
        idx = self.output_size_combo.findData(cur_out)
        self.output_size_combo.setCurrentIndex(idx if idx != -1 else 5)
        self.output_size_combo.currentIndexChanged.connect(self._on_output_size_combo_changed)
        layout.addRow('Output Size (px)', self.output_size_combo)

        # Preview Size
        self.preview_size_combo = QComboBox()
        for s in SQUARE_SIZE_CHOICES:
            self.preview_size_combo.addItem(str(s), s)
        
        idx_p = self.preview_size_combo.findData(self.preview_size)
        self.preview_size_combo.setCurrentIndex(idx_p if idx_p != -1 else 4)
        self.preview_size_combo.currentIndexChanged.connect(self._on_preview_size_combo_changed)
        layout.addRow('Preview Size (px)', self.preview_size_combo)

        # UI Scale
        self.ui_scale_box = QDoubleSpinBox()
        self.ui_scale_box.setRange(0.5, 3.0)
        self.ui_scale_box.setSingleStep(0.1)
        self.ui_scale_box.setValue(1.0)
        self.ui_scale_box.valueChanged.connect(self._on_ui_scale_changed)
        layout.addRow('Node UI Scale (×)', self.ui_scale_box)

        dock.setWidget(widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_palette_dock(self):
        dock = QDockWidget('Palette', self)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        grid = QGridLayout()
        grid.setSpacing(8)
        
        icons = [
            (':/ui/icons/gradient_linear_128.png', 'Linear', lambda: GradientLinear(name='Linear')),
            (':/ui/icons/gradient_radial_128.png', 'Radial', lambda: GradientRadial(invert=True, name='Radial')),
            (':/ui/icons/gradient_reflected_128.png', 'Reflected', lambda: GradientReflected(name='Reflected')),
            (':/ui/icons/gradient_angle_128.png', 'Angle', lambda: GradientAngle(name='Angle')),
            (':/ui/icons/perlin_128.png', 'Perlin', lambda: PerlinNoise(seed=42, name='Perlin')),
            (':/ui/icons/worley_128.png', 'Worley', lambda: WorleyNoise(points=16, seed=42, name='Worley')),
            (':/ui/icons/circle_128.png', 'Circle', lambda: Circle(color=(1,1,1,1), name='Circle')),
            (':/ui/icons/rectangle_128.png', 'Rect', lambda: Rectangle(color=(1,1,1,1), name='Rect')),
            (':/ui/icons/triangle_128.png', 'Triangle', lambda: Triangle(color=(1,1,1,1), name='Triangle')),
            (':/ui/icons/line_128.png', 'Line', lambda: Line(name='Line')),
            (':/ui/icons/stripes_128.png', 'Stripes', lambda: Stripes(name='Stripes')),
            (':/ui/icons/hex_grid_128.png', 'HexGrid', lambda: HexGrid(name='HexGrid')),
        ]

        for i, (path, tip, node_gen) in enumerate(icons):
            # Capture node_gen by default argument to avoid late-binding closure issues
            btn = self._make_icon_button(path, tip, lambda checked=False, g=node_gen: self.add_node_ui(g()))
            grid.addWidget(btn, i // 3, i % 3)

        layout.addLayout(grid)

        # Scalar Math Icon Buttons (small square buttons in a row)
        scalar_math_layout = QHBoxLayout()
        scalar_math_layout.setSpacing(4)
        scalar_math_icons = [
            (':/ui/icons/scalar_add_32.png', '+', lambda: ScalarAdd(name='Add')),
            (':/ui/icons/scalar_sub_32.png', '-', lambda: ScalarSub(name='Sub')),
            (':/ui/icons/scalar_mul_32.png', '*', lambda: ScalarMul(name='Mul')),
            (':/ui/icons/scalar_div_32.png', '/', lambda: ScalarDiv(name='Div')),
        ]
        for icon_path, tooltip, node_gen in scalar_math_icons:
            btn = self._make_icon_button(icon_path, tooltip, lambda checked=False, g=node_gen: self.add_node_ui(g()), size=32)
            scalar_math_layout.addWidget(btn)
        scalar_math_layout.addStretch(1)
        layout.addLayout(scalar_math_layout)

        # Functional Buttons
        btns_layout = QVBoxLayout()
        btns_layout.setSpacing(4)

        node_types = [
            ('Float', lambda: Float(value=0.5, name='Float')),
            ('Int', lambda: Int(value=0, name='Int')),
            ('Clamp', lambda: ScalarClamp(name='Clamp')),
            ('Constant', lambda: Constant(color=(0,0,0,1), name='Constant')),
            ('Image', lambda: ImageNode(name='Image')),
            ('Blur', lambda: GaussianBlur(sigma=2.0, name='Blur')),
            ('Transform', lambda: Transform(name='Transform')),
            ('Invert', lambda: Invert(name='Invert')),
            ('Levels', lambda: Levels(name='Levels')),
            ('Combine', lambda: Combine(name='Combine')),
            ('Split', lambda: Split(name='Split')),
            ('Lerp', lambda: Lerp(name='Lerp')),
            ('Outline', lambda: Outline(name='Outline', thickness=3)),
            ('Blend (Add)', lambda: Blend(mode='add', name='Blend')),
            ('Blend (Sub)', lambda: Blend(mode='subtract', name='Blend')),
            ('Grid', lambda: Grid(nx=2, ny=2, name='Grid')),
            ('Radial Grid', lambda: RadialGrid(name='RadialGrid')),
            ('Mirror', lambda: Mirror(name='Mirror')),
        ]

        for label, gen in node_types:
            b = QPushButton(label)
            # Capture gen by default argument to ensure the correct node type is added
            b.clicked.connect(lambda checked=False, g=gen: self.add_node_ui(g()))
            btns_layout.addWidget(b)

        layout.addLayout(btns_layout)
        layout.addStretch(1)
        dock.setWidget(w)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_inspector_dock(self):
        dock = QDockWidget('Inspector', self)
        self.inspector = Inspector(self)
        dock.setWidget(self.inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    # ---------- Internal Helpers ----------
    def _make_icon_button(self, icon_path: str, tooltip: str, on_click, size: int = 48) -> QToolButton:
        btn = QToolButton(self)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        btn.setIconSize(QSize(size - 10, size - 10))
        btn.setFixedSize(size, size)
        btn.clicked.connect(on_click)
        btn.setIcon(resolve_qt_resource_or_fs(icon_path))
        return btn

    def _update_status_load_counters(self, cur=None, total=None, force_process=False):
        if cur is None:
            cur = self._load_nodes_done + self._load_edges_done
        if total is None:
            total = self._load_total

        msg = (f"Nodes: {self._load_nodes_done}/{self._load_total_nodes} — "
               f"Edges: {self._load_edges_done}/{self._load_total_edges} "
               f"({cur}/{total})")
        self.statusBar().showMessage(msg)
        # Only process events periodically to avoid re-entry issues
        if force_process or (cur % 10 == 0):
            QApplication.processEvents()

    # ---------- Logic & Event Handlers ----------
    def _on_selection(self):
        if not isValid(self.scene):
            return
        
        selected = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem) and isValid(it)]
        self.inspector.set_node(selected[0] if selected else None)

        if hasattr(self, 'output_node_item') and self.output_node_item:
            if self.large_preview.panel.current_node_item is not self.output_node_item:
                self.large_preview.set_node_item(self.output_node_item)

    def _create_output_node(self):
        out_backend = self.graph.add(Output(name='Output'))
        self.output_backend = out_backend

        out_item = NodeItem(out_backend.name, out_backend, width=self._default_card_width())
        out_item.add_input('src')
        out_item.add_output('out')
        out_item._is_output_node = True
        
        # Assign this BEFORE adding to scene so update_previews_from can find it
        self.output_node_item = out_item

        pos = QPointF(max(60.0, 0.75 * self.view.viewport().width()), 60.0)
        self.scene.add_node_item(out_item, pos)
        
        out_item.setScale(self.ui_scale_box.value())
        out_item.layout_ports_and_resize()
        out_item.update_preview(self.graph)

    def _on_output_size_combo_changed(self, _):
        try:
            size = int(self.output_size_combo.currentData())
            self.graph.size = size
            for nitem in self.scene.nodes:
                nitem.update_preview(self.graph)
            self.scene._refresh_edge_paths()
            self.large_preview.on_graph_size_changed()
            # Refresh inspector to update size-dependent displays (e.g., HexGrid tileable dimensions)
            if self.inspector.current_node_item:
                self.inspector.set_node(self.inspector.current_node_item)
        except Exception as e:
            print('Failed to set graph size:', e)

    def _on_preview_size_combo_changed(self, _):
        self.preview_size = int(self.preview_size_combo.currentData())
        target_width = self._default_card_width()
        for nitem in self.scene.nodes:
            nitem.set_card_width(target_width)
            nitem.update_preview(self.graph)
        self.scene._refresh_edge_paths()

    def _on_ui_scale_changed(self, scale: float):
        for nitem in self.scene.nodes:
            nitem.setScale(scale)
        self.scene._refresh_edge_paths()

    def open_quick_add(self):
        dlg = QuickAddDialog(self)
        dlg.exec()

    def _default_card_width(self) -> int:
        return default_card_width(
            preview_size=int(self.preview_size),
            fm=self.view.fontMetrics(),
            left_pad=LEFT_PAD,
            right_pad=RIGHT_PAD,
            port_circle_diam=16,
            gap=8,
            output_label_text='out'
        )

    # ---------- Node Management ----------
    def add_node_ui(self, backend_node, inputs=None, outputs=None, pos_scene=None):
        bnode = self.graph.add(backend_node)
        nitem = NodeItem(bnode.name, bnode)

        if inputs is None:
            inputs = list(getattr(bnode, 'inputs', {}).keys()) if hasattr(bnode, 'inputs') else []

        for name in inputs:
            nitem.add_input(name)

        # Handle outputs - default to single 'out', but support multi-output nodes
        if outputs is None:
            # Check if this is a known multi-output node type
            if isinstance(bnode, Split):
                outputs = ['r', 'g', 'b', 'a']
            elif isinstance(bnode, (Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp)):
                outputs = [('out', 'scalar')]  # Scalar nodes output scalar
            elif isinstance(bnode, Constant):
                outputs = ['out', ('scalar', 'scalar')]  # Constant has both image and scalar outputs
            else:
                outputs = ['out']

        for out_spec in outputs:
            if isinstance(out_spec, tuple):
                out_name, port_type = out_spec
                nitem.add_output(out_name, port_type=port_type)
            else:
                nitem.add_output(out_spec)

        # Add scalar inputs for math nodes
        if isinstance(bnode, (ScalarAdd, ScalarSub, ScalarMul, ScalarDiv)):
            nitem.add_input('a', port_type='scalar')
            nitem.add_input('b', port_type='scalar')
        elif isinstance(bnode, ScalarClamp):
            nitem.add_input('value', port_type='scalar')
            nitem.add_input('min_val', port_type='scalar')
            nitem.add_input('max_val', port_type='scalar')

        # Disable preview for scalar-only nodes
        if isinstance(bnode, (Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp)):
            nitem.preview_enabled = False
            nitem.preview_item.setVisible(False)
            nitem.layout_ports_and_resize()

        if pos_scene is None:
            # Place new node at center of visible viewport
            viewport_rect = self.view.viewport().rect()
            viewport_center = viewport_rect.center()
            pos_scene = self.view.mapToScene(viewport_center)

        self.scene.add_node_item(nitem, pos_scene)
        nitem.setScale(self.ui_scale_box.value())
        nitem.layout_ports_and_resize()
        return nitem

    def _set_output_src(self, node_item: NodeItem):
        """Connect the given node's 'out' port to the Output node's 'src' port."""
        if not hasattr(self, 'output_node_item') or not self.output_node_item:
            self.ensure_output_node()

        dst_port = self.output_node_item.ports_in.get('src')
        src_port = node_item.ports_out.get('out')

        if not dst_port or not src_port:
            return

        # 1. Clear existing edge on the output node's input
        existing = self.scene.find_edge_for_input_port(dst_port)
        if existing:
            self.scene.delete_edge(existing)

        # 2. Backend connection
        self.output_backend.connect('src', node_item.backend_node)

        # 3. Visual connection
        from texture_pig.ui.nodes.edge_item import EdgeItem
        edge = EdgeItem(src_port, dst_port)
        self.scene.edges.append(edge)
        self.scene.addItem(edge)

        # 4. Update
        self.update_previews_from(node_item)

    def duplicate_selected(self, rewire_downstream: bool = False):
        items = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        if not items:
            return

        src_item = items[0]
        src_backend = src_item.backend_node

        # Create clone
        cls = src_backend.__class__
        params = {k: v for k, v in vars(src_backend).items()
                  if k not in ('name', 'inputs', 'dependents', '_cache', '_dirty', '_generation', '_gen_cache')}

        dup_backend = cls(name=f"{src_backend.name}_copy", **params)
        dup_backend = self.graph.add(dup_backend)

        dup_item = NodeItem(dup_backend.name, dup_backend, width=int(src_item.rect().width()))

        # Copy input ports with their port types
        for in_name, in_port in src_item.ports_in.items():
            dup_item.add_input(in_name, port_type=in_port.port_type)

        # Copy output ports with their port types
        for out_name, out_port in src_item.ports_out.items():
            dup_item.add_output(out_name, port_type=out_port.port_type)

        # Copy exposed params
        dup_item.exposed_params = set(src_item.exposed_params)

        # Copy preview state
        dup_item.preview_enabled = src_item.preview_enabled
        dup_item.preview_item.setVisible(src_item.preview_enabled)

        self.scene.add_node_item(dup_item, src_item.pos() + QPointF(40, 40))

        # Re-wire inputs
        for edge in list(self.scene.edges):
            if edge.dst and edge.dst.node_item is src_item:
                in_name = edge.dst.name
                if in_name in dup_item.ports_in:
                    dup_backend.connect(in_name, edge.src.node_item.backend_node)
                    new_edge = EdgeItem(edge.src, dup_item.ports_in[in_name])
                    self.scene.edges.append(new_edge)
                    self.scene.addItem(new_edge)

        if rewire_downstream:
            for edge in list(self.scene.edges):
                if edge.src and edge.src.node_item is src_item:
                    dst_port = edge.dst
                    src_port_name = edge.src.name if edge.src else 'out'
                    dst_port.node_item.backend_node.connect(dst_port.name, dup_backend, src_port_name)
                    self.scene.delete_edge(edge)
                    new_edge = EdgeItem(dup_item.ports_out.get(src_port_name, dup_item.ports_out.get('out')), dst_port)
                    self.scene.edges.append(new_edge)
                    self.scene.addItem(new_edge)

        dup_item.update_preview(self.graph)

    def update_previews_from(self, node_item: NodeItem):
        adj: Dict[NodeItem, set] = {}
        for e in self.scene.edges:
            if e.src and e.dst:
                adj.setdefault(e.src.node_item, set()).add(e.dst.node_item)

        downstream = set()
        stack = [node_item]
        while stack:
            cur = stack.pop()
            if cur not in downstream:
                downstream.add(cur)
                stack.extend(adj.get(cur, []))

        # Invalidate all downstream nodes' caches first
        # (some nodes like RadialGrid don't cascade invalidation to dependents)
        for n in downstream:
            backend = n.backend_node
            if hasattr(backend, '_cache'):
                if isinstance(backend._cache, dict):
                    backend._cache.clear()
                else:
                    backend._cache = None
            if hasattr(backend, '_dirty'):
                backend._dirty = True
            # Also bump generation for nodes using GenerationCacheMixin
            if hasattr(backend, '_bump_generation'):
                backend._bump_generation()

        for n in downstream:
            try:
                n.update_preview(self.graph)
            except Exception as e:
                print(f"[Preview Error] {getattr(n.backend_node, 'name', '?')}: {e}")
        self.scene._refresh_edge_paths()

        if hasattr(self, 'large_preview'):
            out_item = getattr(self, 'output_node_item', None)
            if out_item:
                self.large_preview.refresh_if_tracking(out_item)

        # Refresh inspector if the updated node is currently selected (for undo/redo)
        # Use QTimer.singleShot to defer the refresh - this prevents crashes when
        # the inspector widget that triggered the change is destroyed during refresh
        if hasattr(self, 'inspector') and self.inspector.current_node_item is node_item:
            QTimer.singleShot(0, lambda: self._deferred_inspector_refresh(node_item))

    def _deferred_inspector_refresh(self, node_item):
        """Refresh inspector after signal handling completes (prevents crash from widget destruction)."""
        if hasattr(self, 'inspector') and isValid(node_item) and self.inspector.current_node_item is node_item:
            self.inspector.set_node(node_item)

    def remove_backend_node(self, backend_node):
        """Safely remove a node from the backend graph using various possible method names."""
        try_methods = [('remove', backend_node), ('delete', backend_node), 
                       ('remove_node', backend_node), ('discard', backend_node)]
        for method_name, arg in try_methods:
            m = getattr(self.graph, method_name, None)
            if callable(m):
                try:
                    m(arg)
                    return
                except Exception as e:
                    print(f'Graph.{method_name} failed:', e)
        try:
            if hasattr(self.graph, 'nodes') and backend_node in self.graph.nodes:
                self.graph.nodes.remove(backend_node)
        except Exception as e:
            print('Graph internal removal failed:', e)

    def delete_selected_nodes(self):
        items = [it for it in self.scene.selectedItems() 
                 if isinstance(it, NodeItem) and not getattr(it, '_is_output_node', False)]
        if not items:
            return

        cmd = DeleteNodesCommand(self, items) if len(items) > 1 else DeleteNodeCommand(self, items[0])
        try:
            self.undo_stack.push(cmd)
        except Exception as e:
            print(f"[Delete] undo push failed: {e}")
            for it in items:
                self.scene.delete_node_item(it)

    # ---------- Export Logic ----------
    def _update_reexport_enabled(self):
        has_path = bool(self.last_export_path)
        self.btn_reexport.setEnabled(has_path)
        if hasattr(self, 'act_reexport'):
            self.act_reexport.setEnabled(has_path)
        
        import os
        txt = f"Last: {os.path.basename(self.last_export_path)}" if has_path else "Last: (none)"
        self.lbl_last_export.setText(txt)

    def export_selected(self):
        if not self.output_node_item or getattr(self.output_backend, 'inputs', {}).get('src') is None:
            QMessageBox.information(self, 'Export', 'Connect a source to the Output node first.')
            return

        fn, _ = QFileDialog.getSaveFileName(self, 'Export PNG', 'output.png', 'PNG Files (*.png)')
        if fn:
            try:
                self.graph.export_png(self.output_backend, fn, size=self.graph.size)
                self.last_export_path = fn
                self._update_reexport_enabled()
                QMessageBox.information(self, 'Export', f'Saved {fn}')
            except Exception as e:
                QMessageBox.warning(self, 'Export failed', str(e))

    def reexport_output(self):
        if not self.last_export_path:
            return
        
        if self.confirm_overwrite_on_reexport:
            box = QMessageBox(self)
            box.setWindowTitle("Overwrite?")
            box.setText(f"Overwrite {self.last_export_path}?")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            cb = QCheckBox("Don't ask again")
            box.setCheckBox(cb)
            if box.exec() != QMessageBox.Yes:
                return
            if cb.isChecked():
                self.confirm_overwrite_on_reexport = False

        try:
            self.graph.export_png(self.output_backend, self.last_export_path, size=self.graph.size)
            self.statusBar().showMessage(f"Re-exported: {self.last_export_path}", 2000)
        except Exception as e:
            QMessageBox.warning(self, 'Re-Export failed', str(e))

    # ---------- Async Loading Callbacks ----------
    def load_graph_async(self):
        fn, _ = QFileDialog.getOpenFileName(self, 'Load Graph', '', 'JSON Files (*.json)')
        if not fn: return

        self._load_pd = QProgressDialog("Loading...", "Cancel", 0, 0, self)
        self._load_pd.canceled.connect(self._cancel_load_worker)

        self._load_nodes_done = self._load_edges_done = 0
        self._load_id_to_item = {}
        
        self._load_thread = QThread(self)
        self._load_worker = GraphLoadWorker(fn, NODE_REGISTRY)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.meta_ready.connect(self._on_load_meta_ready)
        self._load_worker.counts_ready.connect(self._on_load_counts_ready)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.node_ready.connect(self._on_load_node_ready)
        self._load_worker.edge_ready.connect(self._on_load_edge_ready)
        self._load_worker.done.connect(self._on_load_done)

        self._load_thread.start()

    def _cancel_load_worker(self):
        """Handle the user clicking 'Cancel' on the loading progress dialog."""
        if self._load_worker:
            self._load_worker.cancel()
        if self._load_thread:
            self._load_thread.quit()
            self._load_thread.wait(500)
        self.statusBar().showMessage("Load cancelled.", 2000)

    def _on_load_meta_ready(self, graph_size, preview_size, ui_scale, version):
        self.new_graph(size=graph_size, create_output=False)
        self.output_size_combo.blockSignals(True)
        self.output_size_combo.setCurrentIndex(self.output_size_combo.findData(graph_size))
        self.output_size_combo.blockSignals(False)
        self.preview_size = preview_size
        self.ui_scale_box.setValue(ui_scale)

    def _on_load_counts_ready(self, total_nodes, total_edges):
        self._load_total_nodes = total_nodes
        self._load_total_edges = total_edges
        self._load_total = max(1, total_nodes + total_edges)
        self._update_status_load_counters()

    def _on_load_progress(self, cur, total, msg):
        self._load_pd.setMaximum(total)
        self._load_pd.setValue(cur)
        self._load_pd.setLabelText(msg)
        self._update_status_load_counters(cur, total)

    def _on_load_node_ready(self, node_entry):
        try:
            cls_name = node_entry.get('class')
            cls = NODE_REGISTRY.get(cls_name)
            if not cls:
                print(f"[LOAD] Unknown node class: {cls_name}", flush=True)
                return

            params = normalize_params(node_entry.get('params', {}))

            # Filter params to only include those accepted by the class constructor
            try:
                sig = inspect.signature(cls.__init__)
                valid_params = set(sig.parameters.keys()) - {'self'}
                # Check if **kwargs is accepted
                accepts_kwargs = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if not accepts_kwargs:
                    params = {k: v for k, v in params.items() if k in valid_params}
            except (ValueError, TypeError) as e:
                print(f"[LOAD] Could not inspect {cls_name}: {e}", flush=True)

            inst = cls(name=node_entry.get('name'), **params)
            bnode = self.graph.add(inst)

            nitem = NodeItem(bnode.name, bnode, width=node_entry.get('width', self._default_card_width()))

            # Defer layout during batch add for performance
            for in_name in node_entry.get('inputs', []):
                nitem.add_input(in_name, defer_layout=True)

            # Handle outputs - check for saved outputs or known multi-output types
            outputs = node_entry.get('outputs', None)
            if outputs is None:
                if isinstance(bnode, Split):
                    outputs = ['r', 'g', 'b', 'a']
                elif isinstance(bnode, (Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp)):
                    outputs = [('out', 'scalar')]
                elif isinstance(bnode, Constant):
                    outputs = ['out', ('scalar', 'scalar')]
                else:
                    outputs = ['out']
            for out_spec in outputs:
                if isinstance(out_spec, (tuple, list)) and len(out_spec) == 2:
                    out_name, port_type = out_spec
                    nitem.add_output(out_name, port_type=port_type, defer_layout=True)
                else:
                    nitem.add_output(out_spec, defer_layout=True)

            # Restore exposed params
            exposed = node_entry.get('exposed_params', [])
            for param_name in exposed:
                nitem.exposed_params.add(param_name)
                # Add scalar input port for exposed param
                nitem.add_input(param_name, port_type="scalar", defer_layout=True)

            # Single layout call after all ports added
            nitem.layout_ports_and_resize()

            # During loading, set visibility directly without triggering expensive operations
            # Scalar nodes default to no preview
            default_preview = not isinstance(bnode, (Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp))
            nitem.preview_enabled = node_entry.get('preview_enabled', default_preview)
            nitem.preview_item.setVisible(nitem.preview_enabled)
            nitem.preview_frame.setVisible(nitem.preview_enabled)
            if not nitem.preview_enabled:
                nitem._last_preview_pil = None

            pos = node_entry.get('pos', [60, 60])
            self.scene.add_node_item(nitem, QPointF(pos[0], pos[1]))
            self._load_id_to_item[node_entry.get('id')] = nitem

            if nitem.backend_node.__class__.__name__ == 'Output':
                self.output_backend = nitem.backend_node
                self.output_node_item = nitem
                nitem._is_output_node = True

            self._load_nodes_done += 1
            self._update_status_load_counters()
        except Exception as e:
            import traceback
            print(f"[LOAD] Node load error for {node_entry.get('class', '?')}: {e}", flush=True)
            traceback.print_exc()

    def _on_load_edge_ready(self, e):
        try:
            src = self._load_id_to_item.get(e.get('src'))
            dst = self._load_id_to_item.get(e.get('dst'))
            if not src or not dst:
                return

            src_port = src.ports_out.get(e.get('src_port', 'out'))
            dst_port = dst.ports_in.get(e.get('dst_port')) or dst.ports_in.get(e.get('dst_port', '').lower())

            if src_port and dst_port:
                src_port_name = e.get('src_port', 'out')
                dst.backend_node.connect(dst_port.name, src.backend_node, src_port_name)
                edge = EdgeItem(src_port, dst_port)
                self.scene.edges.append(edge)
                self.scene.addItem(edge)
                self._load_edges_done += 1
                self._update_status_load_counters()
        except Exception as ex:
            print(f"Edge load error: {ex}")

    def _on_load_done(self, ok, msg):
        self._load_pd.reset()
        if ok:
            try:
                self.ensure_output_node()
                for n in self.scene.nodes:
                    if getattr(n, 'preview_enabled', True):
                        try:
                            n.update_preview(self.graph)
                        except Exception as e:
                            print(f"[LOAD] Preview update error for {getattr(n, 'label', '?')}: {e}")
                self.scene._refresh_edge_paths()
                self.large_preview.set_node_item(self.output_node_item)
                # Force one render after load even if paused
                self.large_preview.panel.render()
                self.statusBar().showMessage("Load complete.", 2000)
            except Exception as e:
                import traceback
                print(f"[LOAD] Finalization error: {e}")
                traceback.print_exc()
        elif msg:
            QMessageBox.warning(self, "Load failed", msg)

        if self._load_thread:
            self._load_thread.quit()
            self._load_thread.wait(1000)

    # ---------- Graph Management ----------
    def new_graph(self, size=None, create_output=True):
        for item in list(self.scene.items()):
            self.scene.removeItem(item)
        self.scene.nodes.clear()
        self.scene.edges.clear()

        size = size or OUTPUT_SIZE
        self.graph = Graph(size=size)
        self.inspector.set_node(None)

        self.last_export_path = None
        self._update_reexport_enabled()

        if create_output:
            self._create_output_node()

    def ensure_output_node(self):
        if not hasattr(self, 'output_node_item') or not self.output_node_item:
            self._create_output_node()

    # ---------- Save/Load ----------
    def save_graph(self):
        fn, _ = QFileDialog.getSaveFileName(self, 'Save Graph', 'graph.json', 'JSON Files (*.json)')
        if not fn: return

        id_map = {}
        nodes_data = []
        for idx, nitem in enumerate(self.scene.nodes):
            bnode = nitem.backend_node
            id_map[bnode] = idx
            params = {}
            for k, v in vars(bnode).items():
                if k.startswith('_') or k in ('name', 'inputs', 'dependents'):
                    continue
                params[k] = list(v) if isinstance(v, (tuple, list)) else v

            inputs = list(getattr(bnode, 'inputs', {}).keys())
            # Save outputs with their port types
            outputs = []
            for port_name, port in nitem.ports_out.items():
                if port.port_type != "image":
                    outputs.append([port_name, port.port_type])
                else:
                    outputs.append(port_name)
            nodes_data.append({
                'id': idx,
                'class': bnode.__class__.__name__,
                'name': getattr(bnode, 'name', bnode.__class__.__name__),
                'params': params,
                'inputs': inputs,
                'outputs': outputs,
                'exposed_params': list(getattr(nitem, 'exposed_params', set())),
                'pos': [float(nitem.pos().x()), float(nitem.pos().y())],
                'width': int(nitem.rect().width()),
                'preview_enabled': bool(getattr(nitem, 'preview_enabled', True)),
            })

        edges_data = []
        for dst_item in self.scene.nodes:
            dst_b = dst_item.backend_node
            for in_name, connection in getattr(dst_b, 'inputs', {}).items():
                if connection is None:
                    continue
                # Handle both tuple format (node, output_port) and legacy direct node reference
                if isinstance(connection, tuple):
                    src_b, src_port = connection
                else:
                    src_b, src_port = connection, 'out'
                edges_data.append({
                    'src': id_map.get(src_b),
                    'src_port': src_port,
                    'dst': id_map.get(dst_b),
                    'dst_port': in_name
                })

        def _spin_value(widget, default=0.0):
            val = getattr(widget, 'value', default)
            return float(val() if callable(val) else val)

        data = {
            'version': 1,
            'graph_size': int(getattr(self.graph, 'size', 512)),
            'preview_size': int(self.preview_size),
            'ui_scale': _spin_value(self.ui_scale_box, 1.0),
            'nodes': nodes_data,
            'edges': edges_data
        }

        try:
            with open(fn, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, 'Save Graph', f'Saved {fn}')
        except Exception as e:
            QMessageBox.warning(self, 'Save failed', str(e))

    def closeEvent(self, event):
        try:
            from texture_pig.ui.utils.actions import teardown_editor_actions
            if hasattr(self, 'actions') and self.actions:
                teardown_editor_actions(self, self.actions)
        except Exception:
            pass

        try:
            if self._load_worker and self._load_thread:
                self._load_worker.cancel()
                self._load_thread.quit()
                self._load_thread.wait(1000)
        except Exception:
            pass

        # Cleanup large preview render threads
        try:
            if hasattr(self, 'large_preview') and self.large_preview:
                self.large_preview.panel.cleanup()
        except Exception:
            pass

        super().closeEvent(event)

# ---- Node cloning helper ----
def clone_backend_node(orig):
    cls = orig.__class__
    params = {}
    for k, v in vars(orig).items():
        if k in ('name', 'inputs', 'dependents', '_cache', '_dirty', '_generation', '_gen_cache'):
            continue
        params[k] = v
    new_name = f"{getattr(orig, 'name', cls.__name__)}_copy"
    try:
        node = cls(name=new_name, **params)
    except TypeError:
        node = cls(**params)
        try:
            node.name = new_name
        except Exception:
            pass
    return node


def run():
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    register_qt_resources()
    load_stylesheet_with_fallback(app)

    win = GraphEditor()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
