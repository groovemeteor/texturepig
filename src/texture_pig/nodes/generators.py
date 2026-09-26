# pynodes/nodes/generators.py
from __future__ import annotations
import numpy as np
from texture_pig.nodes.core import Node

def _normalize01(v: np.ndarray) -> np.ndarray:
    vmin = float(v.min())
    vmax = float(v.max())
    return (v - vmin) / (max(vmax - vmin, 1e-8))

def _validate_color_stops(stops):
    """
    Validate and normalize color stops.
    Returns sorted tuple of (position, (R, G, B, A)) tuples.
    """
    if stops is None:
        return None
    stops = list(stops)
    if len(stops) < 2:
        raise ValueError("At least 2 color stops required")
    # Sort by position
    stops.sort(key=lambda s: s[0])
    validated = []
    for pos, color in stops:
        pos = max(0.0, min(1.0, float(pos)))
        # Ensure RGBA (add alpha if only RGB)
        color = tuple(float(c) for c in color)
        if len(color) == 3:
            color = color + (1.0,)
        validated.append((pos, color))
    return tuple(validated)

def _interpolate_color_stops(t_array, color_stops):
    """
    Interpolate colors for a 2D array of t values in [0,1].
    Returns RGBA array of shape (H, W, 4).
    """
    h, w = t_array.shape
    result = np.zeros((h, w, 4), dtype=np.float32)

    # Handle each segment between stops
    for i in range(len(color_stops) - 1):
        pos0, color0 = color_stops[i]
        pos1, color1 = color_stops[i + 1]

        # Mask for values in this segment
        if i == 0:
            mask = t_array <= pos1
        elif i == len(color_stops) - 2:
            mask = t_array >= pos0
        else:
            mask = (t_array >= pos0) & (t_array <= pos1)

        # Local t within segment
        segment_len = max(pos1 - pos0, 1e-8)
        local_t = (t_array - pos0) / segment_len
        local_t = np.clip(local_t, 0.0, 1.0)

        # Interpolate RGBA
        c0 = np.array(color0, dtype=np.float32)
        c1 = np.array(color1, dtype=np.float32)

        for ch in range(4):
            result[..., ch] = np.where(
                mask,
                (1.0 - local_t) * c0[ch] + local_t * c1[ch],
                result[..., ch]
            )

    return result

class GradientLinear(Node):
    def __init__(self, angle_deg: float = 0.0, offset: float = 0.0,
                 output_mode: str = 'rgb',
                 invert: bool = False,
                 start_color: tuple = (1.0, 1.0, 1.0),
                 end_color: tuple = (0.0, 0.0, 0.0),
                 color_stops: tuple = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.angle_deg   = float(angle_deg)
        self.offset      = float(offset)
        self.output_mode = str(output_mode).lower()
        self.invert      = bool(invert)
        self.start_color = tuple(map(float, start_color))
        self.end_color   = tuple(map(float, end_color))
        # Backward compatibility: convert start/end to color_stops if not provided
        if color_stops is None:
            sc = self.start_color + (1.0,) if len(self.start_color) == 3 else self.start_color
            ec = self.end_color + (1.0,) if len(self.end_color) == 3 else self.end_color
            self.color_stops = ((0.0, sc), (1.0, ec))
        else:
            self.color_stops = _validate_color_stops(color_stops)

    def _compute(self, size: int) -> np.ndarray:
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        # map to [-1, 1]
        xx = (x / (size - 1)) * 2.0 - 1.0
        yy = (y / (size - 1)) * 2.0 - 1.0
        theta = np.deg2rad(self.p('angle_deg'))
        v = np.cos(theta) * xx + np.sin(theta) * yy + self.p('offset')
        v = _normalize01(v)
        if self.invert:
            v = 1.0 - v

        mode = self.output_mode
        if mode == 'rgb':
            rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1).astype(np.float32)
            return rgba
        elif mode == 'alpha':
            rgba = np.stack([np.ones_like(v), np.ones_like(v), np.ones_like(v), v], axis=-1).astype(np.float32)
            return rgba
        elif mode == 'color':
            return _interpolate_color_stops(v, self.color_stops)

        # Fallback: legacy RGB
        rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1).astype(np.float32)
        return rgba

