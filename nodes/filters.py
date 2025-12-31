
# pynodes/nodes/filters.py
import numpy as np
import math
import cv2

from texture_pig.nodes.utils import channel_value_with_alpha, extract_mask
from texture_pig.nodes.core import GenerationCacheMixin


def _eval_connection(connection, size):
    """
    Evaluate a connection, handling both (node, output_port) tuples and direct node refs.
    Returns the evaluated image array, or None if connection is None.
    """
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


class GaussianBlur(GenerationCacheMixin):
    """
    Gaussian blur node using OpenCV for speed.

    Inputs:
      - 'image': upstream node that itself implements evaluate(size) → (H, W, 4) float[0..1]

    Params:
      - sigma (float >= 0): blur standard deviation in *pixels*
      - alpha_only (bool): if True, blur only alpha channel and keep RGB untouched
    """
    def __init__(self, sigma=2.0, alpha_only=False, name='GaussianBlur'):
        self.sigma = float(sigma)
        self.alpha_only = bool(alpha_only)
        self.name = name
        self.inputs = {'image': None}
        self._dirty = True
        self.dependents = set()
        self._init_generation_cache()

    # --- plumbing consistent with your nodes ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def invalidate_cascade(self):
        self._dirty = True

    def connect(self, in_name, node, output_port='out'):
        """Connect upstream node to an input key (e.g., 'image')."""
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    @staticmethod
    def _cv2_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
        """Apply Gaussian blur using OpenCV. Preserves input shape."""
        # Kernel size must be odd; use 3*sigma rule
        ksize = max(1, int(math.ceil(3.0 * sigma))) * 2 + 1
        # cv2.GaussianBlur works directly on float32 arrays
        original_shape = arr.shape
        result = cv2.GaussianBlur(arr, (ksize, ksize), sigma, borderType=cv2.BORDER_REFLECT)
        # cv2.GaussianBlur drops trailing dimension of 1, restore it if needed
        if result.shape != original_shape:
            result = result.reshape(original_shape)
        return result

    # --- Graph protocol entry point ---
    def evaluate(self, size=512):
        """
        Return RGBA float image (H, W, 4) in [0..1].
        Uses upstream_node.evaluate(size) to stay compatible with Graph.output.
        """
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        img = _eval_connection(self.inputs.get('image'), size)

        if img is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)

        if self.sigma <= 0.0:
            result = np.clip(img, 0.0, 1.0)
            self._store_cache(size, result)
            return result

        if self.alpha_only:
            # Blur A only, keep RGB unchanged -> great for soft masks
            a = img[..., 3:4]
            a_blur = self._cv2_blur(a, self.sigma)
            out = img.copy()
            out[..., 3:4] = a_blur
            out = np.clip(out, 0.0, 1.0)
            result = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)
            self._store_cache(size, result)
            return result

        # ---- Premultiplied blur (fixes dark halos) ----
        rgb = img[..., :3]
        a = np.clip(img[..., 3:4], 0.0, 1.0)  # clamp alpha defensively
        rgb_pm = rgb * a

        # Use OpenCV GaussianBlur for speed
        rgb_pm_b = self._cv2_blur(rgb_pm, self.sigma)
        a_b = self._cv2_blur(a, self.sigma)

        # Safe un-premultiply: only divide where a_b > eps
        eps = 1e-8
        rgb_unpm = np.zeros_like(rgb_pm_b, dtype=np.float32)
        np.divide(rgb_pm_b, np.clip(a_b, eps, None), out=rgb_unpm, where=(a_b > eps))

        out = np.concatenate([np.clip(rgb_unpm, 0.0, 1.0), np.clip(a_b, 0.0, 1.0)], axis=-1)
        result = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)
        self._store_cache(size, result)
        return result

