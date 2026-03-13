import pytest

from PyQt6.QtCore import QCoreApplication, QSettings, Qt
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _force_snapshot_keep_count() -> None:
    settings = QSettings("TykockiLab", "VasoAnalyzer")
    key = "snapshots/keep_count"
    had_value = settings.contains(key)
    previous_value = settings.value(key) if had_value else None

    settings.setValue(key, 2)
    settings.sync()

    yield

    if had_value:
        settings.setValue(key, previous_value)
    else:
        settings.remove(key)
    settings.sync()


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi, True)
        app = QApplication([])
    return app