class GradientRadial(Node):
    def __init__(self, cx: float = 0.5, cy: float = 0.5, radius: float = 0.5,
                 invert: bool = False,
                 output_mode: str = 'rgb',
                 start_color: tuple = (1.0, 1.0, 1.0),
                 end_color: tuple = (0.0, 0.0, 0.0),
                 color_stops: tuple = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.cx = float(cx)
        self.cy = float(cy)
        self.radius = float(radius)
        self.invert = bool(invert)
        self.output_mode = str(output_mode).lower()
        self.start_color = tuple(map(float, start_color))
        self.end_color = tuple(map(float, end_color))
        # Backward compatibility
        if color_stops is None:
            sc = self.start_color + (1.0,) if len(self.start_color) == 3 else self.start_color
            ec = self.end_color + (1.0,) if len(self.end_color) == 3 else self.end_color
            self.color_stops = ((0.0, sc), (1.0, ec))
        else:
            self.color_stops = _validate_color_stops(color_stops)

    def _compute(self, size: int) -> np.ndarray:
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        xn = x / (size - 1)
        yn = y / (size - 1)
        dx = xn - self.p('cx')
        dy = yn - self.p('cy')
        d = np.sqrt(dx*dx + dy*dy)
        v = np.clip(d / max(self.p('radius'), 1e-6), 0.0, 1.0)
        if self.invert:
            v = 1.0 - v

        mode = self.output_mode
        if mode == 'rgb':
            rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1).astype(np.float32)
            return rgba
        elif mode == 'alpha':
            rgba = np.stack([np.ones_like(v), np.ones_like(v), np.ones_like(v), v], axis=-1).astype(np.float32)
            return rgba
        elif mode == 'color':
            return _interpolate_color_stops(v, self.color_stops)

        rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1).astype(np.float32)
        return rgba

def _fade(t): return t * t * t * (t * (t * 6 - 15) + 10)
def _lerp(a, b, t): return a + t * (b - a)

def _grad(hash, x, y):
    g = (hash & 7).astype(np.int32)
    ret = np.zeros_like(x, dtype=np.float32)
    ret = np.where(g == 0, x + y, ret)
    ret = np.where(g == 1, -x + y, ret)
    ret = np.where(g == 2, x - y, ret)
    ret = np.where(g == 3, -x - y, ret)
    ret = np.where(g == 4, x, ret)
    ret = np.where(g == 5, -x, ret)
    ret = np.where(g == 6, y, ret)
    ret = np.where(g == 7, -y, ret)
    return ret.astype(np.float32)


