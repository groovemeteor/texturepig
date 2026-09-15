from __future__ import annotations
import logging
from typing import Optional
from shiboken6 import isValid

logger = logging.getLogger(__name__)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QFormLayout, QLabel, QMessageBox, QCheckBox

from texture_pig.ui.inspector.fields import FieldBuilder
from texture_pig.ui.commands.undo_commands import SetNodeParamCommand

# Debounce delay for downstream node updates (ms)
DOWNSTREAM_UPDATE_DEBOUNCE_MS = 150

# Backend node classes
from texture_pig.nodes.core import Graph, Constant, get_scalar_param
from texture_pig.nodes.scalar import Float, Int, ScalarAdd, ScalarSub, ScalarMul, ScalarDiv, ScalarClamp
from texture_pig.nodes.generators import (
    GradientRadial, GradientLinear, GradientReflected, GradientAngle,
    PerlinNoise, WorleyNoise
)
from texture_pig.nodes.shapes import Circle, Rectangle, Triangle, Line, Stripes, HexGrid
from texture_pig.nodes.blends import Blend, Lerp
from texture_pig.nodes.filters import GaussianBlur, Transform, Invert, Levels, Combine, Split
from texture_pig.nodes.layout import Grid, RadialGrid, Mirror, Atlas
from texture_pig.nodes.image_source import ImageNode
from texture_pig.nodes.outline import Outline
from texture_pig.nodes.text import Text, get_font_names

