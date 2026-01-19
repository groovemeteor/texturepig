
# TexturePig.spec
# PyInstaller spec file for building TexturePig (one-folder by default).
# Run: pyinstaller --clean TexturePig.spec

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---- Paths (adjust if your working directory differs) ----
# SPECPATH is a built-in PyInstaller variable containing the spec file's directory
REPO_ROOT = SPECPATH

# Entry script - use launcher.py which has absolute imports for PyInstaller compatibility
ENTRY_SCRIPT = os.path.join(REPO_ROOT, 'launcher.py')

# ---- Data collection ----
datas = []

# Bundle all non-Python data from your package (QSS, JSON examples, etc.)
# If your top-level package is named 'texture_pig', uncomment the next line
# datas += collect_data_files('texture_pig')

# Alternatively, include specific folders relative to repo:
datas += collect_data_files(os.path.join(REPO_ROOT, 'ui'))       # includes qss and resources.rcc
datas += collect_data_files(os.path.join(REPO_ROOT, 'examples')) # JSON example(s)

# Explicitly include icon files for window icon
icons_dir = os.path.join(REPO_ROOT, 'ui', 'icons')
if os.path.isdir(icons_dir):
    datas.append((icons_dir, 'ui/icons'))

# Ensure the compiled .rcc is included explicitly (robust)
rcc_src = os.path.join(REPO_ROOT, 'ui', 'resources.rcc')
if os.path.exists(rcc_src):
    datas.append((rcc_src, 'ui/resources.rcc'))

# Include PySide6 data (plugins like platforms/qwindows.dll)
datas += collect_data_files('PySide6')
datas += collect_data_files('numpy')
datas += collect_data_files('PIL')

# ---- Hidden imports (ensure all Qt/numpy/PIL submodules discovered) ----
hiddenimports = []
hiddenimports += collect_submodules('texture_pig')  # Include the entire texture_pig package
hiddenimports += collect_submodules('PySide6')
hiddenimports += collect_submodules('numpy')
hiddenimports += collect_submodules('PIL')

# ---- Analysis ----
block_cipher = None

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[REPO_ROOT, os.path.dirname(REPO_ROOT)],  # Include parent dir for texture_pig package
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---- EXE settings ----
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TexturePig',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI app → no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, 'ui', 'icons', 'app.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TexturePig',
)