class Transform(GenerationCacheMixin):
    """
    Affine transform node: scale, rotate, translate the upstream RGBA image.
    Supports per-pixel parameter falloff so black=0 → no transform, white=1 → full transform.

    Uses OpenCV warpAffine for uniform transforms (no falloff) and cv2.remap for per-pixel transforms.

    Inputs:
      - 'image'   : upstream node producing (H, W, 4) float in [0..1]
      - 'falloff' : optional grayscale or RGBA image; if RGBA, a channel or luma is extracted

    Params:
      - tx, ty            : translation, normalized to width/height (e.g. 0.1 moves 10% of size)
      - scale             : overall uniform scale (1.0 = no scale)
      - scale_x, scale_y  : per-axis scaling factors (1.0 = no scale)
      - rotation_deg      : rotation angle in degrees
      - pivot_cx, pivot_cy: pivot point (normalized [0..1]), default center
      - falloff_channel   : 'luma' (default), 'a', 'r', 'g', 'b' — used only if falloff is RGBA

    Protocol: implements evaluate(size) to match Graph.output(...).
    """
    def __init__(self,
                 tx=0.0, ty=0.0,
                 scale=1.0,
                 scale_x=1.0, scale_y=1.0,
                 rotation_deg=0.0,
                 pivot_cx=0.5, pivot_cy=0.5,
                 falloff_channel='luma',
                 name='Transform'):
        self.tx = float(tx)
        self.ty = float(ty)
        self.scale = float(scale)              # overall uniform scale
        self.scale_x = float(scale_x)
        self.scale_y = float(scale_y)
        self.rotation_deg = float(rotation_deg)
        self.pivot_cx = float(pivot_cx)
        self.pivot_cy = float(pivot_cy)
        self.falloff_channel = str(falloff_channel).lower()
        self.name = name
        self.inputs = {'image': None, 'falloff': None}
        self._dirty = True
        self.dependents: set = set()
        self._init_generation_cache()

    # plumbing consistent with your framework
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def invalidate_cascade(self):
        self._dirty = True

    # ---- core helpers ----
    @staticmethod
    def _safe_eval(connection, size):
        """Evaluate a connection, handling tuple format (node, port)."""
        return _eval_connection(connection, size)

    @staticmethod
    def _ensure_rgba(img, size):
        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)
        return np.clip(img, 0.0, 1.0)

    @staticmethod
    def _luma(rgb):
        return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]).astype(np.float32)

    def _extract_falloff(self, img: np.ndarray, size: int) -> np.ndarray:
        H = W = size
        img = np.asarray(img, dtype=np.float32)

        if img.ndim == 2:                      # (H,W)
            return np.clip(img[..., None], 0.0, 1.0)
        if img.ndim == 3 and img.shape[-1] == 1:  # (H,W,1)
            return np.clip(img, 0.0, 1.0)
        if img.ndim == 3 and img.shape[-1] == 3:  # (H,W,3)
            F = self._luma(img)[..., None]
            return np.clip(F, 0.0, 1.0)
        if img.ndim == 3 and img.shape[-1] == 4:  # (H,W,4)
            # Transparent pixels are black:
            F = channel_value_with_alpha(img, self.falloff_channel)[..., None]
            return np.clip(F, 0.0, 1.0)

        return np.zeros((H, W, 1), dtype=np.float32)

    def _uniform_transform(self, img: np.ndarray, size: int) -> np.ndarray:
        """Fast path: uniform affine transform using cv2.warpAffine."""
        H = W = size

        # Pivot in pixels
        pivot_x = float(self.pivot_cx) * W
        pivot_y = float(self.pivot_cy) * H

        # Translation in pixels
        tx_px = float(self.tx) * W
        ty_px = float(self.ty) * H

        # Combined scale
        sx = float(self.scale) * float(self.scale_x)
        sy = float(self.scale) * float(self.scale_y)

        # Rotation in radians
        theta = np.deg2rad(float(self.rotation_deg))
        cos_t = np.cos(theta)
        sin_t = np.sin(theta)

        # For warpAffine, we need the inverse transform (dst to src mapping)
        # Forward: p' = R @ S @ (p - pivot) + pivot + t
        # Inverse: p = S^-1 @ R^T @ (p' - pivot - t) + pivot
        # where R^T = [[cos, sin], [-sin, cos]] (transpose of rotation matrix)

        # Inverse scale
        sx_inv = 1.0 / sx if sx != 0 else 1e8
        sy_inv = 1.0 / sy if sy != 0 else 1e8

        # Combined inverse: S^-1 @ R^T
        # [[1/sx, 0], [0, 1/sy]] @ [[cos, sin], [-sin, cos]]
        # = [[cos/sx, sin/sx], [-sin/sy, cos/sy]]
        a00 = sx_inv * cos_t
        a01 = sx_inv * sin_t
        a10 = -sy_inv * sin_t
        a11 = sy_inv * cos_t

        # The full inverse transform for a point (x', y'):
        # dx = x' - pivot_x - tx_px
        # dy = y' - pivot_y - ty_px
        # x = a00*dx + a01*dy + pivot_x
        # y = a10*dx + a11*dy + pivot_y

        # Expand: x = a00*x' + a01*y' + (pivot_x - a00*(pivot_x + tx_px) - a01*(pivot_y + ty_px))
        tx_final = pivot_x - a00 * (pivot_x + tx_px) - a01 * (pivot_y + ty_px)
        ty_final = pivot_y - a10 * (pivot_x + tx_px) - a11 * (pivot_y + ty_px)

        # Build 2x3 affine matrix for cv2.warpAffine
        M = np.array([[a00, a01, tx_final],
                      [a10, a11, ty_final]], dtype=np.float32)

        # Apply transform with bilinear interpolation and transparent border
        out = cv2.warpAffine(
            img, M, (W, H),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0.0, 0.0, 0.0, 0.0)
        )
        return out.astype(np.float32)

    def _perpixel_transform(self, img: np.ndarray, size: int, F: np.ndarray) -> np.ndarray:
        """Per-pixel affine transform using cv2.remap for speed."""
        H = W = size

        # Destination grid
        xd = (np.arange(W, dtype=np.float32)[None, :]).repeat(H, axis=0)
        yd = (np.arange(H, dtype=np.float32)[:, None]).repeat(W, axis=1)

        # Pivot in px
        pivot_x = np.float32(self.pivot_cx) * W
        pivot_y = np.float32(self.pivot_cy) * H

        # Effective per-pixel parameters
        tx_px = np.float32(self.tx) * W * F
        ty_px = np.float32(self.ty) * H * F

        # Uniform scale multiplies X/Y scales
        base_scale_x = np.float32(self.scale) * np.float32(self.scale_x)
        base_scale_y = np.float32(self.scale) * np.float32(self.scale_y)

        sx_eff = 1.0 + F * (base_scale_x - 1.0)  # lerp identity -> base scale
        sy_eff = 1.0 + F * (base_scale_y - 1.0)

        th_eff = np.deg2rad(np.float32(self.rotation_deg)) * F
        c = np.cos(th_eff).astype(np.float32)
        s = np.sin(th_eff).astype(np.float32)

        sx_inv = np.where(sx_eff != 0.0, 1.0 / sx_eff, np.float32(1e-8))
        sy_inv = np.where(sy_eff != 0.0, 1.0 / sy_eff, np.float32(1e-8))

        # Sinv @ Rinv per pixel
        a00 = (sx_inv * c)[..., 0]
        a01 = (sx_inv * s)[..., 0]
        a10 = (-sy_inv * s)[..., 0]
        a11 = (sy_inv * c)[..., 0]

        dx = xd - tx_px[..., 0] - pivot_x
        dy = yd - ty_px[..., 0] - pivot_y
        map_x = (a00 * dx + a01 * dy + pivot_x).astype(np.float32)
        map_y = (a10 * dx + a11 * dy + pivot_y).astype(np.float32)

        # Use cv2.remap for fast per-pixel coordinate mapping
        out = cv2.remap(
            img, map_x, map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0.0, 0.0, 0.0, 0.0)
        )
        return out.astype(np.float32)

    def evaluate(self, size=512):
        # Check cache first
        cached = self._check_cache(size)
        if cached is not None:
            return cached

        upstream = self.inputs.get('image')
        H = W = int(size)

        if upstream is None:
            return np.zeros((H, W, 4), dtype=np.float32)

        img = self._safe_eval(upstream, size)
        if img is None:
            return np.zeros((H, W, 4), dtype=np.float32)
        img = self._ensure_rgba(img, size)

        # Get falloff (defaults to ones = full transform everywhere)
        falloff_node = self.inputs.get('falloff')
        if falloff_node is not None:
            f_img = self._safe_eval(falloff_node, size)
            F = self._extract_falloff(f_img if f_img is not None else np.zeros((H, W, 1), dtype=np.float32), size)
        else:
            F = np.ones((H, W, 1), dtype=np.float32)

        # Use cv2.remap for fast per-pixel coordinate mapping
        out = self._perpixel_transform(img, size, F)

        result = np.clip(out, 0.0, 1.0)
        self._store_cache(size, result)
        return result

