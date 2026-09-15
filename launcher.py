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

from texture_pig.logging_setup import setup_logging

_logger = None

if __name__ == "__main__":
    setup_logging()
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from texture_pig.ui.qt_editor import run
        run()
    except Exception:
        # console=False in the packaged build means an uncaught exception here
        # would otherwise vanish with no trace at all. Log it before exiting.
        _logger.critical("Fatal error during startup/run", exc_info=True)
        raise
