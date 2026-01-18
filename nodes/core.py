from __future__ import annotations
import numpy as np
import cv2
from PIL import Image, ImageDraw
from typing import Dict, Optional, Tuple, Set, Protocol, runtime_checkable, TYPE_CHECKING
from collections import OrderedDict

# Maximum cache entries per node per size (LRU eviction)
MAX_CACHE_ENTRIES_PER_SIZE = 4


@runtime_checkable
class TextureNode(Protocol):
    """
    Protocol defining the interface that all texture nodes must implement.

    This enables static type checking and documents the expected contract
    for node implementations. Use this for type hints when accepting any node.

    Required Attributes:
        name: Display name for the node
        inputs: Dict mapping input names to (node, output_port) tuples
        dependents: Set of downstream nodes that depend on this node

    Required Methods:
        evaluate(size) -> np.ndarray: Render the node at given resolution
        connect(input_name, node, output_port) -> Self: Connect upstream node
        set_params(**kwargs) -> Self: Update parameters
        invalidate() -> None: Mark cache as stale

    Optional Methods:
        evaluate_port(port_name, size) -> np.ndarray: For multi-output nodes

    Example:
        def process_node(node: TextureNode, size: int) -> np.ndarray:
            return node.evaluate(size)
    """

    # Required attributes
    name: str
    inputs: Dict[str, tuple]  # {input_name: (node, output_port)}
    dependents: Set['TextureNode']

    def evaluate(self, size: int) -> np.ndarray:
        """
        Evaluate and return the node's output at the given resolution.

        Args:
            size: Output resolution (size x size pixels)

        Returns:
            np.ndarray: RGBA float32 array of shape (size, size, 4) with values in [0, 1]
        """
        ...

    def connect(self, input_name: str, node: 'TextureNode',
                output_port: str = 'out') -> 'TextureNode':
        """
        Connect an upstream node to this node's input.

        Args:
            input_name: Name of the input slot to connect
            node: Upstream node to connect
            output_port: Which output port of the upstream node to use

        Returns:
            Self for method chaining
        """
        ...

    def set_params(self, **kwargs) -> 'TextureNode':
        """
        Update node parameters and invalidate cache.

        Args:
            **kwargs: Parameter name-value pairs to update

        Returns:
            Self for method chaining
        """
        ...

    def invalidate(self) -> None:
        """
        Mark this node's cache as stale.

        Called automatically when parameters change or connections are modified.
        Implementations should increment their generation counter.
        """
        ...

    def evaluate_port(self, port_name: str, size: int) -> np.ndarray:
        """
        Evaluate a specific output port (for multi-output nodes).

        Default implementation returns evaluate(size) for all ports.
        Override for nodes with multiple distinct outputs (e.g., Split).

        Args:
            port_name: Name of the output port to evaluate
            size: Output resolution

        Returns:
            np.ndarray: RGBA float32 array of shape (size, size, 4)
        """
        ...


