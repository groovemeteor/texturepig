# pynodes/core.py
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw
from typing import Dict, Optional, Tuple

def clamp01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)

def to_uint8(arr: np.ndarray) -> np.ndarray:
    arr = clamp01(arr)
    return (arr * 255.0 + 0.5).astype(np.uint8)

def from_uint8(arr: np.ndarray) -> np.ndarray:
    return (arr.astype(np.float32) / 255.0)

def ensure_rgba(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr, np.ones_like(arr)], axis=-1)
    elif arr.ndim == 3:
        h, w, c = arr.shape
        if c == 1:
            a = np.ones((h, w), dtype=arr.dtype)
            arr = np.concatenate([arr, arr, arr, a[..., None]], axis=-1)
        elif c == 3:
            a = np.ones((h, w), dtype=arr.dtype)
            arr = np.concatenate([arr, a[..., None]], axis=-1)
        elif c != 4:
            raise ValueError(f"Unsupported channel count: {c}")
    else:
        raise ValueError("Unsupported array shape")
    return arr.astype(np.float32)

def resample_to_size(arr: np.ndarray, size: int) -> np.ndarray:
    h, w = arr.shape[:2]
    if h == size and w == size:
        return arr
    img = Image.fromarray(to_uint8(arr), mode="RGBA")
    img = img.resize((size, size), resample=Image.BILINEAR)
    out = np.asarray(img).astype(np.float32) / 255.0
    return out

def mask_to_scalar(mask_arr: np.ndarray) -> np.ndarray:
    if mask_arr.ndim == 2:
        m = mask_arr
    elif mask_arr.ndim == 3:
        c = mask_arr.shape[-1]
        if c == 1:
            m = mask_arr[..., 0]
        elif c == 4:
            m = mask_arr[..., 3]
        elif c == 3:
            r, g, b = mask_arr[..., 0], mask_arr[..., 1], mask_arr[..., 2]
            m = 0.2126 * r + 0.7152 * g + 0.0722 * b
        else:
            raise ValueError("Unsupported mask channels")
    else:
        raise ValueError("Unsupported mask shape")
    return clamp01(m.astype(np.float32))

class Node:
    def __init__(self, name: Optional[str] = None, seed: Optional[int] = None, opacity: float = 1.0):
        self.name = name or self.__class__.__name__
        self.seed = seed
        self.opacity = float(opacity)
        self.inputs: Dict[str, Node] = {}
        self.dependents: set[Node] = set()
        self._cache: Dict[int, np.ndarray] = {}
        self._dirty: bool = True

    def connect(self, input_name: str, node: "Node") -> "Node":
        self.inputs[input_name] = node
        node.dependents.add(self)
        self.invalidate()
        return self

    def set_params(self, **kwargs) -> "Node":
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()
        return self

    def invalidate(self):
        self._cache.clear()
        self._dirty = True
        for dep in list(self.dependents):
            dep.invalidate_cascade()

    def invalidate_cascade(self):
        self._cache.clear()
        self._dirty = True
        for dep in list(self.dependents):
            dep.invalidate_cascade()

    def _rng(self) -> np.random.Generator:
        seed = self.seed if self.seed is not None else 0
        return np.random.default_rng(seed)

    def input_arr(self, key: str, size: int) -> Optional[np.ndarray]:
        """Helper to evaluate an input node and return its array."""
        node = self.inputs.get(key)
        if node is None:
            return None
        return node.evaluate(size)

    def evaluate(self, size: int) -> np.ndarray:
        size = int(size)
        if size not in self._cache:
            img = self._compute(size)
            img = ensure_rgba(img)
            if img.shape[0] != size or img.shape[1] != size:
                img = resample_to_size(img, size)
            img = clamp01(img.astype(np.float32))
            self._cache[size] = img
            self._dirty = False
        return self._cache[size]

    def _compute(self, size: int) -> np.ndarray:
        raise NotImplementedError

class Graph:
    def __init__(self, size: int = 512):
        self.size = int(size)
        self.nodes: list[Node] = []

    def add(self, node: Node) -> Node:
        self.nodes.append(node)
        return node

    def output(self, node: Node, size: Optional[int] = None) -> np.ndarray:
        return node.evaluate(size or self.size)

    def export_png(self, node: Node, path: str, size: Optional[int] = None):
        arr = self.output(node, size)
        img = Image.fromarray(to_uint8(arr), mode="RGBA")
        img.save(path, format="PNG")

class Constant(Node):
    def __init__(self, color: Tuple[float, float, float, float] = (0, 0, 0, 0), **kwargs):
        super().__init__(**kwargs)
        self.color = tuple(float(c) for c in color)

    def evaluate(self, size: int) -> np.ndarray:
        # Fast path: skip ensure_rgba/resample/clamp01 since we produce valid RGBA directly
        size = int(size)
        if size not in self._cache:
            img = np.empty((size, size, 4), dtype=np.float32)
            img[:] = self.color
            self._cache[size] = img
            self._dirty = False
        return self._cache[size]

    def _compute(self, size: int) -> np.ndarray:
        # Fallback (not used since we override evaluate)
        img = np.empty((size, size, 4), dtype=np.float32)
        img[:] = self.color
        return img
