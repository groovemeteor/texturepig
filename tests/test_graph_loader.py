# tests/test_graph_loader.py
"""
Tests for GraphLoadWorker (ui/utils/loader.py) -- the JSON graph-file parser
that streams nodes/edges via Qt signals during Load Graph. Covers the happy
path plus the two failure modes (missing file, cancel mid-stream).
"""
import json

from texture_pig.ui.utils.loader import GraphLoadWorker


def _write_graph(tmp_path, nodes=None, edges=None, **meta):
    data = {
        "version": meta.get("version", 1),
        "graph_size": meta.get("graph_size", 512),
        "preview_size": meta.get("preview_size", 256),
        "ui_scale": meta.get("ui_scale", 1.0),
        "nodes": nodes or [],
        "edges": edges or [],
    }
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_loader_streams_nodes_and_edges_in_order(qcore_app, tmp_path):
    nodes = [{"class": "Constant", "name": "A"}, {"class": "Constant", "name": "B"}]
    edges = [{"src": "A", "dst": "B", "dst_port": "in0"}]
    path = _write_graph(tmp_path, nodes=nodes, edges=edges, graph_size=256)

    seen_nodes, seen_edges, done_calls, meta_calls = [], [], [], []
    w = GraphLoadWorker(path, {})
    w.meta_ready.connect(lambda gs, ps, sc, v: meta_calls.append((gs, ps, sc, v)))
    w.node_ready.connect(seen_nodes.append)
    w.edge_ready.connect(seen_edges.append)
    w.done.connect(lambda ok, msg: done_calls.append((ok, msg)))

    w.run()

    assert meta_calls == [(256, 256, 1.0, 1)]
    assert seen_nodes == nodes
    assert seen_edges == edges
    assert done_calls == [(True, "")]


def test_loader_reports_failure_for_missing_file(qcore_app, tmp_path):
    missing_path = str(tmp_path / "does_not_exist.json")
    done_calls = []
    w = GraphLoadWorker(missing_path, {})
    w.done.connect(lambda ok, msg: done_calls.append((ok, msg)))

    w.run()

    assert len(done_calls) == 1
    ok, msg = done_calls[0]
    assert ok is False
    assert msg  # non-empty error message


def test_loader_cancel_stops_streaming_early(qcore_app, tmp_path):
    nodes = [{"class": "Constant", "name": f"N{i}"} for i in range(5)]
    path = _write_graph(tmp_path, nodes=nodes)

    seen_nodes, done_calls = [], []
    w = GraphLoadWorker(path, {})

    def _on_node(ne):
        seen_nodes.append(ne)
        if len(seen_nodes) == 2:
            w.cancel()

    w.node_ready.connect(_on_node)
    w.done.connect(lambda ok, msg: done_calls.append((ok, msg)))

    w.run()

    assert len(seen_nodes) == 2
    assert done_calls == [(False, "Canceled")]
