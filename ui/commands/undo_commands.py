# ui/commands/undo_commands.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional
from shiboken6 import isValid
from PySide6.QtGui import QUndoCommand
from PySide6.QtCore import QPointF

from texture_pig.ui.nodes.edge_item import EdgeItem
from texture_pig.ui.nodes.port_item import PortItem
from texture_pig.ui.utils.editor_helpers import normalize_params

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from texture_pig.ui.nodes.node_item import NodeItem

def _new_node_item(*args, **kwargs):
    from texture_pig.ui.nodes.node_item import NodeItem
    return NodeItem(*args, **kwargs)

@dataclass
class _NodeSnapshot:
    cls: type
    name: str
    params: dict
    inputs: List[str]
    pos: QPointF
    width: int
    preview_enabled: bool
    scale: float
    # (src_backend, src_port_name, dst_port_name_on_this_node)
    incoming_edges: List[Tuple[object, str, str]]
    # (dst_backend, dst_port_name_on_dst, src_port_name_on_this_node)
    outgoing_edges: List[Tuple[object, str, str]]


def _make_node_snapshot(editor, node_item: NodeItem) -> _NodeSnapshot:
    b = node_item.backend_node
    cls = b.__class__

    # Capture backend params (excluding wiring/internal)
    params = {}
    for k, v in vars(b).items():
        if k.startswith('_') or k in ('name', 'inputs', 'dependents'):
            continue
        params[k] = list(v) if isinstance(v, (tuple, list)) else v

    inputs = list(getattr(b, 'inputs', {}).keys())
    pos = QPointF(node_item.pos())
    width = int(node_item.rect().width())
    preview_enabled = bool(getattr(node_item, 'preview_enabled', True))
    try:
        scale = float(node_item.scale())
    except Exception:
        scale = 1.0

    incoming: List[Tuple[object, str, str]] = []
    outgoing: List[Tuple[object, str, str]] = []
    for e in list(editor.scene.edges):
        if e.dst and e.dst.node_item is node_item:
            # src -> this
            incoming.append((e.src.node_item.backend_node, e.src.name, e.dst.name))
        if e.src and e.src.node_item is node_item:
            # this -> dst
            outgoing.append((e.dst.node_item.backend_node, e.dst.name, e.src.name))

    return _NodeSnapshot(
        cls=cls,
        name=getattr(b, 'name', cls.__name__),
        params=params,
        inputs=inputs,
        pos=pos,
        width=width,
        preview_enabled=preview_enabled,
        scale=scale,
        incoming_edges=incoming,
        outgoing_edges=outgoing,
    )


def _find_item_by_backend(editor, backend_obj) -> Optional[NodeItem]:
    """Find the current NodeItem in the scene whose backend_node is backend_obj."""
    for it in editor.scene.nodes:
        try:
            if it.backend_node is backend_obj:
                return it
        except Exception:
            pass
    return None

