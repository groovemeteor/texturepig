# tests/conftest.py
import pytest


@pytest.fixture(scope="session")
def qcore_app():
    """
    A QCoreApplication instance, needed for any test that touches QObject/Signal
    (e.g. GraphLoadWorker) even when nothing is actually rendered on screen.
    Session-scoped since Qt only allows one application instance per process.
    """
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app