class GenerationCacheMixin:
    """
    Mixin providing generation-based caching for standalone node classes.

    Classes using this mixin should:
    1. Call _init_generation_cache() in __init__
    2. Call _check_cache(size) before computing, returns cached result or None
    3. Call _store_cache(size, result) after computing
    4. Call _bump_generation() in invalidate()
    """

    def _init_generation_cache(self):
        """Initialize generation cache state. Call in __init__."""
        self._generation: int = 0
        self._gen_cache: Dict[int, OrderedDict] = {}  # {size: OrderedDict{gen_hash: result}}

    def _bump_generation(self):
        """Increment generation counter. Call when params change."""
        if not hasattr(self, '_generation'):
            self._generation = 0
        self._generation += 1

    def _upstream_generation_hash(self) -> tuple:
        """Compute hash of upstream node generations (recursive). Returns tuple for reliable hashing."""
        result = []
        inputs = getattr(self, 'inputs', None)
        if not inputs or not isinstance(inputs, dict):
            return ()
        for key in sorted(inputs.keys()):  # Sort for deterministic order
            conn = inputs.get(key)
            if conn is None:
                continue
            if isinstance(conn, tuple) and len(conn) >= 2:
                node, port = conn[0], conn[1]
            else:
                node = conn
                port = 'out'
            if node is not None:
                # Use full generation hash (recursive) to detect deep upstream changes
                try:
                    if hasattr(node, '_get_generation_hash'):
                        node_hash = node._get_generation_hash()
                    else:
                        node_hash = getattr(node, '_generation', 0)
                    result.append((key, id(node), node_hash, port))
                except Exception:
                    # If anything fails, include node id to at least track identity
                    result.append((key, id(node), 0, port))
        return tuple(result)

    def _get_generation_hash(self) -> tuple:
        """Get full generation hash (self + upstream)."""
        if not hasattr(self, '_generation'):
            self._generation = 0
        return (self._generation, self._upstream_generation_hash())

    def _check_cache(self, size: int) -> Optional[np.ndarray]:
        """
        Check if valid cached result exists for current generation.
        Returns cached array or None if cache miss.
        """
        # Defensive: ensure cache structures exist
        if not hasattr(self, '_gen_cache'):
            self._gen_cache = {}
        if not hasattr(self, '_generation'):
            self._generation = 0

        gen_hash = self._get_generation_hash()
        if size not in self._gen_cache:
            return None
        size_cache = self._gen_cache[size]
        if gen_hash in size_cache:
            size_cache.move_to_end(gen_hash)
            return size_cache[gen_hash]
        return None

    def _store_cache(self, size: int, result: np.ndarray):
        """Store result in generation cache with LRU eviction."""
        # Defensive: ensure cache structures exist
        if not hasattr(self, '_gen_cache'):
            self._gen_cache = {}
        if not hasattr(self, '_generation'):
            self._generation = 0

        gen_hash = self._get_generation_hash()
        if size not in self._gen_cache:
            self._gen_cache[size] = OrderedDict()
        size_cache = self._gen_cache[size]
        size_cache[gen_hash] = result
        # LRU eviction
        while len(size_cache) > MAX_CACHE_ENTRIES_PER_SIZE:
            size_cache.popitem(last=False)

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
    # Use cv2.resize for speed (works directly on float32 arrays)
    out = cv2.resize(arr, (size, size), interpolation=cv2.INTER_LINEAR)
    return np.clip(out, 0.0, 1.0).astype(np.float32)

def get_scalar_param(node, param_name: str, default=None):
    """
    Get a parameter value, checking if it's connected to a scalar input first.
    Works with any node that has an 'inputs' dict.

    Args:
        node: The node object (must have 'inputs' dict attribute)
        param_name: Name of the parameter to get
        default: Default value if parameter doesn't exist

    Returns:
        The scalar value from connected node, or the internal parameter value
    """
    inputs = getattr(node, 'inputs', {})
    connection = inputs.get(param_name)
    if connection is not None:
        # Handle tuple format (node, output_port)
        if isinstance(connection, tuple):
            upstream_node, output_port = connection
        else:
            upstream_node = connection
        # Check if the connected node can provide a scalar value
        if hasattr(upstream_node, 'get_scalar_value') and callable(upstream_node.get_scalar_value):
            return upstream_node.get_scalar_value()
    # Fall back to internal parameter
    return getattr(node, param_name, default)


