
# 🐷 Texture Pig

[![test](https://github.com/groovemeteor/texturepig/actions/workflows/test.yml/badge.svg)](https://github.com/groovemeteor/texturepig/actions/workflows/test.yml)

Texture Pig is a powerful, node-based procedural texture generation tool built with Python and PySide6. It allows technical artists and developers to create textures for various effects in game engines in a flexible graph-based workflow.

---

## ✨ Key Features

- **Node-Based Workflow**: Create textures by connecting generators, filters, and mixers.
- **🔄 Full Undo/Redo**: Every parameter change, node movement, and connection is fully reversible (Ctrl+Z / Ctrl+Y).
- **🎛️ Dynamic Inspector**: Context-aware parameter editing.
- **🎨 Rich Node Library**:
    - **Generators**: Perlin Noise, Worley Noise, and various Gradient types.
    - **Shapes**: Procedural Circles, Rectangles, Triangles, Lines, Stripes, and HexGrid (honeycomb pattern).
    - **Filters**: Gaussian Blur, Levels, Inversion, and Channel Combining.
    - **Layouts**: Grid and Radial repeating patterns with optional gradient coloring.
    - **Scalar**: Float/Int values, arithmetic operations (Add, Sub, Mul, Div, Clamp).
    - **Sources**: Image loading and Text rendering with system fonts.
- **🔭 Dual Previews**: Real-time thumbnail previews on every node, plus a full-resolution "Output" dock with **progressive rendering**.
- **📸 High-Res Export**: Render and save your final results directly to PNG.
- **⚡ Optimized UX**: Lazy-follow sliders, debounced preview updates, and background rendering for smooth interaction.

---

## 🚀 Quick Start

1. **Launch the App**: Run `python -m texture_pig.ui` to open the editor.
2. **Add Nodes**: Drag nodes from the **Palette** on the left or use the **Quick Add** menu.
3. **Connect**: Click and drag from an **Output Port** (right side of a node) to an **Input Port** (left side).
    - *Tip: Ports will "glow" and grow when a compatible connection is nearby!*
4. **Inspect**: Select a node to view and edit its properties in the **Inspector** panel.
5. **Set Output**: Right-click any node and select **"Set as Output"** to see it in the full-res preview dock.
6. **Export**: Use the **Export** dock at the bottom to save your creation to disk.

---

## ⌨️ Controls & Shortcuts

| Action | Shortcut |
| :--- | :--- |
| **Undo** | `Ctrl + Z` |
| **Redo** | `Ctrl + Y` / `Ctrl + Shift + Z` |
| **Duplicate Node** | `Ctrl + D` |
| **Delete Selection** | `Delete` / `Backspace` |
| **Zoom Preview** | `Mouse Wheel` |
| **Pan Preview** | `Left Click + Drag` |
| **Context Menu** | `Right Click` |
| **Toggle Output Preview** | `View` menu → `Output Preview` |

---

## 🛠️ Technical Details

Texture Pig uses a decoupled architecture:
- **Backend**: Pure Python/Numpy/PIL for image processing logic.
- **Frontend**: PySide6 (Qt) for a responsive, hardware-accelerated user interface.
- **Command Pattern**: All user actions are encapsulated into `QUndoCommand` objects for robust state management.

### Project layout

```
src/texture_pig/        the package (standard src layout)
├── nodes/              backend: node types + graph evaluation, no Qt in the math
│   ├── core.py         Node/Graph base, caching, scalar-param resolution
│   ├── generators.py   noise + gradients
│   ├── shapes.py       circle/rect/triangle/line/stripes/hexgrid
│   ├── filters.py      blur, transform, levels, invert, combine/split
│   ├── layout.py       grid, radial grid, mirror, atlas
│   ├── blends.py       blend modes, lerp
│   └── scalar/         Float/Int + arithmetic nodes
├── ui/                 PySide6 editor
│   ├── qt_editor.py    main window, NODE_REGISTRY, save/load
│   ├── nodes/          node/port/edge graphics items
│   ├── inspector/      parameter panel + field widgets
│   ├── scene/          canvas scene & view
│   ├── preview/        threaded preview rendering
│   ├── palette/        node palette, quick-add, gradient editor
│   └── commands/       undo/redo commands
└── logging_setup.py    rotating file log + excepthook

packaging/              build inputs (TexturePig.spec, installer.iss, launcher.py)
tests/                  pytest suite
examples/               sample graphs (.json)
build.bat               one-click: resources -> PyInstaller -> installer
```

Build outputs (`build/`, `dist/`, `installer_output/`) are generated and git-ignored.

### Requirements
- Python 3.10+
- PySide6
- NumPy
- OpenCV (opencv-python-headless)
- Pillow (PIL)

```bash
# recommended: create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\\Scripts\\activate

# install dependencies
pip install PySide6 numpy opencv-python-headless pillow
# or, to also get the `texture-pig-editor` command and the test suite:
pip install -e ".[dev]"
```

## 🚀 Running the app

```bash
python -m texture_pig.ui
# or, if you prefer direct:
python -m texture_pig.ui.__main__
```

The main window opens with an empty graph. Use the **Palette** dock (left) to add nodes, or press **Space** in the canvas to open the **Quick Add** dialog.

### Logs

The app logs to a rotating file instead of stdout (the packaged .exe has no console window, so `print()` output would otherwise be lost):
- Windows: `%APPDATA%\TexturePig\texture_pig.log`
- macOS: `~/Library/Logs/TexturePig/texture_pig.log`
- Linux: `~/.local/share/texture_pig/logs/texture_pig.log`

Check this file first when reporting a bug.

### Running the tests

```bash
pip install -e ".[dev]"
pytest
```

---

## 🔧 Compiling Qt Resources

The app works without compiled resources (uses filesystem fallback), but for distribution you should compile them:

**Option 1: Python module (recommended for PyInstaller)**
```cmd
pyside6-rcc src/texture_pig/ui/resources.qrc -o src/texture_pig/ui/icons_rc.py
```

**Option 2: Binary .rcc file**
```cmd
pyside6-rcc src/texture_pig/ui/resources.qrc -binary -o src/texture_pig/ui/resources.rcc
```

If `pyside6-rcc` is not in your PATH, use the full path to the executable:
```cmd
# Standard Python installation:
python -c "import PySide6; print(PySide6.__file__)"  # Find PySide6 location
# Then use: <PySide6_path>\rcc.exe src/texture_pig/ui/resources.qrc -o src/texture_pig/ui/icons_rc.py

# Example for typical Windows installation:
"C:\Users\<username>\AppData\Local\Programs\Python\Python311\Lib\site-packages\PySide6\rcc.exe" src/texture_pig/ui/resources.qrc -o src/texture_pig/ui/icons_rc.py
```

---

## Windows executable build (PyInstaller + Inno Setup)

### Quick Build (Recommended)

Use the provided build script for a one-click build:

```cmd
build.bat
```

This script automatically:
1. Installs required dependencies (if missing)
2. Compiles Qt resources
3. Builds the app with PyInstaller (one-folder / "onedir")
4. Packages it into a Windows installer with Inno Setup (if installed --
   get it from https://jrsoftware.org/isinfo.php or `winget install JRSoftware.InnoSetup`)

### Manual Build

If you prefer to build manually:

**1. Install build dependencies:**
```cmd
pip install -r requirements.txt
```

**2. Compile Qt resources:**
```cmd
pyside6-rcc src/texture_pig/ui/resources.qrc -o src/texture_pig/ui/icons_rc.py
pyside6-rcc src/texture_pig/ui/resources.qrc -binary -o src/texture_pig/ui/resources.rcc
```

**3. Run PyInstaller:**
```cmd
pyinstaller --clean packaging/TexturePig.spec
```

**4. Build the installer (optional):**
```cmd
ISCC packaging/installer.iss
```

### Build Output

| Output | Path | Size | Description |
|--------|------|------|-------------|
| **App folder** | `dist/TexturePig/` | ~213 MB on disk | The app itself (onedir). Run `TexturePig.exe` from here directly, or zip the folder to share it. |
| **Installer** | `installer_output/TexturePigSetup-*.exe` | ~57 MB download | What you actually hand to users: a normal installer wizard, Start Menu shortcut, optional desktop icon, and a proper uninstaller in "Apps & Features". |

The build is intentionally **onedir, not onefile**: a onefile exe re-extracts its entire payload to a temp directory on every launch, which for a Qt + NumPy + OpenCV app measurably dominates startup time. Onedir has nothing to unpack at runtime -- in local testing, the app is fully initialized (interpreter + Qt + logging) well under half a second after launch.

TexturePig.spec also explicitly excludes several large Qt subsystems the app never uses (WebEngine/Chromium, QML/Quick, 3D, multimedia codecs, SQL drivers, networking, translations) that PyInstaller's default PySide6 hook otherwise bundles wholesale -- unfiltered, the onedir build was 789 MB; filtered, it's 213 MB. If you add a feature that needs one of those Qt modules back, remove the matching pattern from `_UNUSED_QT_PATTERNS` in `TexturePig.spec`.

**Note on unsigned installers:** `TexturePigSetup-*.exe` isn't code-signed, so Windows SmartScreen may warn first-time users ("Windows protected your PC" -> More info -> Run anyway), and some locked-down machines (Application Control / WDAC policies) may block it outright. Code signing requires purchasing a certificate and is out of scope here, but is the standard fix if this becomes a problem for your users.

### Troubleshooting

**"pyside6-rcc not found"**: Install PySide6 (`pip install PySide6`) or use the full path to rcc.exe as shown above.

**"ModuleNotFoundError"**: Ensure all dependencies are installed: `pip install -r requirements.txt`

**Build warnings about missing DLLs** (OCI.dll, LIBPQ.dll, etc.): These are optional database drivers for a Qt SQL plugin the app doesn't use, and get filtered out of the final build regardless -- safe to ignore.

**"ISCC not found" / installer step skipped**: Install Inno Setup 6 and make sure `ISCC.exe` is on PATH, or edit the `ISCC` path resolution at the top of `build.bat`.

---

## 🧩 Built-in Nodes

### Generators
- `Constant` — solid color RGBA.
- `GradientLinear` — angle, offset; **output_mode** (`rgb`, `alpha`, or `color`), optional invert. In `color` mode, uses the **Gradient Editor** for multi-stop color gradients with RGBA support.
- `GradientRadial` — center (`cx, cy`), radius; **output_mode** (`rgb`, `alpha`, or `color`), invert. In `color` mode, uses the **Gradient Editor**.
- `GradientReflected` — angle, midpoint; **output_mode** (`rgb`, `alpha`, or `color`), invert. Creates a reflected gradient (black to white at midpoint, back to black). In `color` mode, uses the **Gradient Editor**.
- `GradientAngle` — center (`cx, cy`), angle offset; **output_mode** (`rgb`, `alpha`, or `color`), invert. Creates an angular/conical gradient. In `color` mode, uses the **Gradient Editor**.
- `PerlinNoise` — scale, octaves, persistence, lacunarity.
- `WorleyNoise` — points, jitter, metric.

### Shapes
- `Circle` — center (`cx, cy`, normalized), radius, color, **edge_softness**.
- `Rectangle` — center (`cx, cy`), width/height, rotation, color, **corner_radius**, **edge_softness**.
- `Triangle` — center (`cx, cy`), base, height, scale, rotation, color, **edge_softness**, `equilateral` toggle.
- `Line` — endpoints (`x0, y0, x1, y1`), width, color (uses Pillow for AA).
- `Stripes` — evenly-spaced parallel stripes. Parameters: `count` (number of stripes), `thickness`, `rotation_deg`, `color`, **edge_softness**, **frame** (adds half-thickness stripes at edges for seamless tiling).
- `HexGrid` — hexagonal grid pattern (honeycomb lines) with seamless tiling support. Parameters: `hex_size` (size of hexagons as fraction of canvas, automatically quantized for seamless tiling), `thickness` (line width), `color`, **edge_softness**, `orientation` (`pointy|flat`), `offset_x`, `offset_y`, `stretch_x`, `stretch_y` (deform hexagons to fit square textures). The inspector shows **"Tileable at: W x H"** displaying the exact dimensions where the pattern tiles seamlessly, and a **"Make Tileable"** button that auto-calculates the stretch value needed to tile on a square texture.

### Filters / Channels
- `GaussianBlur` — sigma, alpha-only toggle.
- `Transform` — translate (`tx, ty`), scale (`scale, scale_x, scale_y`), rotation, pivot. The **falloff** input lets you control where and how strongly a Transform is applied, using a grayscale image.
- `Invert` — invert rgb/alpha with mask channel selection.
- `Levels` — full RGB + Alpha levels; mask channel and opacity.
- `Outline` — creates a stroke/outline around shapes using contour detection. Parameters: `thickness` (stroke width), `color` (RGBA).
- `Combine` — assemble output RGBA channels from source inputs (luma/r/g/b/a).
- `Split` — separate an RGBA image into its 4 component channels (R, G, B, A), each output as grayscale.
- `Mirror` — mirror across the center axis. `axis='x'|'y'`; `side='keep_left|keep_right|keep_top|keep_bottom'`; `copy_center=True|False`.

### Blends
- `Blend` — `mode='normal|add|subtract|multiply|screen|overlay'`, `opacity`.
- `Lerp` — Linear interpolation between two images. Inputs: `a` (first image), `b` (second image), `t` (mask/factor). When `t` is black (0), outputs `a`; when `t` is white (1), outputs `b`. Uses the luminance of the mask image to determine the blend factor. 

### Layout
- `Grid` — replicate a source into an `nx × ny` grid inside a region with padding; supports `scale > 1.0`, bilinear resampling, and high-quality tile evaluation.
  - **Multi-input**: Supports multiple inputs (`num_inputs`) that cycle through grid cells. Unconnected inputs show as transparent.
  - **Gradient coloring**: Enable `use_gradient` to tint each tile based on its position. Configure `color_stops` as a list of `(position, (R, G, B, A))` tuples.
  - **Gradient mode** (`gradient_mode`): Controls how tiles sample the gradient:
    - `index` — tiles are colored sequentially from first to last (default)
    - `column` — tiles in the same column share the same color (left-to-right gradient)
    - `row` — tiles in the same row share the same color (top-to-bottom gradient)
- `RadialGrid` — arrange instances around a circle/arc; count, center, radius, sweep, per-tile scale and rotation (`none|radial|tangent`).
  - **Multi-input**: Supports multiple inputs (`num_inputs`) that cycle through positions around the arc. Unconnected inputs show as transparent.
  - **Pivot**: Control the rotation pivot point for tiles (`center`, `top`, `bottom`). Affects how tiles rotate when using radial or tangent rotation modes.
  - **Gradient coloring**: Enable `use_gradient` to tint each tile based on its position around the arc. Configure `color_stops` as a list of `(position, (R, G, B, A))` tuples.
- `Atlas` — pack multiple images into a single texture atlas. Parameters: `cells` (4, 9, 16, 25, 36, 49, or 64 — perfect squares for 2x2 up to 8x8 grids). Images are arranged left-to-right, top-to-bottom. Useful for sprite sheets and texture atlases.

### Scalar
Scalar nodes output single numeric values and can be connected to numeric input ports on other nodes.

- `Float` — outputs a single floating-point value. Parameters: `value` (default 0.5), `min_value`, `max_value`.
- `Int` — outputs a single integer value. Parameters: `value` (default 0), `min_value`, `max_value`.
- `ScalarAdd` — adds two scalar inputs (`a + b`).
- `ScalarSub` — subtracts two scalar inputs (`a - b`).
- `ScalarMul` — multiplies two scalar inputs (`a * b`).
- `ScalarDiv` — divides two scalar inputs (`a / b`), with safe division by zero handling.
- `ScalarClamp` — clamps a value between min and max bounds. Inputs: `value`, `min_val`, `max_val`.

### Sources
- `Image` — loads an image file and converts it to RGBA. Supports PNG, JPG, and other common formats.
- `Text` — renders text to a texture with configurable styling. Parameters:
  - `text` — the text to render (supports multi-line with `\n`)
  - `font_name` — system font name (auto-discovered from Windows/macOS/Linux font directories)
  - `font_size` — font size as fraction of canvas height (0.0-1.0)
  - `color` — RGBA text color in [0..1]
  - `align` — horizontal alignment (`left`, `center`, `right`)
  - `valign` — vertical alignment (`top`, `center`, `bottom`)
  - `line_spacing` — multiplier for line spacing (1.0 = normal)
  - `padding` — padding from edges as fraction of canvas (0.0-0.5)

---

## 🖥️ UI Overview

- **Palette (left)** — buttons to create nodes.
- **Inspector (right)** — edit parameters for the selected node. Most numeric controls use **sliders** with fine resolution; integers use **spin boxes** for precision.

### Slider Controls
The inspector uses two types of sliders:

**Standard Sliders** (most parameters):
- Immediate response for quick editing
- Full undo support with single undo entry per drag

**Scale Sliders** (scale, scale_x, scale_y):
- **Lazy Follow**: Value moves slowly at first (5% speed), ramping up to full speed. Makes fine adjustments easier without overshooting.
- **Debounced Preview**: Previews update after the slider stops for 80ms, reducing lag during fast adjustments.
- **Handle-Only**: Clicking on the track doesn't jump the value—only dragging the handle moves it.
- Used for computationally heavy operations like Transform and Grid scaling.

- **Canvas** — pan with **middle mouse drag**; box-select with left drag.

### Quick Add (Space)
Press **Space** in the canvas to open a searchable list of nodes. Type to filter; **Enter** or **double-click** adds the node **under the mouse cursor**.

### Grid + Snapping
The canvas shows a **dim grid**. Nodes **snap** to grid spacing as you move them. Hold **Alt** while dragging to **temporarily disable snapping**. Grid spacing can be adjusted via **View → Grid Spacing…**.

### Gradient Editor
When a gradient node is set to `color` mode, a visual **Gradient Editor** appears in the Inspector. It provides a Photoshop-style interface for creating multi-stop color gradients:

| Action | How |
| :--- | :--- |
| **Add color stop** | Click on the gradient bar |
| **Move stop** | Drag the triangle handle |
| **Edit stop color** | Double-click the handle (opens color picker with alpha) |
| **Delete stop** | Right-click the handle (minimum 2 stops required) |

The gradient bar shows a checkerboard pattern behind colors with transparency. Each stop supports full RGBA colors.

### Output Preview
The **Output Preview** dock displays the full-resolution render of the current output node. It includes zoom controls (**Fit**, **Full**, **+**, **-**) and an **Auto** toggle:

- **Auto ON**: The preview updates automatically whenever the graph changes.
- **Auto OFF**: Auto-refresh is disabled. Use the **Refresh** button to manually update.

#### Progressive Rendering
For high-resolution outputs (>256px), the preview uses **progressive rendering**:
1. A **low-resolution preview** (1/4 size) appears immediately for quick feedback
2. The **full-resolution render** runs in a background thread
3. The UI stays **responsive** during heavy renders
4. The **status bar** shows render progress: "Rendering preview at 2048x2048..." → "Preview rendered in 1.23s"

This is especially useful when working with complex graphs at high resolutions (1024px+) where rendering would otherwise freeze the UI.

---

## 💾 Save / Load / Export

- **Save Graph…** writes a JSON with:
  - `version`, `graph_size`, `preview_size`
  - serialized node entries (`class`, `name`, `params`, `inputs`, `pos`, `width`)
  - edges (`src`, `src_port`, `dst`, `dst_port`)
- **Load Graph…** rebuilds nodes from the registry and reconnects edges.
- **Export PNG…** saves the selected node’s output at the chosen resolution.

> The serializer skips transient fields like caches and dirty flags.

---

## 🧭 Keyboard & Mouse Shortcuts

- **Space** — open Quick Add dialog.
- **Middle mouse** — pan.
- **Ctrl + mouse wheel** — zoom in/out.
- **Ctrl + 0** — reset zoom.
- **Ctrl + +/-** — zoom steps.
- **Delete/Backspace** — delete selected nodes.
- **Ctrl + D** — duplicate node.
- **Ctrl + Shift + D** — duplicate **and rewire downstream**.
- **Alt (hold while dragging)** — temporarily disable snapping.

---

## 🛠️ Development Notes

- Most nodes are **NumPy-only**. `Line` uses Pillow for antialiased stroke.
- Previews are generated by calling `Graph.output(node, size=preview_size)` and converted to QPixmap.
- The editor keeps a reverse adjacency to propagate preview updates downstream of the edited node.
- The **Node registry** (`NODE_REGISTRY`) maps class names ↔ implementations for serialization.

### Node Protocol

All nodes implement the `TextureNode` protocol, which defines the standard interface:

```python
from texture_pig.nodes import TextureNode

class TextureNode(Protocol):
    name: str
    inputs: Dict[str, tuple]      # {input_name: (node, output_port)}
    dependents: Set[TextureNode]

    def evaluate(self, size: int) -> np.ndarray: ...
    def connect(self, input_name: str, node: TextureNode, output_port: str = 'out') -> TextureNode: ...
    def set_params(self, **kwargs) -> TextureNode: ...
    def invalidate(self) -> None: ...
    def evaluate_port(self, port_name: str, size: int) -> np.ndarray: ...  # For multi-output nodes
```

### Scalar Node Protocol

Scalar nodes (nodes that output numeric values) implement the `ScalarNodeProtocol`:

```python
from texture_pig.nodes.scalar import ScalarNodeProtocol, ScalarNode

@runtime_checkable
class ScalarNodeProtocol(Protocol):
    def get_scalar_value(self) -> float: ...
    def get_int_value(self) -> int: ...
```

The `ScalarNode` base class provides a default implementation:

```python
from texture_pig.nodes.scalar import ScalarNode

class MyScalarNode(ScalarNode):
    def __init__(self, value: float = 0.5, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def get_scalar_value(self) -> float:
        return self.value

    # get_int_value() is inherited: returns int(round(get_scalar_value()))
```

Scalar nodes can be connected to numeric input ports. When evaluated as an image, they produce a solid gray image where the brightness equals the clamped scalar value.

### Adding a new node

**Option 1: Generator node (no inputs)**
```python
from texture_pig.nodes import Node

class MyGenerator(Node):
    def __init__(self, my_param: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.my_param = my_param

    def _compute(self, size: int) -> np.ndarray:
        # Return (size, size, 4) RGBA float32 array in [0, 1]
        return np.zeros((size, size, 4), dtype=np.float32)
```

**Option 2: Filter node (with inputs)**
```python
from texture_pig.nodes import GenerationCacheMixin, ensure_rgba

class MyFilter(GenerationCacheMixin):
    def __init__(self, strength: float = 1.0, name: str = 'MyFilter'):
        self.name = name
        self.strength = strength
        self.inputs = {}
        self.dependents = set()
        self._init_generation_cache()

    def connect(self, input_name, node, output_port='out'):
        self.inputs[input_name] = (node, output_port)
        node.dependents.add(self)
        self.invalidate()
        return self

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.invalidate()
        return self

    def invalidate(self):
        self._bump_generation()

    def evaluate(self, size: int) -> np.ndarray:
        cached = self._check_cache(size)
        if cached is not None:
            return cached
        # Get input, apply filter, store result
        src = self.inputs.get('src')
        if src:
            node, port = src
            arr = node.evaluate_port(port, size) if hasattr(node, 'evaluate_port') else node.evaluate(size)
        else:
            arr = np.zeros((size, size, 4), dtype=np.float32)
        result = self._apply_filter(arr)
        self._store_cache(size, result)
        return result
```

**Integration steps:**
1. Add to `NODE_REGISTRY` in `src/texture_pig/ui/qt_editor.py`
2. Add a button/entry in the **Palette**
3. Add an Inspector branch to expose parameters
