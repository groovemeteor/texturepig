
# texture_pig/nodes/layout.py
from __future__ import annotations
import numpy as np
import math
import cv2

from texture_pig.nodes.core import GenerationCacheMixin, get_scalar_param_int


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


def _sample_gradient_color(t: float, color_stops) -> tuple:
    """
    Sample a single RGBA color from gradient at position t in [0, 1].
    Returns (R, G, B, A) tuple with values in [0, 1].
    """
    if color_stops is None or len(color_stops) < 2:
        return (1.0, 1.0, 1.0, 1.0)

    t = max(0.0, min(1.0, t))

    # Find the two stops that bracket t
    for i in range(len(color_stops) - 1):
        pos0, color0 = color_stops[i]
        pos1, color1 = color_stops[i + 1]

        if t <= pos1 or i == len(color_stops) - 2:
            # Interpolate within this segment
            segment_len = max(pos1 - pos0, 1e-8)
            local_t = max(0.0, min(1.0, (t - pos0) / segment_len))

            r = (1.0 - local_t) * color0[0] + local_t * color1[0]
            g = (1.0 - local_t) * color0[1] + local_t * color1[1]
            b = (1.0 - local_t) * color0[2] + local_t * color1[2]
            a = (1.0 - local_t) * color0[3] + local_t * color1[3]
            return (r, g, b, a)

    # Fallback to last color
    return color_stops[-1][1]


def _tint_tile(tile: np.ndarray, color: tuple) -> np.ndarray:
    """
    Apply a color tint to a tile by multiplying RGB and alpha.
    """
    result = tile.copy()
    result[..., 0] *= color[0]  # R
    result[..., 1] *= color[1]  # G
    result[..., 2] *= color[2]  # B
    result[..., 3] *= color[3]  # A
    return np.clip(result, 0.0, 1.0).astype(np.float32)

def _ensure_rgba(img, size):
    img = np.asarray(img, dtype=np.float32)
    if img.ndim != 3 or img.shape[-1] != 4:
        return np.zeros((size, size, 4), dtype=np.float32)
    return np.clip(img, 0.0, 1.0)

def _safe_eval(connection, size):
    """Evaluate a connection, handling both (node, output_port) tuples and direct node refs."""
    if connection is None:
        return None

    # Handle tuple format (node, output_port)
    if isinstance(connection, tuple):
        node, output_port = connection
        if hasattr(node, 'evaluate_port') and callable(node.evaluate_port):
            return node.evaluate_port(output_port, size)
        if hasattr(node, 'evaluate') and callable(node.evaluate):
            return node.evaluate(size)
        return None

    # Legacy: direct node reference
    node = connection
    if hasattr(node, 'evaluate') and callable(node.evaluate):
        return node.evaluate(size)
    for fn_name in ('eval', 'output', 'render', '__call__'):
        fn = getattr(node, fn_name, None)
        if callable(fn):
            try:
                return fn(size=size)
            except TypeError:
                return fn(size)
            except Exception:
                pass
    return None

def _resize_bilinear(img: np.ndarray, new_h: int, new_w: int) -> np.ndarray:
    """Resize image using OpenCV bilinear interpolation."""
    h, w = img.shape[:2]
    if new_h == h and new_w == w:
        return img
    # cv2.resize takes (width, height) order
    out = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    return np.clip(out, 0.0, 1.0).astype(np.float32)

def _composite_over(dst: np.ndarray, src: np.ndarray, y0: int, x0: int,
                    clip_y0: int, clip_y1: int, clip_x0: int, clip_x1: int) -> None:
    h, w = src.shape[:2]
    Y0 = max(y0, clip_y0); X0 = max(x0, clip_x0)
    Y1 = min(y0 + h, clip_y1); X1 = min(x0 + w, clip_x1)
    if Y0 >= Y1 or X0 >= X1:
        return
    sy0 = Y0 - y0; sx0 = X0 - x0
    sy1 = sy0 + (Y1 - Y0); sx1 = sx0 + (X1 - X0)
    region_dst = dst[Y0:Y1, X0:X1, :]
    region_src = src[sy0:sy1, sx0:sx1, :]
    Sa = np.clip(region_src[..., 3:4], 0.0, 1.0)
    Da = np.clip(region_dst[..., 3:4], 0.0, 1.0)
    Sc = np.clip(region_src[..., :3], 0.0, 1.0)
    Dc = np.clip(region_dst[..., :3], 0.0, 1.0)
    out_a = Sa + Da * (1.0 - Sa)
    out_c = (Sc * Sa + Dc * Da * (1.0 - Sa)) / np.clip(out_a, 1e-8, 1.0)
    region_dst[..., :3] = np.clip(out_c, 0.0, 1.0)
    region_dst[..., 3:4] = np.clip(out_a, 0.0, 1.0)
    dst[Y0:Y1, X0:X1, :] = region_dst

