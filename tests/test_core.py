# tests/test_core.py
"""
Tests for texture_pig.nodes.core: the array helpers, and the generation-based
caching that both Node and GenerationCacheMixin implement. This is the most
bug-sensitive part of the backend (cache invalidation bugs are invisible in
the UI until a stale texture ships), so it gets the most thorough coverage.
"""
import numpy as np
import pytest

from texture_pig.nodes.core import (
    Node, Graph, Constant, GenerationCacheMixin,
    clamp01, to_uint8, from_uint8, ensure_rgba, resample_to_size,
    mask_to_scalar, get_scalar_param, get_scalar_param_int,
    MAX_CACHE_ENTRIES_PER_SIZE,
)


# ---------------------------------------------------------------------------
# Array helpers
# ---------------------------------------------------------------------------

def test_clamp01_clips_out_of_range_values():
    x = np.array([-1.0, 0.0, 0.5, 1.0, 2.0], dtype=np.float32)
    out = clamp01(x)
    assert np.allclose(out, [0.0, 0.0, 0.5, 1.0, 1.0])


def test_to_uint8_from_uint8_round_trip():
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    u8 = to_uint8(x)
    assert u8.dtype == np.uint8
    back = from_uint8(u8)
    # Round trip through 8-bit quantization should stay within one step.
    assert np.allclose(back, x, atol=1.0 / 255.0 + 1e-6)


def test_to_uint8_clamps_before_converting():
    x = np.array([-1.0, 2.0], dtype=np.float32)
    u8 = to_uint8(x)
    assert list(u8) == [0, 255]


@pytest.mark.parametrize("shape", [(4, 4), (4, 4, 1), (4, 4, 3), (4, 4, 4)])
def test_ensure_rgba_produces_hw4_float32(shape):
    arr = np.random.rand(*shape).astype(np.float32)
    out = ensure_rgba(arr)
    assert out.shape == (4, 4, 4)
    assert out.dtype == np.float32


def test_ensure_rgba_grayscale_sets_opaque_alpha():
    arr = np.full((2, 2), 0.5, dtype=np.float32)
    out = ensure_rgba(arr)
    assert np.allclose(out[..., 3], 1.0)
    assert np.allclose(out[..., 0], 0.5)
    assert np.allclose(out[..., 1], 0.5)
    assert np.allclose(out[..., 2], 0.5)


def test_ensure_rgba_rgb_sets_opaque_alpha():
    arr = np.random.rand(3, 3, 3).astype(np.float32)
    out = ensure_rgba(arr)
    assert np.allclose(out[..., :3], arr)
    assert np.allclose(out[..., 3], 1.0)


def test_ensure_rgba_rejects_bad_channel_count():
    arr = np.random.rand(4, 4, 2).astype(np.float32)
    with pytest.raises(ValueError):
        ensure_rgba(arr)


def test_ensure_rgba_rejects_bad_ndim():
    arr = np.random.rand(4, 4, 4, 4).astype(np.float32)
    with pytest.raises(ValueError):
        ensure_rgba(arr)


def test_resample_to_size_passthrough_when_already_correct_size():
    arr = np.random.rand(8, 8, 4).astype(np.float32)
    out = resample_to_size(arr, 8)
    assert out.shape == (8, 8, 4)
    assert np.array_equal(out, arr)


def test_resample_to_size_resizes():
    arr = np.zeros((4, 4, 4), dtype=np.float32)
    arr[..., 3] = 1.0
    out = resample_to_size(arr, 16)
    assert out.shape == (16, 16, 4)
    assert out.dtype == np.float32
    # values must still be a valid, clamped [0,1] image
    assert out.min() >= 0.0 and out.max() <= 1.0


@pytest.mark.parametrize("channels,expected", [
    (1, 0.5),
    (4, 0.75),  # alpha channel picked
])
def test_mask_to_scalar_single_and_alpha_channel(channels, expected):
    arr = np.zeros((2, 2, channels), dtype=np.float32)
    if channels == 1:
        arr[..., 0] = expected
    else:
        arr[..., 3] = expected
    out = mask_to_scalar(arr)
    assert out.shape == (2, 2)
    assert np.allclose(out, expected)


def test_mask_to_scalar_rgb_uses_luma_weights():
    arr = np.zeros((1, 1, 3), dtype=np.float32)
    arr[0, 0] = [1.0, 0.0, 0.0]  # pure red
    out = mask_to_scalar(arr)
    assert np.isclose(out[0, 0], 0.2126, atol=1e-4)


