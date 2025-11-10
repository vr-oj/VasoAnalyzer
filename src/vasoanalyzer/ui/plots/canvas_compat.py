"""Canvas compatibility layer for PyQtGraph to support matplotlib-style events."""

from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QWidget, QVBoxLayout


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
        }
        self._connection_ids: int = 0
        self.toolbar: Any = None  # Compatibility attribute

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

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """Intercept Qt events and translate to matplotlib-style events."""
        if obj != self._pg_widget:
            return False

        # Mouse move -> motion_notify_event
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent):
            mock_event = self._create_mock_mouse_event(event)
            self._dispatch_event("motion_notify_event", mock_event)

        # Mouse press -> button_press_event
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            mock_event = self._create_mock_mouse_event(event)
            self._dispatch_event("button_press_event", mock_event)

        # Mouse release -> button_release_event
        elif event.type() == QEvent.MouseButtonRelease and isinstance(
            event, QMouseEvent
        ):
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
            try:
                handler(event)
            except Exception:
                # Silently ignore handler exceptions to prevent crashes
                pass

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
