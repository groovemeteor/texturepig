import cv2
import numpy as np
from .core import Node, get_scalar_param_int


class Outline(Node):
    """
    Creates a clean stroke/outline using OpenCV contour detection.
    Follows the framework pattern used by Transform and Filters.
    """

    def __init__(self, name="Outline", thickness=2, color=(1.0, 1.0, 1.0, 1.0), opacity=1.0, seed=None):
        super().__init__(name=name, opacity=opacity, seed=seed)
        self.thickness = float(thickness)
        self.color = color
        self.inputs = {'src': None}
        self._dirty = True

    def invalidate(self):
        self._dirty = True

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def evaluate(self, size=512):
        """Protocol implementation to match Graph.output behavior."""
        connection = self.inputs.get('src')
        if connection is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        # Handle both tuple format (node, output_port) and legacy direct node reference
        if isinstance(connection, tuple):
            upstream, output_port = connection
        else:
            upstream, output_port = connection, 'out'

        if upstream is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        # 1. Evaluate upstream node
        if hasattr(upstream, 'evaluate_port') and callable(upstream.evaluate_port):
            src_arr = upstream.evaluate_port(output_port, size)
        elif hasattr(upstream, 'evaluate'):
            src_arr = upstream.evaluate(size)
        else:
            src_arr = upstream(size) if callable(upstream) else None

        if src_arr is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        # 2. Convert Alpha to binary 8-bit for OpenCV
        alpha = (np.clip(src_arr[:, :, 3], 0, 1) * 255).astype(np.uint8)

        # 3. Find Contours
        _, binary = cv2.threshold(alpha, 127, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 4. Draw the contours
        mask = np.zeros((size, size), dtype=np.uint8)
        thickness_val = max(1, get_scalar_param_int(self, 'thickness', self.thickness))
        cv2.drawContours(mask, contours, -1, 255, thickness_val)

        # 5. Assemble RGBA result
        r, g, b, a = self.color
        out = np.zeros((size, size, 4), dtype=np.float32)
        out[:, :, 0] = float(r)
        out[:, :, 1] = float(g)
        out[:, :, 2] = float(b)
        out[:, :, 3] = (mask.astype(np.float32) / 255.0) * float(a)

        return out