def test_mask_to_scalar_rejects_bad_channel_count():
    arr = np.zeros((2, 2, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        mask_to_scalar(arr)


def test_mask_to_scalar_rejects_bad_ndim():
    with pytest.raises(ValueError):
        mask_to_scalar(np.zeros((2, 2, 2, 2), dtype=np.float32))


# ---------------------------------------------------------------------------
# get_scalar_param / get_scalar_param_int
# ---------------------------------------------------------------------------

class _FakeNodeWithParam:
    """Minimal stand-in with a plain attribute, no scalar input connected."""
    def __init__(self):
        self.inputs = {}
        self.amount = 0.75


def test_get_scalar_param_falls_back_to_attribute():
    n = _FakeNodeWithParam()
    assert get_scalar_param(n, "amount") == 0.75


def test_get_scalar_param_uses_default_when_missing():
    n = _FakeNodeWithParam()
    assert get_scalar_param(n, "does_not_exist", default=42) == 42


def test_get_scalar_param_prefers_connected_scalar_source():
    upstream = Constant(scalar_value=3.5)
    n = _FakeNodeWithParam()
    n.inputs["amount"] = (upstream, "out")
    assert get_scalar_param(n, "amount") == 3.5


def test_get_scalar_param_int_rounds():
    n = _FakeNodeWithParam()
    n.amount = 2.6
    assert get_scalar_param_int(n, "amount") == 3


# ---------------------------------------------------------------------------
# Node: generation-based caching & invalidation
# ---------------------------------------------------------------------------

class _CountingNode(Node):
    """A node that records how many times _compute actually ran, and paints
    the whole tile with `value` so tests can see when the output changes."""
    def __init__(self, value: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.compute_calls = 0

    def _compute(self, size: int) -> np.ndarray:
        self.compute_calls += 1
        img = np.zeros((size, size, 4), dtype=np.float32)
        img[..., 0] = self.value
        img[..., 3] = 1.0
        return img


def test_node_evaluate_is_cached_for_same_generation():
    n = _CountingNode(value=0.5)
    a = n.evaluate(8)
    b = n.evaluate(8)
    assert n.compute_calls == 1
    assert np.shares_memory(a, b)  # same cached array object


def test_node_evaluate_recomputes_after_set_params():
    n = _CountingNode(value=0.5)
    n.evaluate(8)
    n.set_params(value=0.9)
    out = n.evaluate(8)
    assert n.compute_calls == 2
    assert np.allclose(out[..., 0], 0.9)


def test_node_evaluate_recomputes_when_upstream_changes():
    src = _CountingNode(value=0.2)
    downstream = _CountingNode(value=0.0)
    downstream.connect("in0", src)

    downstream.evaluate(8)
    assert downstream.compute_calls == 1

    # Changing the upstream node must invalidate the downstream cache even
    # though downstream's own params didn't change.
    src.set_params(value=0.8)
    downstream.evaluate(8)
    assert downstream.compute_calls == 2


def test_node_evaluate_output_is_rgba_clamped_and_resized():
    class _OddSizeNode(Node):
        def _compute(self, size):
            # Deliberately return the wrong size / channel count / out-of-range
            # values to exercise evaluate()'s normalization pipeline.
            img = np.full((4, 4, 1), 5.0, dtype=np.float32)
            return img

    n = _OddSizeNode()
    out = n.evaluate(16)
    assert out.shape == (16, 16, 4)
    assert out.max() <= 1.0 and out.min() >= 0.0


def test_node_cache_lru_eviction_caps_entries_per_size():
    n = _CountingNode(value=0.0)
    # Force more distinct generations (at the same size) than the cache holds.
    for i in range(MAX_CACHE_ENTRIES_PER_SIZE + 3):
        n.set_params(value=float(i))
        n.evaluate(8)
    assert len(n._cache[8]) <= MAX_CACHE_ENTRIES_PER_SIZE


def test_node_clear_cache_drops_all_entries():
    n = _CountingNode(value=0.1)
    n.evaluate(8)
    assert n._cache
    n.clear_cache()
    assert n._cache == {}


def test_node_connect_registers_dependent():
    src = _CountingNode(value=0.1)
    dst = _CountingNode(value=0.2)
    dst.connect("in0", src)
    assert dst in src.dependents


# ---------------------------------------------------------------------------
# GenerationCacheMixin (used by standalone/non-Node classes)
# ---------------------------------------------------------------------------

class _MixinNode(GenerationCacheMixin):
    """Minimal class exercising the mixin the way real filter classes do."""
    def __init__(self, value: float = 0.0):
        self.inputs = {}
        self.dependents = set()
        self.value = value
        self.compute_calls = 0
        self._init_generation_cache()

    def invalidate(self):
        self._bump_generation()

    def evaluate(self, size: int) -> np.ndarray:
        cached = self._check_cache(size)
        if cached is not None:
            return cached
        self.compute_calls += 1
        img = np.full((size, size, 4), self.value, dtype=np.float32)
        self._store_cache(size, img)
        return img


def test_mixin_caches_until_invalidated():
    n = _MixinNode(value=0.3)
    n.evaluate(8)
    n.evaluate(8)
    assert n.compute_calls == 1

    n.value = 0.9
    n.invalidate()
    n.evaluate(8)
    assert n.compute_calls == 2


def test_mixin_lru_eviction_caps_entries_per_size():
    n = _MixinNode()
    for i in range(MAX_CACHE_ENTRIES_PER_SIZE + 3):
        n.value = float(i)
        n.invalidate()
        n.evaluate(8)
    assert len(n._gen_cache[8]) <= MAX_CACHE_ENTRIES_PER_SIZE


# ---------------------------------------------------------------------------
# Constant node
# ---------------------------------------------------------------------------

def test_constant_fills_tile_with_color():
    c = Constant(color=(0.1, 0.2, 0.3, 0.4))
    out = c.evaluate(4)
    assert out.shape == (4, 4, 4)
    assert np.allclose(out[0, 0], [0.1, 0.2, 0.3, 0.4])


def test_constant_get_scalar_value():
    c = Constant(scalar_value=7.0)
    assert c.get_scalar_value() == 7.0


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def test_graph_output_evaluates_node_at_graph_size():
    g = Graph(size=8)
    n = g.add(Constant(color=(1, 0, 0, 1)))
    out = g.output(n)
    assert out.shape == (8, 8, 4)


def test_graph_output_size_override():
    g = Graph(size=8)
    n = g.add(Constant(color=(1, 0, 0, 1)))
    out = g.output(n, size=16)
    assert out.shape == (16, 16, 4)


def test_graph_export_png_writes_valid_file(tmp_path):
    from PIL import Image
    g = Graph(size=4)
    n = g.add(Constant(color=(1.0, 0.0, 0.0, 1.0)))
    out_path = tmp_path / "out.png"
    g.export_png(n, str(out_path))
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (4, 4)
    assert img.mode == "RGBA"
