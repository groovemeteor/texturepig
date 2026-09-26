
# TexturePig.spec
# PyInstaller spec file for building TexturePig as a one-folder ("onedir") app.
# Run: pyinstaller --clean TexturePig.spec
#
# Why onedir, not onefile:
#   A onefile build zips everything into a single exe and re-extracts the
#   whole thing to a temp directory on *every launch* before the app can even
#   start importing. For a bundle this size (Qt + NumPy + OpenCV + Pillow)
#   that extraction step dominates startup time. Onedir ships a small launcher
#   exe next to a folder of DLLs/data -- nothing to unpack at runtime, so
#   startup is limited only by actual DLL loading. Distribute it as the
#   generated installer (see installer.iss) or a zip of out/TexturePig/.

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---- Paths ----
# This spec lives in packaging/, so the repo root is one level up.
PACKAGING_DIR = SPECPATH
REPO_ROOT = os.path.dirname(PACKAGING_DIR)
SRC_DIR = os.path.join(REPO_ROOT, 'src')
PKG_DIR = os.path.join(SRC_DIR, 'texture_pig')

# Entry script - launcher.py uses absolute imports for PyInstaller compatibility
ENTRY_SCRIPT = os.path.join(PACKAGING_DIR, 'launcher.py')

# ---- Data collection ----
datas = []

# App's own non-Python data (QSS, compiled Qt resources, JSON examples).
datas += collect_data_files(os.path.join(PKG_DIR, 'ui'))         # includes qss and resources.rcc
datas += collect_data_files(os.path.join(REPO_ROOT, 'examples')) # JSON example(s)

icons_dir = os.path.join(PKG_DIR, 'ui', 'icons')
if os.path.isdir(icons_dir):
    datas.append((icons_dir, 'ui/icons'))

rcc_src = os.path.join(PKG_DIR, 'ui', 'resources.rcc')
if os.path.exists(rcc_src):
    datas.append((rcc_src, 'ui/resources.rcc'))

# PySide6's own runtime data (platform plugin qwindows.dll, image format
# plugins, styles, translations) -- required, this is not bloat to trim.
datas += collect_data_files('PySide6')

# NOTE: we deliberately do NOT collect_data_files('numpy') / ('PIL') here.
# Those mostly ship test fixtures / f2py templates that aren't needed at
# runtime; if a future numpy/Pillow release genuinely needs a data file we're
# missing, PyInstaller's warnings (or a runtime FileNotFoundError) will say so.

# ---- Hidden imports ----
# The app only actually uses QtCore/QtGui/QtWidgets (verified by grepping
# every `from PySide6...` import in the codebase) plus shiboken6. Previously
# this collected *every* PySide6 submodule, which pulls in Qt modules the app
# never touches (QtQml, QtNetwork, QtMultimedia, QtPdf, Qt3D*, ...) -- each
# with its own multi-MB DLL(s). Being explicit here, combined with the
# excludes list below, keeps those out of the bundle.
hiddenimports = [
    'shiboken6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
]
hiddenimports += collect_submodules('texture_pig')  # our own package; small, keep it safe

# Large Qt modules this app never imports. Listed explicitly so PyInstaller's
# binary dependency walker can't pull their DLLs in transitively either.
excludes = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuick3D',
    'PySide6.QtNetwork', 'PySide6.QtNetworkAuth',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSensors', 'PySide6.QtSerialPort',
    'PySide6.QtSerialBus', 'PySide6.QtPositioning', 'PySide6.QtLocation',
    'PySide6.QtRemoteObjects', 'PySide6.QtHttpServer',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtUiTools',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.scripts',
]

# ---- Analysis ----
a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[SRC_DIR],  # src layout: texture_pig lives under src/
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ---- Strip Qt binaries/data the `excludes` list above can't reach ----
# `excludes` only keeps PyInstaller's *module graph* from treating those Qt
# submodules as importable Python code. It has no effect here: PySide6 ships
# every Qt6*.dll (and each module's plugins/resources/translations) as a flat
# pile of files inside the PySide6 package directory, and PyInstaller's own
# PySide6 hook bundles that pile as *binaries*/*datas*, not by following
# Python imports. So a 195MB Qt6WebEngineCore.dll (plus its 102MB Chromium
# resources/) got bundled anyway, the first time this was built, despite the
# app never importing QtWebEngine. Filter the collected TOC lists directly.
import fnmatch

