"""Canvas compatibility layer for PyQtGraph to support matplotlib-style events."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtWidgets import QVBoxLayout, QWidget

log = logging.getLogger(__name__)


class _DummyWidgetLock:
    """Dummy widget lock for matplotlib toolbar compatibility.

    Matplotlib toolbars use widgetlock to prevent multiple tools
    from being active simultaneously. PyQtGraph doesn't need this,
    so we provide a dummy that always returns True for availability.
    """

    def available(self, *args, **kwargs) -> bool:
        """Always return True - no locking needed for PyQtGraph."""
        return True

    def __call__(self, *args, **kwargs):
        """Make it callable for compatibility."""
        return self

    def release(self, *args, **kwargs):
        """Release lock (no-op for PyQtGraph)."""
        pass


class PyQtGraphCanvasCompat(QWidget):
    """Compatibility wrapper for PyQtGraph canvas to support matplotlib event connections.

    This allows matplotlib-style event handlers to work with PyQtGraph widgets,
    enabling gradual migration without breaking existing code.
    """

    def __init__(self, pyqtgraph_widget: QWidget) -> None:
        super().__init__()
        self._pg_widget = pyqtgraph_widget
        self._event_handlers: dict[str, list[Callable]] = {
            "draw_event": [],
            "motion_notify_event": [],
            "button_press_event": [],
            "button_release_event": [],
            "figure_leave_event": [],
            "scroll_event": [],  # CRITICAL: Required for pan/zoom interactions
        }
        self._connection_ids: int = 0

        # Matplotlib compatibility attributes
        self.toolbar: Any = None
        self.figure: Any = None  # PyQtGraph doesn't use matplotlib Figure
        self.widgetlock: Any = _DummyWidgetLock()  # For toolbar pan/zoom compatibility

        # Create layout and add the PyQtGraph widget to it
        # This ensures the canvas wrapper actually displays the plots
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._pg_widget)

        # Install event filter on PyQtGraph widget to intercept events
        self._pg_widget.installEventFilter(self)

    def mpl_connect(self, event_name: str, callback: Callable) -> int:
        """Connect a matplotlib-style event handler.

        Args:
            event_name: Event type (e.g., "button_press_event")
            callback: Handler function

        Returns:
            Connection ID for later disconnection
        """
        if event_name not in self._event_handlers:
            # Unsupported event type - return dummy ID
            return -1

        self._event_handlers[event_name].append(callback)
        self._connection_ids += 1
        return self._connection_ids

    def mpl_disconnect(self, cid: int) -> None:
        """Disconnect an event handler (not implemented for simplicity)."""
        pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Intercept Qt events and translate to matplotlib-style events."""
        if obj != self._pg_widget:
            return False

        # WHEEL EVENTS: Translate to matplotlib scroll_event (for compatibility only)
        # Note: PyQtGraph's PanOnlyViewBox handles wheel directly now, so this is mainly
        # for any matplotlib-style event handlers that might be listening
        if event.type() == QEvent.Wheel and isinstance(event, QWheelEvent):
            mock_event = self._create_mock_wheel_event(event)
            self._dispatch_event("scroll_event", mock_event)
            return False  # Don't consume - ViewBox will handle it

        # Mouse move -> motion_notify_event
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent):
            mock_event = self._create_mock_mouse_event(event)
            self._dispatch_event("motion_notify_event", mock_event)

        # Mouse press -> button_press_event
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            mock_event = self._create_mock_mouse_event(event)
            self._dispatch_event("button_press_event", mock_event)

        # Mouse release -> button_release_event
        elif event.type() == QEvent.MouseButtonRelease and isinstance(event, QMouseEvent):
            mock_event = self._create_mock_mouse_event(event)
            self._dispatch_event("button_release_event", mock_event)

        # Leave -> figure_leave_event
        elif event.type() == QEvent.Leave:
            mock_event = type("Event", (), {"canvas": self})()
            self._dispatch_event("figure_leave_event", mock_event)

        return False  # Don't consume events

    def _create_mock_mouse_event(self, qt_event: QMouseEvent) -> Any:
        """Create a matplotlib-compatible mock event from Qt event."""
        # Mock matplotlib mouse event
        mock_event = type(
            "MouseEvent",
            (),
            {
                "x": qt_event.x(),
                "y": qt_event.y(),
                "button": self._qt_button_to_mpl(qt_event.button()),
                "xdata": None,  # Would need axis transformation
                "ydata": None,  # Would need axis transformation
                "canvas": self,
                "guiEvent": qt_event,
            },
        )()
        return mock_event

    def _create_mock_wheel_event(self, qt_event: QWheelEvent) -> Any:
        """Create a matplotlib-compatible scroll event from Qt wheel event."""
        # Get scroll direction from wheel delta
        delta = qt_event.angleDelta().y()
        step = 1 if delta > 0 else -1

        # Extract modifier keys from Qt event
        modifiers = qt_event.modifiers()
        key_parts = []
        if modifiers & Qt.ControlModifier:
            key_parts.append("ctrl")
        if modifiers & Qt.ShiftModifier:
            key_parts.append("shift")
        if modifiers & Qt.AltModifier:
            key_parts.append("alt")
        if modifiers & Qt.MetaModifier:
            key_parts.append("cmd")  # Meta key is Cmd on macOS
        key_str = "+".join(key_parts) if key_parts else None

        # Create mock matplotlib scroll event
        mock_event = type(
            "MouseEvent",
            (),
            {
                "x": qt_event.position().x() if hasattr(qt_event.position(), "x") else qt_event.x(),
                "y": qt_event.position().y() if hasattr(qt_event.position(), "y") else qt_event.y(),
                "button": "up" if step > 0 else "down",
                "step": step,
                "xdata": None,  # Would need axis transformation
                "ydata": None,  # Would need axis transformation
                "canvas": self,
                "guiEvent": qt_event,
                "key": key_str,  # Now contains actual modifier keys
            },
        )()
        return mock_event

    def _qt_button_to_mpl(self, qt_button: Qt.MouseButton) -> int:
        """Convert Qt mouse button to matplotlib button number."""
        if qt_button == Qt.LeftButton:
            return 1
        elif qt_button == Qt.MiddleButton:
            return 2
        elif qt_button == Qt.RightButton:
            return 3
        return 0

    def _dispatch_event(self, event_name: str, event: Any) -> None:
        """Dispatch event to all registered handlers."""
        for handler in self._event_handlers.get(event_name, []):
            # Silently ignore handler exceptions to prevent crashes
            with contextlib.suppress(Exception):
                handler(event)

    def draw(self) -> None:
        """Trigger a redraw (matplotlib compatibility)."""
        # Dispatch draw_event
        mock_event = type("Event", (), {"canvas": self})()
        self._dispatch_event("draw_event", mock_event)

        # Force PyQtGraph widget update
        self._pg_widget.update()

    def draw_idle(self) -> None:
        """Schedule a redraw on next event loop (matplotlib compatibility)."""
        self.draw()

    def setMouseTracking(self, enable: bool) -> None:
        """Set mouse tracking for the PyQtGraph widget."""
        self._pg_widget.setMouseTracking(enable)

    def width(self) -> int:
        """Get widget width."""
        return self._pg_widget.width()

    def height(self) -> int:
        """Get widget height."""
        return self._pg_widget.height()

    def get_renderer(self) -> None:
        """Get renderer (matplotlib compatibility - returns None for PyQtGraph)."""
        return None

    def get_width_height(self) -> tuple[int, int]:
        """Get canvas width and height (for gesture scaling)."""
        return (self._pg_widget.width(), self._pg_widget.height())
