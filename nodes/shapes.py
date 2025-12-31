# pynodes/nodes/shapes.py
from __future__ import annotations
import numpy as np
import math
import cv2
from PIL import Image, ImageDraw
from typing import Tuple
from texture_pig.nodes.core import Node, get_scalar_param, get_scalar_param_int

class Circle:
    def __init__(self, cx=0.5, cy=0.5, radius=0.2, color=(1, 1, 1, 1),
                 edge_softness=0.0, name='Circle'):
        """
        cx, cy: center in normalized [0..1] coordinates
        radius: normalized (0..1 of min(image side))
        edge_softness: normalized feather width (0..1 of min(image side)); 0 = hard edge
        color: RGBA in [0..1]
        """
        self.cx = float(cx)
        self.cy = float(cy)
        self.radius = float(radius)
        self.edge_softness = float(edge_softness)
        self.color = tuple(float(c) for c in color)
        self.name = name
        self.inputs = {}
        self._dirty = True
        self._cache = None
        self.dependents = set()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._dirty = True
        self._cache = None

    # --- Graph protocol entry point ---

    def evaluate(self, size=512):
        """
        Return RGBA float image (H, W, 4) in [0..1].
        cx controls horizontal (X), cy controls vertical (Y).
        """
        H = W = int(size)

        # Get parameters (check for scalar inputs first)
        cx = get_scalar_param(self, 'cx', self.cx)
        cy = get_scalar_param(self, 'cy', self.cy)
        radius = get_scalar_param(self, 'radius', self.radius)
        edge_softness = get_scalar_param(self, 'edge_softness', self.edge_softness)

        # Build normalized coordinate grid in [0..1]
        x = (np.arange(W, dtype=np.float32) + 0.5) / np.float32(W)  # horizontal
        y = (np.arange(H, dtype=np.float32) + 0.5) / np.float32(H)  # vertical
        X, Y = np.meshgrid(x, y, indexing='xy')  # X: (H,W) columns, Y: (H,W) rows

        # Pixel-space offsets relative to center (cx, cy)
        dx = (X - np.float32(cx)) * np.float32(W)  # horizontal offset in pixels
        dy = (Y - np.float32(cy)) * np.float32(H)  # vertical offset in pixels

        # Distance from center
        dist = np.sqrt(dx * dx + dy * dy, dtype=np.float32)

        # Radius & softness in pixels (normalized by min side for resolution independence)
        min_side = np.float32(min(H, W))
        r_px = np.float32(radius) * min_side
        s_px = max(np.float32(0.0), np.float32(edge_softness)) * min_side

        # Signed distance: negative inside, positive outside
        sdf = dist - r_px

        # Smooth mask across s_px using smootherstep; hard edge if s_px == 0
        if s_px > 0.0:
            # Map sdf in [-s_px, s_px] to t in [0,1] where 1=inside, 0=outside
            t = np.clip(0.5 - 0.5 * (sdf / s_px), 0.0, 1.0)
            mask = t * t * t * (t * (t * np.float32(6) - np.float32(15)) + np.float32(10))
        else:
            mask = (sdf <= 0.0).astype(np.float32)

        r, g, b, a = [np.float32(c) for c in self.color]
        out = np.zeros((H, W, 4), dtype=np.float32)
        out[..., 0] = r
        out[..., 1] = g
        out[..., 2] = b
        out[..., 3] = a * mask
        return out

