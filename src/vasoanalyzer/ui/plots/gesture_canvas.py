# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Gesture-enabled matplotlib canvas with trackpad support."""

from __future__ import annotations

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from PyQt5.QtCore import QEvent, Qt


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
        self._last_scale_factor: float = 1.0
        self._gesture_pan_start: tuple[float, float] | None = None
        self._accumulated_pan_x: float = 0.0
        self._accumulated_pan_y: float = 0.0

        # Callback for gesture events (set by InteractionController)
        self.on_pinch_zoom: callable | None = None
        self.on_pan_gesture: callable | None = None

    def event(self, event):
        """Override event handler to process gestures."""
        if event.type() == QEvent.Gesture:
            return self._handle_gesture_event(event)
        return super().event(event)

    def _handle_gesture_event(self, event) -> bool:
        """Handle gesture events (pinch, pan)."""
        # Handle pinch gesture for zooming
        pinch = event.gesture(Qt.PinchGesture)
        if pinch is not None:
            handled = self._handle_pinch_gesture(pinch)
            if handled:
                event.accept()
                return True

        # Handle pan gesture for panning
        pan = event.gesture(Qt.PanGesture)
        if pan is not None:
            handled = self._handle_pan_gesture(pan)
            if handled:
                event.accept()
                return True

        return False

    def _handle_pinch_gesture(self, gesture) -> bool:
        """Handle pinch-to-zoom gesture."""
        state = gesture.state()

        if state == Qt.GestureStarted:
            # Store initial scale
            self._last_scale_factor = 1.0
            return True

        elif state == Qt.GestureUpdated:
            # Get scale change since last update
            current_scale = gesture.totalScaleFactor()

            # Calculate incremental scale change
            scale_change = current_scale / self._last_scale_factor
            self._last_scale_factor = current_scale

            # Apply zoom if we have a callback
            if self.on_pinch_zoom and abs(scale_change - 1.0) > 0.01:
                # Get gesture center point
                center = gesture.centerPoint()
                center_x = center.x()
                center_y = center.y()

                # Zoom factor: > 1 means zoom out (pinch fingers)
                # < 1 means zoom in (spread fingers)
                zoom_factor = 1.0 / scale_change

                self.on_pinch_zoom(center_x, center_y, zoom_factor)

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            # Reset gesture state
            self._last_scale_factor = 1.0
            return True

        return False

    def _handle_pan_gesture(self, gesture) -> bool:
        """Handle two-finger pan gesture."""
        state = gesture.state()

        if state == Qt.GestureStarted:
            # Reset accumulated pan
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            return True

        elif state == Qt.GestureUpdated:
            # Get total pan offset from start
            offset = gesture.offset()
            total_dx = offset.x()
            total_dy = offset.y()

            # Calculate incremental delta since last update
            dx = total_dx - self._accumulated_pan_x
            dy = total_dy - self._accumulated_pan_y

            # Update accumulated values
            self._accumulated_pan_x = total_dx
            self._accumulated_pan_y = total_dy

            # Apply pan if we have a callback and delta is significant
            if self.on_pan_gesture and (abs(dx) > 1 or abs(dy) > 1):
                self.on_pan_gesture(dx, dy)

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            # Reset gesture state
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            return True

        return False
