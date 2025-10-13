from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

from PyQt5.QtCore import QSignalBlocker


@contextmanager
def block_signals(widgets: Iterable[object]):
    """Temporarily block signals for an iterable of Qt widgets."""

    blockers = [QSignalBlocker(getattr(widget, "widget", widget)) for widget in widgets if widget is not None]
    try:
        yield
    finally:
        del blockers