def _rotate_bilinear(img: np.ndarray, angle_deg: float) -> np.ndarray:
    """
    Centered bilinear rotation using OpenCV for speed.
    img: (H, W, 4) float32 in [0..1]
    Returns rotated image with transparent outside source bounds.
    """
    h, w = img.shape[:2]
    if abs(angle_deg) < 1e-6:
        return img

    # Center of rotation
    cx = w * 0.5
    cy = h * 0.5

    # Get rotation matrix
    # Negate angle because OpenCV uses image coordinates (Y-down) which
    # inverts the rotation direction compared to math convention (Y-up)
    M = cv2.getRotationMatrix2D((cx, cy), -angle_deg, 1.0)

    # Use warpAffine with bilinear interpolation and transparent border
    out = cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0.0, 0.0, 0.0, 0.0)
    )
    return out.astype(np.float32)

def _pad_to_square(arr: np.ndarray, side: int) -> np.ndarray:
    """
    Center-pad RGBA tile to a square RGBA canvas of 'side' with transparent background.
    """
    h, w = arr.shape[0], arr.shape[1]
    out = np.zeros((side, side, 4), dtype=arr.dtype)
    y0 = (side - h) // 2
    x0 = (side - w) // 2
    out[y0:y0+h, x0:x0+w, :] = arr
    return out