class Rectangle:
    def __init__(self, cx=0.5, cy=0.5, width=0.5, height=0.5, rotation_deg=0.0,
                 color=(1, 1, 1, 1), edge_softness=0.0, corner_radius=0.0, name='Rect'):
        """
        cx, cy           : center in normalized [0..1]
        width, height    : normalized fraction of the image dimension (0..1)
        rotation_deg     : rotation in degrees
        color            : RGBA in [0..1]
        edge_softness    : feather width (normalized to min image side); 0 => hard edge
        corner_radius    : rounded corner radius (normalized to min image side); 0 => sharp corners
        """
        self.cx = float(cx)
        self.cy = float(cy)
        self.width = float(width)
        self.height = float(height)
        self.rotation_deg = float(rotation_deg)
        self.edge_softness = float(edge_softness)
        self.corner_radius = float(corner_radius)
        self.color = tuple(float(c) for c in color)
        self.name = name
        self.inputs = {}
        self._dirty = True
        self._cache = None
        self.dependents = set()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._dirty = True
        self._cache = None

    @staticmethod
    def _sdf_rounded_box(px: np.ndarray, py: np.ndarray,
                         half_w: float, half_h: float, radius: float) -> np.ndarray:
        """
        Signed distance to a rounded rectangle centered at (0,0) with half extents (half_w, half_h)
        and corner radius 'radius' (all in pixels).
        Formula adapted from standard SDF references:
            q = abs(p) - b
            d = length(max(q, 0)) + min(max(q.x, q.y), 0) - r
        """
        ax = np.abs(px) - half_w
        ay = np.abs(py) - half_h
        qx = np.maximum(ax, 0.0)
        qy = np.maximum(ay, 0.0)
        outside = np.sqrt(qx * qx + qy * qy, dtype=np.float32)
        inside = np.minimum(np.maximum(ax, ay), 0.0)
        return outside + inside - radius

    # --- Graph protocol entry point ---
    def evaluate(self, size=512):
        """
        Return RGBA float image (H, W, 4) in [0..1].
        cx controls horizontal (X), cy controls vertical (Y).
        """
        H = W = int(size)

        # Get parameters (check for scalar inputs first)
        cx = get_scalar_param(self, 'cx', self.cx)
        cy = get_scalar_param(self, 'cy', self.cy)
        width = get_scalar_param(self, 'width', self.width)
        height = get_scalar_param(self, 'height', self.height)
        rotation_deg = get_scalar_param(self, 'rotation_deg', self.rotation_deg)
        edge_softness = get_scalar_param(self, 'edge_softness', self.edge_softness)
        corner_radius = get_scalar_param(self, 'corner_radius', self.corner_radius)

        # Normalized grid
        x = (np.arange(W, dtype=np.float32) + 0.5) / np.float32(W)  # horizontal [0..1]
        y = (np.arange(H, dtype=np.float32) + 0.5) / np.float32(H)  # vertical   [0..1]
        X, Y = np.meshgrid(x, y, indexing='xy')

        # Pixel-space offsets relative to center
        dx = (X - np.float32(cx)) * np.float32(W)
        dy = (Y - np.float32(cy)) * np.float32(H)

        # Rotate coordinates to rectangle's local axes
        th = np.deg2rad(np.float32(rotation_deg))
        c = np.cos(th).astype(np.float32)
        s = np.sin(th).astype(np.float32)
        rx =  c * dx + s * dy
        ry = -s * dx + c * dy

        # Half sizes in pixels
        half_w = np.float32(0.5 * width * W)
        half_h = np.float32(0.5 * height * H)

        # Corner radius in pixels (normalized by min side), clamped to min(half_w, half_h)
        min_side = np.float32(min(H, W))
        r_px = np.float32(max(0.0, corner_radius)) * min_side
        r_px = float(np.minimum(r_px, np.minimum(half_w, half_h)))

        # Signed distance from rounded rectangle boundary (centered at origin)
        sdf = self._sdf_rounded_box(rx, ry, float(half_w), float(half_h), r_px)

        # Softness in pixels (normalized)
        s_px = np.float32(max(0.0, edge_softness)) * min_side

        if s_px > 0.0:
            # Smootherstep across +/- s_px
            t = np.clip(0.5 - 0.5 * (sdf / s_px), 0.0, 1.0)
            mask = t * t * t * (t * (t * np.float32(6) - np.float32(15)) + np.float32(10))
        else:
            mask = (sdf <= 0.0).astype(np.float32)

        r, g, b, a = [np.float32(c) for c in self.color]
        out = np.zeros((H, W, 4), dtype=np.float32)
        out[..., 0] = r
        out[..., 1] = g
        out[..., 2] = b
        out[..., 3] = a * mask
        return out

