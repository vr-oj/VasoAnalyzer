from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager

from PyQt5.QtCore import QObject, QSignalBlocker


@contextmanager
def block_signals(widgets: Iterable[object]):
    """Temporarily block signals for an iterable of Qt widgets."""

    blockers = []
    for widget in widgets:
        if widget is None:
            continue
        candidate = getattr(widget, "widget", widget)
        if isinstance(candidate, QObject):
            blockers.append(QSignalBlocker(candidate))
    try:
        yield
    finally:
        del blockers