class Grid(GenerationCacheMixin):
    """
    Replicate inputs into an nx × ny grid inside a configurable region.
    - High quality: renders at final tile resolution (no upscale pixelation).
    - Region control: position/size (in 0..1 of output).
    - Padding per cell to create spacing.
    - Uniform and non-uniform scale (can exceed 1.0 for overlaps).
    - Optional gradient coloring: tiles are tinted based on their position.
    - Multi-input support: inputs cycle through grid cells (in0, in1, in2, in0, in1, ...)
    Inputs:
      - in0, in1, ... inN (where N = num_inputs - 1)
    Params:
      - nx, ny: int >= 1
      - num_inputs: int >= 1 (how many input slots; max = nx * ny)
      - region_x, region_y, region_w, region_h: float in [0..1] (grid area within output)
      - pad_x, pad_y: float in [0..1] (fraction of cell dimension removed as padding)
      - scale (>=0), scale_x (>=0|None), scale_y (>=0|None)
      - eval_cell_square: bool (when deriving base dims; matters if render_at_tile_resolution=False)
      - render_at_tile_resolution: bool (default True)
      - use_gradient: bool (if True, apply gradient coloring to tiles)
      - gradient_mode: 'index' | 'column' | 'row' (how gradient position is calculated)
      - color_stops: tuple of (position, (R, G, B, A)) for gradient coloring
      - name
    """
    def __init__(self, nx: int = 2, ny: int = 2,
                 num_inputs: int = 1,
                 region_x: float = 0.0, region_y: float = 0.0,
                 region_w: float = 1.0, region_h: float = 1.0,
                 pad_x: float = 0.0, pad_y: float = 0.0,
                 scale: float = 1.0,
                 scale_x: float | None = None,
                 scale_y: float | None = None,
                 eval_cell_square: bool = True,
                 render_at_tile_resolution: bool = True,
                 use_gradient: bool = False,
                 gradient_mode: str = 'index',
                 color_stops: tuple = None,
                 name: str = 'Grid'):
        self.nx = int(nx); self.ny = int(ny)
        self.num_inputs = max(1, min(int(num_inputs), self.nx * self.ny))
        self.region_x = float(region_x); self.region_y = float(region_y)
        self.region_w = float(region_w); self.region_h = float(region_h)
        self.pad_x = float(pad_x); self.pad_y = float(pad_y)
        self.scale = float(scale)
        self.scale_x = None if scale_x is None else float(scale_x)
        self.scale_y = None if scale_y is None else float(scale_y)
        self.eval_cell_square = bool(eval_cell_square)
        self.render_at_tile_resolution = bool(render_at_tile_resolution)
        self.use_gradient = bool(use_gradient)
        self.gradient_mode = str(gradient_mode).lower()  # 'index', 'column', 'row'
        # Default gradient: white to black with full alpha
        if color_stops is None:
            self.color_stops = ((0.0, (1.0, 1.0, 1.0, 1.0)), (1.0, (0.0, 0.0, 0.0, 1.0)))
        else:
            self.color_stops = _validate_color_stops(color_stops)
        self.name = name
        self.inputs = {}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()
        self._rebuild_inputs()

    def _rebuild_inputs(self):
        """Rebuild inputs dict based on current num_inputs."""
        old_inputs = dict(self.inputs)
        self.inputs = {}
        for i in range(self.num_inputs):
            key = f'in{i}'
            self.inputs[key] = old_inputs.get(key)
        # Backwards compatibility: if old 'src' was connected, map to 'in0'
        if 'src' in old_inputs and old_inputs['src'] is not None and self.inputs.get('in0') is None:
            self.inputs['in0'] = old_inputs['src']

    def get_input_names(self) -> list:
        """Return list of current input names based on num_inputs."""
        return [f'in{i}' for i in range(self.num_inputs)]

    def connect(self, name, node, output_port='out'):
        # Support legacy 'src' name by mapping to 'in0'
        if name == 'src':
            name = 'in0'
        if name in self.inputs:
            self.inputs[name] = (node, output_port)
            if hasattr(node, 'dependents'):
                node.dependents.add(self)
        self.invalidate()

    def set_params(self, **kwargs):
        if 'color_stops' in kwargs:
            kwargs['color_stops'] = _validate_color_stops(kwargs['color_stops'])
        if 'gradient_mode' in kwargs:
            kwargs['gradient_mode'] = str(kwargs['gradient_mode']).lower()

        old_num_inputs = self.num_inputs
        old_nx, old_ny = self.nx, self.ny

        for k, v in kwargs.items():
            setattr(self, k, v)

        # Update num_inputs max based on new grid size
        max_inputs = self.nx * self.ny
        self.num_inputs = max(1, min(self.num_inputs, max_inputs))

        # Rebuild inputs if num_inputs or grid size changed
        if self.num_inputs != old_num_inputs or self.nx != old_nx or self.ny != old_ny:
            self._rebuild_inputs()

        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def evaluate(self, size: int = 512) -> np.ndarray:
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        nx = max(1, get_scalar_param_int(self, 'nx', self.nx))
        ny = max(1, get_scalar_param_int(self, 'ny', self.ny))
        num_inputs = max(1, min(self.num_inputs, nx * ny))

        # Check if any input is connected
        any_connected = any(self.inputs.get(f'in{i}') is not None for i in range(num_inputs))
        if not any_connected:
            return np.zeros((size, size, 4), dtype=np.float32)

        # Grid region in pixels (clamped to canvas)
        rx = int(np.clip(self.region_x, 0.0, 1.0) * size)
        ry = int(np.clip(self.region_y, 0.0, 1.0) * size)
        rw = int(np.clip(self.region_w, 0.0, 1.0) * size)
        rh = int(np.clip(self.region_h, 0.0, 1.0) * size)
        rx = max(0, min(rx, size)); ry = max(0, min(ry, size))
        rw = max(1, min(rw, size - rx)); rh = max(1, min(rh, size - ry))

        # Cell size in region (use float division; we'll place with rounding)
        cw_f = rw / float(nx)
        ch_f = rh / float(ny)

        # Padding (fraction of cell). 0.1 => 10% margins inside the cell.
        px = float(np.clip(self.pad_x, 0.0, 1.0))
        py = float(np.clip(self.pad_y, 0.0, 1.0))
        inner_w_f = max(0.0, cw_f * (1.0 - px))
        inner_h_f = max(0.0, ch_f * (1.0 - py))

        # Base "fit" dimensions before scale (square vs rectangular)
        if self.eval_cell_square:
            base_edge = int(max(1, round(min(inner_w_f, inner_h_f))))
            base_w = base_h = base_edge
        else:
            base_w = int(max(1, round(inner_w_f)))
            base_h = int(max(1, round(inner_h_f)))

        # Scales (>=0; allow >1)
        s_uni = float(np.clip(self.scale, 0.0, None))
        sx = float(np.clip(self.scale_x if self.scale_x is not None else s_uni, 0.0, None))
        sy = float(np.clip(self.scale_y if self.scale_y is not None else s_uni, 0.0, None))

        # Final tile dimensions
        tile_w = max(1, int(round(base_w * sx)))
        tile_h = max(1, int(round(base_h * sy)))

        # Prepare output
        out = np.zeros((size, size, 4), dtype=np.float32)

        # Pre-render all input tiles at the tile resolution
        eval_size = max(tile_h, tile_w)
        src_tiles = []
        for i in range(num_inputs):
            src_node = self.inputs.get(f'in{i}')
            if src_node is None:
                src_tiles.append(None)  # Empty slot
            else:
                if self.render_at_tile_resolution:
                    src_eval = _ensure_rgba(_safe_eval(src_node, eval_size), eval_size)
                    if src_eval.shape[0] != tile_h or src_eval.shape[1] != tile_w:
                        src_tile = _resize_bilinear(src_eval, tile_h, tile_w)
                    else:
                        src_tile = src_eval
                else:
                    # Legacy: render at base and resize (may upscale)
                    base_eval_size = max(base_h, base_w)
                    src_base = _ensure_rgba(_safe_eval(src_node, base_eval_size), base_eval_size)
                    if src_base.shape[0] != base_h or src_base.shape[1] != base_w:
                        src_base = _resize_bilinear(src_base, base_h, base_w)
                    src_tile = src_base if (tile_w == base_w and tile_h == base_h) else _resize_bilinear(src_base, tile_h, tile_w)
                src_tiles.append(src_tile)

        # Place tiles, centered inside each (padded) cell, within the region
        clip_y0, clip_y1 = 0, size
        clip_x0, clip_x1 = 0, size
        total_tiles = nx * ny
        tile_index = 0
        for r in range(ny):
            for c in range(nx):
                # Get the input for this cell (cycling through inputs)
                input_idx = tile_index % num_inputs
                src_tile = src_tiles[input_idx]

                # Skip if this input slot is not connected (empty)
                if src_tile is None:
                    tile_index += 1
                    continue

                # cell origin (float), then center the tile
                y_cell0_f = ry + r * ch_f
                x_cell0_f = rx + c * cw_f
                y_inner0_f = y_cell0_f + 0.5 * (ch_f - inner_h_f)
                x_inner0_f = x_cell0_f + 0.5 * (cw_f - inner_w_f)
                # center the tile in the inner rect
                y0 = int(round(y_inner0_f + (inner_h_f - tile_h) * 0.5))
                x0 = int(round(x_inner0_f + (inner_w_f - tile_w) * 0.5))

                # Apply gradient coloring if enabled
                if self.use_gradient and self.color_stops:
                    # Calculate gradient position based on mode
                    if self.gradient_mode == 'column':
                        t = c / max(1, nx - 1) if nx > 1 else 0.0
                    elif self.gradient_mode == 'row':
                        t = r / max(1, ny - 1) if ny > 1 else 0.0
                    else:  # 'index' (default)
                        t = tile_index / max(1, total_tiles - 1) if total_tiles > 1 else 0.0
                    color = _sample_gradient_color(t, self.color_stops)
                    tinted_tile = _tint_tile(src_tile, color)
                    _composite_over(out, tinted_tile, y0, x0, clip_y0, clip_y1, clip_x0, clip_x1)
                else:
                    _composite_over(out, src_tile, y0, x0, clip_y0, clip_y1, clip_x0, clip_x1)

                tile_index += 1

        result = out.astype(np.float32)
        self._store_cache(size, result)
        return result