class Invert(GenerationCacheMixin):
    """
    Invert (one-minus) node.
    Inputs:
      - 'image': upstream RGBA float [0..1]
      - 'mask' : optional RGBA float [0..1]; controls where invert applies
    Params:
      - invert_rgb   : bool (default True)
      - invert_alpha : bool (default False)
      - opacity      : float 0..1 (default 1.0)
      - mask_channel : 'a'|'luma'|'r'|'g'|'b' (default 'a')
    Protocol:
      - implements evaluate(size) for Graph.output(...).
    """
    def __init__(self, invert_rgb=True, invert_alpha=False, opacity=1.0,
                 mask_channel='a', name='Invert'):
        self.invert_rgb = bool(invert_rgb)
        self.invert_alpha = bool(invert_alpha)
        self.opacity = float(opacity)
        self.mask_channel = str(mask_channel)
        self.name = name
        self.inputs = {'image': None, 'mask': None}
        self._dirty = True
        self.dependents: set = set()
        self._init_generation_cache()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def invalidate_cascade(self):
        self._dirty = True

    # --- helpers ---
    @staticmethod
    def _ensure_rgba(img, size):
        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)
        return np.clip(img, 0.0, 1.0)

    @staticmethod
    def _luma(rgb):
        return (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]).astype(np.float32)

    # --- main evaluation ---
    def evaluate(self, size=512):
        # Filter classes don't cache - upstream generators cache instead
        H = W = int(size)

        img = _eval_connection(self.inputs.get('image'), size)
        if img is None:
            return np.zeros((H, W, 4), dtype=np.float32)
        img = self._ensure_rgba(img, H)

        # Base opacity
        op = np.float32(np.clip(self.opacity, 0.0, 1.0))

        # Optional mask modulation
        mimg = _eval_connection(self.inputs.get('mask'), size)
        if mimg is not None:
            mimg = self._ensure_rgba(mimg, H)
            mask = extract_mask(mimg)  # (H,W,1)
        else:
            mask = None

        rgb = img[...,:3]
        a   = img[..., 3:4]
        out_rgb = rgb.copy()
        out_a   = a.copy()

        # Effective opacity per pixel (modulated by mask if present)
        if mask is not None:
            eff = op * mask  # (H,W,1)
        else:
            eff = op         # scalar

        # Invert RGB
        if self.invert_rgb:
            inv_rgb = 1.0 - rgb
            out_rgb = rgb*(1.0 - eff) + inv_rgb*eff

        # Invert alpha
        if self.invert_alpha:
            inv_a = 1.0 - a
            out_a = a*(1.0 - eff) + inv_a*eff

        out = np.concatenate([np.clip(out_rgb, 0.0, 1.0), np.clip(out_a, 0.0, 1.0)], axis=-1)
        return np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)


