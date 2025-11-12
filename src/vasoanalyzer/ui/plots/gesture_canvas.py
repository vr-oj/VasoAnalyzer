# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Gesture-enabled matplotlib canvas with trackpad support."""

from __future__ import annotations

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGestureEvent


class GestureCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas with native trackpad gesture support.

    Supports:
    - Pinch-to-zoom: spread fingers to zoom in, pinch to zoom out
    - Two-finger pan: slide two fingers to pan the plot
    """

    def __init__(self, figure):
        super().__init__(figure)

        # Enable gesture recognition
        self.grabGesture(Qt.PinchGesture)
        self.grabGesture(Qt.PanGesture)

        # Gesture state
        self._gesture_zoom_center: tuple[float, float] | None = None
        self._gesture_zoom_factor: float = 1.0
        self._gesture_pan_start: tuple[float, float] | None = None

        # Callback for gesture events (set by InteractionController)
        self.on_pinch_zoom: callable | None = None
        self.on_pan_gesture: callable | None = None

    def event(self, event):
        """Override event handler to process gestures."""
        if event.type() == QGestureEvent.Gesture:
            return self._handle_gesture_event(event)
        return super().event(event)

    def _handle_gesture_event(self, event: QGestureEvent) -> bool:
        """Handle gesture events (pinch, pan)."""
        gesture_event = event

        # Handle pinch gesture for zooming
        pinch = gesture_event.gesture(Qt.PinchGesture)
        if pinch is not None:
            return self._handle_pinch_gesture(pinch)

        # Handle pan gesture for panning
        pan = gesture_event.gesture(Qt.PanGesture)
        if pan is not None:
            return self._handle_pan_gesture(pan)

        return False

    def _handle_pinch_gesture(self, gesture) -> bool:
        """Handle pinch-to-zoom gesture."""
        if gesture.state() == Qt.GestureStarted:
            # Store initial zoom state
            center = gesture.centerPoint()
            self._gesture_zoom_center = (center.x(), center.y())
            self._gesture_zoom_factor = 1.0

        elif gesture.state() == Qt.GestureUpdated:
            # Calculate zoom delta from scale change
            scale_factor = gesture.scaleFactor()

            # Apply zoom if we have a callback
            if self.on_pinch_zoom and self._gesture_zoom_center:
                # Convert widget coordinates to data coordinates
                center_x, center_y = self._gesture_zoom_center

                # Zoom factor: > 1 means zoom in (spread fingers)
                # < 1 means zoom out (pinch fingers)
                zoom_factor = 1.0 / scale_factor  # Invert for intuitive feel

                self.on_pinch_zoom(center_x, center_y, zoom_factor)

        elif gesture.state() == Qt.GestureFinished or gesture.state() == Qt.GestureCanceled:
            # Reset gesture state
            self._gesture_zoom_center = None
            self._gesture_zoom_factor = 1.0

        return True

    def _handle_pan_gesture(self, gesture) -> bool:
        """Handle two-finger pan gesture."""
        if gesture.state() == Qt.GestureStarted:
            # Store initial pan position
            delta = gesture.delta()
            self._gesture_pan_start = (delta.x(), delta.y())

        elif gesture.state() == Qt.GestureUpdated:
            # Get pan delta
            delta = gesture.delta()
            dx = delta.x()
            dy = delta.y()

            # Apply pan if we have a callback
            if self.on_pan_gesture:
                self.on_pan_gesture(dx, dy)

        elif gesture.state() == Qt.GestureFinished or gesture.state() == Qt.GestureCanceled:
            # Reset gesture state
            self._gesture_pan_start = None

        return True
