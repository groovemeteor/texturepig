# tests/test_logging_setup.py
"""
Tests for texture_pig.logging_setup. This module exists specifically because
the packaged app runs with console=False (TexturePig.spec), so print()
diagnostics have nowhere to go in production -- these tests just confirm the
file handler actually gets attached and writes records.
"""
import logging

import texture_pig.logging_setup as logging_setup


def test_setup_logging_creates_log_file(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "_configured", False, raising=False)
    monkeypatch.setattr(logging_setup, "get_log_dir", lambda: tmp_path)

    log_path = logging_setup.setup_logging()

    assert log_path == tmp_path / "texture_pig.log"
    assert log_path.exists()

    logger = logging.getLogger("texture_pig.tests.dummy")
    logger.warning("hello from test")
    for h in logging.getLogger().handlers:
        h.flush()

    assert "hello from test" in log_path.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_setup, "_configured", False, raising=False)
    monkeypatch.setattr(logging_setup, "get_log_dir", lambda: tmp_path)

    first = logging_setup.setup_logging()
    root = logging.getLogger()
    handler_count = len(root.handlers)

    second = logging_setup.setup_logging()

    assert first == second
    assert len(root.handlers) == handler_count  # no duplicate handlers added
