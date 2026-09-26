from __future__ import annotations
from typing import Callable, Tuple, Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QSlider,
    QDoubleSpinBox, QToolButton, QColorDialog, QLabel
)

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))

def _parse_hex_color(text: str, default=(1.0, 0.0, 1.0, 1.0)) -> Tuple[float, float, float, float]:
    """
    Accepts: #rgb, #rgba, #rrggbb, #rrggbbaa (case-insensitive).
    Returns normalized RGBA floats in [0..1].
    """
    if not text:
        return default
    s = text.strip().lower()
    if s.startswith('#'): s = s[1:]
    try:
        if len(s) == 3:  # rgb
            r = int(s[0]*2, 16); g = int(s[1]*2, 16); b = int(s[2]*2, 16); a = 255
        elif len(s) == 4:  # rgba
            r = int(s[0]*2, 16); g = int(s[1]*2, 16); b = int(s[2]*2, 16); a = int(s[3]*2, 16)
        elif len(s) == 6:  # rrggbb
            r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16); a = 255
        elif len(s) == 8:  # rrggbbaa
            r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16); a = int(s[6:8], 16)
        else:
            return default
        return (r/255.0, g/255.0, b/255.0, a/255.0)
    except Exception:
        return default

def _rgba_to_hex(r: float, g: float, b: float, a: float, include_alpha: bool = True) -> str:
    R = max(0, min(255, int(round(r * 255))))
    G = max(0, min(255, int(round(g * 255))))
    B = max(0, min(255, int(round(b * 255))))
    A = max(0, min(255, int(round(a * 255))))
    if include_alpha:
        return f'#{R:02x}{G:02x}{B:02x}{A:02x}'
    return f'#{R:02x}{G:02x}{B:02x}'

