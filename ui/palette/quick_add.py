
# ui/palette/quick_add.py
from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QAbstractItemView
)

from texture_pig.ui.palette.palette_model import build_default_entries, PaletteEntry
from texture_pig.nodes.utils import resolve_qt_resource_or_fs


# Optional icon mapping for nicer list visuals (uses your compiled :/ui/icons/*)
_ICON_MAP = {
    'GradientLinear':   ':/ui/icons/gradient_linear_128.png',
    'GradientRadial':   ':/ui/icons/gradient_radial_128.png',
    'GradientReflected':':/ui/icons/gradient_reflected_128.png',
    'GradientAngle':    ':/ui/icons/gradient_angle_128.png',
    'PerlinNoise':      ':/ui/icons/perlin_128.png',
    'WorleyNoise':      ':/ui/icons/worley_128.png',
    'Circle':           ':/ui/icons/circle_128.png',
    'Rectangle':        ':/ui/icons/rectangle_128.png',
    'Triangle':         ':/ui/icons/triangle_128.png',
    'Line':             ':/ui/icons/line_128.png',
    'Stripes':          ':/ui/icons/stripes_128.png',
    'HexGrid':          ':/ui/icons/hex_grid_128.png',
    # Filters / Ops (no specific icons in your bundle — leave blank or reuse)
    # 'GaussianBlur':   '',
    # 'Transform':      '',
    # 'Invert':         '',
    # 'Levels':         '',
    # 'Combine':        '',
    # Blends (could reuse one icon for all)
    # 'Blend (normal)': '',
    # Sources
    # 'Image':          '',
    # Layout
    # 'Grid':           '',
    # 'RadialGrid':     '',
}


class QuickAddDialog(QDialog):
    """
    Spacebar “Quick Add” palette:
      - Search bar filters nodes by name (case-insensitive substring).
      - Enter / double-click adds the selected node under the mouse cursor.
    """
    def __init__(self, editor: 'GraphEditor'):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle("Add Node")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search nodes…")
        layout.addWidget(self.search)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.list)

        self.entries: List[PaletteEntry] = build_default_entries()
        self._populate_list(self.entries)

        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self._on_search_enter)
        self.list.itemActivated.connect(self._on_item_activated)
        self.search.setFocus()

    def _populate_list(self, entries: List[PaletteEntry]):
        self.list.clear()
        for e in entries:
            label = e.label
            category = e.category or ''
            text = label if not category else f"{label}  —  {category}"

            item = QListWidgetItem(text)
            # Optional: add icons to the list if available
            icon_path = _ICON_MAP.get(label)
            if icon_path:
                icon = resolve_qt_resource_or_fs(icon_path)
                item.setIcon(icon if isinstance(icon, QIcon) else QIcon(icon))
            item.setData(Qt.UserRole, e)
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _on_search_text(self, text: str):
        q = (text or '').strip().lower()
        if not q:
            self._populate_list(self.entries)
            return
        filtered = [e for e in self.entries if q in e.label.lower()]
        self._populate_list(filtered)

    def _on_search_enter(self):
        """When Enter is pressed in search, activate the first item."""
        if self.list.count() > 0:
            item = self.list.item(0)
            if item:
                self._on_item_activated(item)

    def _on_item_activated(self, item: QListWidgetItem):
        entry: PaletteEntry = item.data(Qt.UserRole)
        if not entry:
            return
        try:
            backend_node = entry.factory()
            inputs = entry.inputs

            # Add under mouse cursor
            pos_global = QCursor.pos()
            view = self.editor.view
            pos_view = view.mapFromGlobal(pos_global)
            pos_scene = view.mapToScene(pos_view)

            self.editor.add_node_ui(backend_node, inputs=inputs, pos_scene=pos_scene)
            self.accept()
        except Exception as e:
            import traceback
            traceback.print_exc()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Add Node Failed", f"{type(e).__name__}: {e}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