_UNUSED_QT_PATTERNS = [
    # WebEngine (Chromium) -- huge, never used (no QtWebEngine* import anywhere)
    '**/Qt6WebEngine*', '**/QtWebEngine*', '**/resources/*', '**/qtwebengine*',
    # QML/Quick/3D -- app is QGraphicsView + Widgets only, no QML anywhere
    '**/Qt6Qml*', '**/Qt6Quick*', '**/QtQml*', '**/QtQuick*', '**/Qt63D*',
    '**/qml/**', '**/qmllint*', '**/qmlformat*', '**/qmlls*', '**/qmlcachegen*',
    '**/qmlimportscanner*', '**/plugins/sceneparsers/*', '**/plugins/renderers/*',
    '**/plugins/renderplugins/*', '**/plugins/assetimporters/*',
    '**/plugins/geometryloaders/*', '**/plugins/qmltooling/*',
    # Designer / UI tooling -- design-time only, not needed at runtime
    '**/Qt6Designer*', '**/QtDesigner*', '**/QtUiTools*', '**/plugins/designer/*',
    # Multimedia (av codecs) -- app has no audio/video/camera features
    '**/Qt6Multimedia*', '**/QtMultimedia*', '**/avcodec*', '**/avformat*',
    '**/avutil*', '**/avfilter*', '**/avdevice*', '**/swscale*', '**/swresample*',
    '**/plugins/multimedia/*',
    # Network / SQL / IPC -- app does no networking, DB access, or IPC
    '**/Qt6Network*', '**/QtNetwork*', '**/Qt6Sql*', '**/QtSql*',
    '**/plugins/sqldrivers/*', '**/plugins/tls/*', '**/plugins/networkinformation/*',
    '**/Qt6RemoteObjects*', '**/Qt6HttpServer*',
    # Misc device/embedded Qt modules -- irrelevant to a desktop image editor
    '**/Qt6Pdf*', '**/QtPdf*', '**/Qt6Bluetooth*', '**/Qt6Nfc*', '**/Qt6Sensors*',
    '**/Qt6SerialPort*', '**/Qt6SerialBus*', '**/Qt6Positioning*', '**/Qt6Location*',
    '**/Qt6Charts*', '**/Qt6DataVisualization*', '**/Qt6Graphs*', '**/Qt6Test*',
    '**/plugins/position/*', '**/plugins/sensors/*', '**/plugins/geoservices/*',
    '**/plugins/canbus/*', '**/plugins/texttospeech/*', '**/plugins/webview/*',
    '**/plugins/scxmldatamodel/*',
    # Translations -- app UI is English-only; drop Qt's own translated strings
    '**/translations/*',
    # OpenGL -- QGraphicsView uses the default raster paint engine here, no
    # QOpenGLWidget/QML anywhere (verified: no "OpenGL" hit in ui/ at all).
    # opengl32sw.dll alone (Qt's software GL rasterizer fallback) is 20MB.
    '**/opengl32sw.dll', '**/Qt6OpenGL*', '**/QtOpenGL*',
    '**/Qt6ShaderTools*', '**/Qt6LabsStyleKit*',
    # Qt SDK/dev tools (Designer, Linguist, uic, rcc, qsb, ...) bundled as
    # loose PySide6/*.exe files -- these are build-time tools, never launched
    # by the app itself, so they have no business in a shipped build.
    '**/PySide6/assistant.exe', '**/PySide6/balsam.exe', '**/PySide6/balsamui.exe',
    '**/PySide6/designer.exe', '**/PySide6/linguist.exe', '**/PySide6/lrelease.exe',
    '**/PySide6/lupdate.exe', '**/PySide6/qmltyperegistrar.exe', '**/PySide6/qsb.exe',
    '**/PySide6/rcc.exe', '**/PySide6/svgtoqml.exe', '**/PySide6/uic.exe',
    # OpenCV's FFmpeg video I/O backend -- app only ever calls cv2.resize() on
    # still images, never reads/writes video.
    '**/opencv_videoio_ffmpeg*',
]


def _strip_unused_qt(entries):
    kept = []
    for entry in entries:
        dest = entry[0].replace('\\', '/')
        if any(fnmatch.fnmatch(dest, pat) for pat in _UNUSED_QT_PATTERNS):
            continue
        kept.append(entry)
    return kept


a.binaries = _strip_unused_qt(a.binaries)
a.datas = _strip_unused_qt(a.datas)

pyz = PYZ(a.pure, a.zipped_data)

# ---- EXE: launcher stub only (onedir) ----
# exclude_binaries=True is what makes this onedir instead of onefile: binaries
# and data are NOT embedded here, they're assembled by COLLECT() below into a
# plain folder next to this small exe.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TexturePig',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can trip some AV heuristics on Qt DLLs; leave off by default
    upx_exclude=[],
    console=False,   # GUI app -> no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PKG_DIR, 'ui', 'icons', 'app.ico'),
)

# ---- COLLECT: assembles the exe + all binaries/data into <distpath>/TexturePig/ ----
# build.bat passes --distpath out, so that's out/TexturePig/.
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
