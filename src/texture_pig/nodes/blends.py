
import numpy as np
import cv2
from .core import Node, get_scalar_param

class Lerp(Node):
    """
    Linear interpolation between two images based on a mask.
    Formula: Result = A * (1 - T) + B * T
    """
    def __init__(self, name='Lerp', opacity=1.0, seed=None):
        super().__init__(name=name, opacity=opacity, seed=seed)
        self.inputs = {'a': None, 'b': None, 't': None}

    def _compute(self, size: int) -> np.ndarray:
        # Import dependencies locally to avoid circular issues
        from .core import ensure_rgba, clamp01

        arr_a_raw = self.input_arr('a', size)
        arr_b_raw = self.input_arr('b', size)
        mask_raw  = self.input_arr('t', size)

        # Normalize inputs to RGBA float32
        arr_a = ensure_rgba(arr_a_raw if arr_a_raw is not None else np.zeros((size, size, 4), dtype=np.float32))
        arr_b = ensure_rgba(arr_b_raw if arr_b_raw is not None else np.zeros((size, size, 4), dtype=np.float32))

        # Handle Mask - use luminance from RGB multiplied by alpha
        # Alpha=0 is treated as black (t=0), so transparent areas output A
        if mask_raw is None:
            # Default to 50/50 mix if nothing connected
            t = np.full((size, size, 1), 0.5, dtype=np.float32)
        else:
            # Calculate luminance from RGB channels (standard Rec. 709 coefficients)
            r, g, b, a = mask_raw[..., 0], mask_raw[..., 1], mask_raw[..., 2], mask_raw[..., 3]
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            # Multiply by alpha so transparent pixels are treated as black (t=0)
            t = clamp01(luma * a).astype(np.float32)[..., np.newaxis]

        # Standard Lerp formula: (1-t)*a + t*b
        return (1.0 - t) * arr_a + t * arr_b

from texture_pig.nodes.utils import channel_value_with_alpha, extract_mask

def _ensure_rgba(img, size):
    img = np.asarray(img, dtype=np.float32)
    if img.ndim != 3 or img.shape[-1] != 4:
        return np.zeros((size, size, 4), dtype=np.float32)
    return np.clip(img, 0.0, 1.0)

def _luma(rgb):
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]).astype(np.float32)

def _safe_eval(connection, size):
    """Evaluate a connection, handling both (node, port) tuples and direct node refs."""
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

def _safe_div(numer: np.ndarray, denom: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    out = np.zeros_like(numer, dtype=np.float32)
    np.divide(numer, np.clip(denom, eps, None), out=out, where=(denom > eps))
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)

def _over(dst_rgba: np.ndarray, src_rgba: np.ndarray) -> np.ndarray:
    """Standard Porter–Duff OVER (non-premultiplied inputs)."""
    Sa = np.clip(src_rgba[..., 3:4], 0.0, 1.0)
    Da = np.clip(dst_rgba[..., 3:4], 0.0, 1.0)
    Sc = np.clip(src_rgba[..., :3], 0.0, 1.0)
    Dc = np.clip(dst_rgba[..., :3], 0.0, 1.0)
    out_a = Sa + Da * (1.0 - Sa)
    out_c = (Sc * Sa + Dc * Da * (1.0 - Sa)) / np.clip(out_a, 1e-8, 1.0)
    return np.concatenate([np.clip(out_c, 0.0, 1.0), np.clip(out_a, 0.0, 1.0)], axis=-1)

