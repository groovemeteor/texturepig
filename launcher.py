# launcher.py - Entry point for PyInstaller builds
# Uses absolute imports to avoid "relative import with no known parent package" error

import sys
import os

# Ensure the package root is in the path
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    app_path = os.path.dirname(sys.executable)
    if app_path not in sys.path:
        sys.path.insert(0, app_path)

from texture_pig.ui.qt_editor import run

if __name__ == "__main__":
    run()