class Levels(GenerationCacheMixin):
    """
    Levels adjustment node (Photoshop-style) for RGBA images.

    Inputs:
      - 'image': upstream RGBA float [0..1]
      - 'mask' : optional RGBA float [0..1]; modulates the effect

    Params (RGB/master):
      - in_black   : float [0..1] (default 0.0)
      - in_white   : float [0..1] (default 1.0)
      - gamma      : float > 0   (default 1.0)
      - out_black  : float [0..1] (default 0.0)
      - out_white  : float [0..1] (default 1.0)

    Params (Alpha):
      - a_in_black  : float [0..1] (default 0.0)
      - a_in_white  : float [0..1] (default 1.0)
      - a_gamma     : float > 0   (default 1.0)
      - a_out_black : float [0..1] (default 0.0)
      - a_out_white : float [0..1] (default 1.0)

    Blend & Mask:
      - opacity      : float [0..1] (default 1.0)
      - mask_channel : 'a'|'luma'|'r'|'g'|'b' (default 'a')

    Protocol:
      - implements evaluate(size) for Graph.output(...).
    """
    def __init__(self,
                 in_black=0.0, in_white=1.0, gamma=1.0, out_black=0.0, out_white=1.0,
                 a_in_black=0.0, a_in_white=1.0, a_gamma=1.0, a_out_black=0.0, a_out_white=1.0,
                 opacity=1.0, mask_channel='a', name='Levels'):
        # Parameters
        self.in_black    = float(in_black)
        self.in_white    = float(in_white)
        self.gamma       = float(gamma)
        self.out_black   = float(out_black)
        self.out_white   = float(out_white)

        self.a_in_black  = float(a_in_black)
        self.a_in_white  = float(a_in_white)
        self.a_gamma     = float(a_gamma)
        self.a_out_black = float(a_out_black)
        self.a_out_white = float(a_out_white)

        self.opacity      = float(opacity)
        self.mask_channel = str(mask_channel)

        self.name = name
        self.inputs = {'image': None, 'mask': None}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        if in_name not in self.inputs:
            raise ValueError(f'Unknown input: {in_name}')
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def invalidate_cascade(self):
        self._dirty = True

    # --- helpers ---
    @staticmethod
    def _ensure_rgba(img, size):
        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)
        return np.clip(img, 0.0, 1.0)

    @staticmethod
    def _luma(rgb):
        # Rec.709 luma
        return (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]).astype(np.float32)

    @staticmethod
    def _levels_map(x, in_b, in_w, gamma, out_b, out_w):
        """Apply levels mapping to array x in [0..1]. Works for shape (...,C) or (...,1)."""
        # Avoid division by zero or invalid gamma
        denom = np.maximum(in_w - in_b, 1e-6)
        t = np.clip((x - in_b) / denom, 0.0, 1.0)
        g = np.maximum(gamma, 1e-6)
        t = np.power(t, 1.0 / g)
        return out_b + t * (out_w - out_b)

    # --- main evaluation ---
    def evaluate(self, size=512):
        # Filter classes don't cache - upstream generators cache instead
        H = W = int(size)

        img = _eval_connection(self.inputs.get('image'), size)
        if img is None:
            return np.zeros((H, W, 4), dtype=np.float32)
        img = self._ensure_rgba(img, H)

        # Optional mask
        mimg = _eval_connection(self.inputs.get('mask'), size)
        if mimg is not None:
            mimg = self._ensure_rgba(mimg, H)
            mask = extract_mask(mimg)  # (H,W,1)
        else:
            mask = None

        # Split channels
        rgb = img[...,:3]
        a   = img[..., 3:4]

        # Apply RGB levels
        adj_rgb = self._levels_map(
            rgb,
            float(self.in_black), float(self.in_white),
            float(self.gamma),
            float(self.out_black), float(self.out_white)
        )

        # Apply Alpha levels
        adj_a = self._levels_map(
            a,
            float(self.a_in_black), float(self.a_in_white),
            float(self.a_gamma),
            float(self.a_out_black), float(self.a_out_white)
        )

        adjusted = np.concatenate([adj_rgb, adj_a], axis=-1)

        # Opacity and mask modulation
        op = np.float32(np.clip(self.opacity, 0.0, 1.0))
        if mask is not None:
            eff = op * mask  # (H,W,1)
        else:
            eff = op         # scalar

        # Blend adjusted with original
        out = img + (adjusted - img) * eff
        out = np.clip(out, 0.0, 1.0)
        return np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)

