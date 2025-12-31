# ui/preview/preview_worker.py
"""
Threaded preview rendering system with progressive resolution and cancellation.

Architecture:
1. Slider changes → Queue downstream nodes for update
2. Worker thread pool picks up nodes from queue
3. Worker renders preview at small size first (64px)
4. Signal back to main thread → update thumbnail
5. If no new changes, render full size
6. New slider change → cancel pending full-size renders
"""
from __future__ import annotations
from typing import Optional, Dict, Set, List, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import IntEnum
import threading
import time

import numpy as np
from PIL import Image

from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, QMutex, QMutexLocker

if TYPE_CHECKING:
    from texture_pig.ui.nodes.node_item import NodeItem
    from texture_pig.nodes.core import Graph


class TaskPriority(IntEnum):
    """Priority levels for preview tasks (lower = higher priority)."""
    CURRENT_NODE = 0      # The node being edited - highest priority
    DIRECT_CHILD = 1      # Immediate downstream nodes
    DOWNSTREAM = 2        # Further downstream nodes
    LOW = 3               # Background/idle updates


@dataclass
class PreviewTask:
    """Represents a preview rendering task."""
    node_item: 'NodeItem'
    graph: 'Graph'
    priority: TaskPriority
    size: int                          # Target render size
    generation: int                    # Cancellation token - older generations are skipped
    is_low_res: bool = True            # True for quick preview, False for full quality
    created_at: float = field(default_factory=time.time)

    def __lt__(self, other: 'PreviewTask') -> bool:
        """For priority queue ordering."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class PreviewWorkerSignals(QObject):
    """Signals for communicating results back to main thread."""
    # (node_item, rendered_image_array, is_low_res)
    preview_ready = Signal(object, object, bool)
    # (node_item, error_message)
    preview_error = Signal(object, str)


class PreviewRunnable(QRunnable):
    """
    Worker that renders a single node preview.
    Checks cancellation before and after rendering.
    """

    def __init__(self, task: PreviewTask, signals: PreviewWorkerSignals,
                 cancel_check: callable):
        super().__init__()
        self.task = task
        self.signals = signals
        self.cancel_check = cancel_check
        self.setAutoDelete(True)

    def run(self):
        """Execute the preview render in worker thread."""
        # Check if cancelled before starting
        if self.cancel_check(self.task.node_item, self.task.generation):
            return

        try:
            # Render the preview
            node = self.task.node_item.backend_node
            size = self.task.size

            # For low-res preview, use smaller size
            render_size = 64 if self.task.is_low_res else size

            arr = self.task.graph.output(node, size=render_size)

            # Check if cancelled after rendering
            if self.cancel_check(self.task.node_item, self.task.generation):
                return

            # Emit result back to main thread
            self.signals.preview_ready.emit(
                self.task.node_item,
                arr,
                self.task.is_low_res
            )

        except Exception as e:
            self.signals.preview_error.emit(self.task.node_item, str(e))


class PreviewWorkerPool(QObject):
    """
    Manages threaded preview rendering with priority queue and cancellation.

    Usage:
        pool = PreviewWorkerPool(editor)
        pool.queue_node(node_item, priority=TaskPriority.CURRENT_NODE)
        pool.queue_downstream(node_item)  # Queue all downstream nodes
        pool.cancel_pending(node_item)    # Cancel pending tasks for a node
    """

    def __init__(self, editor: 'GraphEditor', max_threads: int = 4):
        super().__init__()
        self.editor = editor
        self.signals = PreviewWorkerSignals()

        # Thread pool
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)

        # Track generations for cancellation (node_item -> current generation)
        self._generations: Dict[object, int] = {}
        self._generation_lock = QMutex()

        # Track pending tasks
        self._pending: Set[object] = set()
        self._pending_lock = QMutex()

        # Connect signals
        self.signals.preview_ready.connect(self._on_preview_ready)
        self.signals.preview_error.connect(self._on_preview_error)

    def _get_generation(self, node_item: 'NodeItem') -> int:
        """Get current generation for a node (thread-safe)."""
        with QMutexLocker(self._generation_lock):
            return self._generations.get(id(node_item), 0)

    def _increment_generation(self, node_item: 'NodeItem') -> int:
        """Increment and return new generation for a node (thread-safe)."""
        with QMutexLocker(self._generation_lock):
            node_id = id(node_item)
            gen = self._generations.get(node_id, 0) + 1
            self._generations[node_id] = gen
            return gen

    def _is_cancelled(self, node_item: 'NodeItem', generation: int) -> bool:
        """Check if a task's generation is outdated (thread-safe)."""
        current = self._get_generation(node_item)
        return generation < current

    def cancel_pending(self, node_item: 'NodeItem'):
        """Cancel all pending tasks for a node by incrementing its generation."""
        self._increment_generation(node_item)

    def cancel_all_downstream(self, start_node: 'NodeItem'):
        """Cancel all pending tasks for downstream nodes."""
        downstream = self._get_downstream_nodes(start_node)
        for node in downstream:
            self.cancel_pending(node)

    def queue_node(self, node_item: 'NodeItem', priority: TaskPriority = TaskPriority.DOWNSTREAM,
                   low_res_first: bool = True):
        """
        Queue a single node for preview update.

        Args:
            node_item: The node to update
            priority: Task priority level
            low_res_first: If True, render low-res preview first, then full
        """
        if not node_item or not hasattr(self.editor, 'graph'):
            return

        # Cancel any pending tasks for this node
        generation = self._increment_generation(node_item)

        # Get target size from editor
        preview_size = getattr(self.editor, 'preview_size', 128)

        if low_res_first:
            # Queue low-res task (high priority within same level)
            task_low = PreviewTask(
                node_item=node_item,
                graph=self.editor.graph,
                priority=priority,
                size=preview_size,
                generation=generation,
                is_low_res=True
            )
            self._submit_task(task_low)

            # Queue full-res task (slightly lower priority)
            task_full = PreviewTask(
                node_item=node_item,
                graph=self.editor.graph,
                priority=TaskPriority(min(priority + 1, TaskPriority.LOW)),
                size=preview_size,
                generation=generation,
                is_low_res=False
            )
            self._submit_task(task_full)
        else:
            # Single full-res task
            task = PreviewTask(
                node_item=node_item,
                graph=self.editor.graph,
                priority=priority,
                size=preview_size,
                generation=generation,
                is_low_res=False
            )
            self._submit_task(task)

    def queue_downstream(self, start_node: 'NodeItem', include_start: bool = False):
        """
        Queue all downstream nodes for preview update.

        Args:
            start_node: The node that was modified
            include_start: Whether to include start_node itself
        """
        downstream = self._get_downstream_nodes(start_node)

        if include_start:
            self.queue_node(start_node, priority=TaskPriority.CURRENT_NODE)

        # Get direct children for higher priority
        direct_children = self._get_direct_children(start_node)

        for node in downstream:
            if node is start_node:
                continue

            if node in direct_children:
                priority = TaskPriority.DIRECT_CHILD
            else:
                priority = TaskPriority.DOWNSTREAM

            self.queue_node(node, priority=priority)

    def _get_downstream_nodes(self, start_node: 'NodeItem') -> Set['NodeItem']:
        """Get all nodes downstream from start_node."""
        if not hasattr(self.editor, 'scene'):
            return set()

        # Build adjacency
        adj: Dict['NodeItem', Set['NodeItem']] = {}
        for e in self.editor.scene.edges:
            if e.src and e.dst:
                adj.setdefault(e.src.node_item, set()).add(e.dst.node_item)

        # BFS to find all downstream
        downstream = set()
        stack = list(adj.get(start_node, []))
        while stack:
            cur = stack.pop()
            if cur not in downstream:
                downstream.add(cur)
                stack.extend(adj.get(cur, []))

        return downstream

    def _get_direct_children(self, node: 'NodeItem') -> Set['NodeItem']:
        """Get nodes directly connected to node's outputs."""
        if not hasattr(self.editor, 'scene'):
            return set()

        children = set()
        for e in self.editor.scene.edges:
            if e.src and e.src.node_item is node and e.dst:
                children.add(e.dst.node_item)
        return children

    def _submit_task(self, task: PreviewTask):
        """Submit a task to the thread pool."""
        with QMutexLocker(self._pending_lock):
            self._pending.add(id(task.node_item))

        runnable = PreviewRunnable(
            task=task,
            signals=self.signals,
            cancel_check=self._is_cancelled
        )

        # Set priority (QThreadPool uses higher number = higher priority, we invert)
        priority = 10 - int(task.priority)
        self._pool.start(runnable, priority)

    def _on_preview_ready(self, node_item: 'NodeItem', arr: np.ndarray, is_low_res: bool):
        """Handle completed preview render (called on main thread)."""
        with QMutexLocker(self._pending_lock):
            self._pending.discard(id(node_item))

        # Update the node's preview
        try:
            if hasattr(node_item, '_update_preview_from_array'):
                node_item._update_preview_from_array(arr, is_low_res)
            else:
                # Fallback: use existing update method
                node_item.update_preview(self.editor.graph)
        except Exception as e:
            print(f"[PreviewWorker] Error updating preview: {e}")

    def _on_preview_error(self, node_item: 'NodeItem', error: str):
        """Handle preview render error (called on main thread)."""
        with QMutexLocker(self._pending_lock):
            self._pending.discard(id(node_item))
        print(f"[PreviewWorker] Render error for {getattr(node_item, 'label', '?')}: {error}")

    def shutdown(self):
        """Wait for all pending tasks to complete."""
        self._pool.waitForDone(5000)  # 5 second timeout