def get_scalar_param_int(node, param_name: str, default=0):
    """
    Get an integer parameter value, rounding if connected to a scalar input.
    Works with any node that has an 'inputs' dict.

    Args:
        node: The node object (must have 'inputs' dict attribute)
        param_name: Name of the parameter to get
        default: Default value if parameter doesn't exist

    Returns:
        The rounded integer value from connected node, or the internal parameter value
    """
    value = get_scalar_param(node, param_name, default)
    return int(round(value))


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
    """
    Base class for all texture nodes with generation-based caching.

    Implements the TextureNode protocol. Subclasses should override _compute(size)
    to provide their rendering logic.

    Cache invalidation uses generation counters instead of clearing caches:
    - Each node has a _generation counter that increments when params change
    - Cache entries store (generation_hash, result) tuples
    - generation_hash = hash of (self._generation, upstream_generations)
    - Cache hit only if generation_hash matches (upstream unchanged)

    Example:
        class MyGenerator(Node):
            def __init__(self, my_param: float = 1.0, **kwargs):
                super().__init__(**kwargs)
                self.my_param = my_param

            def _compute(self, size: int) -> np.ndarray:
                # Return (size, size, 4) RGBA float32 array
                return np.zeros((size, size, 4), dtype=np.float32)
    """

    def __init__(self, name: Optional[str] = None, seed: Optional[int] = None, opacity: float = 1.0):
        self.name: str = name or self.__class__.__name__
        self.seed = seed
        self.opacity = float(opacity)
        self.inputs: Dict[str, tuple] = {}  # {input_name: (node, output_port)}
        self.dependents: Set[TextureNode] = set()
        # Generation-based cache: {size: OrderedDict{gen_hash: result}}
        self._cache: Dict[int, OrderedDict] = {}
        self._generation: int = 0  # Increments when this node's params change
        self._dirty: bool = True

    def connect(self, input_name: str, node: TextureNode, output_port: str = 'out') -> 'Node':
        """Connect an input to another node's output port."""
        # Store as tuple (node, output_port) to support multi-output nodes
        self.inputs[input_name] = (node, output_port)
        if hasattr(node, 'dependents'):
            node.dependents.add(self)
        self.invalidate()
        return self

    def set_params(self, **kwargs) -> "Node":
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()
        return self

    def invalidate(self):
        """
        Mark this node as changed by incrementing generation.
        Does NOT clear cache - let lazy evaluation handle staleness.
        Does NOT propagate - downstream nodes will detect via generation hash.
        """
        self._generation += 1
        self._dirty = True

    def invalidate_cascade(self):
        """
        Called when an upstream node changes.
        With generation-based caching, we don't need to do anything here -
        the evaluate() method will detect stale cache via generation hash.
        Kept for compatibility with standalone filter classes.
        """
        self._dirty = True

    def _upstream_generation_hash(self) -> tuple:
        """
        Compute a hash representing the current state of all upstream nodes.
        Uses recursive generation hash to detect deep upstream changes.
        Returns tuple for reliable hashing without collisions.
        """
        result = []
        if not hasattr(self, 'inputs') or not isinstance(self.inputs, dict):
            return ()
        for key in sorted(self.inputs.keys()):  # Sort for deterministic order
            conn = self.inputs.get(key)
            if conn is None:
                continue
            if isinstance(conn, tuple) and len(conn) >= 2:
                node, port = conn[0], conn[1]
            else:
                node = conn
                port = 'out'

            if node is not None:
                # Use full generation hash (recursive) to detect deep upstream changes
                try:
                    if hasattr(node, '_get_generation_hash'):
                        node_hash = node._get_generation_hash()
                    else:
                        node_hash = getattr(node, '_generation', 0)
                    result.append((key, id(node), node_hash, port))
                except Exception:
                    result.append((key, id(node), 0, port))
        return tuple(result)

    def _get_generation_hash(self) -> tuple:
        """Get the full generation hash (self + upstream)."""
        if not hasattr(self, '_generation'):
            self._generation = 0
        return (self._generation, self._upstream_generation_hash())

    def _rng(self) -> np.random.Generator:
        seed = self.seed if self.seed is not None else 0
        return np.random.default_rng(seed)

    def input_arr(self, key: str, size: int) -> Optional[np.ndarray]:
        """Helper to evaluate an input node and return its array."""
        connection = self.inputs.get(key)
        if connection is None:
            return None
        # Handle both old format (node) and new format (node, output_port)
        if isinstance(connection, tuple):
            node, output_port = connection
            if hasattr(node, 'evaluate_port') and callable(node.evaluate_port):
                return node.evaluate_port(output_port, size)
            else:
                return node.evaluate(size)
        else:
            # Legacy: direct node reference
            return connection.evaluate(size)

    def get_param(self, param_name: str, default=None):
        """
        Get a parameter value, checking if it's connected to a scalar input first.
        If connected to a scalar node, returns the scalar value from that node.
        Otherwise returns the internal parameter value.
        """
        # Check if this parameter has a scalar input connected
        connection = self.inputs.get(param_name)
        if connection is not None:
            # Handle tuple format (node, output_port)
            if isinstance(connection, tuple):
                node, output_port = connection
            else:
                node = connection
            # Check if the connected node can provide a scalar value
            if hasattr(node, 'get_scalar_value') and callable(node.get_scalar_value):
                return node.get_scalar_value()
        # Fall back to internal parameter
        return getattr(self, param_name, default)

    def evaluate_port(self, port_name: str, size: int) -> np.ndarray:
        """Evaluate a specific output port. Override for multi-output nodes."""
        # Default: all ports return the same output
        return self.evaluate(size)

    def evaluate(self, size: int) -> np.ndarray:
        """
        Evaluate the node with generation-based caching.
        Cache hit only if generation hash matches (self + all upstream unchanged).
        """
        size = int(size)
        gen_hash = self._get_generation_hash()

        # Get or create cache for this size
        if size not in self._cache:
            self._cache[size] = OrderedDict()
        size_cache = self._cache[size]

        # Check if we have a valid cached result for this generation
        if gen_hash in size_cache:
            # Move to end (LRU update)
            size_cache.move_to_end(gen_hash)
            return size_cache[gen_hash]

        # Cache miss - compute the result
        img = self._compute(size)
        img = ensure_rgba(img)
        if img.shape[0] != size or img.shape[1] != size:
            img = resample_to_size(img, size)
        img = clamp01(img.astype(np.float32))

        # Store in cache with generation hash
        size_cache[gen_hash] = img

        # LRU eviction: keep only MAX_CACHE_ENTRIES_PER_SIZE entries
        while len(size_cache) > MAX_CACHE_ENTRIES_PER_SIZE:
            size_cache.popitem(last=False)  # Remove oldest

        self._dirty = False
        return img

    def clear_cache(self):
        """Explicitly clear all cached data (for memory management)."""
        self._cache.clear()

    def _compute(self, size: int) -> np.ndarray:
        raise NotImplementedError

