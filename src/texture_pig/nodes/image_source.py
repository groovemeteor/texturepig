
# texture_pig/nodes/image_source.py
import os
import numpy as np
import cv2
from PIL import Image

class ImageNode:
    """
    Load an image from disk and output RGBA float in [0..1] at requested size.

    Params:
      - path: str (file path)
      - scale_mode: 'crop' | 'fit' | 'stretch'
          crop    -> scale to cover, center-crop to target size (default)
          fit     -> scale to fit inside, letterbox with transparent pixels
          stretch -> direct resize to target (no aspect preservation)
    """
    def __init__(self, path='', scale_mode='crop', name='Image'):
        self.path = str(path or '')
        self.scale_mode = str(scale_mode or 'crop').lower()
        self.name = name
        self.inputs = {}
        self._dirty = True
        self.dependents: set = set()  # Required for Node.connect() compatibility

        # Cache of original PIL RGBA + file mtime
        self._pil_rgba = None
        self._mtime = None

    # ---- plumbing consistent with your framework
    def set_params(self, **kwargs):
        # normalize mode
        if 'scale_mode' in kwargs:
            self.scale_mode = str(kwargs.pop('scale_mode')).lower()
        if 'path' in kwargs:
            new_path = str(kwargs.pop('path') or '')
            if new_path != self.path:
                self.path = new_path
                # clear cache so we reload
                self._pil_rgba = None
                self._mtime = None
        # apply rest
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()

    def connect(self, in_name, node, output_port='out'):
        # no inputs for source node
        self.inputs[in_name] = (node, output_port)
        self.invalidate()

    def invalidate(self):
        self._dirty = True

    # ---- public: force reload from disk
    def reload(self):
        """Drop cache and force re-open on next evaluate()."""
        self._pil_rgba = None
        self._mtime = None
        self.invalidate()

    # ---- internal helpers
    def _open_pil_rgba(self):
        """Open the file as PIL RGBA, caching by mtime."""
        p = (self.path or '').strip()
        if not p or not os.path.isfile(p):
            self._pil_rgba = None
            self._mtime = None
            return None

        try:
            mtime = os.path.getmtime(p)
            if self._pil_rgba is not None and self._mtime == mtime:
                return self._pil_rgba  # still valid

            img = Image.open(p)
            # Handle EXIF orientation (optional; uncomment if needed)
            # try:
            #     from PIL import ImageOps
            #     img = ImageOps.exif_transpose(img)
            # except Exception:
            #     pass
            img = img.convert('RGBA')  # ensure RGBA
            self._pil_rgba = img
            self._mtime = mtime
            return img
        except Exception:
            self._pil_rgba = None
            self._mtime = None
            return None

    @staticmethod
    def _pil_to_rgba_array(pil_img: Image.Image) -> np.ndarray:
        """Convert PIL RGBA -> float32 array in [0..1], shape (H, W, 4)."""
        arr = np.asarray(pil_img, dtype=np.uint8)
        arr = arr.astype(np.float32) / 255.0
        return arr

    @staticmethod
    def _resize_cover_and_crop(img: Image.Image, size: int) -> Image.Image:
        """Scale to cover target square, then center-crop to (size,size)."""
        w, h = img.width, img.height
        if w == 0 or h == 0:
            return Image.new('RGBA', (size, size), (0, 0, 0, 0))
        s = max(size / float(w), size / float(h))
        new_w = max(1, int(round(w * s)))
        new_h = max(1, int(round(h * s)))
        # Use cv2.resize (faster than PIL)
        arr = np.asarray(img, dtype=np.uint8)
        # cv2 expects BGR, but we have RGBA - resize works on any channel count
        resized_arr = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        # center crop
        x0 = max(0, (new_w - size) // 2)
        y0 = max(0, (new_h - size) // 2)
        cropped = resized_arr[y0:y0 + size, x0:x0 + size]
        return Image.fromarray(cropped, mode='RGBA')

    @staticmethod
    def _resize_contain_and_letterbox(img: Image.Image, size: int) -> Image.Image:
        """Scale to fit inside target square, pad transparent to (size,size)."""
        w, h = img.width, img.height
        if w == 0 or h == 0:
            return Image.new('RGBA', (size, size), (0, 0, 0, 0))
        s = min(size / float(w), size / float(h))
        new_w = max(1, int(round(w * s)))
        new_h = max(1, int(round(h * s)))
        # Use cv2.resize (faster than PIL)
        arr = np.asarray(img, dtype=np.uint8)
        resized_arr = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Create transparent canvas and paste resized image
        canvas = np.zeros((size, size, 4), dtype=np.uint8)
        x0 = (size - new_w) // 2
        y0 = (size - new_h) // 2
        canvas[y0:y0 + new_h, x0:x0 + new_w] = resized_arr
        return Image.fromarray(canvas, mode='RGBA')

    @staticmethod
    def _resize_stretch(img: Image.Image, size: int) -> Image.Image:
        """Resize directly to (size,size) without preserving aspect."""
        # Use cv2.resize (faster than PIL)
        arr = np.asarray(img, dtype=np.uint8)
        resized_arr = cv2.resize(arr, (size, size), interpolation=cv2.INTER_LANCZOS4)
        return Image.fromarray(resized_arr, mode='RGBA')

    # ---- Graph protocol
    def evaluate(self, size=512):
        """
        Return RGBA float array (H, W, 4) in [0..1] at requested square resolution.
        """
        S = int(size)
        if S <= 0:
            return np.zeros((1, 1, 4), dtype=np.float32)

        pil = self._open_pil_rgba()
        if pil is None:
            return np.zeros((S, S, 4), dtype=np.float32)

        mode = (self.scale_mode or 'crop').lower()
        if mode == 'fit':
            out_pil = self._resize_contain_and_letterbox(pil, S)
        elif mode == 'stretch':
            out_pil = self._resize_stretch(pil, S)
        else:
            # default: crop (cover + center-crop)
            out_pil = self._resize_cover_and_crop(pil, S)

        return self._pil_to_rgba_array(out_pil)
