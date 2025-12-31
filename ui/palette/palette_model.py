
# ui/palette/palette_model.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, List


@dataclass(frozen=True)
class PaletteEntry:
    """
    Data model for a Quick Add entry.
    - label: display name
    - category: grouping for readability
    - factory: callable producing a backend node instance
    - inputs: optional list of input port names (None -> auto/Backend default)
    """
    label: str
    category: str
    factory: Callable[[], object]
    inputs: Optional[List[str]] = None


def build_default_entries() -> List[PaletteEntry]:
    """
    Build the same set of Quick Add entries as you currently expose in the inline dialog,
    kept here so you can extend without touching the main editor code.
    """
    # Backend imports kept local so the module loads fast and remains decoupled
    from texture_pig.nodes.generators import (
        GradientLinear, GradientRadial, GradientReflected, GradientAngle,
        PerlinNoise, WorleyNoise
    )
    from texture_pig.nodes.shapes import Circle, Rectangle, Triangle, Line, Stripes, HexGrid
    from texture_pig.nodes.filters import GaussianBlur, Transform, Invert, Levels, Combine, Split
    from texture_pig.nodes.outline import Outline
    from texture_pig.nodes.blends import Blend, Lerp
    from texture_pig.nodes.image_source import ImageNode
    from texture_pig.nodes.layout import Grid, RadialGrid, Atlas

    entries: List[PaletteEntry] = []

    # Generators
    entries += [
        PaletteEntry('GradientLinear',   'Generators', lambda: GradientLinear(name='Linear')),
        PaletteEntry('GradientRadial',   'Generators', lambda: GradientRadial(invert=True, name='Radial')),
        PaletteEntry('GradientReflected','Generators', lambda: GradientReflected(name='Reflected')),
        PaletteEntry('GradientAngle',    'Generators', lambda: GradientAngle(name='Angle')),
        PaletteEntry('PerlinNoise',      'Generators', lambda: PerlinNoise(seed=42, name='Perlin')),
        PaletteEntry('WorleyNoise',      'Generators', lambda: WorleyNoise(points=16, seed=42, name='Worley')),
    ]

    # Shapes
    entries += [
        PaletteEntry('Circle',           'Shapes',     lambda: Circle(color=(1, 1, 1, 1), name='Circle')),
        PaletteEntry('Rectangle',        'Shapes',     lambda: Rectangle(color=(1, 1, 1, 1), name='Rect')),
        PaletteEntry('Triangle',         'Shapes',     lambda: Triangle(color=(1, 1, 1, 1), name='Triangle')),
        PaletteEntry('Line',             'Shapes',     lambda: Line(name='Line')),
        PaletteEntry('Stripes',          'Shapes',     lambda: Stripes(name='Stripes')),
        PaletteEntry('HexGrid',          'Shapes',     lambda: HexGrid(name='HexGrid')),
    ]

    # Filters / Ops
    entries += [
        PaletteEntry('GaussianBlur',     'Filters',    lambda: GaussianBlur(sigma=2.0, alpha_only=False, name='Blur')),
        PaletteEntry('Transform',        'Filters',    lambda: Transform(name='Transform')),
        PaletteEntry('Invert',           'Filters',    lambda: Invert(name='Invert')),
        PaletteEntry('Levels',           'Filters',    lambda: Levels(name='Levels')),
        PaletteEntry('Outline',          'Filters',    lambda: Outline(name='Outline'), inputs=['src']),
        PaletteEntry('Combine',          'Channels',   lambda: Combine(name='Combine')),
        PaletteEntry('Split',            'Channels',   lambda: Split(name='Split')),
    ]

    # Blends
    entries += [
        PaletteEntry('Lerp', 'Blend', lambda: Lerp(name='Lerp'), inputs=['a', 'b', 't']),
        PaletteEntry('Blend (normal)',   'Blend',      lambda: Blend(mode='normal',   opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
        PaletteEntry('Blend (add)',      'Blend',      lambda: Blend(mode='add',      opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
        PaletteEntry('Blend (subtract)', 'Blend',      lambda: Blend(mode='subtract', opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
        PaletteEntry('Blend (multiply)', 'Blend',      lambda: Blend(mode='multiply', opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
        PaletteEntry('Blend (screen)',   'Blend',      lambda: Blend(mode='screen',   opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
        PaletteEntry('Blend (overlay)',  'Blend',      lambda: Blend(mode='overlay',  opacity=1.0, name='Blend'), inputs=['base', 'blend', 'mask']),
    ]

    # Sources
    entries += [
        PaletteEntry('Image',            'Sources',    lambda: ImageNode(name='Image')),
    ]

    # Layout
    entries += [
        PaletteEntry('Grid',             'Layout',     lambda: Grid(nx=2, ny=2, scale=1.0, name='Grid'), inputs=['src']),
        PaletteEntry('RadialGrid',       'Layout',     lambda: RadialGrid(count=8, cx=0.5, cy=0.5, radius=0.35, tile_edge_frac=0.15, rotate_mode='none', name='RadialGrid'), inputs=['src']),
        PaletteEntry('Atlas',            'Layout',     lambda: Atlas(cells=4, name='Atlas'), inputs=['in0', 'in1', 'in2', 'in3']),
    ]

    return entries