class RadialGrid(GenerationCacheMixin):
    """
    Arrange inputs into a circular (or arc) pattern using square tiles,
    restoring the same rotation semantics as your working 'Circular'.
    - Multi-input support: inputs cycle through instances (in0, in1, in2, in0, in1, ...)

    Inputs:
      - in0, in1, ... inN (where N = num_inputs - 1)

    Params:
      - count               : int >= 1 (number of instances)
      - num_inputs          : int >= 1 (how many input slots; max = count)
      - cx, cy              : center (0..1 of canvas)
      - radius              : 0..1 of canvas (distance from center to instance centers)
      - start_angle_deg     : start angle in degrees (0 = +X axis, CCW positive)
      - sweep_deg           : arc sweep in degrees (360 for full circle)
      - angle_offset_deg    : extra phase shift applied to all instances
      - tile_edge_frac      : base square tile edge as a fraction of canvas (0..1), before non-uniform scales
      - scale               : uniform scale >= 0
      - scale_x, scale_y    : optional non-uniform scales >= 0 (defaults to 'scale' if None)
      - rotate_mode         : 'none' | 'radial' | 'tangent' (per-instance rotation)
      - item_rotation_deg   : per-instance extra rotation added after rotate_mode
      - pivot               : 'center' | 'top' | 'bottom' (rotation pivot point)
                              'center' = rotate around tile center (default)
                              'top' = rotate around tile's top edge
                              'bottom' = rotate around tile's bottom edge
      - render_at_tile_resolution : bool (default True, high quality)
      - use_gradient        : bool (if True, apply gradient coloring to tiles)
      - color_stops         : tuple of (position, (R, G, B, A)) for gradient coloring
      - name                : display name
    """
    def __init__(self,
                 count: int = 8,
                 num_inputs: int = 1,
                 cx: float = 0.5, cy: float = 0.5,
                 radius: float = 0.35,
                 start_angle_deg: float = 0.0,
                 sweep_deg: float = 360.0,
                 angle_offset_deg: float = 0.0,
                 tile_edge_frac: float = 0.15,
                 scale: float = 1.0,
                 scale_x: float | None = None,
                 scale_y: float | None = None,
                 rotate_mode: str = 'none',
                 item_rotation_deg: float = 0.0,
                 pivot: str = 'center',
                 render_at_tile_resolution: bool = True,
                 use_gradient: bool = False,
                 color_stops: tuple = None,
                 name: str = 'RadialGrid'):
        self.count = int(count)
        self.num_inputs = max(1, min(int(num_inputs), self.count))
        self.cx = float(cx); self.cy = float(cy)
        self.radius = float(radius)
        self.start_angle_deg = float(start_angle_deg)
        self.sweep_deg = float(sweep_deg)
        self.angle_offset_deg = float(angle_offset_deg)

        self.tile_edge_frac = float(tile_edge_frac)
        self.scale = float(scale)
        self.scale_x = float(scale_x) if (scale_x is not None) else float(self.scale)
        self.scale_y = float(scale_y) if (scale_y is not None) else float(self.scale)

        # Normalize rotate_mode consistently with Circular
        self.rotate_mode = str(rotate_mode).lower()
        self.item_rotation_deg = float(item_rotation_deg)
        self.pivot = str(pivot).lower()  # 'center', 'top', 'bottom'
        self.render_at_tile_resolution = bool(render_at_tile_resolution)

        # Gradient coloring
        self.use_gradient = bool(use_gradient)
        if color_stops is None:
            self.color_stops = ((0.0, (1.0, 1.0, 1.0, 1.0)), (1.0, (0.0, 0.0, 0.0, 1.0)))
        else:
            self.color_stops = _validate_color_stops(color_stops)

        self.name = name
        self.inputs = {}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()
        self._rebuild_inputs()

    def _rebuild_inputs(self):
        """Rebuild inputs dict based on current num_inputs."""
        old_inputs = dict(self.inputs)
        self.inputs = {}
        for i in range(self.num_inputs):
            key = f'in{i}'
            self.inputs[key] = old_inputs.get(key)
        # Backwards compatibility: if old 'src' was connected, map to 'in0'
        if 'src' in old_inputs and old_inputs['src'] is not None and self.inputs.get('in0') is None:
            self.inputs['in0'] = old_inputs['src']

    def get_input_names(self) -> list:
        """Return list of current input names based on num_inputs."""
        return [f'in{i}' for i in range(self.num_inputs)]

    def connect(self, name, node, output_port='out'):
        # Support legacy 'src' name by mapping to 'in0'
        if name == 'src':
            name = 'in0'
        if name in self.inputs:
            self.inputs[name] = (node, output_port)
            if hasattr(node, 'dependents'):
                node.dependents.add(self)
        self.invalidate()

    def set_params(self, **kwargs):
        if 'rotate_mode' in kwargs:
            self.rotate_mode = str(kwargs.pop('rotate_mode')).lower()
        if 'pivot' in kwargs:
            self.pivot = str(kwargs.pop('pivot')).lower()
        if 'color_stops' in kwargs:
            kwargs['color_stops'] = _validate_color_stops(kwargs['color_stops'])

        old_num_inputs = self.num_inputs
        old_count = self.count

        for k, v in kwargs.items():
            setattr(self, k, v)

        # Update num_inputs max based on new count
        self.num_inputs = max(1, min(self.num_inputs, self.count))

        # Rebuild inputs if num_inputs or count changed
        if self.num_inputs != old_num_inputs or self.count != old_count:
            self._rebuild_inputs()

        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def _instance_angle_deg(self, i: int, n: int) -> float:
        if n <= 1:
            return self.start_angle_deg + self.angle_offset_deg
        # identical to Circular: distribute over sweep; for full circle use count, else count-1
        full_circle = abs(self.sweep_deg) >= 360.0 - 1e-6
        t = float(i) / float(n) if full_circle else float(i) / float(n - 1)
        return self.start_angle_deg + t * self.sweep_deg + self.angle_offset_deg

    def evaluate(self, size: int = 512) -> np.ndarray:
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        n = max(1, get_scalar_param_int(self, 'count', self.count))
        num_inputs = max(1, min(self.num_inputs, n))

        # Check if any input is connected
        any_connected = any(self.inputs.get(f'in{i}') is not None for i in range(num_inputs))
        if not any_connected:
            return np.zeros((size, size, 4), dtype=np.float32)

        # Canvas-space center and radius
        cx_px = int(round(np.clip(self.cx, 0.0, 1.0) * size))
        cy_px = int(round(np.clip(self.cy, 0.0, 1.0) * size))
        radius_px = float(np.clip(self.radius, 0.0, 1.0) * size)

        # Base tile edge in pixels, then apply scales (no fitting)
        base_edge = max(1, int(round(np.clip(self.tile_edge_frac, 0.0, 1.0) * size)))
        s = max(0.0, self.scale)
        sx = s * max(0.0, self.scale_x)
        sy = s * max(0.0, self.scale_y)
        tile_w = max(1, int(round(base_edge * sx)))
        tile_h = max(1, int(round(base_edge * sy)))

        # Pre-render all input tiles at the tile resolution
        eval_size = max(tile_h, tile_w)
        src_tiles = []
        for i in range(num_inputs):
            src_node = self.inputs.get(f'in{i}')
            if src_node is None:
                src_tiles.append(None)  # Empty slot
            else:
                if self.render_at_tile_resolution:
                    src_eval = _ensure_rgba(_safe_eval(src_node, eval_size), eval_size)
                    src_tile = src_eval if (src_eval.shape[0] == tile_h and src_eval.shape[1] == tile_w) \
                        else _resize_bilinear(src_eval, tile_h, tile_w)
                else:
                    src_base = _ensure_rgba(_safe_eval(src_node, base_edge), base_edge)
                    src_tile = src_base if (tile_w == base_edge and tile_h == base_edge) \
                        else _resize_bilinear(src_base, tile_h, tile_w)
                src_tiles.append(src_tile)

        out = np.zeros((size, size, 4), dtype=np.float32)
        clip_y0, clip_y1 = 0, size
        clip_x0, clip_x1 = 0, size

        # Place each instance
        for i in range(n):
            # Get the input for this instance (cycling through inputs)
            input_idx = i % num_inputs
            src_tile_base = src_tiles[input_idx]

            # Skip if this input slot is not connected (empty)
            if src_tile_base is None:
                continue

            ang_deg = self._instance_angle_deg(i, n)
            ang_rad = np.deg2rad(ang_deg)

            x_center = cx_px + int(round(radius_px * np.cos(ang_rad)))
            y_center = cy_px + int(round(radius_px * np.sin(ang_rad)))

            # Apply gradient coloring if enabled
            if self.use_gradient and self.color_stops:
                t = i / max(1, n - 1) if n > 1 else 0.0
                color = _sample_gradient_color(t, self.color_stops)
                current_tile_base = _tint_tile(src_tile_base, color)
            else:
                current_tile_base = src_tile_base

            # Rotation — match Circular exactly:
            # radial  → ang_deg + 90 + extra
            # tangent → ang_deg + extra
            # none    → extra
            tile = current_tile_base
            inst_angle = 0.0
            if self.rotate_mode != 'none' or abs(self.item_rotation_deg) > 1e-6:
                extra = float(self.item_rotation_deg)
                if self.rotate_mode == 'radial':
                    inst_angle = ang_deg + 90.0 + extra
                elif self.rotate_mode == 'tangent':
                    inst_angle = ang_deg + extra
                else:
                    inst_angle = extra

                rot_bbox = int(math.ceil(math.hypot(tile_w, tile_h)))  # diagonal
                rot_bbox = max(rot_bbox, 1)

                # Optional safety margin (e.g. +8px) to avoid rounding edge clipping
                safety = 8
                rot_side = rot_bbox + safety

                padded = _pad_to_square(current_tile_base, rot_side)
                tile = _rotate_bilinear(padded, inst_angle)

            # Calculate pivot offset for placement
            # Pivot point in original tile coordinates (relative to tile center)
            pivot_x, pivot_y = 0.0, 0.0
            if self.pivot == 'top':
                pivot_y = -tile_h * 0.5  # Top is negative Y (up)
            elif self.pivot == 'bottom':
                pivot_y = tile_h * 0.5   # Bottom is positive Y (down)

            # After rotation, the pivot point moves
            # Rotation transforms: x' = x*cos(θ) - y*sin(θ), y' = x*sin(θ) + y*cos(θ)
            rot_rad = np.deg2rad(inst_angle)
            rotated_pivot_x = pivot_x * np.cos(rot_rad) - pivot_y * np.sin(rot_rad)
            rotated_pivot_y = pivot_x * np.sin(rot_rad) + pivot_y * np.cos(rot_rad)

            # Place tile so the pivot point ends up at (x_center, y_center)
            # Tile center should be at: (x_center - rotated_pivot_x, y_center - rotated_pivot_y)
            tile_center_x = x_center - rotated_pivot_x
            tile_center_y = y_center - rotated_pivot_y

            x0 = int(round(tile_center_x - tile.shape[1] * 0.5))
            y0 = int(round(tile_center_y - tile.shape[0] * 0.5))
            _composite_over(out, tile, y0, x0, clip_y0, clip_y1, clip_x0, clip_x1)

        result = out.astype(np.float32)
        self._store_cache(size, result)
        return result

