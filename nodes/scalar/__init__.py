from __future__ import annotations
import numpy as np
from typing import Protocol, runtime_checkable
from texture_pig.nodes.core import Node, get_scalar_param


@runtime_checkable
class ScalarNodeProtocol(Protocol):
    """
    Protocol defining the interface for scalar nodes.

    Scalar nodes output a single numeric value (float or int) that can be used
    to control parameters on other nodes. They also render as grayscale preview images.

    Required Methods:
        get_scalar_value() -> float: Return the computed scalar value as float
        get_int_value() -> int: Return the computed scalar value as integer

    Example:
        def use_scalar(node: ScalarNodeProtocol) -> float:
            return node.get_scalar_value()

        def use_int(node: ScalarNodeProtocol) -> int:
            return node.get_int_value()
    """

    def get_scalar_value(self) -> float:
        """
        Compute and return the scalar output value as a float.

        Returns:
            float: The computed scalar value (may be outside [0, 1] range)
        """
        ...

    def get_int_value(self) -> int:
        """
        Compute and return the scalar output value as an integer.

        Returns:
            int: The computed scalar value rounded to nearest integer
        """
        ...


class ScalarNode(Node):
    """
    Base class for scalar nodes that output a single numeric value.

    Subclasses must implement get_scalar_value() to compute their output.
    The get_int_value() method is provided by default (rounds the float value).
    The _compute() method is provided automatically and renders a grayscale
    preview image based on the scalar value (clamped to [0, 1]).

    Example:
        class MyScalar(ScalarNode):
            def __init__(self, value: float = 0.0, **kwargs):
                super().__init__(**kwargs)
                self.value = value

            def get_scalar_value(self) -> float:
                return self.value * 2.0
    """

    def get_scalar_value(self) -> float:
        """Override this to compute the scalar output value as float."""
        raise NotImplementedError

    def get_int_value(self) -> int:
        """Return the scalar value as an integer (rounded)."""
        return int(round(self.get_scalar_value()))

    def _compute(self, size: int) -> np.ndarray:
        v = np.clip(self.get_scalar_value(), 0.0, 1.0)
        return np.full((size, size, 4), [v, v, v, 1.0], dtype=np.float32)


class Float(ScalarNode):
    """
    A node that outputs a scalar float value.
    Used to control parameters across multiple nodes.
    """
    def __init__(self, value: float = 0.5, min_value: float = 0.0, max_value: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.value = float(value)
        self.min_value = float(min_value)
        self.max_value = float(max_value)

    def get_scalar_value(self) -> float:
        """Return the scalar value, clamped to min/max range."""
        return float(np.clip(self.value, self.min_value, self.max_value))


class Int(ScalarNode):
    """
    A node that outputs an integer value.
    Used to control integer parameters across multiple nodes.
    """
    def __init__(self, value: int = 0, min_value: int = 0, max_value: int = 100, **kwargs):
        super().__init__(**kwargs)
        self.value = int(value)
        self.min_value = int(min_value)
        self.max_value = int(max_value)

    def get_scalar_value(self) -> float:
        """Return the integer value as float, clamped to min/max range."""
        return float(np.clip(self.value, self.min_value, self.max_value))

    def get_int_value(self) -> int:
        """Return the integer value, clamped to min/max range."""
        return int(np.clip(self.value, self.min_value, self.max_value))


class ScalarAdd(ScalarNode):
    """Adds two scalar values: out = a + b"""
    def __init__(self, a: float = 0.0, b: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.a = float(a)
        self.b = float(b)

    def get_scalar_value(self) -> float:
        a = get_scalar_param(self, 'a', self.a)
        b = get_scalar_param(self, 'b', self.b)
        return float(a + b)


class ScalarSub(ScalarNode):
    """Subtracts two scalar values: out = a - b"""
    def __init__(self, a: float = 0.0, b: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.a = float(a)
        self.b = float(b)

    def get_scalar_value(self) -> float:
        a = get_scalar_param(self, 'a', self.a)
        b = get_scalar_param(self, 'b', self.b)
        return float(a - b)


class ScalarMul(ScalarNode):
    """Multiplies two scalar values: out = a * b"""
    def __init__(self, a: float = 1.0, b: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.a = float(a)
        self.b = float(b)

    def get_scalar_value(self) -> float:
        a = get_scalar_param(self, 'a', self.a)
        b = get_scalar_param(self, 'b', self.b)
        return float(a * b)


class ScalarDiv(ScalarNode):
    """Divides two scalar values: out = a / b"""
    def __init__(self, a: float = 1.0, b: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.a = float(a)
        self.b = float(b)

    def get_scalar_value(self) -> float:
        a = get_scalar_param(self, 'a', self.a)
        b = get_scalar_param(self, 'b', self.b)
        if b == 0:
            return 0.0
        return float(a / b)


class ScalarClamp(ScalarNode):
    """Clamps a scalar value between min and max: out = clamp(value, min, max)"""
    def __init__(self, value: float = 0.5, min_val: float = 0.0, max_val: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.value = float(value)
        self.min_val = float(min_val)
        self.max_val = float(max_val)

    def get_scalar_value(self) -> float:
        value = get_scalar_param(self, 'value', self.value)
        min_val = get_scalar_param(self, 'min_val', self.min_val)
        max_val = get_scalar_param(self, 'max_val', self.max_val)
        return float(np.clip(value, min_val, max_val))


__all__ = [
    # Protocol and base class
    'ScalarNodeProtocol',
    'ScalarNode',
    # Concrete nodes
    'Float',
    'Int',
    'ScalarAdd',
    'ScalarSub',
    'ScalarMul',
    'ScalarDiv',
    'ScalarClamp',
]