class Graph:
    """
    Container for a texture node graph.

    Manages a collection of nodes and provides evaluation/export utilities.
    """

    def __init__(self, size: int = 512):
        self.size = int(size)
        self.nodes: list[TextureNode] = []

    def add(self, node: TextureNode) -> TextureNode:
        """Add a node to the graph and return it."""
        self.nodes.append(node)
        return node

    def output(self, node: TextureNode, size: Optional[int] = None) -> np.ndarray:
        """Evaluate a node and return its output array."""
        return node.evaluate(size or self.size)

    def export_png(self, node: TextureNode, path: str, size: Optional[int] = None):
        """Export a node's output to a PNG file."""
        arr = self.output(node, size)
        img = Image.fromarray(to_uint8(arr), mode="RGBA")
        img.save(path, format="PNG")

class Constant(Node):
    def __init__(self, color: Tuple[float, float, float, float] = (0, 0, 0, 0),
                 scalar_value: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.color = tuple(float(c) for c in color)
        self.scalar_value = float(scalar_value)

    def get_scalar_value(self) -> float:
        """Return the constant scalar value."""
        return float(self.scalar_value)

    def _compute(self, size: int) -> np.ndarray:
        c = np.array(self.color, dtype=np.float32)
        img = np.tile(c[None, None, :], (size, size, 1))
        return img


