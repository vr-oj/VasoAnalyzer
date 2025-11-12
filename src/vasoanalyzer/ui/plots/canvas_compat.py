"""Canvas compatibility layer for PyQtGraph to support matplotlib-style events."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QMouseEvent
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
        }
        self._connection_ids: int = 0

        # Matplotlib compatibility attributes
        self.toolbar: Any = None
        self.figure: Any = None  # PyQtGraph doesn't use matplotlib Figure
        self.widgetlock: Any = _DummyWidgetLock()  # For toolbar pan/zoom compatibility

        # Gesture support - enable on BOTH wrapper and child widget
        log.info("PyQtGraphCanvasCompat: Initializing with gesture support")
        self.grabGesture(Qt.PinchGesture)
        self.grabGesture(Qt.PanGesture)
        log.info("PyQtGraphCanvasCompat (wrapper): Gestures enabled")

        # CRITICAL: Also enable gestures on the child PyQtGraph widget
        # This is where user interactions actually occur!
        self._pg_widget.grabGesture(Qt.PinchGesture)
        self._pg_widget.grabGesture(Qt.PanGesture)
        log.info("PyQtGraphCanvasCompat (child): Gestures enabled")

        self._last_scale_factor: float = 1.0
        self._accumulated_pan_x: float = 0.0
        self._accumulated_pan_y: float = 0.0
        self.on_pinch_zoom: Callable | None = None
        self.on_pan_gesture: Callable | None = None

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

    def event(self, event: QEvent) -> bool:
        """Override event handler to process gestures."""
        if event.type() == QEvent.Gesture:
            log.debug("PyQtGraphCanvasCompat: Gesture event detected")
            return self._handle_gesture_event(event)
        return super().event(event)

    def _handle_gesture_event(self, event) -> bool:
        """Handle gesture events (pinch, pan)."""
        # Handle pinch gesture for zooming
        pinch = event.gesture(Qt.PinchGesture)
        if pinch is not None:
            log.debug(f"PyQtGraphCanvasCompat: Pinch gesture detected, state={pinch.state()}")
            handled = self._handle_pinch_gesture(pinch)
            if handled:
                event.accept()
                return True

        # Handle pan gesture for panning
        pan = event.gesture(Qt.PanGesture)
        if pan is not None:
            log.debug(f"PyQtGraphCanvasCompat: Pan gesture detected, state={pan.state()}")
            handled = self._handle_pan_gesture(pan)
            if handled:
                event.accept()
                return True

        return False

    def _handle_pinch_gesture(self, gesture) -> bool:
        """Handle pinch-to-zoom gesture."""
        state = gesture.state()

        if state == Qt.GestureStarted:
            self._last_scale_factor = 1.0
            log.info("PyQtGraphCanvasCompat: Pinch gesture STARTED")
            return True

        elif state == Qt.GestureUpdated:
            current_scale = gesture.totalScaleFactor()
            scale_change = current_scale / self._last_scale_factor
            self._last_scale_factor = current_scale

            # Only trigger pinch zoom for significant scale changes (> 2%)
            # This prevents horizontal swipes from being misdetected as pinch
            if self.on_pinch_zoom and abs(scale_change - 1.0) > 0.02:
                center = gesture.centerPoint()
                zoom_factor = 1.0 / scale_change
                log.info(f"PyQtGraphCanvasCompat: Pinch zoom - zoom_factor={zoom_factor:.3f}")
                self.on_pinch_zoom(center.x(), center.y(), zoom_factor)
            elif abs(scale_change - 1.0) <= 0.02:
                # Ignore tiny scale changes (likely from horizontal swipe)
                log.debug(f"PyQtGraphCanvasCompat: Ignoring tiny scale change: {scale_change:.4f}")
            elif not self.on_pinch_zoom:
                log.warning("PyQtGraphCanvasCompat: Pinch gesture detected but no callback set!")

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            self._last_scale_factor = 1.0
            log.info(
                f"PyQtGraphCanvasCompat: Pinch gesture {'FINISHED' if state == Qt.GestureFinished else 'CANCELED'}"
            )
            return True

        return False

    def _handle_pan_gesture(self, gesture) -> bool:
        """Handle two-finger pan gesture."""
        state = gesture.state()

        if state == Qt.GestureStarted:
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            log.info("PyQtGraphCanvasCompat: Pan gesture STARTED")
            return True

        elif state == Qt.GestureUpdated:
            offset = gesture.offset()
            total_dx = offset.x()
            total_dy = offset.y()

            dx = total_dx - self._accumulated_pan_x
            dy = total_dy - self._accumulated_pan_y

            self._accumulated_pan_x = total_dx
            self._accumulated_pan_y = total_dy

            if self.on_pan_gesture and (abs(dx) > 1 or abs(dy) > 1):
                log.info(f"PyQtGraphCanvasCompat: Pan gesture - dx={dx:.1f}, dy={dy:.1f}")
                self.on_pan_gesture(dx, dy)
            elif not self.on_pan_gesture:
                log.warning("PyQtGraphCanvasCompat: Pan gesture detected but no callback set!")

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            log.info(
                f"PyQtGraphCanvasCompat: Pan gesture {'FINISHED' if state == Qt.GestureFinished else 'CANCELED'}"
            )
            return True

        return False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Intercept Qt events and translate to matplotlib-style events."""
        if obj != self._pg_widget:
            return False

        # GESTURE EVENTS: Forward gestures from child widget to wrapper
        if event.type() == QEvent.Gesture:
            log.debug("PyQtGraphCanvasCompat: Gesture event from child widget, handling...")
            return self._handle_gesture_event(event)

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
