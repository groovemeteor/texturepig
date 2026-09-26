# texture_pig/nodes/text.py
from __future__ import annotations
import numpy as np
import os
import sys
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from texture_pig.nodes.core import Node


def get_system_fonts() -> List[str]:
    """
    Discover available system fonts and return a list of font names.
    Returns font file paths that can be loaded with PIL.
    """
    font_dirs = []
    font_files = {}

    # Platform-specific font directories
    if sys.platform == 'win32':
        font_dirs = [
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts'),
        ]
    elif sys.platform == 'darwin':
        font_dirs = [
            '/System/Library/Fonts',
            '/Library/Fonts',
            os.path.expanduser('~/Library/Fonts'),
        ]
    else:  # Linux and others
        font_dirs = [
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.fonts'),
            os.path.expanduser('~/.local/share/fonts'),
        ]

    # Scan font directories
    for font_dir in font_dirs:
        if not os.path.isdir(font_dir):
            continue
        for root, dirs, files in os.walk(font_dir):
            for f in files:
                if f.lower().endswith(('.ttf', '.otf', '.ttc')):
                    font_path = os.path.join(root, f)
                    # Use filename without extension as display name
                    name = os.path.splitext(f)[0]
                    if name not in font_files:
                        font_files[name] = font_path

    return font_files


# Cache of discovered fonts
_FONT_CACHE: Optional[dict] = None


def get_font_dict() -> dict:
    """Get cached font dictionary."""
    global _FONT_CACHE
    if _FONT_CACHE is None:
        _FONT_CACHE = get_system_fonts()
    return _FONT_CACHE


def get_font_names() -> List[str]:
    """Get sorted list of available font names."""
    fonts = get_font_dict()
    return sorted(fonts.keys())


def get_font_path(font_name: str) -> Optional[str]:
    """Get the file path for a font name."""
    fonts = get_font_dict()
    return fonts.get(font_name)


class Text(Node):
    """
    Render text to a texture with configurable font, size, color, and alignment.

    Params:
      - text          : str - the text to render (supports multi-line with \\n)
      - font_name     : str - name of the font to use (from system fonts)
      - font_size     : float - font size as fraction of canvas height (0.0-1.0)
      - color         : tuple (R, G, B, A) - text color in 0.0-1.0 range
      - align         : 'left' | 'center' | 'right' - horizontal alignment
      - valign        : 'top' | 'center' | 'bottom' - vertical alignment
      - line_spacing  : float - multiplier for line spacing (1.0 = normal)
      - padding       : float - padding from edges as fraction of canvas (0.0-0.5)
      - name          : display name
    """

    def __init__(self,
                 text: str = "Text",
                 font_name: str = "Arial",
                 font_size: float = 0.1,
                 color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
                 align: str = 'center',
                 valign: str = 'center',
                 line_spacing: float = 1.0,
                 padding: float = 0.05,
                 name: str = 'Text',
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.text = str(text)
        self.font_name = str(font_name)
        self.font_size = float(font_size)
        self.color = tuple(float(c) for c in color)
        if len(self.color) == 3:
            self.color = self.color + (1.0,)
        self.align = str(align).lower()
        self.valign = str(valign).lower()
        self.line_spacing = float(line_spacing)
        self.padding = float(padding)
        self.inputs = {}
        self.dependents = set()

    def set_params(self, **kwargs):
        if 'align' in kwargs:
            kwargs['align'] = str(kwargs['align']).lower()
        if 'valign' in kwargs:
            kwargs['valign'] = str(kwargs['valign']).lower()
        if 'color' in kwargs:
            c = kwargs['color']
            c = tuple(float(x) for x in c)
            if len(c) == 3:
                c = c + (1.0,)
            kwargs['color'] = c
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()
        return self

    def _get_font(self, size_px: int) -> ImageFont.FreeTypeFont:
        """Load the specified font at the given pixel size."""
        font_path = get_font_path(self.font_name)

        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size_px)
            except Exception:
                pass

        # Fallback: try common font names directly
        fallback_fonts = ['Arial', 'arial', 'DejaVuSans', 'Helvetica', 'FreeSans']
        for fallback in fallback_fonts:
            try:
                return ImageFont.truetype(fallback, size_px)
            except Exception:
                continue

        # Last resort: PIL default font (bitmap, limited size)
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _compute(self, size: int) -> np.ndarray:
        # Create transparent RGBA image
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Calculate font size in pixels
        font_size_px = max(1, int(self.p('font_size') * size))
        font = self._get_font(font_size_px)

        if font is None or not self.text.strip():
            return np.zeros((size, size, 4), dtype=np.float32)

        # Convert color to 0-255 range for PIL
        color_255 = tuple(int(c * 255) for c in self.color)

        # Calculate padding
        pad = int(self.p('padding') * size)
        available_width = size - 2 * pad
        available_height = size - 2 * pad

        # Split text into lines
        lines = self.text.split('\n')

        # Calculate line heights and total text height
        line_heights = []
        line_widths = []
        for line in lines:
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(line or " ")
                lw = bbox[2] - bbox[0]
                lh = bbox[3] - bbox[1]
            else:
                # Fallback for older PIL
                lw, lh = draw.textsize(line or " ", font=font)
            line_widths.append(lw)
            line_heights.append(lh)

        base_line_height = max(line_heights) if line_heights else font_size_px
        spacing = int(base_line_height * (self.p('line_spacing') - 1.0))
        total_height = sum(line_heights) + spacing * (len(lines) - 1)

        # Calculate starting Y position based on vertical alignment
        if self.valign == 'top':
            y = pad
        elif self.valign == 'bottom':
            y = size - pad - total_height
        else:  # center
            y = (size - total_height) // 2

        # Draw each line
        for i, line in enumerate(lines):
            if not line:
                y += line_heights[i] + spacing
                continue

            lw = line_widths[i]

            # Calculate X position based on horizontal alignment
            if self.align == 'left':
                x = pad
            elif self.align == 'right':
                x = size - pad - lw
            else:  # center
                x = (size - lw) // 2

            draw.text((x, y), line, font=font, fill=color_255)
            y += line_heights[i] + spacing

        # Convert to numpy array (0-1 float32)
        arr = np.array(img, dtype=np.float32) / 255.0
        return arr