def _checkerboard(size: int = 12) -> QPixmap:
    """Small checkerboard tile for transparency preview."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    c1 = QColor(180, 180, 180)
    c2 = QColor(220, 220, 220)
    s = size // 2
    p.fillRect(0, 0, s, s, c1)
    p.fillRect(s, 0, s, s, c2)
    p.fillRect(0, s, s, s, c2)
    p.fillRect(s, s, s, s, c1)
    p.end()
    return pix

class ColorField(QWidget):
    """
    Unified color editor:
      - Swatch with checkerboard
      - Hex line edit (#rgb, #rgba, #rrggbb, #rrggbbaa)
      - RGBA sliders + spins (0..1)
      - HSL sliders + spins (H in degrees, S/L/A in 0..1)
    Emits colorChanged(r, g, b, a) on user commits (debounced).
    """
    colorChanged = Signal(float, float, float, float)

    def __init__(self,
                 rgba: Tuple[float, float, float, float] = (1, 1, 1, 1),
                 parent: Optional[QWidget] = None,
                 live_debounce_ms: int = 60,
                 show_alpha: bool = True):
        super().__init__(parent)
        self._updating = False
        self._debounce_ms = int(live_debounce_ms)
        self._debouncer = QTimer(self); self._debouncer.setSingleShot(True)
        self._debouncer.timeout.connect(self._emit_color)

        self._show_alpha = bool(show_alpha)

        # --- Current color (QColor for HSL/Alpha ops) ---
        r, g, b, a = rgba
        self._qc = QColor.fromRgbF(_clamp01(r), _clamp01(g), _clamp01(b), _clamp01(a))

        # --- UI ---
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Row 1: Swatch + Hex
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.btn_swatch = QToolButton(self)
        self.btn_swatch.setFixedSize(QSize(28, 28))
        self.btn_swatch.clicked.connect(self._open_qt_color_dialog)
        top_row.addWidget(self.btn_swatch, 0)

        self.hex_edit = QLineEdit(self)
        self.hex_edit.setPlaceholderText("#rrggbb or #rrggbbaa")
        self.hex_edit.editingFinished.connect(self._on_hex_commit)
        top_row.addWidget(self.hex_edit, 1)

        root.addLayout(top_row)

        # Row 2: RGBA
        self.r_form = QFormLayout(); self.r_form.setSpacing(4)
        self._r_s, self._r_spin = self._make_channel("R", 0, 1.0, 0.001)
        self._g_s, self._g_spin = self._make_channel("G", 0, 1.0, 0.001)
        self._b_s, self._b_spin = self._make_channel("B", 0, 1.0, 0.001)
        if self._show_alpha:
            self._a_s, self._a_spin = self._make_channel("A", 0, 1.0, 0.001)
        root.addRow = root.addLayout  # small trick to mimic addRow
        root.addLayout(self.r_form)

        # Row 3: HSL
        self.h_form = QFormLayout(); self.h_form.setSpacing(4)
        # Hue in degrees 0..360 for user; internally store 0..1 for QColor.setHslF
        self._h_s, self._h_spin = self._make_channel("Hue (°)", 0, 360.0, 1.0, is_hue=True)
        self._s_s, self._s_spin = self._make_channel("Sat", 0, 1.0, 0.001)
        self._l_s, self._l_spin = self._make_channel("Light", 0, 1.0, 0.001)
        # Alpha is shared with RGBA; no need to duplicate
        root.addLayout(self.h_form)

        # Hook signals after building
        self._wire_rgba()
        self._wire_hsl()

        # Set initial UI state from current color
        self._refresh_ui_from_qcolor()

    # ---------- UI building helpers ----------
    def _make_channel(self, label: str, vmin: float, vmax: float, step: float, is_hue: bool=False):
        """Return (slider, spinbox) and append to appropriate form."""
        row = QHBoxLayout()
        s = QSlider(Qt.Horizontal, self)
        s.setMinimum(0)
        s.setMaximum(1000)
        s.setSingleStep(1)
        spin = QDoubleSpinBox(self)
        spin.setDecimals(4)
        spin.setRange(vmin, vmax)
        spin.setSingleStep(step)
        spin.setKeyboardTracking(False)  # only apply on Enter or focus-out

        row.addWidget(s, 3)
        row.addWidget(spin, 1)

        form = self.h_form if "Hue" in label or is_hue else self.r_form
        form.addRow(QLabel(label), row)
        return s, spin

    def _wire_rgba(self):
        self._r_s.valueChanged.connect(lambda i: self._on_slider_rgba(i, 'r'))
        self._g_s.valueChanged.connect(lambda i: self._on_slider_rgba(i, 'g'))
        self._b_s.valueChanged.connect(lambda i: self._on_slider_rgba(i, 'b'))
        if self._show_alpha:
            self._a_s.valueChanged.connect(lambda i: self._on_slider_rgba(i, 'a'))

        self._r_spin.valueChanged.connect(lambda v: self._on_spin_rgba(v, 'r'))
        self._g_spin.valueChanged.connect(lambda v: self._on_spin_rgba(v, 'g'))
        self._b_spin.valueChanged.connect(lambda v: self._on_spin_rgba(v, 'b'))
        if self._show_alpha:
            self._a_spin.valueChanged.connect(lambda v: self._on_spin_rgba(v, 'a'))

    def _wire_hsl(self):
        self._h_s.valueChanged.connect(lambda i: self._on_slider_hsl(i, 'h'))
        self._s_s.valueChanged.connect(lambda i: self._on_slider_hsl(i, 's'))
        self._l_s.valueChanged.connect(lambda i: self._on_slider_hsl(i, 'l'))

        self._h_spin.valueChanged.connect(lambda v: self._on_spin_hsl(v, 'h'))
        self._s_spin.valueChanged.connect(lambda v: self._on_spin_hsl(v, 's'))
        self._l_spin.valueChanged.connect(lambda v: self._on_spin_hsl(v, 'l'))

    # ---------- Conversions ----------
    def _rgba(self) -> Tuple[float, float, float, float]:
        return (self._qc.redF(), self._qc.greenF(), self._qc.blueF(), self._qc.alphaF())

    def _set_rgba(self, r: float, g: float, b: float, a: Optional[float]=None):
        a = self._qc.alphaF() if a is None else a
        self._qc.setRgbF(_clamp01(r), _clamp01(g), _clamp01(b), _clamp01(a))
        self._refresh_ui_from_qcolor()
        self._debounce_emit()

    def _set_hsl(self, h_deg: float, s: float, l: float, a: Optional[float]=None):
        # QColor expects H in 0..1 for setHslF; clip ranges
        h = (float(h_deg) % 360.0) / 360.0
        s = _clamp01(s); l = _clamp01(l)
        a = self._qc.alphaF() if a is None else _clamp01(a)
        self._qc.setHslF(h, s, l, a)
        self._refresh_ui_from_qcolor()
        self._debounce_emit()

    # ---------- Event handlers ----------
    def _on_slider_rgba(self, i: int, comp: str):
        if self._updating: return
        t = i / 1000.0
        r, g, b, a = self._rgba()
        if comp == 'r': r = t
        elif comp == 'g': g = t
        elif comp == 'b': b = t
        elif comp == 'a': a = t
        self._set_rgba(r, g, b, a)

    def _on_spin_rgba(self, v: float, comp: str):
        if self._updating: return
        r, g, b, a = self._rgba()
        if comp == 'r': r = v
        elif comp == 'g': g = v
        elif comp == 'b': b = v
        elif comp == 'a': a = v
        self._set_rgba(r, g, b, a)

    def _on_slider_hsl(self, i: int, comp: str):
        if self._updating: return
        # Hue slider 0..1000 -> 0..360°
        h_deg = self._h_s.value() * 360.0 / 1000.0
        s = self._s_s.value() / 1000.0
        l = self._l_s.value() / 1000.0
        self._set_hsl(h_deg, s, l)

    def _on_spin_hsl(self, v: float, comp: str):
        if self._updating: return
        h_deg = float(self._h_spin.value())
        s = float(self._s_spin.value())
        l = float(self._l_spin.value())
        self._set_hsl(h_deg, s, l)

    def _on_hex_commit(self):
        if self._updating: return
        r, g, b, a = _parse_hex_color(self.hex_edit.text(), default=self._rgba())
        self._set_rgba(r, g, b, a)

    def _open_qt_color_dialog(self):
        dlg = QColorDialog(self._qc, self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, self._show_alpha)
        if dlg.exec():
            qc = dlg.selectedColor()
            if qc.isValid():
                self._qc = qc
                self._refresh_ui_from_qcolor()
                self._debounce_emit()

    # ---------- Sync & emit ----------
    def _refresh_ui_from_qcolor(self):
        self._updating = True
        try:
            # RGBA sliders/spins
            r, g, b, a = self._rgba()
            self._r_s.setValue(int(round(r * 1000))); self._r_spin.setValue(r)
            self._g_s.setValue(int(round(g * 1000))); self._g_spin.setValue(g)
            self._b_s.setValue(int(round(b * 1000))); self._b_spin.setValue(b)
            if self._show_alpha:
                self._a_s.setValue(int(round(a * 1000))); self._a_spin.setValue(a)

            # HSL sliders/spins
            h, s, l, _ = self._qc.getHslF()  # h in 0..1
            h_deg = (h * 360.0) % 360.0
            self._h_s.setValue(int(round(h_deg * 1000.0 / 360.0))); self._h_spin.setValue(h_deg)
            self._s_s.setValue(int(round(s * 1000))); self._s_spin.setValue(s)
            self._l_s.setValue(int(round(l * 1000))); self._l_spin.setValue(l)

            # Hex
            self.hex_edit.setText(_rgba_to_hex(r, g, b, a, include_alpha=True))

            # Swatch
            self._update_swatch_pixmap()
        finally:
            self._updating = False

    def _update_swatch_pixmap(self):
        base = _checkerboard(16)
        # composite the color on top
        size = self.btn_swatch.iconSize() or QSize(24, 24)
        w = max(16, size.width()); h = max(16, size.height())
        tiled = QPixmap(w, h)
        # tile checkerboard
        painter = QPainter(tiled)
        brush = QBrush(base)
        painter.fillRect(0, 0, w, h, brush)
        painter.fillRect(0, 0, w, h, self._qc)
        painter.end()
        self.btn_swatch.setIcon(QIcon(tiled))
        self.btn_swatch.setIconSize(QSize(w, h))

    def _debounce_emit(self):
        if self._debounce_ms <= 0:
            self._emit_color(); return
        self._debouncer.start(self._debounce_ms)

    def _emit_color(self):
        r, g, b, a = self._rgba()
        self.colorChanged.emit(r, g, b, a)
