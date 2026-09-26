
# ui/utils/editor_helpers.py
from __future__ import annotations
from typing import Optional

from PySide6.QtGui import QFontMetrics, QKeySequence, QAction
from PySide6.QtWidgets import QMenu


def shorten_label(text: str, max_chars: int = 40) -> str:
    """Shorten overly long menu labels with an ellipsis."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"


def compute_edit_menu_min_width(menu: QMenu) -> int:
    """
    Compute a minimum width that fits current Edit menu action texts and their shortcuts.
    Returns a pixel width; caller should add a small margin if desired.
    """
    if not menu:
        return 0

    fm: QFontMetrics = menu.fontMetrics()
    max_w = 0

    for act in menu.actions():
        if not isinstance(act, QAction):
            continue

        label = act.text() or ""
        label_w = fm.horizontalAdvance(label)

        # Gather shortcuts from either .shortcuts() or .shortcut()
        shortcut_strs = []
        try:
            seqs = list(getattr(act, 'shortcuts', lambda: [])())
        except Exception:
            seqs = []

        if not seqs:
            seq = getattr(act, 'shortcut', lambda: QKeySequence())()
            if isinstance(seq, QKeySequence) and not seq.isEmpty():
                shortcut_strs.append(seq.toString())
        else:
            for s in seqs:
                if isinstance(s, QKeySequence) and not s.isEmpty():
                    shortcut_strs.append(s.toString())

        # Widest shortcut column
        shortcut_w = 0
        for s in shortcut_strs:
            shortcut_w = max(shortcut_w, fm.horizontalAdvance(s))

        # Add spacing between label and shortcut + some margins
        total_w = label_w + 24 + shortcut_w
        max_w = max(max_w, total_w)

    # Return final width + a small margin
    return max_w + 24

def normalize_params(params: dict) -> dict:
    """
    Convert JSON-saved params to runtime-friendly types:
      - lists -> tuples
      - numpy scalars -> Python scalars
    """
    def _to_py(v):
        try:
            import numpy as np
            np_scalar_types = (np.generic,)
        except Exception:
            np_scalar_types = tuple()
        if isinstance(v, list):
            return tuple(_to_py(x) for x in v)
        if isinstance(v, dict):
            return {k: _to_py(vv) for k, vv in v.items()}
        if np_scalar_types and isinstance(v, np_scalar_types):
            try:
                return v.item()
            except Exception:
                pass
        return v
    try:
        return {k: _to_py(v) for k, v in params.items()}
    except Exception:
        return params

def default_card_width(
    preview_size: int,
    fm: Optional[QFontMetrics],
    left_pad: int = 12,
    right_pad: int = 12,
    port_circle_diam: int = 16,
    gap: int = 8,
    output_label_text: str = "out",
) -> int:
    """
    Compute a sensible default node card width based on preview size,
    a port column on the right, and padding.

    Layout formula:
      LEFT_PAD + preview_size + RIGHT_PAD + (port_circle + gap + output_label_width)
    """
    try:
        label_w = fm.horizontalAdvance(output_label_text) if fm else 32
    except Exception:
        label_w = 32

    ports_col = port_circle_diam + gap + label_w
    return int(left_pad + int(preview_size) + right_pad + ports_col)
