
# ui/utils/actions.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List
from shiboken6 import isValid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

from texture_pig.ui.utils.editor_helpers import shorten_label, compute_edit_menu_min_width


@dataclass
class EditorActions:
    """Container for editor-wide actions and shortcuts."""
    # Menus
    file_menu: QMenu
    edit_menu: QMenu

    # Actions
    act_undo: QAction
    act_redo: QAction
    act_export: QAction
    act_reexport: QAction

    # Shortcuts (keep references so they don't get GC'd)
    shortcuts: List[QShortcut]

    def sync_undo_redo_labels(self, editor: 'GraphEditor'):
        # Guard against teardown — skip if objects are already destroyed
        if editor is None or not isValid(editor):
            return
        st = getattr(editor, 'undo_stack', None)
        if st is None or not isValid(st):
            return
        if self.edit_menu is None or not isValid(self.edit_menu):
            return

        # ---- Normal logic below ----
        if st.canUndo():
            txt = st.undoText()
            self.act_undo.setText(f"Undo {shorten_label(txt)}")
            self.act_undo.setEnabled(True)
        else:
            self.act_undo.setText("Undo")
            self.act_undo.setEnabled(False)

        if st.canRedo():
            txt = st.redoText()
            self.act_redo.setText(f"Redo {shorten_label(txt)}")
            self.act_redo.setEnabled(True)
        else:
            self.act_redo.setText("Redo")
            self.act_redo.setEnabled(False)

        needed = compute_edit_menu_min_width(self.edit_menu)
        self.edit_menu.setMinimumWidth(needed)

    def on_undo_triggered(self, editor: 'GraphEditor'):
        try:
            editor.undo_stack.undo()
        finally:
            QTimer.singleShot(0, lambda: self._safe_sync(editor))

    def on_redo_triggered(self, editor: 'GraphEditor'):
        try:
            editor.undo_stack.redo()
        finally:
            QTimer.singleShot(0, lambda: self._safe_sync(editor))

    def _safe_sync(self, editor: 'GraphEditor'):
        # only sync if still valid
        if editor is None or not isValid(editor):
            return
        st = getattr(editor, 'undo_stack', None)
        if st is None or not isValid(st):
            return
        self.sync_undo_redo_labels(editor)


