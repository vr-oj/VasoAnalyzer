"""ViewBox with smooth horizontal pan and momentum-based scrolling."""

from __future__ import annotations

import logging
import math
import time

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsSceneWheelEvent

from vasoanalyzer.ui.plots.pan_only_viewbox import PanOnlyViewBox


log = logging.getLogger(__name__)


class SmoothPanViewBox(PanOnlyViewBox):
    """PanOnlyViewBox with inertia and clean boundary clamping."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._momentum_timer = QTimer()
        self._momentum_timer.setInterval(16)
        self._momentum_timer.timeout.connect(self._on_momentum_tick)

        self._velocity = 0.0
        self._last_input_ts: float | None = None
        self._momentum_ts: float | None = None
        self._drag_active = False
        self._last_drag_ts: float | None = None
        self._last_drag_center: float | None = None

        self._friction = 6.0
        self._min_velocity = 1e-4

    def _current_center(self) -> float:
        (x_min, x_max), _ = self.viewRange()
        return 0.5 * (x_min + x_max)

    def _apply_pan(self, shift: float) -> bool:
        (x_min, x_max), _ = self.viewRange()
        span = x_max - x_min
        if span <= 0:
            return False

        new_x_min = x_min + shift
        new_x_max = x_max + shift
        new_x_min, new_x_max = self._clamp_x_range(new_x_min, new_x_max)

        if math.isclose(new_x_min, x_min, rel_tol=0.0, abs_tol=1e-12) and math.isclose(
            new_x_max, x_max, rel_tol=0.0, abs_tol=1e-12
        ):
            return False

        self.setXRange(new_x_min, new_x_max, padding=0.0, update=True)
        return True

    def _stop_momentum(self) -> None:
        self._velocity = 0.0
        self._momentum_ts = None
        if self._momentum_timer.isActive():
            self._momentum_timer.stop()

    def _start_momentum(self) -> None:
        if abs(self._velocity) < self._min_velocity:
            return
        self._momentum_ts = time.monotonic()
        if not self._momentum_timer.isActive():
            self._momentum_timer.start()

    def _on_momentum_tick(self) -> None:
        if abs(self._velocity) < self._min_velocity:
            self._stop_momentum()
            return

        now = time.monotonic()
        if self._momentum_ts is None:
            self._momentum_ts = now
        dt = max(now - self._momentum_ts, 1e-3)
        self._momentum_ts = now

        shift = self._velocity * dt
        moved = self._apply_pan(shift)
        if not moved:
            self._stop_momentum()
            return

        decay = math.exp(-self._friction * dt)
        self._velocity *= decay

        if abs(self._velocity) < self._min_velocity:
            self._stop_momentum()

    def _update_velocity_from_shift(self, shift: float) -> None:
        now = time.monotonic()
        if self._last_input_ts is None:
            self._velocity = shift / 0.016
            self._last_input_ts = now
            return
        dt = max(now - self._last_input_ts, 1e-3)
        instant = shift / dt
        self._velocity = 0.6 * self._velocity + 0.4 * instant
        self._last_input_ts = now

    def wheelEvent(self, ev: QGraphicsSceneWheelEvent, axis=None, **_ignored) -> None:
        self._stop_momentum()
        try:
            angle_delta = ev.angleDelta().y()
        except Exception:
            try:
                angle_delta = ev.delta()
            except Exception:
                angle_delta = 0
        if angle_delta == 0:
            try:
                pixel_delta = ev.pixelDelta().y()
            except Exception:
                pixel_delta = 0
            angle_delta = pixel_delta

        if angle_delta == 0:
            ev.accept()
            return

        (x_min, x_max), _ = self.viewRange()
        span = x_max - x_min
        if span <= 0:
            ev.accept()
            return

        zoom_in = angle_delta > 0
        factor = 0.9 if zoom_in else 1.1
        new_span = span * factor
        if self._min_x_range is not None:
            new_span = max(new_span, float(self._min_x_range))
        if self._max_x_range is not None:
            new_span = min(new_span, float(self._max_x_range))

        center = 0.5 * (x_min + x_max)
        new_x_min = center - new_span * 0.5
        new_x_max = center + new_span * 0.5
        new_x_min, new_x_max = self._clamp_x_range(new_x_min, new_x_max)
        self.setXRange(new_x_min, new_x_max, padding=0.0, update=True)

        try:
            self.sigWheelEvent.emit(ev)
        except Exception:
            log.exception("Error emitting sigWheelEvent from SmoothPanViewBox")

        ev.accept()

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent) -> None:
        self._stop_momentum()
        super().mousePressEvent(ev)
        self.sigMousePressEvent.emit(ev)

    def mouseReleaseEvent(self, ev: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(ev)
        self.sigMouseReleaseEvent.emit(ev)

    def mouseDragEvent(self, ev, axis=None) -> None:  # type: ignore[override]
        if ev.isStart():
            self._stop_momentum()
            self._drag_active = True
            self._last_drag_ts = time.monotonic()
            self._last_drag_center = self._current_center()

        super().mouseDragEvent(ev, axis=axis)

        if self._drag_active:
            now = time.monotonic()
            if self._last_drag_ts is None or self._last_drag_center is None:
                self._last_drag_ts = now
                self._last_drag_center = self._current_center()
            else:
                dt = max(now - self._last_drag_ts, 1e-3)
                center = self._current_center()
                self._velocity = (center - self._last_drag_center) / dt
                self._last_drag_ts = now
                self._last_drag_center = center

        if ev.isFinish():
            self._drag_active = False
            self._start_momentum()
