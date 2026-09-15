# tests/test_scalar.py
"""Tests for texture_pig.nodes.scalar: the scalar math node library."""
import numpy as np
import pytest

from texture_pig.nodes.scalar import (
    Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp,
)


def test_float_clamps_to_range():
    f = Float(value=5.0, min_value=0.0, max_value=1.0)
    assert f.get_scalar_value() == 1.0

    f = Float(value=-5.0, min_value=0.0, max_value=1.0)
    assert f.get_scalar_value() == 0.0


def test_float_get_int_value_rounds():
    f = Float(value=0.6, min_value=0.0, max_value=1.0)
    assert f.get_int_value() == 1


def test_int_clamps_and_returns_int():
    i = Int(value=150, min_value=0, max_value=100)
    assert i.get_int_value() == 100
    assert isinstance(i.get_int_value(), int)


def test_scalar_add():
    n = ScalarAdd(a=2.0, b=3.5)
    assert n.get_scalar_value() == 5.5


def test_scalar_sub():
    n = ScalarSub(a=5.0, b=3.0)
    assert n.get_scalar_value() == 2.0


def test_scalar_mul():
    n = ScalarMul(a=2.0, b=3.0)
    assert n.get_scalar_value() == 6.0


def test_scalar_div():
    n = ScalarDiv(a=6.0, b=3.0)
    assert n.get_scalar_value() == 2.0


def test_scalar_div_by_zero_returns_zero_instead_of_raising():
    n = ScalarDiv(a=6.0, b=0.0)
    assert n.get_scalar_value() == 0.0


def test_scalar_clamp():
    n = ScalarClamp(value=5.0, min_val=0.0, max_val=1.0)
    assert n.get_scalar_value() == 1.0
    n = ScalarClamp(value=-5.0, min_val=0.0, max_val=1.0)
    assert n.get_scalar_value() == 0.0
    n = ScalarClamp(value=0.5, min_val=0.0, max_val=1.0)
    assert n.get_scalar_value() == 0.5


def test_scalar_math_nodes_read_connected_input_over_literal_value():
    """
    ScalarAdd/Sub/Mul/Div/Clamp all resolve their operands via
    get_scalar_param(), which prefers a connected scalar node's value over
    the node's own literal attribute. Verify that wiring actually overrides.
    """
    source = Float(value=10.0, min_value=0.0, max_value=100.0)
    add = ScalarAdd(a=1.0, b=1.0)
    add.connect('a', source)
    assert add.get_scalar_value() == 11.0  # 10 (from source) + 1 (literal b)


def test_scalar_node_renders_grayscale_preview():
    n = Float(value=0.5, min_value=0.0, max_value=1.0)
    img = n.evaluate(4)
    assert img.shape == (4, 4, 4)
    assert np.allclose(img[..., 0], 0.5)
    assert np.allclose(img[..., 1], 0.5)
    assert np.allclose(img[..., 2], 0.5)
    assert np.allclose(img[..., 3], 1.0)


def test_scalar_node_preview_clamps_out_of_range_value_for_display():
    # Float(value=5, max=10) -> scalar value 5 (valid), but ScalarAdd summing
    # past 1.0 should still clamp the *preview* pixels to [0,1] even though
    # get_scalar_value() itself may exceed that range.
    n = ScalarAdd(a=0.9, b=0.9)
    assert n.get_scalar_value() == pytest.approx(1.8)
    img = n.evaluate(2)
    assert img.max() <= 1.0