class Mirror(GenerationCacheMixin):
    """
    Mirror the input image across the center X or Y axis.

    Inputs:
      - src : upstream node producing RGBA in [0..1]

    Params:
      - axis : 'x' or 'y'
        'x' → mirror across the vertical center line (X-axis symmetry: left/right)
        'y' → mirror across the horizontal center line (Y-axis symmetry: top/bottom)
      - side : which half to keep as the source and copy to the other:
        For axis='x': 'keep_left' or 'keep_right'
        For axis='y': 'keep_top'  or 'keep_bottom'
      - copy_center : bool; if size is odd, whether to copy the center column/row from the kept half (default True)
      - name : display name
    """
    def __init__(self, axis: str = 'x', side: str = 'keep_left', copy_center: bool = True, name: str = 'Mirror'):
        self.axis = str(axis).lower()         # 'x' or 'y'
        self.side = str(side).lower()
        self.copy_center = bool(copy_center)
        self.name = name
        self.inputs = {'src': None}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()

    def connect(self, name, node, output_port='out'):
        self.inputs[name] = (node, output_port)
        self.invalidate()

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # normalize
        if hasattr(self, 'axis'):
            self.axis = str(self.axis).lower()
        if hasattr(self, 'side'):
            self.side = str(self.side).lower()
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def evaluate(self, size: int = 512) -> np.ndarray:
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        src_node = self.inputs.get('src')
        if src_node is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        img = _ensure_rgba(_safe_eval(src_node, size), size)
        h, w = img.shape[:2]
        out = img.copy()

        axis = 'x' if self.axis not in ('x', 'y') else self.axis

        if axis == 'x':
            # Mirror across vertical center line (affects left/right)
            mid = w // 2
            odd = (w % 2) == 1

            if self.side == 'keep_right':
                # Copy right half to left (mirror horizontally)
                # right half indices: mid .. w-1
                right = img[:, mid + (1 if odd else 0):, :]
                right_flipped = np.flip(right, axis=1)
                out[:, :mid, :] = right_flipped[:, :mid, :]
                if odd and self.copy_center:
                    # copy the center column from right side's nearest into mid
                    out[:, mid:mid+1, :] = img[:, mid:mid+1, :]
            else:
                # Default: keep_left (copy left half to right)
                left = img[:, :mid, :]
                left_flipped = np.flip(left, axis=1)
                if odd and self.copy_center:
                    out[:, mid:mid+1, :] = img[:, mid:mid+1, :]
                    out[:, mid+1:, :] = left_flipped[:, :w - (mid + 1), :]
                else:
                    out[:, mid:, :] = left_flipped[:, :w - mid, :]

        else:  # axis == 'y'
            # Mirror across horizontal center line (affects top/bottom)
            mid = h // 2
            odd = (h % 2) == 1

            if self.side == 'keep_bottom':
                bottom = img[mid + (1 if odd else 0):, :, :]
                bottom_flipped = np.flip(bottom, axis=0)
                out[:mid, :, :] = bottom_flipped[:mid, :, :]
                if odd and self.copy_center:
                    out[mid:mid+1, :, :] = img[mid:mid+1, :, :]
            else:
                # Default: keep_top (copy top half to bottom)
                top = img[:mid, :, :]
                top_flipped = np.flip(top, axis=0)
                if odd and self.copy_center:
                    out[mid:mid+1, :, :] = img[mid:mid+1, :, :]
                    out[mid+1:, :, :] = top_flipped[:h - (mid + 1), :, :]
                else:
                    out[mid:, :, :] = top_flipped[:h - mid, :, :]

        result = np.clip(out, 0.0, 1.0).astype(np.float32)
        self._store_cache(size, result)
        return result


