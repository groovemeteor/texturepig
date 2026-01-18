"""
Texture Pig node system.

This module provides the node-based texture generation framework.

Key exports:
    TextureNode: Protocol defining the node interface
    Node: Base class for generator nodes
    Graph: Container for node graphs
    GenerationCacheMixin: Mixin for filter nodes with caching
"""

from texture_pig.nodes.core import (
    TextureNode,
    Node,
    Graph,
    GenerationCacheMixin,
    Constant,
    # Utility functions
    ensure_rgba,
    clamp01,
    resample_to_size,
    to_uint8,
    from_uint8,
    mask_to_scalar,
)

from texture_pig.nodes.scalar import (
    ScalarNodeProtocol,
    ScalarNode,
    Float,
    Int,
    ScalarAdd,
    ScalarSub,
    ScalarMul,
    ScalarDiv,
    ScalarClamp,
)

__all__ = [
    # Protocols
    'TextureNode',
    'ScalarNodeProtocol',
    # Base classes
    'Node',
    'Graph',
    'GenerationCacheMixin',
    'ScalarNode',
    # Built-in nodes
    'Constant',
    # Scalar nodes
    'Float',
    'Int',
    'ScalarAdd',
    'ScalarSub',
    'ScalarMul',
    'ScalarDiv',
    'ScalarClamp',
    # Utilities
    'ensure_rgba',
    'clamp01',
    'resample_to_size',
    'to_uint8',
    'from_uint8',
    'mask_to_scalar',
]