class Inspector(QWidget):
    """
    Right-hand parameter inspector.
    Switches widget sets based on the currently selected node.
    Uses FieldBuilder helpers to keep code clean.
    """

    def __init__(self, editor: 'GraphEditor'):
        super().__init__()
        self.editor = editor
        self.form = QFormLayout(self)
        self.current_node_item: Optional['NodeItem'] = None
        self._in_change = False  # Guard against re-entrant calls

        # Debounce timer for downstream updates
        self._downstream_timer = QTimer(self)
        self._downstream_timer.setSingleShot(True)
        self._downstream_timer.timeout.connect(self._update_downstream_nodes)

    # ---------- Public API ----------

    def _get_effective_value(self, node, param_name: str, default):
        """
        Get the effective value of a parameter, checking for scalar connections first.
        If the parameter is connected to a scalar input, returns the connected node's value.
        Otherwise returns the stored attribute value.
        """
        return get_scalar_param(node, param_name, default)

    def _is_param_connected(self, node, param_name: str) -> bool:
        """Check if a parameter has a scalar connection."""
        inputs = getattr(node, 'inputs', {})
        connection = inputs.get(param_name)
        if connection is not None:
            if isinstance(connection, tuple):
                upstream_node, _ = connection
            else:
                upstream_node = connection
            if hasattr(upstream_node, 'get_scalar_value') and callable(upstream_node.get_scalar_value):
                return True
        return False

    def set_node(self, node_item: Optional['NodeItem']):
        # Stop any pending timers before clearing widgets
        self._downstream_timer.stop()

        # Clear form
        while self.form.rowCount():
            self.form.removeRow(0)

        self.current_node_item = node_item
        if not node_item:
            self.form.addRow(QLabel('No selection'))
            return

        fb = FieldBuilder(self)
        n = node_item.backend_node

        # ---- Per-node controls ----

        if isinstance(n, Constant):
            fb.add_color_fields('color', n.color)
            fb.add_thin_separator()
            fb.add_float('scalar_value', float(getattr(n, 'scalar_value', 0.0)), -1000.0, 1000.0, 0.01, exposable=False)

        elif isinstance(n, (ScalarAdd, ScalarSub, ScalarMul, ScalarDiv)):
            # Math nodes - show a/b parameters (can be overridden by scalar inputs)
            fb.add_float_input('a', float(getattr(n, 'a', 0.0)), -1000.0, 1000.0, 0.01, exposable=False)
            fb.add_float_input('b', float(getattr(n, 'b', 0.0)), -1000.0, 1000.0, 0.01, exposable=False)

        elif isinstance(n, ScalarClamp):
            fb.add_float_input('value', float(getattr(n, 'value', 0.5)), -1000.0, 1000.0, 0.01, exposable=False)
            fb.add_float_input('min_val', float(getattr(n, 'min_val', 0.0)), -1000.0, 1000.0, 0.01, exposable=False)
            fb.add_float_input('max_val', float(getattr(n, 'max_val', 1.0)), -1000.0, 1000.0, 0.01, exposable=False)

        elif isinstance(n, Float):
            fb.add_float_input('min_value', float(getattr(n, 'min_value', 0.0)), -1000.0, 1000.0, 0.01, exposable=False)
            fb.add_float_input('max_value', float(getattr(n, 'max_value', 1.0)), -1000.0, 1000.0, 0.01, exposable=False)
            fb.add_thin_separator()
            # Dynamic slider based on min/max (ensure valid range)
            min_v = float(getattr(n, 'min_value', 0.0))
            max_v = float(getattr(n, 'max_value', 1.0))
            if min_v > max_v:
                min_v, max_v = max_v, min_v  # Swap to ensure valid range
            if min_v == max_v:
                max_v = min_v + 1.0  # Ensure non-zero range
            fb.add_float_with_slider('value', float(getattr(n, 'value', 0.5)),
                                     min_v, max_v, 0.001, slider_resolution=1000, exposable=False)

        elif isinstance(n, Int):
            fb.add_int_input('min_value', int(getattr(n, 'min_value', 0)), -2**31, 2**31 - 1, 1, exposable=False)
            fb.add_int_input('max_value', int(getattr(n, 'max_value', 100)), -2**31, 2**31 - 1, 1, exposable=False)
            fb.add_thin_separator()
            # Dynamic slider based on min/max (ensure valid range)
            min_v = int(getattr(n, 'min_value', 0))
            max_v = int(getattr(n, 'max_value', 100))
            if min_v > max_v:
                min_v, max_v = max_v, min_v  # Swap to ensure valid range
            if min_v == max_v:
                max_v = min_v + 1  # Ensure non-zero range
            fb.add_int_input('value', int(getattr(n, 'value', 0)), min_v, max_v, 1, exposable=False)

        elif isinstance(n, PerlinNoise):
            fb.add_int('seed', n.seed if n.seed is not None else 0, -2 ** 31, 2 ** 31 - 1, 1)
            fb.add_float('scale', n.scale, 1e-3, 1024, 0.1)
            fb.add_int('octaves', n.octaves, 1, 10, 1)
            fb.add_float('persistence', n.persistence, 0.0, 1.0, 0.01)
            fb.add_float('lacunarity', n.lacunarity, 0.5, 8.0, 0.1)

        elif isinstance(n, WorleyNoise):
            fb.add_int('seed', n.seed if n.seed is not None else 0, -2 ** 31, 2 ** 31 - 1, 1)
            fb.add_int('points', n.points, 1, 4096, 1)
            fb.add_float('jitter', n.jitter, 0.0, 4.0, 0.01)

        elif isinstance(n, GradientLinear):
            fb.add_float('angle_deg', n.angle_deg, -360, 360, 1.0)
            fb.add_float('offset', n.offset, -1.0, 1.0, 0.01)
            fb.add_mode_dropdown('output_mode', getattr(n, 'output_mode', 'rgb'), ['rgb', 'alpha', 'color'])
            fb.add_bool('invert', bool(getattr(n, 'invert', False)))
            if getattr(n, 'output_mode', 'rgb') == 'color':
                fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, GradientRadial):
            fb.add_float('cx', n.cx, 0.0, 1.0, 0.01)
            fb.add_float('cy', n.cy, 0.0, 1.0, 0.01)
            fb.add_float('radius', n.radius, 0.0, 2.0, 0.01)
            fb.add_mode_dropdown('output_mode', getattr(n, 'output_mode', 'rgb'), ['rgb', 'alpha', 'color'])
            fb.add_bool('invert', bool(getattr(n, 'invert', False)))
            if getattr(n, 'output_mode', 'rgb') == 'color':
                fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, GradientReflected):
            fb.add_float('angle_deg', n.angle_deg, -360, 360, 1.0)
            fb.add_float_with_slider('midpoint', float(getattr(n, 'midpoint', 0.5)),
                                     0.0, 1.0, 0.001, slider_resolution=1000)
            fb.add_mode_dropdown('output_mode', getattr(n, 'output_mode', 'rgb'), ['rgb', 'alpha', 'color'])
            fb.add_bool('invert', bool(getattr(n, 'invert', False)))
            if getattr(n, 'output_mode', 'rgb') == 'color':
                fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, GradientAngle):
            fb.add_float_with_slider('cx', float(getattr(n, 'cx', 0.5)), 0.0, 1.0, 0.001, slider_resolution=1000)
            fb.add_float_with_slider('cy', float(getattr(n, 'cy', 0.5)), 0.0, 1.0, 0.001, slider_resolution=1000)
            fb.add_float('angle_offset_deg', float(getattr(n, 'angle_offset_deg', 0.0)), -360.0, 360.0, 1.0)
            fb.add_mode_dropdown('output_mode', getattr(n, 'output_mode', 'rgb'), ['rgb', 'alpha', 'color'])
            fb.add_bool('invert', bool(getattr(n, 'invert', False)))
            if getattr(n, 'output_mode', 'rgb') == 'color':
                fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, Circle):
            fb.add_float_with_slider('cx', float(self._get_effective_value(n, 'cx', n.cx)), 0.0, 1.0, 0.001,
                                     slider_resolution=1000, connected=self._is_param_connected(n, 'cx'))
            fb.add_float_with_slider('cy', float(self._get_effective_value(n, 'cy', n.cy)), 0.0, 1.0, 0.001,
                                     slider_resolution=1000, connected=self._is_param_connected(n, 'cy'))
            fb.add_float_with_slider('radius', float(self._get_effective_value(n, 'radius', n.radius)), 0.0, 1.0, 0.001,
                                     slider_resolution=1000, connected=self._is_param_connected(n, 'radius'))

            fb.add_float_with_slider('edge_softness', float(self._get_effective_value(n, 'edge_softness', getattr(n, 'edge_softness', 0.0))),
                                     0.0, 0.5, 0.001, slider_resolution=1000, connected=self._is_param_connected(n, 'edge_softness'))

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

            fb.add_thin_separator()
            fb.add_bool('use_gradient', bool(getattr(n, 'use_gradient', False)))
            fb.add_mode_dropdown('gradient_axis', getattr(n, 'gradient_axis', 'x'), ['x', 'y'])
            fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, Rectangle):
            fb.add_float_with_slider('cx', float(self._get_effective_value(n, 'cx', n.cx)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'cx'))
            fb.add_float_with_slider('cy', float(self._get_effective_value(n, 'cy', n.cy)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'cy'))
            fb.add_float_with_slider('width', float(self._get_effective_value(n, 'width', n.width)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'width'))
            fb.add_float_with_slider('height', float(self._get_effective_value(n, 'height', n.height)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'height'))

            fb.add_float_with_slider('rotation_deg', float(self._get_effective_value(n, 'rotation_deg', n.rotation_deg)),
                                     -360.0, 360.0, 1.0, slider_resolution=1440,
                                     connected=self._is_param_connected(n, 'rotation_deg'))

            if hasattr(n, 'corner_radius'):
                fb.add_float_with_slider('corner_radius', float(self._get_effective_value(n, 'corner_radius', getattr(n, 'corner_radius', 0.0))),
                                         0.0, 0.5, 0.001, slider_resolution=1000,
                                         connected=self._is_param_connected(n, 'corner_radius'))

            fb.add_float_with_slider('edge_softness', float(self._get_effective_value(n, 'edge_softness', getattr(n, 'edge_softness', 0.0))),
                                     0.0, 0.5, 0.001, slider_resolution=1000,
                                     connected=self._is_param_connected(n, 'edge_softness'))

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

            fb.add_thin_separator()
            fb.add_bool('use_gradient', bool(getattr(n, 'use_gradient', False)))
            fb.add_mode_dropdown('gradient_axis', getattr(n, 'gradient_axis', 'x'), ['x', 'y'])
            fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, Triangle):
            fb.add_float_with_slider('cx', float(self._get_effective_value(n, 'cx', n.cx)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'cx'))
            fb.add_float_with_slider('cy', float(self._get_effective_value(n, 'cy', n.cy)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'cy'))

            fb.add_float_with_slider('base', float(self._get_effective_value(n, 'base', n.base)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'base'))

            is_equi = bool(getattr(n, 'equilateral', True))
            equi_cb = fb.add_bool('equilateral', is_equi)
            equi_cb.setToolTip("When enabled, height = sqrt(3)/2 × base. Height control is disabled.")

            height_row, _, _ = fb.add_float_with_slider(
                'height', float(self._get_effective_value(n, 'height', n.height)), 0.0, 1.0, 0.001, 1000,
                connected=self._is_param_connected(n, 'height')
            )
            height_row.setEnabled(not is_equi)

            fb.add_float_scale_slider('scale', float(self._get_effective_value(n, 'scale', getattr(n, 'scale', 1.0))), 0.0, 4.0, 0.01, 400,
                                      connected=self._is_param_connected(n, 'scale'))

            fb.add_float_with_slider('rotation_deg', float(self._get_effective_value(n, 'rotation_deg', n.rotation_deg)),
                                     -360.0, 360.0, 1.0, 1440,
                                     connected=self._is_param_connected(n, 'rotation_deg'))

            fb.add_float_with_slider('edge_softness', float(self._get_effective_value(n, 'edge_softness', getattr(n, 'edge_softness', 0.0))),
                                     0.0, 0.5, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'edge_softness'))

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

            fb.add_thin_separator()
            fb.add_bool('use_gradient', bool(getattr(n, 'use_gradient', False)))
            fb.add_mode_dropdown('gradient_axis', getattr(n, 'gradient_axis', 'x'), ['x', 'y'])
            fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

            if isinstance(equi_cb, QCheckBox):
                equi_cb.toggled.connect(lambda checked: height_row.setEnabled(not checked))
                equi_cb.toggled.connect(lambda checked: self._on_change('equilateral', checked))

        elif isinstance(n, Line):
            fb.add_float_with_slider('x0', float(self._get_effective_value(n, 'x0', n.x0)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'x0'))
            fb.add_float_with_slider('y0', float(self._get_effective_value(n, 'y0', n.y0)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'y0'))
            fb.add_float_with_slider('x1', float(self._get_effective_value(n, 'x1', n.x1)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'x1'))
            fb.add_float_with_slider('y1', float(self._get_effective_value(n, 'y1', n.y1)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'y1'))

            fb.add_float_with_slider('width', float(self._get_effective_value(n, 'width', n.width)), 0.0, 1.0, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'width'))

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

        elif isinstance(n, Stripes):
            fb.add_int_with_slider('count', int(self._get_effective_value(n, 'count', getattr(n, 'count', 3))), 1, 32, 1,
                                   connected=self._is_param_connected(n, 'count'))
            fb.add_float_with_slider('thickness', float(self._get_effective_value(n, 'thickness', getattr(n, 'thickness', 0.05))), 0.001, 0.5, 0.001, 1000,
                                     connected=self._is_param_connected(n, 'thickness'))
            fb.add_float_with_slider('rotation_deg', float(self._get_effective_value(n, 'rotation_deg', getattr(n, 'rotation_deg', 0.0))), -180.0, 180.0, 1.0, 720,
                                     connected=self._is_param_connected(n, 'rotation_deg'))
            fb.add_float_with_slider('edge_softness', float(self._get_effective_value(n, 'edge_softness', getattr(n, 'edge_softness', 0.0))), 0.0, 0.2, 0.001, 200,
                                     connected=self._is_param_connected(n, 'edge_softness'))
            fb.add_bool('frame', bool(getattr(n, 'frame', False)))

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

        elif isinstance(n, Blend):
            modes = ['normal', 'add', 'subtract', 'multiply', 'screen', 'overlay']
            fb.add_mode_dropdown('mode', getattr(n, 'mode', 'normal'), modes)
            fb.add_float('opacity', float(getattr(n, 'opacity', 1.0)), 0.0, 1.0, 0.01)

            fb.add_bool('affect_alpha', bool(getattr(n, 'affect_alpha', True)))
            ch_opts = ['a', 'luma', 'r', 'g', 'b']
            fb.add_mode_dropdown('mask_channel', getattr(n, 'mask_channel', 'a'), ch_opts)

        elif isinstance(n, Lerp):
            self.form.addRow(QLabel("Mixes Input A and B using Mask T"))
            self.form.addRow(QLabel("T Alpha = 0.0 -> Input A"))
            self.form.addRow(QLabel("T Alpha = 1.0 -> Input B"))

        elif isinstance(n, GaussianBlur):
            fb.add_float_with_slider('sigma', float(getattr(n, 'sigma', 2.0)), 0.0, 64.0, 0.1)
            fb.add_bool('alpha_only', bool(getattr(n, 'alpha_only', False)))

        elif isinstance(n, Transform):
            fb.add_float_with_slider('tx', float(getattr(n, 'tx', 0.0)), -1.0, 1.0, 0.001)
            fb.add_float_with_slider('ty', float(getattr(n, 'ty', 0.0)), -1.0, 1.0, 0.001)

            fb.add_float_scale_slider('scale', float(getattr(n, 'scale', 1.0)),
                                      0.01, 10.0, 0.01, 2000)
            fb.add_float_scale_slider('scale_x', float(getattr(n, 'scale_x', 1.0)), 0.01, 10.0, 0.01, 2000)
            fb.add_float_scale_slider('scale_y', float(getattr(n, 'scale_y', 1.0)), 0.01, 10.0, 0.01, 2000)

            fb.add_float_with_slider('rotation_deg', float(getattr(n, 'rotation_deg', 0.0)), -360.0, 360.0, 1.0, 1440)

            fb.add_float_with_slider('pivot_cx', float(getattr(n, 'pivot_cx', 0.5)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('pivot_cy', float(getattr(n, 'pivot_cy', 0.5)), 0.0, 1.0, 0.001)

            fb.add_mode_dropdown('falloff_channel', getattr(n, 'falloff_channel', 'luma'),
                                 ['luma', 'a', 'r', 'g', 'b'])

        elif isinstance(n, Invert):
            fb.add_bool('invert_rgb', bool(getattr(n, 'invert_rgb', True)))
            fb.add_bool('invert_alpha', bool(getattr(n, 'invert_alpha', False)))
            fb.add_float('opacity', float(getattr(n, 'opacity', 1.0)), 0.0, 1.0, 0.01)
            ch_opts = ['a', 'luma', 'r', 'g', 'b']
            fb.add_mode_dropdown('mask_channel', getattr(n, 'mask_channel', 'a'), ch_opts)

        elif isinstance(n, Levels):
            self.form.addRow(QLabel('RGB Levels'))
            fb.add_float_with_slider('in_black', float(getattr(n, 'in_black', 0.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('in_white', float(getattr(n, 'in_white', 1.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('gamma', float(getattr(n, 'gamma', 1.0)), 0.01, 10.0, 0.01, 2000)
            fb.add_float_with_slider('out_black', float(getattr(n, 'out_black', 0.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('out_white', float(getattr(n, 'out_white', 1.0)), 0.0, 1.0, 0.001)

            self.form.addRow(QLabel('Alpha Levels'))
            fb.add_float_with_slider('a_in_black', float(getattr(n, 'a_in_black', 0.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('a_in_white', float(getattr(n, 'a_in_white', 1.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('a_gamma', float(getattr(n, 'a_gamma', 1.0)), 0.01, 10.0, 0.01, 2000)
            fb.add_float_with_slider('a_out_black', float(getattr(n, 'a_out_black', 0.0)), 0.0, 1.0, 0.001)
            fb.add_float_with_slider('a_out_white', float(getattr(n, 'a_out_white', 1.0)), 0.0, 1.0, 0.001)

            fb.add_float_with_slider('opacity', float(getattr(n, 'opacity', 1.0)), 0.0, 1.0, 0.01)
            ch_opts = ['a', 'luma', 'r', 'g', 'b']
            fb.add_mode_dropdown('mask_channel', getattr(n, 'mask_channel', 'a'), ch_opts)

        elif isinstance(n, Combine):
            self.form.addRow(QLabel('Channel Sources'))
            ch_opts = ['luma', 'r', 'g', 'b', 'a']
            fb.add_mode_dropdown('r_src', getattr(n, 'r_src', 'luma'), ch_opts)
            fb.add_mode_dropdown('g_src', getattr(n, 'g_src', 'luma'), ch_opts)
            fb.add_mode_dropdown('b_src', getattr(n, 'b_src', 'luma'), ch_opts)
            fb.add_mode_dropdown('a_src', getattr(n, 'a_src', 'a'), ch_opts)
            fb.add_bool('use_source_alpha', bool(getattr(n, 'use_source_alpha', True)))

        elif isinstance(n, Split):
            # Split has no parameters - it simply outputs R, G, B, A channels
            self.form.addRow(QLabel('Outputs: r, g, b, a'))

        elif isinstance(n, Grid):
            fb.add_int_with_slider('nx', int(getattr(n, 'nx', 2)), 1, 256, 1)
            fb.add_int_with_slider('ny', int(getattr(n, 'ny', 2)), 1, 256, 1)

            # num_inputs control with slider - max is nx * ny
            max_inputs = int(getattr(n, 'nx', 2)) * int(getattr(n, 'ny', 2))
            current_num_inputs = min(int(getattr(n, 'num_inputs', 1)), max_inputs)

            from texture_pig.ui.inspector.fields import NumericInput
            from PySide6.QtWidgets import QSlider, QHBoxLayout, QWidget as QW
            from PySide6.QtCore import Qt as QtCore

            num_row = QW()
            num_layout = QHBoxLayout(num_row)
            num_layout.setContentsMargins(0, 0, 0, 0)
            num_layout.setSpacing(8)

            num_slider = QSlider(QtCore.Horizontal)
            num_slider.setMinimum(1)
            num_slider.setMaximum(max_inputs)
            num_slider.setValue(current_num_inputs)

            num_spin = NumericInput(current_num_inputs, 1, max_inputs, 1, decimals=0, is_int=True)

            def on_grid_num_inputs_slider(value):
                num_spin.setValue(int(value))
                self._on_change('num_inputs', int(value))
                self._rebuild_multi_input_ports(self.current_node_item, int(value))

            def on_grid_num_inputs_spin(value):
                num_slider.blockSignals(True)
                num_slider.setValue(int(value))
                num_slider.blockSignals(False)
                self._on_change('num_inputs', int(value))
                self._rebuild_multi_input_ports(self.current_node_item, int(value))

            num_slider.valueChanged.connect(on_grid_num_inputs_slider)
            num_spin.connect_value_changed(on_grid_num_inputs_spin)
            num_spin.connect_editing_finished(on_grid_num_inputs_spin)

            num_layout.addWidget(num_slider, stretch=3)
            num_layout.addWidget(num_spin, stretch=0)
            self.form.addRow('num_inputs', num_row)

            fb.add_float_with_slider('region_x', float(getattr(n, 'region_x', 0.0)), 0.0, 1.0, 0.001, 1000)
            fb.add_float_with_slider('region_y', float(getattr(n, 'region_y', 0.0)), 0.0, 1.0, 0.001, 1000)
            fb.add_float_with_slider('region_w', float(getattr(n, 'region_w', 1.0)), 0.0, 1.0, 0.001, 1000)
            fb.add_float_with_slider('region_h', float(getattr(n, 'region_h', 1.0)), 0.0, 1.0, 0.001, 1000)

            fb.add_float_with_slider('pad_x', float(getattr(n, 'pad_x', 0.0)), 0.0, 0.9, 0.001, 1000)
            fb.add_float_with_slider('pad_y', float(getattr(n, 'pad_y', 0.0)), 0.0, 0.9, 0.001, 1000)

            fb.add_float_scale_slider('scale', float(getattr(n, 'scale', 1.0)), 0.0, 8.0, 0.01, 800)
            fb.add_float_scale_slider('scale_x', float(
                getattr(n, 'scale_x', getattr(n, 'scale', 1.0)) if getattr(n, 'scale_x', None) is not None else getattr(
                    n, 'scale', 1.0)),
                                      0.0, 8.0, 0.01, 800)
            fb.add_float_scale_slider('scale_y', float(
                getattr(n, 'scale_y', getattr(n, 'scale', 1.0)) if getattr(n, 'scale_y', None) is not None else getattr(
                    n, 'scale', 1.0)),
                                      0.0, 8.0, 0.01, 800)

            fb.add_bool('render_at_tile_resolution', bool(getattr(n, 'render_at_tile_resolution', True)))
            fb.add_bool('eval_cell_square', bool(getattr(n, 'eval_cell_square', True)))

            fb.add_thin_separator()
            fb.add_bool('use_gradient', bool(getattr(n, 'use_gradient', False)))
            fb.add_mode_dropdown('gradient_mode', getattr(n, 'gradient_mode', 'index'), ['index', 'column', 'row'])
            fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, RadialGrid):
            fb.add_int_with_slider('count', int(getattr(n, 'count', 8)), 1, 256, 1)

            # num_inputs control with slider - max is count
            max_inputs = int(getattr(n, 'count', 8))
            current_num_inputs = min(int(getattr(n, 'num_inputs', 1)), max_inputs)

            from texture_pig.ui.inspector.fields import NumericInput
            from PySide6.QtWidgets import QSlider, QHBoxLayout, QWidget as QW
            from PySide6.QtCore import Qt as QtCore

            num_row = QW()
            num_layout = QHBoxLayout(num_row)
            num_layout.setContentsMargins(0, 0, 0, 0)
            num_layout.setSpacing(8)

            num_slider = QSlider(QtCore.Horizontal)
            num_slider.setMinimum(1)
            num_slider.setMaximum(max_inputs)
            num_slider.setValue(current_num_inputs)

            num_spin = NumericInput(current_num_inputs, 1, max_inputs, 1, decimals=0, is_int=True)

            def on_radial_num_inputs_slider(value):
                num_spin.setValue(int(value))
                self._on_change('num_inputs', int(value))
                self._rebuild_multi_input_ports(self.current_node_item, int(value))

            def on_radial_num_inputs_spin(value):
                num_slider.blockSignals(True)
                num_slider.setValue(int(value))
                num_slider.blockSignals(False)
                self._on_change('num_inputs', int(value))
                self._rebuild_multi_input_ports(self.current_node_item, int(value))

            num_slider.valueChanged.connect(on_radial_num_inputs_slider)
            num_spin.connect_value_changed(on_radial_num_inputs_spin)
            num_spin.connect_editing_finished(on_radial_num_inputs_spin)

            num_layout.addWidget(num_slider, stretch=3)
            num_layout.addWidget(num_spin, stretch=0)
            self.form.addRow('num_inputs', num_row)

            fb.add_float_with_slider('cx', float(getattr(n, 'cx', 0.5)), 0.0, 1.0, 0.001, 1000)
            fb.add_float_with_slider('cy', float(getattr(n, 'cy', 0.5)), 0.0, 1.0, 0.001, 1000)
            fb.add_float_with_slider('radius', float(getattr(n, 'radius', 0.35)), 0.0, 1.0, 0.001, 1000)

            fb.add_float_with_slider('start_angle_deg', float(getattr(n, 'start_angle_deg', 0.0)), -360.0, 360.0, 1.0,
                                     1440)
            fb.add_float_with_slider('sweep_deg', float(getattr(n, 'sweep_deg', 360.0)), -360.0, 360.0, 1.0, 1440)
            fb.add_float_with_slider('angle_offset_deg', float(getattr(n, 'angle_offset_deg', 0.0)), -360.0, 360.0, 1.0,
                                     1440)

            fb.add_float_with_slider('tile_edge_frac', float(getattr(n, 'tile_edge_frac', 0.15)), 0.0, 1.0, 0.001, 1000)
            fb.add_mode_dropdown('rotate_mode', getattr(n, 'rotate_mode', 'none'), ['none', 'radial', 'tangent'])
            fb.add_float_with_slider('item_rotation_deg', float(getattr(n, 'item_rotation_deg', 0.0)), -360.0, 360.0,
                                     1.0, 1440)
            fb.add_mode_dropdown('pivot', getattr(n, 'pivot', 'center'), ['center', 'top', 'bottom'])

            fb.add_float_scale_slider('scale', float(getattr(n, 'scale', 1.0)), 0.0, 8.0, 0.01, 800)
            sx_val = getattr(n, 'scale_x', None)
            sy_val = getattr(n, 'scale_y', None)
            uni = float(getattr(n, 'scale', 1.0))
            fb.add_float_scale_slider('scale_x', float(sx_val if sx_val is not None else uni), 0.0, 8.0, 0.01, 800)
            fb.add_float_scale_slider('scale_y', float(sy_val if sy_val is not None else uni), 0.0, 8.0, 0.01, 800)

            fb.add_bool('render_at_tile_resolution', bool(getattr(n, 'render_at_tile_resolution', True)))

            fb.add_thin_separator()
            fb.add_bool('use_gradient', bool(getattr(n, 'use_gradient', False)))
            fb.add_gradient_editor('Gradient', 'color_stops', getattr(n, 'color_stops', None))

        elif isinstance(n, Mirror):
            fb.add_mode_dropdown('axis', getattr(n, 'axis', 'x'), ['x', 'y'])
            fb.add_mode_dropdown('side', getattr(n, 'side', 'keep_left'),
                                 ['keep_left', 'keep_right', 'keep_top', 'keep_bottom'])
            fb.add_bool('copy_center', bool(getattr(n, 'copy_center', True)))

        elif isinstance(n, Atlas):
            # Cells dropdown - maps display labels to actual values
            cells_options = ['4 (2x2)', '9 (3x3)', '16 (4x4)', '25 (5x5)', '36 (6x6)', '49 (7x7)', '64 (8x8)']
            cells_values = [4, 9, 16, 25, 36, 49, 64]
            current_cells = int(getattr(n, 'cells', 4))
            current_idx = cells_values.index(current_cells) if current_cells in cells_values else 0
            current_label = cells_options[current_idx]

            from PySide6.QtWidgets import QComboBox
            cells_cb = QComboBox()
            cells_cb.addItems(cells_options)
            cells_cb.setCurrentText(current_label)

            def on_cells_changed(text):
                idx = cells_options.index(text) if text in cells_options else 0
                new_cells = cells_values[idx]
                self._on_change('cells', new_cells)
                # Rebuild the node item's ports
                self._rebuild_atlas_ports(self.current_node_item, new_cells)

            cells_cb.currentTextChanged.connect(on_cells_changed)
            self.form.addRow('cells', cells_cb)

        elif isinstance(n, HexGrid):
            fb.add_float_with_slider('hex_size', float(getattr(n, 'hex_size', 0.2)), 0.01, 1.0, 0.01, 100)
            fb.add_float_with_slider('thickness', float(getattr(n, 'thickness', 0.02)), 0.001, 0.2, 0.001, 200)
            fb.add_mode_dropdown('orientation', getattr(n, 'orientation', 'pointy'), ['pointy', 'flat'])
            fb.add_float_with_slider('edge_softness', float(getattr(n, 'edge_softness', 0.0)), 0.0, 0.1, 0.001, 100)
            fb.add_float_with_slider('offset_x', float(getattr(n, 'offset_x', 0.0)), -1.0, 1.0, 0.01, 200)
            fb.add_float_with_slider('offset_y', float(getattr(n, 'offset_y', 0.0)), -1.0, 1.0, 0.01, 200)
            fb.add_float_with_slider('stretch_x', float(getattr(n, 'stretch_x', 1.0)), 0.1, 2.0, 0.01, 190)
            fb.add_float_with_slider('stretch_y', float(getattr(n, 'stretch_y', 1.0)), 0.1, 2.0, 0.01, 190)

            # Show tileable dimensions and Make Tileable button
            fb.add_thin_separator()
            output_size = int(self.editor.graph.size)
            tileable_w, tileable_h = n.get_tileable_dimensions(output_size)

            # Show the tileable resolution as text labels
            self.form.addRow(QLabel(f'Tileable at: {tileable_w} x {tileable_h}'))

            from PySide6.QtWidgets import QPushButton
            btn_make_tileable = QPushButton('Make Tileable')
            btn_make_tileable.setToolTip(f'Adjust stretch to make the pattern tile on a {output_size}x{output_size} texture')

            def apply_tileable_stretch():
                # Get current output size
                cur_size = int(self.editor.graph.size)
                # Reset both stretch values to 1.0 first
                self._on_change('stretch_x', 1.0)
                self._on_change('stretch_y', 1.0)
                # Calculate tileable dimensions with reset stretch
                tw, th = n.get_tileable_dimensions(cur_size)
                if n.orientation == 'pointy':
                    # Pointy-top tiles vertically, need to stretch horizontally
                    new_stretch_x = float(cur_size) / tw if tw > 0 else 1.0
                    self._on_change('stretch_x', new_stretch_x)
                else:
                    # Flat-top tiles horizontally, need to stretch vertically
                    new_stretch_y = float(cur_size) / th if th > 0 else 1.0
                    self._on_change('stretch_y', new_stretch_y)
                # Refresh inspector to show updated values
                self.set_node(self.current_node_item)

            btn_make_tileable.clicked.connect(apply_tileable_stretch)
            self.form.addRow(btn_make_tileable)

            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)

        elif isinstance(n, ImageNode):
            # File path editor row: [ QLineEdit ][ Browse… ][ Reload ]
            from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog
            row = QWidget(self)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)

            le = QLineEdit(self)
            le.setText(str(getattr(n, 'path', '') or ''))
            btn_browse = QPushButton('Browse…', self)
            btn_reload = QPushButton('Reload', self)

            hl.addWidget(le, stretch=3)
            hl.addWidget(btn_browse, stretch=0)
            hl.addWidget(btn_reload, stretch=0)
            self.form.addRow('File', row)

            fb.add_mode_dropdown('scale_mode', getattr(n, 'scale_mode', 'crop'),
                                 ['crop', 'fit', 'stretch'])

            def apply_path_from_line():
                n.set_params(path=str(le.text()))
                self.editor.update_previews_from(self.current_node_item)

            def browse():
                fn, _ = QFileDialog.getOpenFileName(self, 'Open Image', '',
                                                    'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
                if fn:
                    le.setText(fn)
                    apply_path_from_line()

            def reload():
                try:
                    n.reload()
                except Exception:
                    pass
                self.editor.update_previews_from(self.current_node_item)

            le.editingFinished.connect(apply_path_from_line)
            btn_browse.clicked.connect(browse)
            btn_reload.clicked.connect(reload)

        elif isinstance(n, Text):
            from PySide6.QtWidgets import QTextEdit, QComboBox

            # Text input (multi-line)
            text_edit = QTextEdit(self)
            text_edit.setPlainText(str(getattr(n, 'text', 'Text')))
            text_edit.setMaximumHeight(80)

            def on_text_changed():
                self._on_change('text', text_edit.toPlainText())

            text_edit.textChanged.connect(on_text_changed)
            self.form.addRow('text', text_edit)

            # Font selection dropdown
            font_cb = QComboBox(self)
            available_fonts = get_font_names()
            font_cb.addItems(available_fonts)
            current_font = str(getattr(n, 'font_name', 'Arial'))
            if current_font in available_fonts:
                font_cb.setCurrentText(current_font)
            elif available_fonts:
                font_cb.setCurrentIndex(0)

            def on_font_changed(font_name):
                self._on_change('font_name', font_name)

            font_cb.currentTextChanged.connect(on_font_changed)
            self.form.addRow('font', font_cb)

            # Font size
            fb.add_float_with_slider('font_size', float(getattr(n, 'font_size', 0.1)), 0.01, 0.5, 0.001, 490)

            # Alignment
            fb.add_mode_dropdown('align', getattr(n, 'align', 'center'), ['left', 'center', 'right'])
            fb.add_mode_dropdown('valign', getattr(n, 'valign', 'center'), ['top', 'center', 'bottom'])

            # Line spacing
            fb.add_float_with_slider('line_spacing', float(getattr(n, 'line_spacing', 1.0)), 0.5, 3.0, 0.1, 25)

            # Padding
            fb.add_float_with_slider('padding', float(getattr(n, 'padding', 0.05)), 0.0, 0.5, 0.01, 50)

            # Color
            fb.add_thin_separator()
            fb.add_color_fields('color', getattr(n, 'color', (1.0, 1.0, 1.0, 1.0)))

        elif isinstance(n, Outline):
            fb.add_int_with_slider('thickness', int(getattr(n, 'thickness', 2)), 1, 64, 1)
            fb.add_thin_separator()
            fb.add_color_fields('color', n.color)
        else:
            # Fallback: show raw attributes (optional). Currently keep silence.
            self.form.addRow(QLabel(f"No inspector for: {type(n).__name__}"))

    # ---------- Change propagation ----------

    def _on_change(self, param_name, value, old_value=None):
        """
        Create an undoable SetNodeParamCommand and refresh previews.
        - Current node updates immediately (no delay)
        - Downstream nodes update after debounce delay
        - old_value: explicit old value (used by sliders that apply live changes)
        """
        # Guard against re-entrant calls (can happen when inspector rebuilds)
        if self._in_change:
            return
        self._in_change = True

        try:
            nitem = self.current_node_item
            if not nitem or not isValid(nitem):
                return
            n = nitem.backend_node

            if param_name.startswith('color_'):
                # Consolidated color component logic
                comp_map = {'r': 0, 'g': 1, 'b': 2, 'a': 3}
                comp = param_name.split('_', 1)[1]

                if comp in comp_map:
                    current_color = list(getattr(n, 'color', (0.0, 0.0, 0.0, 1.0)))
                    old_tuple = tuple(current_color)
                    current_color[comp_map[comp]] = float(value)
                    new_tuple = tuple(current_color)

                    cmd = SetNodeParamCommand(self.editor, nitem, 'color', old_tuple, new_tuple)
                    self.editor.undo_stack.push(cmd)
            else:
                # Use explicit old_value if provided, otherwise query current value
                if old_value is None:
                    old = getattr(n, param_name, None)
                else:
                    old = old_value
                # Ensure value type consistency
                if isinstance(old, float):
                    value = float(value)
                elif isinstance(old, int) and not isinstance(value, bool):
                    value = int(value)

                cmd = SetNodeParamCommand(self.editor, nitem, param_name, old, value)
                self.editor.undo_stack.push(cmd)

                # Refresh inspector when output_mode changes (to show/hide color fields)
                # or hex_size/orientation changes (to update tileable dimensions)
                # or min_value/max_value changes (to update Float slider range)
                # Use QTimer.singleShot to defer refresh - prevents crash from destroying
                # the widget that triggered this callback while still in its signal handler
                if param_name in ('output_mode', 'hex_size', 'orientation', 'min_value', 'max_value'):
                    QTimer.singleShot(0, lambda n=nitem: self.set_node(n))

            # Note: The undo command's redo() already calls update_previews_from()
            # which updates both current node and all downstream nodes at full resolution.
            # No need to start the downstream timer here - it would just overwrite
            # full-res previews with low-res worker previews.
        finally:
            self._in_change = False

    def _on_live_change(self, param_name, value):
        """
        Live preview update - applies value and updates current node only.
        No undo command, no downstream update. Used for slider dragging.
        """
        nitem = self.current_node_item
        if not nitem or not isValid(nitem):
            return
        n = nitem.backend_node

        # Apply the value directly (no undo)
        if param_name.startswith('color_'):
            comp_map = {'r': 0, 'g': 1, 'b': 2, 'a': 3}
            comp = param_name.split('_', 1)[1]
            if comp in comp_map:
                current_color = list(getattr(n, 'color', (0.0, 0.0, 0.0, 1.0)))
                current_color[comp_map[comp]] = float(value)
                n.color = tuple(current_color)
        else:
            # Ensure value type consistency
            old = getattr(n, param_name, None)
            if isinstance(old, float):
                value = float(value)
            elif isinstance(old, int) and not isinstance(value, bool):
                value = int(value)
            setattr(n, param_name, value)

        # Invalidate node cache so it re-renders
        # Only clear this node's cache - don't cascade to dependents during live preview
        # (cascading is expensive and unnecessary since we only update current node)
        if hasattr(n, '_cache'):
            if isinstance(n._cache, dict):
                n._cache.clear()
            else:
                n._cache = None
        if hasattr(n, '_dirty'):
            n._dirty = True
        # Also bump generation for nodes using GenerationCacheMixin (like RadialGrid)
        if hasattr(n, '_bump_generation'):
            n._bump_generation()

        # Update current node preview (synchronous for now - threading caused race conditions)
        try:
            nitem.update_preview(self.editor.graph)
        except Exception:
            logger.exception("Live change failed for %s=%r", param_name, value)

    def _update_downstream_nodes(self):
        """
        Update downstream nodes after debounce delay.
        Uses threaded worker pool for efficient background rendering.
        """
        nitem = self.current_node_item
        if not nitem or not isValid(nitem):
            return

        # Use the threaded preview worker pool if available
        if hasattr(self.editor, 'preview_worker'):
            # Cancel any pending tasks for downstream nodes (new values supersede)
            self.editor.preview_worker.cancel_all_downstream(nitem)
            # Queue downstream nodes for threaded preview update
            self.editor.preview_worker.queue_downstream(nitem, include_start=False)
        else:
            # Fallback: synchronous update (old behavior)
            adj = {}
            for e in self.editor.scene.edges:
                if e.src and e.dst:
                    adj.setdefault(e.src.node_item, set()).add(e.dst.node_item)

            downstream = set()
            stack = list(adj.get(nitem, []))
            while stack:
                cur = stack.pop()
                if cur not in downstream and cur is not nitem:
                    downstream.add(cur)
                    stack.extend(adj.get(cur, []))

            for n in downstream:
                n.update_preview(self.editor.graph)

        # Refresh edge paths
        self.editor.scene._refresh_edge_paths()

        # Update large preview if tracking output
        if hasattr(self.editor, 'large_preview'):
            out_item = getattr(self.editor, 'output_node_item', None)
            if out_item:
                self.editor.large_preview.refresh_if_tracking(out_item)

    def _rebuild_atlas_ports(self, node_item, new_cells: int):
        """
        Rebuild the input ports for an Atlas node when cells count changes.
        Preserves existing connections where possible.
        """
        if not node_item:
            return

        # Get current connections before removing ports
        old_connections = {}
        for port_name, port in list(node_item.ports_in.items()):
            # Find edge connected to this port
            for edge in self.editor.scene.edges:
                if edge.dst is port:
                    old_connections[port_name] = (edge.src, edge)
                    break

        # Remove all existing input ports and their edges
        for port_name in list(node_item.ports_in.keys()):
            port = node_item.ports_in[port_name]
            # Remove edges connected to this port
            for edge in list(self.editor.scene.edges):
                if edge.dst is port:
                    self.editor.scene.delete_edge(edge)
            # Remove port from scene
            if port.scene():
                port.scene().removeItem(port)

        node_item.ports_in.clear()

        # Add new ports
        for i in range(new_cells):
            node_item.add_input(f'in{i}', defer_layout=True)

        # Re-establish connections where port names match
        from texture_pig.ui.nodes.edge_item import EdgeItem
        for port_name, (src_port, _) in old_connections.items():
            if port_name in node_item.ports_in:
                dst_port = node_item.ports_in[port_name]
                # Re-create edge
                new_edge = EdgeItem(src_port, dst_port)
                self.editor.scene.edges.append(new_edge)
                self.editor.scene.addItem(new_edge)
                # Re-establish backend connection
                if src_port and src_port.node_item:
                    node_item.backend_node.connect(
                        port_name,
                        src_port.node_item.backend_node,
                        src_port.name
                    )

        # Re-layout ports
        node_item.layout_ports_and_resize()

        # Update preview
        node_item.update_preview(self.editor.graph)

    def _rebuild_multi_input_ports(self, node_item, new_num_inputs: int):
        """
        Rebuild the input ports for Grid/RadialGrid nodes when num_inputs changes.
        Preserves existing connections where possible.
        """
        if not node_item:
            return

        # Get current connections before removing ports
        old_connections = {}
        for port_name, port in list(node_item.ports_in.items()):
            # Find edge connected to this port
            for edge in self.editor.scene.edges:
                if edge.dst is port:
                    old_connections[port_name] = (edge.src, edge)
                    break

        # Remove all existing input ports and their edges
        for port_name in list(node_item.ports_in.keys()):
            port = node_item.ports_in[port_name]
            # Remove edges connected to this port
            for edge in list(self.editor.scene.edges):
                if edge.dst is port:
                    self.editor.scene.delete_edge(edge)
            # Remove port from scene
            if port.scene():
                port.scene().removeItem(port)

        node_item.ports_in.clear()

        # Add new ports
        for i in range(new_num_inputs):
            node_item.add_input(f'in{i}', defer_layout=True)

        # Re-establish connections where port names match
        from texture_pig.ui.nodes.edge_item import EdgeItem
        for port_name, (src_port, _) in old_connections.items():
            if port_name in node_item.ports_in:
                dst_port = node_item.ports_in[port_name]
                # Re-create edge
                new_edge = EdgeItem(src_port, dst_port)
                self.editor.scene.edges.append(new_edge)
                self.editor.scene.addItem(new_edge)
                # Re-establish backend connection
                if src_port and src_port.node_item:
                    node_item.backend_node.connect(
                        port_name,
                        src_port.node_item.backend_node,
                        src_port.name
                    )

        # Re-layout ports
        node_item.layout_ports_and_resize()

        # Update preview
        node_item.update_preview(self.editor.graph)
