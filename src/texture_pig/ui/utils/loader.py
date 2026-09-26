
# ui/utils/loader.py
from __future__ import annotations
from typing import Dict, Any
from PySide6.QtCore import QObject, Signal

class GraphLoadWorker(QObject):
    """
    Loads a graph JSON on a worker thread and emits signals to build the UI incrementally.
    """
    # Header/meta before nodes/edges
    meta_ready   = Signal(int, int, float, int)  # graph_size, preview_size, ui_scale, version
    counts_ready = Signal(int, int)              # total_nodes, total_edges

    # Live progress and streamed entries
    progress   = Signal(int, int, str)           # current, total, message
    node_ready = Signal(dict)                    # node_entry dict
    edge_ready = Signal(dict)                    # edge_entry dict

    # Completion
    done = Signal(bool, str)                     # success, error_message

    def __init__(self, filename: str, node_registry: Dict[str, Any]):
        super().__init__()
        self._fn = filename
        self._node_registry = node_registry
        self._stop = False

    def cancel(self):  # called from UI thread when user presses "Cancel"
        self._stop = True

    def run(self):
        import json
        try:
            with open(self._fn, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.done.emit(False, f"Could not read file: {e}")
            return

        version      = int(data.get('version', 1))
        graph_size   = int(data.get('graph_size', 512))
        preview_size = int(data.get('preview_size', 256))
        ui_scale     = float(data.get('ui_scale', 1.0))

        nodes_entries = list(data.get('nodes', []))
        edges_entries = list(data.get('edges', []))
        total_nodes   = len(nodes_entries)
        total_edges   = len(edges_entries)
        total         = max(1, total_nodes + total_edges)
        cur           = 0

        # Emit meta and counts first so UI can prep and show totals
        self.meta_ready.emit(graph_size, preview_size, ui_scale, version)
        self.counts_ready.emit(total_nodes, total_edges)

        # Stream nodes
        for ne in nodes_entries:
            if self._stop:
                self.done.emit(False, "Canceled")
                return
            self.node_ready.emit(ne)
            cur += 1
            name = ne.get('name', ne.get('class', ''))
            self.progress.emit(cur, total, f"Loading node {name}…")

        # Stream edges
        for ee in edges_entries:
            if self._stop:
                self.done.emit(False, "Canceled")
                return
            self.edge_ready.emit(ee)
            cur += 1
            msg = f"Connecting {ee.get('dst_port', '')}…"
            self.progress.emit(cur, total, msg)

        self.done.emit(True, "")
