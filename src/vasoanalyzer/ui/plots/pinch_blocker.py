"""Event filter to block native pinch-to-zoom gestures on macOS trackpads."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QNativeGestureEvent


class PinchBlocker(QObject):
    """Install on QGraphicsView.viewport() to swallow native pinch zoom gestures on macOS.

    Safe no-op on other platforms. This prevents trackpad pinch from triggering zoom,
    allowing only scroll for panning and toolbar buttons for zoom.
    """

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        """Filter native gesture events, blocking pinch-to-zoom."""
        # Qt ≥5.12+: QNativeGestureEvent exists; on other OS this won't fire for zoom
        # Check if it's a zoom gesture (pinch) and block it
        if (
            isinstance(ev, QNativeGestureEvent)
            and hasattr(Qt, "ZoomNativeGesture")
            and ev.gestureType() == Qt.ZoomNativeGesture
        ):
            ev.accept()
            return True  # Consume pinch zoom
        return super().eventFilter(obj, ev)