def setup_editor_actions(editor: 'GraphEditor') -> EditorActions:
    """
    Build menus, actions and shortcuts for the editor, and wire them up.
    Returns EditorActions container and also sets editor.edit_menu / editor.act_reexport.
    """
    mb = editor.menuBar()

    # --- Menus ---
    file_menu = mb.addMenu("File")
    edit_menu = mb.addMenu("Edit")

    # --- Actions: Undo / Redo (manual, symmetric behavior) ---

    act_undo = QAction("Undo", editor)
    act_redo = QAction("Redo", editor)

    def _unique_shortcuts(*seqs) -> list[QKeySequence]:
        """Return a list of QKeySequence without duplicates (by toString())."""
        seen = set()
        out = []
        for s in seqs:
            if not s:
                continue
            items = s if isinstance(s, (list, tuple)) else [s]
            for it in items:
                try:
                    txt = QKeySequence(it).toString()
                except Exception:
                    continue
                key = (txt or "").lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(QKeySequence(txt))
        return out


    # Duplicate
    act_duplicate = QAction("Duplicate", editor)
    act_duplicate.setShortcuts(_unique_shortcuts(QKeySequence("Ctrl+D")))
    act_duplicate.setShortcutContext(Qt.ApplicationShortcut)
    act_duplicate.triggered.connect(lambda: editor.duplicate_selected(rewire_downstream=False))
    # Add to main window accelerators
    editor.addAction(act_duplicate)
    # (Optional) Show in Edit menu)
    # edit_menu.addAction(act_duplicate)

    # Duplicate & Rewire
    act_duplicate_rewire = QAction("Duplicate & Rewire Downstream", editor)
    act_duplicate_rewire.setShortcuts(_unique_shortcuts(QKeySequence("Ctrl+Shift+D")))
    act_duplicate_rewire.setShortcutContext(Qt.ApplicationShortcut)
    act_duplicate_rewire.triggered.connect(lambda: editor.duplicate_selected(rewire_downstream=True))
    editor.addAction(act_duplicate_rewire)
    # edit_menu.addAction(act_duplicate_rewire)

    # Delete (support both Delete and Backspace)
    act_delete = QAction("Delete Selected", editor)
    act_delete.setShortcuts(_unique_shortcuts(QKeySequence(Qt.Key_Delete), QKeySequence(Qt.Key_Backspace)))
    act_delete.setShortcutContext(Qt.ApplicationShortcut)
    act_delete.triggered.connect(editor.delete_selected_nodes)
    editor.addAction(act_delete)
    # edit_menu.addAction(act_delete)

    # Build Redo shortcut list de-duplicated across platforms
    redo_shortcuts = _unique_shortcuts(
        QKeySequence.Redo,           # platform default
        QKeySequence("Ctrl+Y"),      # explicit Windows habit
        QKeySequence("Ctrl+Shift+Z") # explicit alternative habit
    )
    # Build Undo shortcuts (usually one is enough, but we support both habits)
    undo_shortcuts = _unique_shortcuts(
        QKeySequence.Undo,
        QKeySequence("Ctrl+Z")
    )

    # Assign to actions
    act_undo.setShortcuts(undo_shortcuts)
    act_redo.setShortcuts(redo_shortcuts)

    # Make them active across the whole window (children included)
    act_undo.setShortcutContext(Qt.WidgetWithChildrenShortcut)
    act_redo.setShortcutContext(Qt.WidgetWithChildrenShortcut)

    # Ensure the main window owns the actions so shortcuts are recognized globally
    editor.addAction(act_undo)
    editor.addAction(act_redo)

    # Add to menu (for visibility & shortcut hint)
    edit_menu.addAction(act_undo)
    edit_menu.addAction(act_redo)

    # --- Actions: File menu ---
    act_new = file_menu.addAction("New Graph")
    act_new.triggered.connect(lambda: editor.new_graph())

    act_save = file_menu.addAction("Save Graph…")
    act_save.setShortcut(QKeySequence("Ctrl+S"))
    act_save.triggered.connect(editor.save_graph)

    act_load = file_menu.addAction("Load Graph…")
    act_load.setShortcut(QKeySequence("Ctrl+O"))
    act_load.triggered.connect(editor.load_graph_async)

    act_export = file_menu.addAction("Export Output…")
    act_export.setShortcut(QKeySequence("Ctrl+E"))
    act_export.triggered.connect(editor.export_selected)

    act_reexport = file_menu.addAction("Re-Export")
    act_reexport.setShortcut(QKeySequence("Ctrl+Shift+E"))
    act_reexport.triggered.connect(editor.reexport_output)
    act_reexport.setEnabled(False)  # enabled after first export

    act_quit = file_menu.addAction("Quit")
    act_quit.setShortcut(QKeySequence("Ctrl+Q"))
    act_quit.triggered.connect(editor.close)

    # Publish to editor so existing code keeps working
    editor.edit_menu = edit_menu
    editor.act_reexport = act_reexport
    
    shortcuts: List[QShortcut] = []
    # Quick Add: SPACE (works when the view has focus)
    sc_quick_add = QShortcut(QKeySequence("Space"), editor.view)
    sc_quick_add.setContext(Qt.WidgetWithChildrenShortcut)
    sc_quick_add.activated.connect(editor.open_quick_add)
    shortcuts.append(sc_quick_add)

    # Build container
    actions = EditorActions(
        file_menu=file_menu,
        edit_menu=edit_menu,
        act_undo=act_undo,
        act_redo=act_redo,
        act_export=act_export,
        act_reexport=act_reexport,
        shortcuts=shortcuts,
    )

    # ✅ Connect Undo/Redo menu actions to handlers (this was missing)
    act_undo.triggered.connect(lambda: actions.on_undo_triggered(editor))
    act_redo.triggered.connect(lambda: actions.on_redo_triggered(editor))

    # Sync labels on stack changes
    editor.undo_stack.undoTextChanged.connect(lambda: actions.sync_undo_redo_labels(editor))
    editor.undo_stack.redoTextChanged.connect(lambda: actions.sync_undo_redo_labels(editor))
    editor.undo_stack.canUndoChanged.connect(lambda: actions.sync_undo_redo_labels(editor))
    editor.undo_stack.canRedoChanged.connect(lambda: actions.sync_undo_redo_labels(editor))

    # Initial sync
    actions.sync_undo_redo_labels(editor)

    return actions


def teardown_editor_actions(editor: 'GraphEditor', actions: EditorActions):
    """Disconnect signals and clear references to avoid callbacks during teardown."""
    try:
        # Disconnect stack signals
        editor.undo_stack.undoTextChanged.disconnect()
        editor.undo_stack.redoTextChanged.disconnect()
        editor.undo_stack.canUndoChanged.disconnect()
        editor.undo_stack.canRedoChanged.disconnect()
    except Exception:
        pass

    # Disconnect action triggers
    try:
        actions.act_undo.triggered.disconnect()
    except Exception:
        pass
    try:
        actions.act_redo.triggered.disconnect()
    except Exception:
        pass

    actions.shortcuts.clear()
