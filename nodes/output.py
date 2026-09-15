# texture_pig/nodes/output.py
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

class Output:
    """
    Sink node. Returns the output of its single input 'src'.
    If 'src' is not connected, returns transparent RGBA.
    """
    def __init__(self, name: str = 'Output'):
        self.name = name
        self.inputs = {'src': None}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility

    def set_params(self, **kwargs):
        # Output has no tunable params; ignore for now
        pass

    def connect(self, input_name: str, src_node, output_port: str = 'out'):
        if input_name != 'src':
            return
        self.inputs['src'] = (src_node, output_port)
        self.invalidate()

    def invalidate(self):
        self._dirty = True

    def evaluate(self, size: int = 512) -> np.ndarray:
        connection = self.inputs.get('src')
        if connection is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        # Handle both tuple format (node, port) and legacy format (node)
        if isinstance(connection, tuple):
            src, output_port = connection
            if hasattr(src, 'evaluate_port'):
                return src.evaluate_port(output_port, int(size))
            return src.evaluate(int(size))
        else:
            src = connection
        try:
            return src.evaluate(int(size))
        except Exception:
            # Safe fallback: red tile
            logger.exception("Upstream evaluate failed")
            out = np.zeros((size, size, 4), dtype=np.float32)
            out[..., 0] = 0.6
            out[..., 3] = 1.0
            return out