class Atlas(GenerationCacheMixin):
    """
    Pack multiple input images into a single atlas texture.

    Takes a square number of inputs (4, 9, 16, 25) and arranges them in a grid.
    Each input is resized to fit its cell. Cells are filled left-to-right,
    top-to-bottom starting from the top-left corner.

    Inputs:
      - in0, in1, in2, ... : upstream nodes producing RGBA in [0..1]

    Params:
      - cells : number of cells (must be a perfect square: 4, 9, 16, 25)
      - name : display name
    """

    # Supported cell counts (perfect squares)
    VALID_CELLS = (4, 9, 16, 25, 36, 49, 64)

    def __init__(self, cells: int = 4, name: str = 'Atlas'):
        self.cells = int(cells) if int(cells) in self.VALID_CELLS else 4
        self.name = name
        self._dirty = True
        self.dependents: set = set()
        self._init_generation_cache()

        # Initialize inputs dict with all possible input slots
        self.inputs = {}
        self._rebuild_inputs()

    def _rebuild_inputs(self):
        """Rebuild inputs dict based on current cells count."""
        # Keep existing connections where possible
        old_inputs = dict(self.inputs)
        self.inputs = {}
        for i in range(self.cells):
            key = f'in{i}'
            self.inputs[key] = old_inputs.get(key)

    def connect(self, name, node, output_port='out'):
        if name in self.inputs:
            self.inputs[name] = (node, output_port)
            if hasattr(node, 'dependents'):
                node.dependents.add(self)
        self.invalidate()

    def set_params(self, **kwargs):
        old_cells = self.cells
        for k, v in kwargs.items():
            if k == 'cells':
                v = int(v) if int(v) in self.VALID_CELLS else self.cells
            setattr(self, k, v)

        # Rebuild inputs if cells changed
        if self.cells != old_cells:
            self._rebuild_inputs()

        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def get_input_names(self) -> list:
        """Return list of current input names based on cells count."""
        return [f'in{i}' for i in range(self.cells)]

    def evaluate(self, size: int = 512) -> np.ndarray:
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        # Calculate grid dimensions
        grid_size = int(math.sqrt(self.cells))
        cell_size = size // grid_size

        # Create output image (transparent background)
        out = np.zeros((size, size, 4), dtype=np.float32)

        # Process each input
        for i in range(self.cells):
            key = f'in{i}'
            conn = self.inputs.get(key)

            if conn is None:
                continue

            # Evaluate input at cell size for efficiency
            src_img = _safe_eval(conn, cell_size)
            if src_img is None:
                continue

            src_img = _ensure_rgba(src_img, cell_size)

            # Resize to cell size if needed
            if src_img.shape[0] != cell_size or src_img.shape[1] != cell_size:
                src_img = _resize_bilinear(src_img, cell_size, cell_size)

            # Calculate position in grid (left-to-right, top-to-bottom)
            col = i % grid_size
            row = i // grid_size
            x0 = col * cell_size
            y0 = row * cell_size

            # Place in output
            out[y0:y0 + cell_size, x0:x0 + cell_size, :] = src_img

        result = np.clip(out, 0.0, 1.0).astype(np.float32)
        self._store_cache(size, result)
        return result