class Combine(GenerationCacheMixin):
    """
    Combine node: compose RGBA from separate R, G, B, A inputs.

    Inputs:
      - 'r' : upstream RGBA float [0..1] used to derive R channel (optional)
      - 'g' : upstream RGBA float [0..1] used to derive G channel (optional)
      - 'b' : upstream RGBA float [0..1] used to derive B channel (optional)
      - 'a' : upstream RGBA float [0..1] used to derive A channel (optional)

    Params:
      - r_src, g_src, b_src, a_src : 'luma'|'r'|'g'|'b'|'a' (which channel to extract)
        defaults: r/g/b -> 'luma', a -> 'a'
      - use_source_alpha : bool (default True). If True, multiply extracted scalar (for r/g/b)
        by the input's alpha to confine the color signal to the input's visible area.

    Behavior:
      - Composes from zeros.
      - Each provided input overrides its channel from the scalar extracted using *_src,
        optionally multiplied by the source alpha (except for a_src == 'a', which is already alpha).
      - Unconnected channels remain 0.
    """
    def __init__(self,
                 r_src='luma', g_src='luma', b_src='luma', a_src='luma',
                 use_source_alpha=True,
                 name='Combine'):
        self.r_src = str(r_src)
        self.g_src = str(g_src)
        self.b_src = str(b_src)
        self.a_src = str(a_src)
        self.use_source_alpha = bool(use_source_alpha)
        self.name = name
        self.inputs = {'r': None, 'g': None, 'b': None, 'a': None}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        key = (in_name or '').lower()
        if key not in self.inputs:
            raise ValueError(f'Unknown input: {in_name}')
        self.inputs[key] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True

    def invalidate_cascade(self):
        self._dirty = True

    # --- helpers ---
    @staticmethod
    def _ensure_rgba(img, size):
        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)
        return np.clip(img, 0.0, 1.0)

    @staticmethod
    def _luma(rgb):
        return (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]).astype(np.float32)

    def _extract_scalar(self, rgba, mode: str, respect_alpha: bool):
        """
        Return (H,W,1) scalar channel from RGBA according to mode.
        If respect_alpha=True and mode != 'a', multiply scalar by rgba alpha.
        """
        m = (mode or 'luma').lower()
        if m == 'r': scalar = rgba[..., 0:1]
        elif m == 'g': scalar = rgba[..., 1:2]
        elif m == 'b': scalar = rgba[..., 2:3]
        elif m == 'a': scalar = rgba[..., 3:4]
        else:
            scalar = self._luma(rgba[...,:3])[..., None]

        if respect_alpha and m != 'a':
            scalar = scalar * rgba[..., 3:4]
        return scalar

    def _resolve_upstream(self, connection, size):
        """Resolve a connection to an evaluated image, handling tuple format."""
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
        return None

    # --- main evaluation ---
    def evaluate(self, size=512):
        # Filter classes don't cache - upstream generators cache instead
        H = W = int(size)

        # Resolve all upstreams
        r_img = self._resolve_upstream(self.inputs.get('r'), size)
        g_img = self._resolve_upstream(self.inputs.get('g'), size)
        b_img = self._resolve_upstream(self.inputs.get('b'), size)
        a_img = self._resolve_upstream(self.inputs.get('a'), size)

        rimg = self._ensure_rgba(r_img, H) if r_img is not None else None
        gimg = self._ensure_rgba(g_img, H) if g_img is not None else None
        bimg = self._ensure_rgba(b_img, H) if b_img is not None else None
        aimg = self._ensure_rgba(a_img, H) if a_img is not None else None

        out = np.zeros((H, W, 4), dtype=np.float32)
        respect = bool(self.use_source_alpha)

        # Compose R/G/B from respective inputs (scalar × alpha if enabled)
        if rimg is not None:
            out[..., 0:1] = self._extract_scalar(rimg, self.r_src, respect_alpha=respect)
        if gimg is not None:
            out[..., 1:2] = self._extract_scalar(gimg, self.g_src, respect_alpha=respect)
        if bimg is not None:
            out[..., 2:3] = self._extract_scalar(bimg, self.b_src, respect_alpha=respect)

        # Compose alpha
        if aimg is not None:
            out[..., 3:4] = self._extract_scalar(aimg, self.a_src, respect_alpha=False)
        else:
            out[..., 3:4] = 0.0

        out = np.clip(out, 0.0, 1.0)
        return np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)


