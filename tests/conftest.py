"""Shared pytest fixtures for UI and plotting tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg", force=True)

import pytest
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def configure_qsettings(tmp_path_factory):
    """Persist Qt settings within a temporary directory during tests."""

    root = tmp_path_factory.mktemp("qt_settings")
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, root.as_posix())
    QSettings.setDefaultFormat(QSettings.IniFormat)
    return root


@pytest.fixture(scope="session")
def qapp():
    """Return a shared QApplication instance for tests."""

    app = QApplication.instance() or QApplication([])
    yield app
    app.quit()
