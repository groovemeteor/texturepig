# packaging/launcher.py - entry script for PyInstaller builds.
#
# Uses absolute imports so the frozen app doesn't hit "relative import with no
# known parent package". PyInstaller bundles the package itself (see pathex in
# TexturePig.spec pointing at src/), so no sys.path juggling is needed here.

import logging
import sys

from texture_pig.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    logger = logging.getLogger(__name__)
    try:
        from texture_pig.ui.qt_editor import run
        run()
    except Exception:
        # console=False in the packaged build means an uncaught exception here
        # would otherwise vanish with no trace at all. Log it before exiting.
        logger.critical("Fatal error during startup/run", exc_info=True)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
