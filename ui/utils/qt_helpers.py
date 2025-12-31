
# ui/utils/qt_helpers.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QImage


def _snap_value(v: float, grid: int) -> float:
    if grid <= 0:
        return v
    return float(round(v / grid) * grid)


def _should_snap(view) -> bool:
    """
    Return True if snapping is enabled and Alt is NOT held.
    The view is passed for future expansion (per-view flags), but currently unused.
    """
    # If you later want a global flag, import it or pass it through view/editor
    mods = QApplication.keyboardModifiers()
    return not (mods & Qt.AltModifier)


def _pil_to_qpixmap(img) -> QPixmap:
    img = img.convert('RGBA')
    data = img.tobytes('raw', 'RGBA')
    qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)
