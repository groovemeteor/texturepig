
# ui/inspector/fields.py
from __future__ import annotations
from typing import Tuple

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QHBoxLayout, QVBoxLayout,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QFrame, QSlider,
    QStyleOptionSlider, QStyle, QPushButton
)

from texture_pig.ui.palette.color_field import ColorField
from texture_pig.ui.commands.undo_commands import SetNodeParamCommand

# Debounce delay for sliders (ms)
SLIDER_DEBOUNCE_MS = 100


class HandleOnlySlider(QSlider):
    """Slider that only responds to dragging the handle, ignoring track clicks."""

    def mousePressEvent(self, event):
        # Check if click is on the handle
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self
        )
        if handle_rect.contains(event.pos()):
            super().mousePressEvent(event)
        # else: ignore click on track


class FieldBuilder:
    """
    Helper to add parameter controls into an Inspector form.
    - All widgets propagate changes via inspector._on_change(name, value)
    - ColorField changes push SetNodeParamCommand directly (with immutable tuple)
    """

    def __init__(self, inspector: 'Inspector'):
        self.inspector = inspector
        self.form: QFormLayout = inspector.form

    # ---------- Expose button helper ----------

    def _wrap_with_expose_button(self, param_name: str, widget: QWidget) -> QWidget:
        """Wrap a widget with an expose/unexpose button for scalar input creation."""
        nitem = self.inspector.current_node_item
        if not nitem:
            return widget

        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Add the main widget
        layout.addWidget(widget, stretch=1)

        # Create expose button
        btn = QPushButton()
        btn.setFixedSize(20, 20)
        btn.setToolTip("Expose as scalar input" if not nitem.is_param_exposed(param_name)
                       else "Remove scalar input")

        # Style based on exposed state
        is_exposed = nitem.is_param_exposed(param_name)
        btn.setText("−" if is_exposed else "+")
        btn.setStyleSheet(
            "QPushButton { background: #4dd0e1; color: #000; font-weight: bold; border-radius: 3px; }"
            if is_exposed else
            "QPushButton { background: #555; color: #aaa; font-weight: bold; border-radius: 3px; }"
            "QPushButton:hover { background: #666; }"
        )

        def toggle_expose():
            if nitem.is_param_exposed(param_name):
                nitem.unexpose_param(param_name)
                btn.setText("+")
                btn.setToolTip("Expose as scalar input")
                btn.setStyleSheet(
                    "QPushButton { background: #555; color: #aaa; font-weight: bold; border-radius: 3px; }"
                    "QPushButton:hover { background: #666; }"
                )
            else:
                nitem.expose_param(param_name)
                btn.setText("−")
                btn.setToolTip("Remove scalar input")
                btn.setStyleSheet(
                    "QPushButton { background: #4dd0e1; color: #000; font-weight: bold; border-radius: 3px; }"
                )

        btn.clicked.connect(toggle_expose)
        layout.addWidget(btn)

        return wrapper

    # ---------- Simple fields ----------

    def add_float(self, name: str, value: float, vmin: float, vmax: float, step: float,
                  exposable: bool = True):
        box = QDoubleSpinBox()
        box.setDecimals(6)
        box.setRange(vmin, vmax)
        box.setSingleStep(step)
        box.setValue(float(value))
        box.setKeyboardTracking(False)  # Don't emit valueChanged while typing

        # Track original value for proper undo
        original_value = [float(value)]
        last_committed = [float(value)]  # Track last committed value to avoid duplicates

        def on_value_changed(v: float):
            # Called on arrow buttons and when Enter is pressed
            new_val = float(v)
            if new_val != last_committed[0]:
                self.inspector._on_change(name, new_val, original_value[0])
                last_committed[0] = new_val
                original_value[0] = new_val

        box.valueChanged.connect(on_value_changed)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, box)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, box)
        return box

    def add_int(self, name: str, value: int, vmin: int, vmax: int, step: int = 1,
                exposable: bool = True):
        box = QSpinBox()
        box.setRange(vmin, vmax)
        box.setSingleStep(step)
        box.setValue(int(value))
        box.setKeyboardTracking(False)  # Don't emit valueChanged while typing

        # Track original value for proper undo
        original_value = [int(value)]
        last_committed = [int(value)]  # Track last committed value to avoid duplicates

        def on_value_changed(v: int):
            # Called on arrow buttons and when Enter is pressed
            new_val = int(v)
            if new_val != last_committed[0]:
                self.inspector._on_change(name, new_val, original_value[0])
                last_committed[0] = new_val
                original_value[0] = new_val

        box.valueChanged.connect(on_value_changed)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, box)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, box)
        return box

    def add_bool(self, name: str, value: bool):
        cb = QCheckBox()
        cb.setChecked(bool(value))
        cb.toggled.connect(lambda v, n=name: self.inspector._on_change(n, bool(v)))
        self.form.addRow(name, cb)
        return cb

    def add_mode_dropdown(self, name: str, current_value: str, options):
        cb = QComboBox()
        cb.addItems(list(options))
        try:
            idx = options.index(current_value)
        except ValueError:
            idx = 0
        cb.setCurrentIndex(idx)
        cb.currentTextChanged.connect(lambda text, n=name: self.inspector._on_change(n, str(text)))
        self.form.addRow(name, cb)
        return cb

    # ---------- Color field (RGBA) ----------

    def add_color_fields(self, name: str, rgba_tuple):
        """
        Unified color editor (RGBA/HSL/Hex).
        Pushes a SetNodeParamCommand('color', old_tuple, new_tuple) for undo/redo.
        """
        try:
            r, g, b, a = rgba_tuple
        except Exception:
            r, g, b, a = 0.0, 0.0, 0.0, 1.0

        w = ColorField((float(r), float(g), float(b), float(a)),
                       self.inspector, live_debounce_ms=60, show_alpha=True)

        def on_color_changed(rf, gf, bf, af):
            nitem = self.inspector.current_node_item
            if not nitem:
                return
            n = nitem.backend_node
            try:
                old_tuple = tuple(getattr(n, 'color'))
            except Exception:
                old_tuple = (float(r), float(g), float(b), float(a))

            new_tuple = (float(rf), float(gf), float(bf), float(af))
            cmd = SetNodeParamCommand(self.inspector.editor, nitem, 'color', old_tuple, new_tuple)
            self.inspector.editor.undo_stack.push(cmd)
            self.inspector.editor.update_previews_from(nitem)

        w.colorChanged.connect(on_color_changed)
        self.form.addRow(name, w)
        return w

    def add_rgb_color_field(self, label: str, attr_name: str, rgb_tuple):
        """
        Color editor for RGB-only attributes (no alpha).
        Pushes a SetNodeParamCommand(attr_name, old_tuple, new_tuple) for undo/redo.
        """
        try:
            r, g, b = rgb_tuple[:3]
        except Exception:
            r, g, b = 0.0, 0.0, 0.0

        w = ColorField((float(r), float(g), float(b), 1.0),
                       self.inspector, live_debounce_ms=60, show_alpha=False)

        def on_color_changed(rf, gf, bf, af):
            nitem = self.inspector.current_node_item
            if not nitem:
                return
            n = nitem.backend_node
            try:
                old_tuple = tuple(getattr(n, attr_name))
            except Exception:
                old_tuple = (float(r), float(g), float(b))

            new_tuple = (float(rf), float(gf), float(bf))
            cmd = SetNodeParamCommand(self.inspector.editor, nitem, attr_name, old_tuple, new_tuple)
            self.inspector.editor.undo_stack.push(cmd)
            self.inspector.editor.update_previews_from(nitem)

        w.colorChanged.connect(on_color_changed)
        self.form.addRow(label, w)
        return w

    def add_gradient_editor(self, label: str, attr_name: str, stops_tuple):
        """
        Add a visual gradient editor for color_stops.
        Pushes SetNodeParamCommand for undo/redo.
        """
        from texture_pig.ui.palette.gradient_editor import GradientStopEditor

        # Normalize input
        try:
            stops = tuple(stops_tuple)
        except Exception:
            stops = ((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))

        editor = GradientStopEditor(stops=stops, parent=self.inspector)

        def on_stops_changed(new_stops):
            nitem = self.inspector.current_node_item
            if not nitem:
                return
            n = nitem.backend_node

            try:
                old_stops = tuple(getattr(n, attr_name))
            except Exception:
                old_stops = stops

            cmd = SetNodeParamCommand(
                self.inspector.editor,
                nitem,
                attr_name,
                old_stops,
                new_stops
            )
            self.inspector.editor.undo_stack.push(cmd)
            self.inspector.editor.update_previews_from(nitem)

        editor.stopsChanged.connect(on_stops_changed)
        self.form.addRow(label, editor)
        return editor

    # ---------- Separators ----------

    def add_thin_separator(self, top_margin: int = 4, bottom_margin: int = 4):
        """Add a subtle horizontal separator line to the form."""
        container = QWidget(self.inspector)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, top_margin, 0, bottom_margin)
        layout.setSpacing(0)

        line = QFrame(container)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color: #3a3a3a; background: #3a3a3a;")

        layout.addWidget(line)
        self.form.addRow(container)
        return line

    # ---------- Sliders with spin boxes ----------

    def add_float_with_slider(self, name: str, value: float,
                              vmin: float, vmax: float, step: float,
                              slider_resolution: int = 10000,
                              exposable: bool = True) -> Tuple[QWidget, QSlider, QDoubleSpinBox]:
        """Simple float slider without lazy-follow easing. For most properties."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(vmin, vmax)
        spin.setSingleStep(step)
        spin.setValue(float(value))
        spin.setKeyboardTracking(False)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(int(slider_resolution))
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::sub-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::add-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -6px 0;
                background: #777;
                border-radius: 7px;
                border: none;
            }
            QSlider::handle:horizontal:hover {
                background: #999;
            }
            QSlider::handle:horizontal:pressed {
                background: #bbb;
            }
        """)

        def f2i(f: float) -> int:
            t = (float(f) - float(vmin)) / (float(vmax) - float(vmin)) if vmax != vmin else 0.0
            return int(round(np.clip(t, 0.0, 1.0) * slider_resolution))

        def i2f(i: int) -> float:
            t = float(i) / float(slider_resolution)
            return float(vmin) + t * (float(vmax) - float(vmin))

        slider.setValue(f2i(value))

        layout.addWidget(slider, stretch=3)
        layout.addWidget(spin, stretch=1)

        pending_value = [float(value)]
        original_value = [float(value)]
        editing_node_item = [self.inspector.current_node_item]

        debounce_timer = QTimer(row)
        debounce_timer.setSingleShot(True)

        def commit_value():
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_change(name, pending_value[0], original_value[0])
            original_value[0] = pending_value[0]

        debounce_timer.timeout.connect(commit_value)

        def on_slider_pressed():
            debounce_timer.stop()
            original_value[0] = float(spin.value())

        def on_slider_released():
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_slider_changed(i: int):
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            f = i2f(i)
            spin.blockSignals(True)
            spin.setValue(f)
            spin.blockSignals(False)
            pending_value[0] = float(f)
            self.inspector._on_live_change(name, f)

        def on_spin_value_changed(f: float):
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            i = f2i(f)
            slider.blockSignals(True)
            slider.setValue(i)
            slider.blockSignals(False)
            pending_value[0] = float(f)
            self.inspector._on_live_change(name, f)
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_spin_finished():
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            debounce_timer.stop()
            f = float(spin.value())
            pending_value[0] = float(f)
            self.inspector._on_change(name, f, original_value[0])
            original_value[0] = f

        slider.sliderPressed.connect(on_slider_pressed)
        slider.sliderReleased.connect(on_slider_released)
        slider.valueChanged.connect(on_slider_changed)
        spin.valueChanged.connect(on_spin_value_changed)
        spin.editingFinished.connect(on_spin_finished)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, row)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, row)
        return row, slider, spin

    def add_float_scale_slider(self, name: str, value: float,
                               vmin: float, vmax: float, step: float,
                               slider_resolution: int = 10000,
                               exposable: bool = True) -> Tuple[QWidget, QSlider, QDoubleSpinBox]:
        """Float slider with lazy-follow easing. Use only for scale, scale_x, scale_y."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(vmin, vmax)
        spin.setSingleStep(step)
        spin.setValue(float(value))
        spin.setKeyboardTracking(False)

        slider = HandleOnlySlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(int(slider_resolution))
        # Subtle slider styling - thin gray groove, round handle
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::sub-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::add-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -6px 0;
                background: #777;
                border-radius: 7px;
                border: none;
            }
            QSlider::handle:horizontal:hover {
                background: #999;
            }
            QSlider::handle:horizontal:pressed {
                background: #bbb;
            }
        """)

        def f2i(f: float) -> int:
            t = (float(f) - float(vmin)) / (float(vmax) - float(vmin)) if vmax != vmin else 0.0
            return int(round(np.clip(t, 0.0, 1.0) * slider_resolution))

        def i2f(i: int) -> float:
            t = float(i) / float(slider_resolution)
            return float(vmin) + t * (float(vmax) - float(vmin))

        slider.setValue(f2i(value))

        layout.addWidget(slider, stretch=3)
        layout.addWidget(spin, stretch=1)

        # State tracking
        pending_value = [float(value)]
        original_value = [float(value)]  # Value before any live changes
        is_dragging = [False]
        drag_start_pos = [0]  # Slider position at drag start

        # Lazy follow: value lags behind mouse, catching up over distance
        ramp_distance = slider_resolution * 0.20  # Distance to reach full speed (20% of range)
        initial_factor = 0.05  # Start at 5% speed

        # Debounce timer for downstream updates (after mouse release or spin arrows)
        debounce_timer = QTimer(row)
        debounce_timer.setSingleShot(True)

        # Preview debounce timer - only update preview after slider stops moving
        PREVIEW_DEBOUNCE_MS = 80
        preview_timer = QTimer(row)
        preview_timer.setSingleShot(True)

        # Track the node item we're editing (for safety checks)
        editing_node_item = [self.inspector.current_node_item]

        def trigger_preview():
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_live_change(name, pending_value[0])

        preview_timer.timeout.connect(trigger_preview)

        def commit_value():
            # Safety check: ensure we're still editing the same node
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_change(name, pending_value[0], original_value[0])
            # Reset original to current for next edit
            original_value[0] = pending_value[0]

        debounce_timer.timeout.connect(commit_value)

        def on_slider_pressed():
            is_dragging[0] = True
            debounce_timer.stop()
            preview_timer.stop()  # Stop preview timer on new drag
            # Capture original value and position at start of drag
            original_value[0] = float(spin.value())
            drag_start_pos[0] = f2i(original_value[0])
            # Restore slider position to prevent any jump from click offset
            slider.blockSignals(True)
            slider.setValue(drag_start_pos[0])
            slider.blockSignals(False)

        def on_slider_released():
            is_dragging[0] = False
            # Snap slider to match the actual (lagged) value
            slider.blockSignals(True)
            slider.setValue(f2i(pending_value[0]))
            slider.blockSignals(False)
            # Trigger preview immediately on release
            preview_timer.stop()
            trigger_preview()
            # Start timer for downstream update after release
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_slider_moved(i: int):
            # Only fires during actual dragging, not on track clicks
            if self.inspector.current_node_item is not editing_node_item[0]:
                return

            # Calculate raw delta from drag start (where mouse is relative to start)
            raw_delta = i - drag_start_pos[0]
            abs_delta = abs(raw_delta)

            # Lazy follow: starts slow, ramps up to 100%
            if abs_delta <= ramp_distance and ramp_distance > 0:
                t = abs_delta / ramp_distance
                factor = initial_factor + (1.0 - initial_factor) * t
            else:
                factor = 1.0

            # The lagged position trails behind the mouse
            lagged_delta = raw_delta * factor
            lagged_pos = drag_start_pos[0] + lagged_delta
            lagged_pos = max(0, min(slider_resolution, lagged_pos))

            f = i2f(int(lagged_pos))
            spin.blockSignals(True)
            spin.setValue(f)
            spin.blockSignals(False)
            pending_value[0] = float(f)
            # Debounce preview update - only trigger after slider stops moving for 300ms
            preview_timer.start(PREVIEW_DEBOUNCE_MS)

        def on_spin_value_changed(f: float):
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            # Sync slider (without triggering sliderMoved)
            i = f2i(f)
            slider.blockSignals(True)
            slider.setValue(i)
            slider.blockSignals(False)
            pending_value[0] = float(f)
            # Live update current node
            self.inspector._on_live_change(name, f)
            # Debounce for arrows (valueChanged fires for arrows but not Enter)
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_spin_finished():
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            # Enter key or focus loss - commit immediately
            debounce_timer.stop()
            f = float(spin.value())
            pending_value[0] = float(f)
            self.inspector._on_change(name, f, original_value[0])
            # Reset original to current for next edit
            original_value[0] = f

        slider.sliderPressed.connect(on_slider_pressed)
        slider.sliderReleased.connect(on_slider_released)
        slider.sliderMoved.connect(on_slider_moved)  # Use sliderMoved instead of valueChanged
        spin.valueChanged.connect(on_spin_value_changed)
        spin.editingFinished.connect(on_spin_finished)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, row)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, row)
        return row, slider, spin

    def add_int_with_slider(self, name: str, value: int, vmin: int, vmax: int, step: int = 1,
                            exposable: bool = True) -> Tuple[QWidget, QSlider, QSpinBox]:
        """Simple int slider without lazy-follow easing. For most properties."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        spin = QSpinBox()
        spin.setRange(vmin, vmax)
        spin.setSingleStep(step)
        spin.setValue(int(value))
        spin.setKeyboardTracking(False)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(int(vmin))
        slider.setMaximum(int(vmax))
        slider.setSingleStep(int(step))
        slider.setValue(int(value))
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::sub-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::add-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -6px 0;
                background: #777;
                border-radius: 7px;
                border: none;
            }
            QSlider::handle:horizontal:hover {
                background: #999;
            }
            QSlider::handle:horizontal:pressed {
                background: #bbb;
            }
        """)

        pending_value = [int(value)]
        original_value = [int(value)]
        editing_node_item = [self.inspector.current_node_item]

        debounce_timer = QTimer(row)
        debounce_timer.setSingleShot(True)

        def commit_value():
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_change(name, pending_value[0], original_value[0])
            original_value[0] = pending_value[0]

        debounce_timer.timeout.connect(commit_value)

        def on_slider_pressed():
            debounce_timer.stop()
            original_value[0] = int(spin.value())

        def on_slider_released():
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_slider_changed(i: int):
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            spin.blockSignals(True)
            spin.setValue(i)
            spin.blockSignals(False)
            pending_value[0] = int(i)
            self.inspector._on_live_change(name, i)

        def on_spin_value_changed(i: int):
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            slider.blockSignals(True)
            slider.setValue(i)
            slider.blockSignals(False)
            pending_value[0] = int(i)
            self.inspector._on_live_change(name, i)
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_spin_finished():
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            debounce_timer.stop()
            i = int(spin.value())
            pending_value[0] = int(i)
            self.inspector._on_change(name, i, original_value[0])
            original_value[0] = i

        slider.sliderPressed.connect(on_slider_pressed)
        slider.sliderReleased.connect(on_slider_released)
        slider.valueChanged.connect(on_slider_changed)
        spin.valueChanged.connect(on_spin_value_changed)
        spin.editingFinished.connect(on_spin_finished)

        layout.addWidget(slider, stretch=3)
        layout.addWidget(spin, stretch=1)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, row)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, row)
        return row, slider, spin

    def add_int_scale_slider(self, name: str, value: int, vmin: int, vmax: int, step: int = 1,
                             exposable: bool = True) -> Tuple[QWidget, QSlider, QSpinBox]:
        """Int slider with lazy-follow easing. Use only for scale properties."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        spin = QSpinBox()
        spin.setRange(vmin, vmax)
        spin.setSingleStep(step)
        spin.setValue(int(value))
        spin.setKeyboardTracking(False)

        slider = HandleOnlySlider(Qt.Horizontal)
        slider.setMinimum(int(vmin))
        slider.setMaximum(int(vmax))
        slider.setSingleStep(int(step))
        slider.setValue(int(value))
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::sub-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::add-page:horizontal {
                height: 3px;
                background: #555;
                border-radius: 1px;
                border: none;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -6px 0;
                background: #777;
                border-radius: 7px;
                border: none;
            }
            QSlider::handle:horizontal:hover {
                background: #999;
            }
            QSlider::handle:horizontal:pressed {
                background: #bbb;
            }
        """)

        # State tracking
        pending_value = [int(value)]
        original_value = [int(value)]
        is_dragging = [False]
        drag_start_pos = [0]

        # Lazy follow: value lags behind mouse, catching up over distance
        slider_range = vmax - vmin
        ramp_distance = max(1, int(slider_range * 0.20))
        initial_factor = 0.05

        # Debounce timer for downstream updates (after mouse release or spin arrows)
        debounce_timer = QTimer(row)
        debounce_timer.setSingleShot(True)

        # Preview debounce timer - only update preview after slider stops moving
        PREVIEW_DEBOUNCE_MS = 80
        preview_timer = QTimer(row)
        preview_timer.setSingleShot(True)

        # Track the node item we're editing (for safety checks)
        editing_node_item = [self.inspector.current_node_item]

        def trigger_preview():
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_live_change(name, pending_value[0])

        preview_timer.timeout.connect(trigger_preview)

        def commit_value():
            # Safety check: ensure we're still editing the same node
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            if editing_node_item[0] is None:
                return
            self.inspector._on_change(name, pending_value[0], original_value[0])
            # Reset original to current for next edit
            original_value[0] = pending_value[0]

        debounce_timer.timeout.connect(commit_value)

        def on_slider_pressed():
            is_dragging[0] = True
            debounce_timer.stop()
            preview_timer.stop()  # Stop preview timer on new drag
            # Capture original value and position at start of drag
            original_value[0] = int(spin.value())
            drag_start_pos[0] = original_value[0]
            # Restore slider position to prevent any jump from click offset
            slider.blockSignals(True)
            slider.setValue(drag_start_pos[0])
            slider.blockSignals(False)

        def on_slider_released():
            is_dragging[0] = False
            # Snap slider to match the actual (lagged) value
            slider.blockSignals(True)
            slider.setValue(pending_value[0])
            slider.blockSignals(False)
            # Trigger preview immediately on release
            preview_timer.stop()
            trigger_preview()
            # Start timer for downstream update after release
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_slider_moved(i: int):
            # Only fires during actual dragging, not on track clicks
            if self.inspector.current_node_item is not editing_node_item[0]:
                return

            # Calculate raw delta from drag start
            raw_delta = i - drag_start_pos[0]
            abs_delta = abs(raw_delta)

            # Lazy follow: starts slow, ramps up to 100%
            if abs_delta <= ramp_distance and ramp_distance > 0:
                t = abs_delta / ramp_distance
                factor = initial_factor + (1.0 - initial_factor) * t
            else:
                factor = 1.0

            # The lagged position trails behind the mouse
            lagged_delta = raw_delta * factor
            lagged_pos = drag_start_pos[0] + lagged_delta
            lagged_pos = max(vmin, min(vmax, int(round(lagged_pos))))

            spin.blockSignals(True)
            spin.setValue(lagged_pos)
            spin.blockSignals(False)
            pending_value[0] = lagged_pos
            # Debounce preview update - only trigger after slider stops moving for 300ms
            preview_timer.start(PREVIEW_DEBOUNCE_MS)

        def on_spin_value_changed(i: int):
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            # Sync slider (without triggering sliderMoved)
            slider.blockSignals(True)
            slider.setValue(i)
            slider.blockSignals(False)
            pending_value[0] = int(i)
            # Live update current node
            self.inspector._on_live_change(name, i)
            # Debounce for arrows (valueChanged fires for arrows but not Enter)
            debounce_timer.start(SLIDER_DEBOUNCE_MS)

        def on_spin_finished():
            # Safety check
            if self.inspector.current_node_item is not editing_node_item[0]:
                return
            # Enter key or focus loss - commit immediately
            debounce_timer.stop()
            i = int(spin.value())
            pending_value[0] = int(i)
            self.inspector._on_change(name, i, original_value[0])
            # Reset original to current for next edit
            original_value[0] = i

        slider.sliderPressed.connect(on_slider_pressed)
        slider.sliderReleased.connect(on_slider_released)
        slider.sliderMoved.connect(on_slider_moved)  # Use sliderMoved instead of valueChanged
        spin.valueChanged.connect(on_spin_value_changed)
        spin.editingFinished.connect(on_spin_finished)

        layout.addWidget(slider, stretch=3)
        layout.addWidget(spin, stretch=1)

        # Wrap with expose button if exposable
        if exposable:
            widget = self._wrap_with_expose_button(name, row)
            self.form.addRow(name, widget)
        else:
            self.form.addRow(name, row)
        return row, slider, spin
