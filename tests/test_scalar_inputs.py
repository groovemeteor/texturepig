# tests/test_scalar_inputs.py
"""
Tests for wiring a scalar node into another node's parameter.

Regression cover for the bug where connecting a scalar node to RadialGrid's
'count' did nothing: the multi-input layout nodes only accepted connections
whose name was already in self.inputs (i.e. the in0..inN image slots), so the
scalar wire was silently dropped, and _rebuild_inputs() then wiped any that
did get in.
"""
import numpy as np
import pytest

from texture_pig.nodes.core import get_scalar_param, get_scalar_param_int
from texture_pig.nodes.layout import Grid, RadialGrid, Atlas
from texture_pig.nodes.scalar import Float, Int
from texture_pig.nodes.shapes import Circle
from texture_pig.nodes.filters import Transform, GaussianBlur
from texture_pig.nodes.generators import PerlinNoise


# ---------------------------------------------------------------------------
# The reported bug: scalar -> RadialGrid.count
# ---------------------------------------------------------------------------

def test_radialgrid_count_accepts_scalar_connection():
    rg = RadialGrid(count=8)
    rg.connect('in0', Circle())
    rg.connect('count', Int(value=3, min_value=1, max_value=64))

    assert rg.inputs.get('count') is not None, "scalar wire was dropped"
    assert get_scalar_param_int(rg, 'count', rg.count) == 3


def test_radialgrid_count_scalar_survives_rebuild():
    """Changing num_inputs/count rebuilds the image slots; the scalar wire must stay."""
    rg = RadialGrid(count=8)
    rg.connect('in0', Circle())
    rg.connect('count', Int(value=5, min_value=1, max_value=64))

    rg.set_params(num_inputs=2)

    assert rg.inputs.get('count') is not None
    assert get_scalar_param_int(rg, 'count', rg.count) == 5


def test_radialgrid_scalar_count_changes_render():
    """The wired value must actually reach the render, not just the inputs dict."""
    src = Circle(radius=0.3)

    few = RadialGrid(count=8, radius=0.35, tile_edge_frac=0.2)
    few.connect('in0', src)
    few.connect('count', Int(value=2, min_value=1, max_value=64))

    many = RadialGrid(count=8, radius=0.35, tile_edge_frac=0.2)
    many.connect('in0', Circle(radius=0.3))
    many.connect('count', Int(value=12, min_value=1, max_value=64))

    a = few.evaluate(96)
    b = many.evaluate(96)
    # More instances around the ring => more coverage
    assert b[..., 3].sum() > a[..., 3].sum()


def test_radialgrid_recomputes_when_scalar_value_changes():
    """Bumping the upstream scalar must invalidate the cached render."""
    rg = RadialGrid(count=8, radius=0.35, tile_edge_frac=0.2)
    rg.connect('in0', Circle(radius=0.3))
    driver = Int(value=2, min_value=1, max_value=64)
    rg.connect('count', driver)

    first = rg.evaluate(96).copy()
    driver.set_params(value=12)
    second = rg.evaluate(96)

    assert not np.array_equal(first, second), "stale cache: upstream change not detected"


def test_image_slots_still_reject_unknown_names():
    """A phantom in<N> slot beyond the current count must not be created."""
    rg = RadialGrid(count=2, num_inputs=1)
    rg.connect('in7', Circle())
    assert 'in7' not in rg.inputs


def test_legacy_src_still_maps_to_in0():
    rg = RadialGrid(count=4)
    c = Circle()
    rg.connect('src', c)
    assert rg.inputs.get('in0') is not None


@pytest.mark.parametrize("node,param,driver", [
    (Grid(nx=2, ny=2), 'nx', Int(value=4, min_value=1, max_value=16)),
    (Grid(nx=2, ny=2), 'ny', Int(value=3, min_value=1, max_value=16)),
    (RadialGrid(count=4), 'count', Int(value=7, min_value=1, max_value=64)),
    (Atlas(cells=4), 'cells', Int(value=9, min_value=4, max_value=64)),
])
def test_layout_nodes_store_scalar_param_connections(node, param, driver):
    node.connect(param, driver)
    assert node.inputs.get(param) is not None


# ---------------------------------------------------------------------------
# Params wired up alongside the fix
# ---------------------------------------------------------------------------

def test_radialgrid_radius_honors_scalar():
    rg = RadialGrid(count=6, radius=0.1, tile_edge_frac=0.15)
    rg.connect('in0', Circle(radius=0.4))
    rg.connect('radius', Float(value=0.45, min_value=0.0, max_value=1.0))
    assert get_scalar_param(rg, 'radius', rg.radius) == pytest.approx(0.45)


def test_transform_honors_scalar_translation():
    src = Circle(cx=0.5, cy=0.5, radius=0.2)
    t = Transform()
    t.connect('src', src)
    t.connect('tx', Float(value=0.25, min_value=-1.0, max_value=1.0))

    moved = t.evaluate(96)
    plain = Circle(cx=0.5, cy=0.5, radius=0.2).evaluate(96)
    assert not np.array_equal(moved, plain), "tx scalar had no effect"


def test_gaussianblur_honors_scalar_sigma():
    src = Circle(cx=0.5, cy=0.5, radius=0.25, edge_softness=0.0)
    b = GaussianBlur(sigma=0.0)
    b.connect('src', src)
    b.connect('sigma', Float(value=6.0, min_value=0.0, max_value=32.0))

    blurred = b.evaluate(96)
    sharp = src.evaluate(96)
    assert not np.array_equal(blurred, sharp), "sigma scalar had no effect"


def test_perlin_honors_scalar_seed():
    a = PerlinNoise(seed=1)
    b = PerlinNoise(seed=1)
    b.connect('seed', Int(value=99, min_value=0, max_value=9999))
    assert not np.array_equal(a.evaluate(64), b.evaluate(64)), "seed scalar had no effect"


def test_scalar_param_falls_back_when_nothing_connected():
    rg = RadialGrid(count=11)
    assert get_scalar_param_int(rg, 'count', rg.count) == 11