class DeleteNodeCommand(QUndoCommand):
    def __init__(self, editor, node_item):
        super().__init__(f"Delete {getattr(node_item.backend_node, 'name', 'Node')}")
        self.editor = editor
        self.node_item = node_item
        self.snap = _make_node_snapshot(editor, node_item)
        self._restored_item = None

    def redo(self):
        # Delete whichever instance is currently alive (restored after an undo, or original when first pushed)
        target = self._restored_item or self.node_item
        if getattr(target, '_is_output_node', False):
            return
        try:
            self.editor.scene.delete_node_item(target)
            if target is self._restored_item:
                # Clear pointer so next Undo rebuilds from snapshot again
                self._restored_item = None
        except Exception:
            logger.exception("[DeleteNodeCommand] redo failed")

    def undo(self):
        nitem = None  # guard to avoid UnboundLocalError

        # Recreate backend
        cls = self.snap.cls
        params = normalize_params(self.snap.params)
        name = self.snap.name

        try:
            try:
                inst = cls(name=name, **params)
            except TypeError:
                inst = cls(**params)
                try:
                    inst.name = name
                except Exception:
                    pass
        except Exception:
            logger.exception("[DeleteNodeCommand] undo instantiate failed")
            return

        try:
            bnode = self.editor.graph.add(inst)
        except Exception:
            logger.exception("[DeleteNodeCommand] undo graph add failed")
            return

        # Build UI item + add to scene
        try:
            nitem = _new_node_item(bnode.name, bnode, width=int(self.snap.width))
            for in_name in self.snap.inputs:
                try:
                    nitem.add_input(in_name)
                except Exception:
                    pass
            nitem.add_output('out')

            try:
                nitem.preview_enabled = bool(self.snap.preview_enabled)
            except Exception:
                nitem.preview_enabled = True
            nitem._apply_preview_visibility()

            self.editor.scene.add_node_item(nitem, QPointF(self.snap.pos))
            nitem.setScale(float(self.snap.scale))
        except Exception:
            logger.exception("[DeleteNodeCommand] undo UI build failed")
            return  # IMPORTANT: don’t fall through and touch nitem

        # Rewire incoming edges: src -> restored
        for (src_b, src_port_name, dst_port_name) in self.snap.incoming_edges:
            try:
                src_item = _find_item_by_backend(self.editor, src_b)
                if not src_item:
                    continue
                src_port = src_item.ports_out.get(src_port_name) or src_item.ports_out.get('out')
                dst_port = nitem.ports_in.get(dst_port_name)
                if not src_port or not dst_port:
                    continue
                nitem.backend_node.connect(dst_port.name, src_item.backend_node, src_port_name)
                edge = EdgeItem(src_port, dst_port)
                self.editor.scene.edges.append(edge)
                self.editor.scene.addItem(edge)
            except Exception:
                logger.exception("[DeleteNodeCommand] restore incoming failed")

        # Rewire outgoing edges: restored -> dst
        for (dst_b, dst_port_name, src_port_name) in self.snap.outgoing_edges:
            try:
                dst_item = _find_item_by_backend(self.editor, dst_b)
                if not dst_item:
                    # fallback by name
                    try:
                        dst_name = getattr(dst_b, 'name', '')
                        for it2 in self.editor.scene.nodes:
                            if it2.backend_node.name == dst_name:
                                dst_item = it2; break
                    except Exception:
                        pass
                if not dst_item:
                    continue
                src_port = nitem.ports_out.get(src_port_name) or nitem.ports_out.get('out')
                dst_port = dst_item.ports_in.get(dst_port_name)
                if not src_port or not dst_port:
                    continue
                dst_item.backend_node.connect(dst_port.name, nitem.backend_node, src_port_name)
                edge = EdgeItem(src_port, dst_port)
                self.editor.scene.edges.append(edge)
                self.editor.scene.addItem(edge)
            except Exception:
                logger.exception("[DeleteNodeCommand] restore outgoing failed")

        # Finalize
        self._restored_item = nitem
        try:
            self.editor.update_previews_from(nitem)
        except Exception:
            pass

class DeleteNodesCommand(QUndoCommand):
    """
    Undoable delete of multiple selected nodes in one step.
    Applies deletion on redo; on undo, restores all nodes then rewires edges.
    """
    def __init__(self, editor, node_items: List[NodeItem]):
        super().__init__("Delete Nodes")
        self.editor = editor
        self.node_items = [it for it in node_items if not getattr(it, '_is_output_node', False)]
        self.snaps = [ _make_node_snapshot(editor, it) for it in self.node_items ]
        self._restored_items: List[NodeItem] = []

    def redo(self):
        # Prefer deleting the currently restored instances if undo was performed
        targets = self._restored_items if self._restored_items else self.node_items
        for it in list(targets):
            try:
                self.editor.scene.delete_node_item(it)
            except Exception:
                logger.exception("[DeleteNodesCommand] redo failed for %s",
                                  getattr(it.backend_node, 'name', 'Node'))
        # After redo, clear restored list so undo can rebuild fresh from snapshots
        self._restored_items.clear()

    def undo(self):
        self._restored_items = []
        for snap in self.snaps:
            try:
                try:
                    inst = snap.cls(name=snap.name, **normalize_params(snap.params))
                except TypeError:
                    inst = snap.cls(**normalize_params(snap.params))
                    try:
                        inst.name = snap.name
                    except Exception:
                        pass
                bnode = self.editor.graph.add(inst)

                nitem = _new_node_item(bnode.name, bnode, width=int(snap.width))
                for in_name in snap.inputs:
                    try:
                        nitem.add_input(in_name)
                    except Exception:
                        pass
                nitem.add_output('out')
                nitem.preview_enabled = bool(snap.preview_enabled)
                nitem._apply_preview_visibility()
                self.editor.scene.add_node_item(nitem, QPointF(snap.pos))
                nitem.setScale(float(snap.scale))

                self._restored_items.append(nitem)  # only now it’s safe
            except Exception:
                logger.exception("[DeleteNodesCommand] undo instantiate failed")
                continue

        self._restored_item = nitem
        try:
            self.editor.update_previews_from(nitem)
        except Exception:
            pass

        # Rewire edges for each snapshot (best-effort)
        for snap in self.snaps:
            nitem = None
            # find restored item by name (or by position match)
            for it in self._restored_items:
                if it.backend_node.name == snap.name:
                    nitem = it; break
            if not nitem:
                continue

            # incoming: src -> nitem
            for (src_b, src_port_name, dst_port_name) in snap.incoming_edges:
                # src_b may have been restored; find current item either by original backend or by name
                src_item = _find_item_by_backend(self.editor, src_b)  # if still exists
                if not src_item:
                    # try name match: original src_b.name
                    try:
                        src_name = getattr(src_b, 'name', '')
                        for it2 in self.editor.scene.nodes:
                            if it2.backend_node.name == src_name:
                                src_item = it2; break
                    except Exception:
                        pass
                if not src_item:
                    continue
                src_port = src_item.ports_out.get(src_port_name) or src_item.ports_out.get('out')
                dst_port = nitem.ports_in.get(dst_port_name)
                if not src_port or not dst_port:
                    continue
                try:
                    nitem.backend_node.connect(dst_port.name, src_item.backend_node, src_port_name)
                    edge = EdgeItem(src_port, dst_port)
                    self.editor.scene.edges.append(edge)
                    self.editor.scene.addItem(edge)
                except Exception:
                    logger.exception("[DeleteNodesCommand] restore incoming failed")

            # outgoing: nitem -> dst
            for (dst_b, dst_port_name, src_port_name) in snap.outgoing_edges:
                dst_item = _find_item_by_backend(self.editor, dst_b)
                if not dst_item:
                    # try name match
                    try:
                        dst_name = getattr(dst_b, 'name', '')
                        for it2 in self.editor.scene.nodes:
                            if it2.backend_node.name == dst_name:
                                dst_item = it2; break
                    except Exception:
                        pass
                if not dst_item:
                    continue
                src_port = nitem.ports_out.get(src_port_name) or nitem.ports_out.get('out')
                dst_port = dst_item.ports_in.get(dst_port_name)
                if not src_port or not dst_port:
                    continue
                try:
                    dst_item.backend_node.connect(dst_port.name, nitem.backend_node, src_port_name)
                    edge = EdgeItem(src_port, dst_port)
                    self.editor.scene.edges.append(edge)
                    self.editor.scene.addItem(edge)
                except Exception:
                    logger.exception("[DeleteNodesCommand] restore outgoing failed")

        # One downstream refresh
        try:
            if self._restored_items:
                self.editor.update_previews_from(self._restored_items[0])
        except Exception:
            pass