class Triangle:
    def __init__(self,
                 cx=0.5, cy=0.5,
                 base=0.5, height=0.5,
                 scale=1.0,
                 rotation_deg=0.0,
                 color=(1, 1, 1, 1),
                 edge_softness=0.0,
                 equilateral=True,
                 name='Triangle'):
        """
        Isosceles/Equilateral triangle pointing upwards, centered at (cx, cy).

        Parameters (normalized):
          - cx, cy       : center in [0..1] (default 0.5, 0.5 → image center)
          - base, height : size fractions (0..1) relative to image width/height
                           If equilateral=True, height is derived from base (height = sqrt(3)/2 * base).
          - scale        : uniform scale multiplier for base & height (UX-friendly)
          - rotation_deg : rotation in degrees (0 → pointing up)
          - color        : RGBA in [0..1]
          - edge_softness: feather width normalized to min(H, W); 0 → hard edge
          - equilateral  : when True (default), height is computed from base for an equilateral triangle
        """
        self.cx = float(cx)
        self.cy = float(cy)
        self.base = float(base)
        self.height = float(height)     # used if equilateral=False
        self.scale = float(scale)
        self.rotation_deg = float(rotation_deg)
        self.edge_softness = float(edge_softness)
        self.equilateral = bool(equilateral)
        self.color = tuple(float(c) for c in color)
        self.name = name
        self.inputs = {}
        self._dirty = True
        self._cache = None
        self.dependents = set()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._dirty = True
        self._cache = None

    # --- SDF helpers ---
    @staticmethod
    def _sdf_triangle(px: np.ndarray, py: np.ndarray,
                      v0: np.ndarray, v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
        """
        Signed distance to a triangle defined by vertices v0, v1, v2 (2D).
        Negative inside; positive outside.
        """
        P = np.stack((px, py), axis=-1)  # (H,W,2)

        def seg_sdf(p, a, b):
            ab = b - a
            t = np.clip(((p - a) @ ab) / (ab @ ab + 1e-12), 0.0, 1.0)
            closest = a + t[..., None] * ab
            d = p - closest
            return np.sqrt(np.sum(d * d, axis=-1), dtype=np.float32)

        v0 = v0.astype(np.float32); v1 = v1.astype(np.float32); v2 = v2.astype(np.float32)
        d0 = seg_sdf(P, v0, v1)
        d1 = seg_sdf(P, v1, v2)
        d2 = seg_sdf(P, v2, v0)
        dist = np.minimum(np.minimum(d0, d1), d2)  # unsigned distance

        def edge_sign(p, a, b):
            ba = b - a
            pa = p - a
            return ba[..., 0] * pa[..., 1] - ba[..., 1] * pa[..., 0]

        s0 = edge_sign(P, v0, v1) >= 0.0
        s1 = edge_sign(P, v1, v2) >= 0.0
        s2 = edge_sign(P, v2, v0) >= 0.0
        inside = (s0 & s1 & s2)

        sdf = dist.astype(np.float32)
        sdf[inside] *= -1.0
        return sdf

    # --- Graph protocol entry point ---
    def evaluate(self, size=512):
        """
        Return RGBA float image (H, W, 4) in [0..1].

        Geometry (local before rotation):
          - Base centered horizontally.
          - Apex above the base.
          - Vertically centered by subtracting height/2 from vertex Y positions
            (so centroid is at 0, and cx,cy is pivot and visual center).
        """
        H = W = int(size)

        # Get parameters (check for scalar inputs first)
        cx = get_scalar_param(self, 'cx', self.cx)
        cy = get_scalar_param(self, 'cy', self.cy)
        base = get_scalar_param(self, 'base', self.base)
        height = get_scalar_param(self, 'height', self.height)
        scale = get_scalar_param(self, 'scale', self.scale)
        rotation_deg = get_scalar_param(self, 'rotation_deg', self.rotation_deg)
        edge_softness = get_scalar_param(self, 'edge_softness', self.edge_softness)

        # Normalized grid
        x = (np.arange(W, dtype=np.float32) + 0.5) / np.float32(W)  # [0..1]
        y = (np.arange(H, dtype=np.float32) + 0.5) / np.float32(H)  # [0..1]
        X, Y = np.meshgrid(x, y, indexing='xy')

        # Pixel-space offsets relative to center
        dx = (X - np.float32(cx)) * np.float32(W)
        dy = (Y - np.float32(cy)) * np.float32(H)

        # Rotate sampling coords (keep simple)
        th = np.deg2rad(np.float32(rotation_deg))
        c = np.cos(th).astype(np.float32)
        s = np.sin(th).astype(np.float32)
        rx =  c * dx + s * dy
        ry = -s * dx + c * dy

        # Effective base/height with scale, in pixels
        base_eff_norm = np.float32(max(0.0, base) * max(0.0, scale))
        if self.equilateral:
            # height = sqrt(3)/2 * base
            height_eff_norm = np.float32(np.sqrt(3.0) / 2.0) * base_eff_norm
        else:
            height_eff_norm = np.float32(max(0.0, height) * max(0.0, scale))

        base_eff_px   = base_eff_norm   * np.float32(W)
        height_eff_px = height_eff_norm * np.float32(H)

        half_b = 0.5 * base_eff_px
        half_h = 0.5 * height_eff_px

        # Vertices (centered vertically by subtracting height/2)
        # Base line at y = -half_h, apex at y = +half_h (pointing up with rotation=0)
        v0 = np.array([-half_b, -half_h], dtype=np.float32)  # left base
        v1 = np.array([+half_b, -half_h], dtype=np.float32)  # right base
        v2 = np.array([0.0,     +half_h], dtype=np.float32)  # apex

        # Signed distance to triangle
        sdf = self._sdf_triangle(rx, ry, v0, v1, v2)

        # Edge softness in pixels
        min_side = np.float32(min(H, W))
        s_px = np.float32(max(0.0, edge_softness)) * min_side

        if s_px > 0.0:
            t = np.clip(0.5 - 0.5 * (sdf / s_px), 0.0, 1.0)
            mask = t * t * t * (t * (t * np.float32(6) - np.float32(15)) + np.float32(10))
        else:
            mask = (sdf <= 0.0).astype(np.float32)

        r, g, b, a = [np.float32(c) for c in self.color]
        out = np.zeros((H, W, 4), dtype=np.float32)
        out[..., 0] = r
        out[..., 1] = g
        out[..., 2] = b
        out[..., 3] = a * mask
        return out

class Line(Node):
    def __init__(self, x0: float = 0.2, y0: float = 0.2, x1: float = 0.8, y1: float = 0.8,
                 width: float = 0.02, color: Tuple[float, float, float, float] = (1,1,1,1), antialias: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.x0 = float(x0); self.y0 = float(y0)
        self.x1 = float(x1); self.y1 = float(y1)
        self.width = float(width)
        self.color = tuple(float(c) for c in color)
        self.antialias = int(antialias)

    def _compute(self, size: int) -> np.ndarray:
        ss = max(1, self.antialias); S = size * ss
        img = Image.new('RGBA', (S, S), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        col = tuple(int(max(0,min(255,c*255))) for c in self.color)
        draw.line([self.x0*S, self.y0*S, self.x1*S, self.y1*S], fill=col, width=[1, int(self.width*S)][1])
        arr = np.asarray(img, dtype=np.uint8)
        if ss > 1:
            # Use cv2.resize (faster than PIL)
            arr = cv2.resize(arr, (size, size), interpolation=cv2.INTER_LANCZOS4)
        arr = arr.astype(np.float32) / 255.0
        return arr


class Stripes:
    """
    Generates evenly-spaced parallel stripes.

    With N stripes, the canvas is divided into N+1 equal parts with stripes
    placed symmetrically at the division lines.

    Implements the TextureNode protocol.

    Parameters:
        count: Number of stripes (1 = single center stripe, 2 = two stripes at 1/3 and 2/3, etc.)
        thickness: Stripe width as fraction of canvas (0..1)
        rotation_deg: Rotation angle in degrees
        color: RGBA color tuple in [0..1]
        edge_softness: Feather width for soft edges (0 = hard edge)
        frame: If True, adds half-thickness stripes at edges (0 and 1) for seamless tiling
    """

    def __init__(self, count: int = 3, thickness: float = 0.05, rotation_deg: float = 0.0,
                 color: Tuple[float, float, float, float] = (1, 1, 1, 1),
                 edge_softness: float = 0.0, frame: bool = False, name: str = 'Stripes'):
        self.name = name
        self.count = max(1, int(count))
        self.thickness = float(thickness)
        self.rotation_deg = float(rotation_deg)
        self.color = tuple(float(c) for c in color)
        self.edge_softness = float(edge_softness)
        self.frame = bool(frame)
        self.inputs = {}
        self.dependents = set()
        self._dirty = True
        self._cache = None

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()
        return self

    def connect(self, input_name: str, node, output_port: str = 'out'):
        self.inputs[input_name] = (node, output_port)
        if hasattr(node, 'dependents'):
            node.dependents.add(self)
        self.invalidate()
        return self

    def invalidate(self):
        self._dirty = True
        self._cache = None

    def evaluate(self, size: int = 512) -> np.ndarray:
        """Return RGBA float image (H, W, 4) in [0..1]."""
        H = W = int(size)

        # Normalized grid [0..1]
        x = (np.arange(W, dtype=np.float32) + 0.5) / np.float32(W)
        y = (np.arange(H, dtype=np.float32) + 0.5) / np.float32(H)
        X, Y = np.meshgrid(x, y, indexing='xy')

        # Center coordinates at (0.5, 0.5)
        dx = X - 0.5
        dy = Y - 0.5

        # Rotate coordinates
        th = np.deg2rad(np.float32(self.rotation_deg))
        c = np.cos(th).astype(np.float32)
        s = np.sin(th).astype(np.float32)
        # After rotation, we only care about the x-coordinate for vertical stripes
        rx = c * dx + s * dy

        # Shift back to [0..1] range for stripe calculation
        pos = rx + 0.5

        # Calculate stripe positions: i / (count + 1) for i in 1..count
        count = max(1, get_scalar_param_int(self, 'count', self.count))
        half_thickness = self.thickness * 0.5
        edge_soft = max(0.0, self.edge_softness)

        # Initialize mask
        mask = np.zeros((H, W), dtype=np.float32)

        # Helper to add a stripe at a given position with given half-width
        def add_stripe(stripe_pos: float, half_width: float):
            nonlocal mask
            dist = np.abs(pos - stripe_pos)
            if edge_soft > 0:
                t = np.clip(1.0 - (dist - half_width) / edge_soft, 0.0, 1.0)
                stripe_mask = t * t * (3.0 - 2.0 * t)  # smoothstep
            else:
                stripe_mask = (dist <= half_width).astype(np.float32)
            mask = np.maximum(mask, stripe_mask)

        # Add main stripes
        for i in range(1, count + 1):
            stripe_pos = float(i) / float(count + 1)
            add_stripe(stripe_pos, half_thickness)

        # Add frame stripes at edges (centered on border for seamless tiling)
        # Using full half_thickness means only the inner half is visible,
        # and when tiled, two halves combine into a full-width stripe
        if self.frame:
            add_stripe(0.0, half_thickness)  # Left/top edge
            add_stripe(1.0, half_thickness)  # Right/bottom edge

        # Build output RGBA
        r, g, b, a = [np.float32(c) for c in self.color]
        out = np.zeros((H, W, 4), dtype=np.float32)
        out[..., 0] = r
        out[..., 1] = g
        out[..., 2] = b
        out[..., 3] = a * mask
        return out

    def evaluate_port(self, port_name: str, size: int) -> np.ndarray:
        """Evaluate a specific output port (default implementation)."""
        return self.evaluate(size)


class HexGrid:
    """
    Generates a hexagonal grid pattern (honeycomb lines).

    Draws the edges/lines of hexagons arranged in a grid pattern.
    Supports both pointy-top and flat-top orientations.

    Implements the TextureNode protocol.

    Parameters:
        hex_size: Size of each hexagon as fraction of canvas width (0..1)
        thickness: Line thickness as fraction of canvas (0..1)
        color: RGBA color tuple in [0..1]
        edge_softness: Feather width for soft edges (0 = hard edge)
        orientation: 'pointy' (pointy-top) or 'flat' (flat-top) hexagons
        offset_x: Horizontal offset in normalized coords
        offset_y: Vertical offset in normalized coords
    """

    def __init__(self, hex_size: float = 0.2, thickness: float = 0.02,
                 color: Tuple[float, float, float, float] = (1, 1, 1, 1),
                 edge_softness: float = 0.0, orientation: str = 'pointy',
                 offset_x: float = 0.0, offset_y: float = 0.0,
                 stretch_x: float = 1.0, stretch_y: float = 1.0,
                 name: str = 'HexGrid'):
        self.name = name
        self.hex_size = float(hex_size)
        self.thickness = float(thickness)
        self.color = tuple(float(c) for c in color)
        self.edge_softness = float(edge_softness)
        self.orientation = str(orientation).lower()
        self.offset_x = float(offset_x)
        self.offset_y = float(offset_y)
        self.stretch_x = float(stretch_x)
        self.stretch_y = float(stretch_y)
        self.inputs = {}
        self.dependents = set()
        self._dirty = True
        self._cache = None

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if hasattr(self, 'orientation'):
            self.orientation = str(self.orientation).lower()
        self.invalidate()
        return self

    def connect(self, input_name: str, node, output_port: str = 'out'):
        self.inputs[input_name] = (node, output_port)
        if hasattr(node, 'dependents'):
            node.dependents.add(self)
        self.invalidate()
        return self

    def invalidate(self):
        self._dirty = True
        self._cache = None

    def evaluate(self, size: int = 512) -> np.ndarray:
        """Return RGBA float image (H, W, 4) in [0..1]."""
        H = W = int(size)
        sqrt3 = np.sqrt(3.0)

        # Base hex radius from user's hex_size
        base_radius = self.hex_size * size * 0.5

        # Stretch factors - applied to coordinate space to deform hexagons
        stretch_x = max(0.01, self.stretch_x)
        stretch_y = max(0.01, self.stretch_y)

        if self.orientation == 'flat':
            # Flat-top: quantize horizontal period for seamless horizontal tiling
            n_x = max(1, round(size / (3.0 * base_radius)))
            hex_radius = size / (3.0 * n_x)
            # Standard hex spacings (before stretch)
            base_horiz_spacing = 1.5 * hex_radius
            base_vert_spacing = sqrt3 * hex_radius
            angles = np.array([30, 90, 150]) * np.pi / 180.0
        else:
            # Pointy-top: quantize vertical period for seamless vertical tiling
            n_y = max(1, round(size / (3.0 * base_radius)))
            hex_radius = size / (3.0 * n_y)
            # Standard hex spacings (before stretch)
            base_horiz_spacing = sqrt3 * hex_radius
            base_vert_spacing = 1.5 * hex_radius
            angles = np.array([0, 60, 120]) * np.pi / 180.0

        # Apothem of the regular (unstretched) hex
        apothem = hex_radius * sqrt3 / 2.0

        # Pixel coordinates centered on canvas middle, then apply user offset
        x = np.arange(W, dtype=np.float32)
        y = np.arange(H, dtype=np.float32)
        X, Y = np.meshgrid(x, y, indexing='xy')

        # Center the pattern, apply offset
        X = X - size * 0.5 - self.offset_x * size
        Y = Y - size * 0.5 - self.offset_y * size

        # Apply inverse stretch to coordinates (stretching the hex means shrinking coordinate space)
        X_hex = X / stretch_x
        Y_hex = Y / stretch_y

        half_thickness = self.thickness * size * 0.5
        edge_soft = max(0.0, self.edge_softness) * size

        # Use offset coordinate system in unstretched hex space
        if self.orientation == 'flat':
            col = np.floor(X_hex / base_horiz_spacing + 0.5)
            row = np.floor(Y_hex / base_vert_spacing + 0.5 - np.where(np.mod(col, 2) != 0, 0.5, 0.0))
        else:
            row = np.floor(Y_hex / base_vert_spacing + 0.5)
            col = np.floor(X_hex / base_horiz_spacing + 0.5 - np.where(np.mod(row, 2) != 0, 0.5, 0.0))

        # Check multiple candidate hexes in a 3x3 grid to ensure all boundaries are drawn
        mask = np.zeros((H, W), dtype=np.float32)

        for di in [-1, 0, 1]:
            for dj in [-1, 0, 1]:
                if self.orientation == 'flat':
                    test_col = col + di
                    test_row_offset = np.where(np.mod(test_col, 2) != 0, 0.5, 0.0)
                    test_row = row + dj
                    test_cx = test_col * base_horiz_spacing
                    test_cy = (test_row + test_row_offset) * base_vert_spacing
                else:
                    test_row = row + dj
                    test_col_offset = np.where(np.mod(test_row, 2) != 0, 0.5, 0.0)
                    test_col = col + di
                    test_cx = (test_col + test_col_offset) * base_horiz_spacing
                    test_cy = test_row * base_vert_spacing

                # Distance in unstretched hex space
                test_dx = X_hex - test_cx
                test_dy = Y_hex - test_cy

                # Compute distance to this hex's boundary using standard hex SDF
                test_max_dist = np.zeros((H, W), dtype=np.float32)
                for angle in angles:
                    nx = np.cos(angle)
                    ny = np.sin(angle)
                    dist = np.abs(test_dx * nx + test_dy * ny)
                    test_max_dist = np.maximum(test_max_dist, dist)

                test_dist_to_boundary = test_max_dist - apothem

                # Scale boundary distance back to pixel space for thickness
                # Use geometric mean of stretch factors for uniform-ish thickness
                stretch_avg = np.sqrt(stretch_x * stretch_y)
                test_dist_to_edge = np.abs(test_dist_to_boundary * stretch_avg) - half_thickness

                if edge_soft > 0:
                    t = np.clip(1.0 - test_dist_to_edge / edge_soft, 0.0, 1.0)
                    test_mask = t * t * (3.0 - 2.0 * t)
                else:
                    test_mask = (test_dist_to_edge <= 0).astype(np.float32)

                mask = np.maximum(mask, test_mask)

        # Build output RGBA
        r, g, b, a = [np.float32(c) for c in self.color]
        out = np.zeros((H, W, 4), dtype=np.float32)
        out[..., 0] = r
        out[..., 1] = g
        out[..., 2] = b
        out[..., 3] = a * mask
        return out

    def get_tileable_dimensions(self, size: int = 512) -> tuple:
        """
        Calculate the exact tileable dimensions for this hex grid configuration.

        For a regular hex grid to tile seamlessly:
        - Pointy-top: width = √3 · r · N (N even), height = 3/2 · r · M
        - Flat-top:   width = 3/2 · r · N, height = √3 · r · M (M even)

        Returns (tileable_width, tileable_height) as integers.
        """
        sqrt3 = np.sqrt(3.0)
        base_radius = self.hex_size * size * 0.5

        if self.orientation == 'flat':
            # Flat-top: quantize to n_x columns
            n_x = max(1, round(size / (3.0 * base_radius)))
            hex_radius = size / (3.0 * n_x)
            # Exact tileable dimensions
            # Width tiles at 3/2 · r · N period
            # Height tiles at √3 · r · M period (M should be even for offset rows)
            n_y = max(2, round(size / (sqrt3 * hex_radius)))
            if n_y % 2 != 0:
                n_y += 1  # Make even
            tileable_width = int(round(1.5 * hex_radius * n_x * 2))  # *2 for full period
            tileable_height = int(round(sqrt3 * hex_radius * n_y))
        else:
            # Pointy-top: quantize to n_y rows
            n_y = max(1, round(size / (3.0 * base_radius)))
            hex_radius = size / (3.0 * n_y)
            # Exact tileable dimensions
            # Width tiles at √3 · r · N period (N should be even for offset columns)
            # Height tiles at 3/2 · r · M period
            n_x = max(2, round(size / (sqrt3 * hex_radius)))
            if n_x % 2 != 0:
                n_x += 1  # Make even
            tileable_width = int(round(sqrt3 * hex_radius * n_x))
            tileable_height = int(round(1.5 * hex_radius * n_y * 2))  # *2 for full period

        return (tileable_width, tileable_height)

    def evaluate_port(self, port_name: str, size: int) -> np.ndarray:
        """Evaluate a specific output port (default implementation)."""
        return self.evaluate(size)
