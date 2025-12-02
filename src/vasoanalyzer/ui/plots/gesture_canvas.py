# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Gesture-enabled matplotlib canvas with trackpad support."""

from __future__ import annotations

import logging

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from PyQt5.QtCore import QEvent, Qt

log = logging.getLogger(__name__)


class GestureCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas with native trackpad gesture support.

    Supports:
    - Pinch-to-zoom: spread fingers to zoom in, pinch to zoom out
    - Two-finger pan: slide two fingers to pan the plot
    """

    def __init__(self, figure):
        super().__init__(figure)

        log.info("GestureCanvas: Initializing with gesture support")

        # Enable gesture recognition
        pinch_success = self.grabGesture(Qt.PinchGesture)
        pan_success = self.grabGesture(Qt.PanGesture)

        log.info(f"GestureCanvas: grabGesture(PinchGesture) = {pinch_success}")
        log.info(f"GestureCanvas: grabGesture(PanGesture) = {pan_success}")

        # Gesture state
        self._last_scale_factor: float = 1.0
        self._gesture_pan_start: tuple[float, float] | None = None
        self._accumulated_pan_x: float = 0.0
        self._accumulated_pan_y: float = 0.0

        # Callback for gesture events (set by InteractionController)
        self.on_pinch_zoom: callable | None = None
        self.on_pan_gesture: callable | None = None

        # Debug counter
        self._gesture_event_count = 0

    def event(self, event):
        """Override event handler to process gestures."""
        if event.type() == QEvent.Gesture:
            self._gesture_event_count += 1
            log.debug(f"GestureCanvas: Gesture event detected (count={self._gesture_event_count})")
            return self._handle_gesture_event(event)
        return super().event(event)

    def _handle_gesture_event(self, event) -> bool:
        """Handle gesture events (pinch, pan)."""
        log.debug("GestureCanvas: _handle_gesture_event called")

        # Handle pinch gesture for zooming
        pinch = event.gesture(Qt.PinchGesture)
        if pinch is not None:
            log.debug(f"GestureCanvas: Pinch gesture detected, state={pinch.state()}")
            handled = self._handle_pinch_gesture(pinch)
            if handled:
                event.accept()
                return True

        # Handle pan gesture for panning
        pan = event.gesture(Qt.PanGesture)
        if pan is not None:
            log.debug(f"GestureCanvas: Pan gesture detected, state={pan.state()}")
            handled = self._handle_pan_gesture(pan)
            if handled:
                event.accept()
                return True

        return False

    def _handle_pinch_gesture(self, gesture) -> bool:
        """Handle pinch-to-zoom gesture."""
        state = gesture.state()
        log.debug(f"GestureCanvas: _handle_pinch_gesture state={state}")

        if state == Qt.GestureStarted:
            # Store initial scale
            self._last_scale_factor = 1.0
            log.info("GestureCanvas: Pinch gesture STARTED")
            return True

        elif state == Qt.GestureUpdated:
            # Get scale change since last update
            current_scale = gesture.totalScaleFactor()

            # Calculate incremental scale change
            scale_change = current_scale / self._last_scale_factor
            self._last_scale_factor = current_scale

            log.debug(f"GestureCanvas: Pinch UPDATE - scale={current_scale:.3f}, change={scale_change:.3f}")

            # Apply zoom if we have a callback
            if self.on_pinch_zoom and abs(scale_change - 1.0) > 0.01:
                # Get gesture center point
                center = gesture.centerPoint()
                center_x = center.x()
                center_y = center.y()

                # Zoom factor: > 1 means zoom out (pinch fingers)
                # < 1 means zoom in (spread fingers)
                zoom_factor = 1.0 / scale_change

                log.info(f"GestureCanvas: Pinch zoom - center=({center_x:.1f}, {center_y:.1f}), zoom_factor={zoom_factor:.3f}")
                self.on_pinch_zoom(center_x, center_y, zoom_factor)
            elif not self.on_pinch_zoom:
                log.warning("GestureCanvas: Pinch gesture detected but no callback set!")

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            # Reset gesture state
            self._last_scale_factor = 1.0
            log.info(f"GestureCanvas: Pinch gesture {'FINISHED' if state == Qt.GestureFinished else 'CANCELED'}")
            return True

        return False

    def _handle_pan_gesture(self, gesture) -> bool:
        """Handle two-finger pan gesture."""
        state = gesture.state()
        log.debug(f"GestureCanvas: _handle_pan_gesture state={state}")

        if state == Qt.GestureStarted:
            # Reset accumulated pan
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            log.info("GestureCanvas: Pan gesture STARTED")
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

            log.debug(f"GestureCanvas: Pan UPDATE - dx={dx:.1f}, dy={dy:.1f}")

            # Apply pan if we have a callback and delta is significant
            if self.on_pan_gesture and (abs(dx) > 1 or abs(dy) > 1):
                log.info(f"GestureCanvas: Pan gesture - dx={dx:.1f}, dy={dy:.1f}")
                self.on_pan_gesture(dx, dy)
            elif not self.on_pan_gesture:
                log.warning("GestureCanvas: Pan gesture detected but no callback set!")

            return True

        elif state == Qt.GestureFinished or state == Qt.GestureCanceled:
            # Reset gesture state
            self._accumulated_pan_x = 0.0
            self._accumulated_pan_y = 0.0
            log.info(f"GestureCanvas: Pan gesture {'FINISHED' if state == Qt.GestureFinished else 'CANCELED'}")
            return True

        return False