class Split(GenerationCacheMixin):
    """
    Split node: separate an RGBA image into its 4 component channels.

    Inputs:
      - 'image' : upstream RGBA float [0..1]

    Outputs (multi-output node):
      - 'r' : Red channel as grayscale
      - 'g' : Green channel as grayscale
      - 'b' : Blue channel as grayscale
      - 'a' : Alpha channel as grayscale

    Each output is a grayscale RGBA image where R=G=B = channel value, A=1.0
    """
    def __init__(self, name='Split'):
        self.name = name
        self.inputs = {'image': None}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility
        self._init_generation_cache()

    # --- plumbing consistent with your framework ---
    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        if in_name != 'image':
            raise ValueError(f'Unknown input: {in_name}')
        self.inputs['image'] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._bump_generation()
        self._dirty = True
        # Propagate to dependents
        for dep in list(self.dependents):
            if hasattr(dep, 'invalidate_cascade'):
                dep.invalidate_cascade()
            elif hasattr(dep, 'invalidate'):
                dep.invalidate()

    def invalidate_cascade(self):
        """Called when an upstream node changes."""
        self._dirty = True
        for dep in list(self.dependents):
            if hasattr(dep, 'invalidate_cascade'):
                dep.invalidate_cascade()
            elif hasattr(dep, 'invalidate'):
                dep.invalidate()

    # --- helpers ---
    @staticmethod
    def _ensure_rgba(img, size):
        img = np.asarray(img, dtype=np.float32)
        if img.ndim != 3 or img.shape[-1] != 4:
            return np.zeros((size, size, 4), dtype=np.float32)
        return np.clip(img, 0.0, 1.0)

    def _get_input_rgba(self, size):
        """Get the input image. Filter classes don't cache - upstream generators cache instead."""
        connection = self.inputs.get('image')
        if connection is None:
            return np.zeros((size, size, 4), dtype=np.float32)
        elif isinstance(connection, tuple):
            node, output_port = connection
            if hasattr(node, 'evaluate_port'):
                img = node.evaluate_port(output_port, size)
            else:
                img = node.evaluate(size)
            return self._ensure_rgba(img, size)
        else:
            # Legacy direct node reference
            img = connection.evaluate(size)
            return self._ensure_rgba(img, size)

    def _channel_to_grayscale(self, channel_data, size):
        """Convert a single channel to grayscale RGBA output."""
        out = np.zeros((size, size, 4), dtype=np.float32)
        out[..., 0] = channel_data
        out[..., 1] = channel_data
        out[..., 2] = channel_data
        out[..., 3] = 1.0
        return np.clip(out, 0.0, 1.0)

    # --- multi-output evaluation ---
    def evaluate_port(self, port_name: str, size: int) -> np.ndarray:
        """Evaluate a specific output port (r, g, b, or a)."""
        size = int(size)
        rgba = self._get_input_rgba(size)

        if port_name == 'r':
            return self._channel_to_grayscale(rgba[..., 0], size)
        elif port_name == 'g':
            return self._channel_to_grayscale(rgba[..., 1], size)
        elif port_name == 'b':
            return self._channel_to_grayscale(rgba[..., 2], size)
        elif port_name == 'a':
            return self._channel_to_grayscale(rgba[..., 3], size)
        else:
            # Default: return full RGBA (for 'out' port or unknown)
            return rgba.copy()

    def evaluate(self, size=512):
        """Default evaluate returns the full RGBA image."""
        return self._get_input_rgba(int(size)).copy()
