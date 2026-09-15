# ui/style.py
import logging
import os
import sys
from PySide6.QtCore import QResource, QFile
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

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
            logger.warning("Failed to register Qt resources: %s", rcc_path)
        return bool(ok)
    else:
        logger.debug(".rcc not found at %s (falling back to filesystem)", rcc_path)
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
            logger.warning("Could not open :/ui/qss/style.qss from resources.")

    # Fallback to file system (dev mode)
    qss_abs = resource_path('ui/qss/style.qss')
    try:
        with open(qss_abs, 'r', encoding='utf-8') as f:
            qss = f.read()
        app.setStyleSheet(qss)
        logger.debug("Loaded QSS from disk: %s", qss_abs)
        return True
    except Exception:
        logger.exception("Failed to load stylesheet from %s", qss_abs)
        return False