class GradientReflected(Node):
    """
    Linear reflected gradient along an axis:
      black -> white at midpoint -> black.
    Parameters:
      angle_deg: axis direction (0=+X, 90=+Y)
      midpoint: peak position along the ramp [0..1]
      invert: flip black/white
      output_mode: 'rgb' (grayscale in RGB), 'alpha' (value in A), or 'color'
    """
    def __init__(self,
                 angle_deg: float = 0.0,
                 midpoint: float = 0.5,
                 invert: bool = False,
                 output_mode: str = 'rgb',
                 start_color: tuple = (0.0, 0.0, 0.0),
                 end_color: tuple = (1.0, 1.0, 1.0),
                 color_stops: tuple = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.angle_deg = float(angle_deg)
        self.midpoint = float(midpoint)
        self.invert = bool(invert)
        self.output_mode = str(output_mode).lower()
        self.start_color = tuple(map(float, start_color))
        self.end_color = tuple(map(float, end_color))
        # Backward compatibility
        if color_stops is None:
            sc = self.start_color + (1.0,) if len(self.start_color) == 3 else self.start_color
            ec = self.end_color + (1.0,) if len(self.end_color) == 3 else self.end_color
            self.color_stops = ((0.0, sc), (1.0, ec))
        else:
            self.color_stops = _validate_color_stops(color_stops)

    def evaluate(self, size: int) -> np.ndarray:
        return self._compute(size)

    def _compute(self, size: int) -> np.ndarray:
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        xn = x / (size - 1)
        yn = y / (size - 1)

        # Axis direction from angle
        ang = np.deg2rad(self.p('angle_deg')).astype(np.float32)
        dx = np.cos(ang)
        dy = np.sin(ang)

        # Project centered at 0.5 into [0..1]
        t = (xn - 0.5) * dx + (yn - 0.5) * dy + 0.5
        t = np.clip(t, 0.0, 1.0)

        # Triangular ramp peaking at 'midpoint'
        m = float(np.clip(self.p('midpoint'), 1e-6, 1.0 - 1e-6))
        val = np.where(t <= m, t / m, (1.0 - t) / (1.0 - m)).astype(np.float32)
        val = np.clip(val, 0.0, 1.0)

        if self.invert:
            val = 1.0 - val

        if self.output_mode == 'alpha':
            rgba = np.stack([np.ones_like(val), np.ones_like(val), np.ones_like(val), val], axis=-1).astype(np.float32)
        elif self.output_mode == 'color':
            rgba = _interpolate_color_stops(val, self.color_stops)
        else:
            rgba = np.stack([val, val, val, np.ones_like(val)], axis=-1).astype(np.float32)
        return rgba

class GradientAngle(Node):
    """
    Angular gradient around a center:
      value = normalized angle in [0..1] around (cx, cy), with optional rotation offset.
    Parameters:
      cx, cy: center in normalized [0..1]
      angle_offset_deg: rotation offset
      invert: flip
      output_mode: 'rgb', 'alpha', or 'color'
    """
    def __init__(self,
                 cx: float = 0.5,
                 cy: float = 0.5,
                 angle_offset_deg: float = 0.0,
                 invert: bool = False,
                 output_mode: str = 'rgb',
                 start_color: tuple = (0.0, 0.0, 0.0),
                 end_color: tuple = (1.0, 1.0, 1.0),
                 color_stops: tuple = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.cx = float(cx)
        self.cy = float(cy)
        self.angle_offset_deg = float(angle_offset_deg)
        self.invert = bool(invert)
        self.output_mode = str(output_mode).lower()
        self.start_color = tuple(map(float, start_color))
        self.end_color = tuple(map(float, end_color))
        # Backward compatibility
        if color_stops is None:
            sc = self.start_color + (1.0,) if len(self.start_color) == 3 else self.start_color
            ec = self.end_color + (1.0,) if len(self.end_color) == 3 else self.end_color
            self.color_stops = ((0.0, sc), (1.0, ec))
        else:
            self.color_stops = _validate_color_stops(color_stops)

    def evaluate(self, size: int) -> np.ndarray:
        return self._compute(size)

    def _compute(self, size: int) -> np.ndarray:
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        xn = x / (size - 1)
        yn = y / (size - 1)

        dx = xn - self.p('cx')
        dy = yn - self.p('cy')

        theta = np.arctan2(dy, dx)  # [-pi, pi]
        norm = (theta / (2.0 * np.pi)) + 0.5  # [0..1]
        norm = (norm + (self.p('angle_offset_deg') / 360.0)) % 1.0

        val = norm.astype(np.float32)
        if self.invert:
            val = 1.0 - val

        if self.output_mode == 'alpha':
            rgba = np.stack([np.ones_like(val), np.ones_like(val), np.ones_like(val), val], axis=-1).astype(np.float32)
        elif self.output_mode == 'color':
            rgba = _interpolate_color_stops(val, self.color_stops)
        else:
            rgba = np.stack([val, val, val, np.ones_like(val)], axis=-1).astype(np.float32)
        return rgba

class PerlinNoise(Node):
    def __init__(self, scale: float = 8.0, octaves: int = 4, persistence: float = 0.5, lacunarity: float = 2.0, **kwargs):
        super().__init__(**kwargs)
        self.scale = float(scale); self.octaves = int(octaves)
        self.persistence = float(persistence); self.lacunarity = float(lacunarity)

    def _compute(self, size: int) -> np.ndarray:
        rng = self._rng()
        p = np.arange(256, dtype=np.int32)
        rng.shuffle(p)
        p = np.concatenate([p, p])

        def perlin2_tileable(x, y, period):
            xi = np.floor(x).astype(np.int32)
            yi = np.floor(y).astype(np.int32)
            xf = (x - np.floor(x)).astype(np.float32)
            yf = (y - np.floor(y)).astype(np.float32)
            u = _fade(xf)
            v = _fade(yf)
            # Wrap coordinates at the period boundary for seamless tiling
            xi0 = xi % period
            yi0 = yi % period
            xi1 = (xi + 1) % period
            yi1 = (yi + 1) % period
            # Use wrapped coordinates for permutation lookup
            aa = p[p[xi0 & 255] + (yi0 & 255)]
            ab = p[p[xi0 & 255] + (yi1 & 255)]
            ba = p[p[xi1 & 255] + (yi0 & 255)]
            bb = p[p[xi1 & 255] + (yi1 & 255)]
            x1 = _lerp(_grad(aa, xf, yf), _grad(ba, xf - 1, yf), u)
            x2 = _lerp(_grad(ab, xf, yf - 1), _grad(bb, xf - 1, yf - 1), u)
            return _lerp(x1, x2, v)

        # Pixel indices
        iy, ix = np.mgrid[0:size, 0:size].astype(np.float32)

        total = np.zeros((size, size), dtype=np.float32)
        max_amp = 0.0
        amp = 1.0
        freq = 1.0

        for _ in range(max(1, int(self.p('octaves')))):
            # Integer period for this octave - must match coordinate range exactly
            period = max(1, int(round(freq * size / self.p('scale'))))
            # Coordinates span exactly 0 to period across the tile
            # This ensures the seam aligns perfectly when tiled
            nx = ix * period / size
            ny = iy * period / size
            total += amp * perlin2_tileable(nx, ny, period)
            max_amp += amp
            amp *= self.p('persistence')
            freq *= self.p('lacunarity')

        v = total / (max_amp + 1e-8)
        v = (v - v.min()) / (v.max() - v.min() + 1e-8)
        rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1)
        return rgba.astype(np.float32)

class WorleyNoise(Node):
    def __init__(self, points: int = 16, jitter: float = 1.0, metric: str = 'euclidean', **kwargs):
        super().__init__(**kwargs)
        self.points = int(points); self.jitter = float(jitter); self.metric = metric

    def _compute(self, size: int) -> np.ndarray:
        rng = self._rng()
        # Generate base feature points in [0, 1)
        n_points = max(1, int(self.p('points')))
        pts = rng.random((n_points, 2), dtype=np.float32)
        pts += (rng.random((n_points, 2), dtype=np.float32) - 0.5) * self.p('jitter')
        # Wrap points to [0, 1) range
        pts = pts % 1.0

        # Create 3x3 tiled copies of points for seamless wrapping
        # This ensures pixels near edges see points from the opposite side
        offsets = np.array([[-1, -1], [-1, 0], [-1, 1],
                            [0, -1],  [0, 0],  [0, 1],
                            [1, -1],  [1, 0],  [1, 1]], dtype=np.float32)
        tiled_pts = (pts[None, :, :] + offsets[:, None, :]).reshape(-1, 2)  # (points * 9, 2)

        # Create coordinate grids
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        x = x / size
        y = y / size

        # Vectorized computation in chunks to balance speed vs memory
        # At chunk_size=64, memory usage is ~75MB for 2048px with 144 tiled points
        chunk_size = 64
        img = np.empty((size, size), dtype=np.float32)

        # Pre-extract point coordinates for efficiency
        pts_x = tiled_pts[:, 0]  # (num_points,)
        pts_y = tiled_pts[:, 1]  # (num_points,)

        for row_start in range(0, size, chunk_size):
            row_end = min(row_start + chunk_size, size)

            # Get coordinates for this chunk: (chunk_rows, size)
            x_chunk = x[row_start:row_end]
            y_chunk = y[row_start:row_end]

            # Compute distances using broadcasting
            # x_chunk[:, :, None] shape: (chunk_rows, size, 1)
            # pts_x shape: (num_points,) -> broadcasts to (1, 1, num_points)
            dx = x_chunk[:, :, None] - pts_x  # (chunk_rows, size, num_points)
            dy = y_chunk[:, :, None] - pts_y  # (chunk_rows, size, num_points)

            if self.metric == 'manhattan':
                d = np.abs(dx) + np.abs(dy)
            else:
                d = np.sqrt(dx * dx + dy * dy)

            img[row_start:row_end] = d.min(axis=2)

        v = (img - img.min()) / (img.max() - img.min() + 1e-8)
        rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1)
        return rgba.astype(np.float32)