class Blend:
    """
    Inputs: base, blend, mask (optional)

    Params:
      - mode: 'normal' | 'add' | 'subtract' | 'multiply' | 'screen' | 'overlay'
      - opacity: 0..1 (global strength of the blend)
      - mask_channel: 'a'|'luma'|'r'|'g'|'b' (used only if mask input is connected)
      - affect_alpha: bool (default True) → whether the mode changes alpha

      # Hidden (legacy) controls — behavior enforced internally:
      - subtract_as_cutout: always False
      - use_blend_as_mask_when_no_mask: always True
    """
    def __init__(self, mode='normal', opacity=1.0, name='Blend',
                 mask_channel='a',
                 affect_alpha=True,
                 # legacy args kept for load-compatibility; will be overridden:
                 subtract_as_cutout=False,
                 use_blend_as_mask_when_no_mask=True):
        self.mode = str(mode).lower()
        self.opacity = float(opacity)
        self.name = name
        self.inputs = {'base': None, 'blend': None, 'mask': None}
        self.mask_channel = str(mask_channel)
        self.affect_alpha = bool(affect_alpha)

        # 🔒 Enforce desired behavior regardless of incoming args
        self.subtract_as_cutout = False
        self.use_blend_as_mask_when_no_mask = True

        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility

    def connect(self, name, node, output_port='out'):
        self.inputs[name] = (node, output_port)
        self.invalidate()

    def set_params(self, **kwargs):
        if 'mode' in kwargs:
            self.mode = str(kwargs.pop('mode')).lower()

        # 🔒 Ignore legacy keys (from old graphs / external calls)
        kwargs.pop('subtract_as_cutout', None)
        kwargs.pop('use_blend_as_mask_when_no_mask', None)

        for k, v in kwargs.items():
            setattr(self, k, v)

        # 🔒 Re‑enforce constants (in case someone tinkers via setattr elsewhere)
        self.subtract_as_cutout = False
        self.use_blend_as_mask_when_no_mask = True

        self.invalidate()

    def invalidate(self):
        self._dirty = True

    def _resolve_mask(self, size, base, blend, mask_node):
        """Returns M in [0..1] shaped (H,W,1) or None."""
        if mask_node is not None:
            mask_img = _ensure_rgba(_safe_eval(mask_node, size), size)
            return extract_mask(mask_img, self.mask_channel)
        if self.mode == 'subtract' and self.use_blend_as_mask_when_no_mask and blend is not None:
            return extract_mask(blend, self.mask_channel)
        return None

    def evaluate(self, size=512):
        base_node  = self.inputs.get('base')
        blend_node = self.inputs.get('blend')
        mask_node  = self.inputs.get('mask')

        # Base required
        if base_node is None:
            return np.zeros((size, size, 4), dtype=np.float32)

        base  = _ensure_rgba(_safe_eval(base_node, size), size)
        blend = _ensure_rgba(_safe_eval(blend_node, size), size) if blend_node is not None else np.zeros_like(base)
        M     = self._resolve_mask(size, base, blend, mask_node)  # (H,W,1) or None
        op    = np.float32(np.clip(get_scalar_param(self, 'opacity', self.opacity), 0.0, 1.0))

        # If a mask exists, modulate opacity by mask
        if M is not None:
            opM = np.clip(op * M, 0.0, 1.0)
        else:
            opM = op

        mode = self.mode

        # ---------------- NORMAL (composite over) ----------------
        if mode == 'normal':
            # Apply opacity (masked) to source alpha before OVER
            src = blend.copy()
            src[..., 3:4] *= opM
            return _over(base, src)

        # Prepare premultiplied colors
        Ba = np.clip(base[..., 3:4], 0.0, 1.0)
        Bc = np.clip(base[..., :3], 0.0, 1.0)
        Bpm = Bc * Ba

        Sa_full = np.clip(blend[..., 3:4], 0.0, 1.0)
        Sc_full = np.clip(blend[..., :3], 0.0, 1.0)
        # Source premultiplied considering opacity + mask
        Sa = np.clip(Sa_full * opM, 0.0, 1.0)
        Spm = Sc_full * Sa

        # Helper to finalize (convert back from premultiplied)
        def finalize(premult_rgb, alpha):
            out_a = np.clip(alpha, 0.0, 1.0)
            out_c = _safe_div(np.clip(premult_rgb, 0.0, 1.0), np.clip(out_a, 1e-8, 1.0))
            return np.concatenate([np.clip(out_c, 0.0, 1.0), out_a], axis=-1)

        # ---------------- SUBTRACT ----------------
        if mode == 'subtract':
            if self.subtract_as_cutout:
                # (Legacy branch — will never run because subtract_as_cutout is forced False)
                if M is None:
                    mask = Sa_full if self.use_blend_as_mask_when_no_mask else None
                else:
                    mask = M
                if mask is None:
                    out_a = Ba
                else:
                    out_a = np.clip(Ba * (1.0 - np.clip(op * mask, 0.0, 1.0)), 0.0, 1.0)
                ratio = _safe_div(out_a, Ba)
                out_pm = Bpm * ratio
                return finalize(out_pm, out_a)

            # Original color subtract (affects both color and alpha if desired)
            out_pm = np.clip(Bpm - Spm, 0.0, 1.0)
            if self.affect_alpha:
                # Reduce alpha where source covers, proportionally to Sa
                out_a = np.clip(Ba * (1.0 - Sa), 0.0, 1.0)
            else:
                out_a = Ba
            return finalize(out_pm, out_a)

        # ---------------- ADD ----------------
        if mode == 'add':
            out_pm = np.clip(Bpm + Spm, 0.0, 1.0)
            out_a  = np.clip(Ba + Sa * (1.0 - Ba) if self.affect_alpha else Ba, 0.0, 1.0)
            return finalize(out_pm, out_a)

        # ---------------- MULTIPLY ----------------
        if mode == 'multiply':
            # Multiply in non-premultiplied color space, then re-premultiply with base alpha
            factor = np.clip((1.0 - op) + op * Sc_full, 0.0, 1.0)  # opacity-blended factor
            out_rgb = np.clip(Bc * factor, 0.0, 1.0)
            out_pm  = out_rgb * Ba
            out_a   = np.clip(Ba if not self.affect_alpha else (Ba + Sa * (1.0 - Ba)), 0.0, 1.0)
            return finalize(out_pm, out_a)

        # ---------------- SCREEN ----------------
        if mode == 'screen':
            # Screen = 1 - (1-a)*(1-b), modulated by opacity
            scr = 1.0 - (1.0 - Bc) * (1.0 - np.clip(Sc_full * op, 0.0, 1.0))
            out_pm = np.clip(scr, 0.0, 1.0) * Ba
            out_a  = np.clip(Ba if not self.affect_alpha else (Ba + Sa * (1.0 - Ba)), 0.0, 1.0)
            return finalize(out_pm, out_a)

        # ---------------- OVERLAY ----------------
        if mode == 'overlay':
            # Overlay on non-premultiplied RGB, then premultiply with base alpha
            a = Bc
            b = np.clip(Sc_full * op, 0.0, 1.0)
            overlay_rgb = np.where(a <= 0.5, 2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b))
            out_rgb = np.clip(a * (1.0 - op) + overlay_rgb * op, 0.0, 1.0)
            out_pm  = out_rgb * Ba
            out_a   = np.clip(Ba if not self.affect_alpha else (Ba + Sa * (1.0 - Ba)), 0.0, 1.0)
            return finalize(out_pm, out_a)

        # Fallback: return base unchanged
        return base