class SetNodeParamCommand(QUndoCommand):
    """
    Undoable parameter change for a node.
    Uses backend_node.set_params(**{param_name: value}) both on undo/redo.
    Editor is expected to refresh previews via editor.update_previews_from(node_item).
    """
    def __init__(self, editor, node_item, param_name: str, old_value, new_value):
        # Command label surfaces under Undo/Redo menu
        super().__init__(f"Set {getattr(node_item.backend_node, 'name', 'Node')}.{param_name}")
        self.editor = editor
        self.node_item = node_item
        self.param_name = param_name
        # store immutable copies to avoid mutation issues (e.g., tuples vs lists)
        self.old_value = self._clone_value(old_value)
        self.new_value = self._clone_value(new_value)

    @staticmethod
    def _clone_value(v):
        try:
            if isinstance(v, list):
                return tuple(v)
            return v
        except Exception:
            return v

    def undo(self):
        try:
            self.node_item.backend_node.set_params(**{self.param_name: self.old_value})
        except Exception:
            logger.exception("[Undo] SetNodeParamCommand failed")
        self.editor.update_previews_from(self.node_item)

    def redo(self):
        try:
            self.node_item.backend_node.set_params(**{self.param_name: self.new_value})
        except Exception:
            logger.exception("[Redo] SetNodeParamCommand failed")
        self.editor.update_previews_from(self.node_item)

    # Merge identical param changes for smoother slider drags
    def id(self) -> int:
        return 1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetNodeParamCommand):
            return False
        if self.node_item is not other.node_item:
            return False
        if self.param_name != other.param_name:
            return False
        # keep latest value and label (optional)
        self.new_value = other.new_value
        # Optional: keep label short & consistent
        self.setText(other.text())
        return True


class MoveNodeCommand(QUndoCommand):
    """
    Undoable move of a NodeItem on the scene.
    We only move the graphics item; backend graph topology stays intact.
    """
    def __init__(self, editor, node_item, old_pos: QPointF, new_pos: QPointF):
        super().__init__("Move Node")
        self.editor = editor
        self.node_item = node_item
        self.old = QPointF(old_pos)
        self.new = QPointF(new_pos)

    def undo(self):
        try:
            self.node_item.setPos(self.old)
        except Exception:
            logger.exception("[Undo] MoveNodeCommand failed")
        # optional: refresh edges
        try:
            sc = self.editor.scene
            if sc and hasattr(sc, 'update_edges_for_node'):
                sc.update_edges_for_node(self.node_item)
        except Exception:
            pass

    def redo(self):
        try:
            self.node_item.setPos(self.new)
        except Exception:
            logger.exception("[Redo] MoveNodeCommand failed")
        try:
            sc = self.editor.scene
            if sc and hasattr(sc, 'update_edges_for_node'):
                sc.update_edges_for_node(self.node_item)
        except Exception:
            pass
