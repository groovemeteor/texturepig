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

__all__ = [
    # Protocol
    'TextureNode',
    # Base classes
    'Node',
    'Graph',
    'GenerationCacheMixin',
    # Built-in nodes
    'Constant',
    # Utilities
    'ensure_rgba',
    'clamp01',
    'resample_to_size',
    'to_uint8',
    'from_uint8',
    'mask_to_scalar',
]
