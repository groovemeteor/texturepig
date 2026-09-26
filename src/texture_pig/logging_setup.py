# texture_pig/logging_setup.py
"""
Central logging configuration for Texture Pig.

Why this exists: the packaged app builds with console=False (see
TexturePig.spec), which means the distributed .exe has no stdout/stderr for
`print()` to write to. Every `print("...failed...")` diagnostic that used to
help debug undo/redo, node-restore, or loader failures during development
simply vanishes for end users running the real build.

This module routes all of that through the standard `logging` module into a
rotating log file next to the user's app data, plus stderr when one is
actually attached (e.g. running from source). It also installs a global
excepthook so exceptions that escape into the Qt event loop are recorded
instead of silently killing the app with no trace.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_configured = False


def get_log_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "TexturePig"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "TexturePig"
    return Path.home() / ".local" / "share" / "texture_pig" / "logs"


def _install_excepthook() -> None:
    logger = logging.getLogger("texture_pig.uncaught")

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _hook


def setup_logging(level: int = logging.INFO) -> Path:
    """
    Configure the root logger once (idempotent). Returns the active log file path.
    """
    global _configured

    log_dir = get_log_dir()
    log_path = log_dir / "texture_pig.log"

    if _configured:
        return log_path

    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Only useful when a console is actually attached (running from source, or
    # a console=True debug build); a harmless no-op in the windowed release.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)

    _install_excepthook()

    _configured = True
    logging.getLogger(__name__).info("Logging initialized -> %s", log_path)
    return log_path
