# ui/style.py
import os
import sys
from PySide6.QtCore import QResource, QFile
from PySide6.QtWidgets import QApplication

def resource_path(rel_path: str) -> str:
    """
    Return an absolute path to resource, working both in dev and PyInstaller.
    rel_path is relative to repo root (where ui/ lives), e.g., 'ui/resources.rcc'.
    """
    base = getattr(sys, '_MEIPASS', None)
    if base:  # PyInstaller bundle extraction dir
        return os.path.join(base, rel_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', rel_path).replace('\\', '/')

def register_qt_resources() -> bool:
    """
    Register compiled Qt resources (.rcc). Returns True on success.
    """
    rcc_path = resource_path('ui/resources.rcc')
    if os.path.exists(rcc_path):
        ok = QResource.registerResource(rcc_path)
        if not ok:
            print(f"[style] Failed to register Qt resources: {rcc_path}")
        return bool(ok)
    else:
        print(f"[style] .rcc not found at {rcc_path} (did you run pyside6-rcc?)")
        return False

def load_app_stylesheet(app: QApplication) -> bool:
    """
    Load QSS from the Qt resource system (preferred).
    Fallback to reading the file from disk in dev if resources aren't registered.
    """
    # Try resource-based load first
    if register_qt_resources():
        f = QFile(':/ui/qss/style.qss')
        if f.open(QFile.ReadOnly | QFile.Text):
            qss = bytes(f.readAll()).decode('utf-8', errors='replace')
            app.setStyleSheet(qss)
            f.close()
            return True
        else:
            print("[style] Could not open :/ui/qss/style.qss from resources.")

    # Fallback to file system (dev mode)
    qss_abs = resource_path('ui/qss/style.qss')
    try:
        with open(qss_abs, 'r', encoding='utf-8') as f:
            qss = f.read()
        app.setStyleSheet(qss)
        print(f"[style] Loaded QSS from disk: {qss_abs}")
        return True
    except Exception as e:
        print(f"[style] Failed to load stylesheet from {qss_abs}: {e}")
        return False
