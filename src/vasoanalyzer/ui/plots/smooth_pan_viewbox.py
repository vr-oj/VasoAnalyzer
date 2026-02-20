"""ViewBox with smooth horizontal pan and momentum-based scrolling."""

from __future__ import annotations

import contextlib
import logging
import math
import time
from collections.abc import Callable

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsSceneWheelEvent

from vasoanalyzer.ui.plots.pan_only_viewbox import PanOnlyViewBox
from vasoanalyzer.ui.plots.pyqtgraph_nav_math import (
    ZOOM_STEP_IN,
    ZOOM_STEP_OUT,
    pan_step,
    zoomed_range,
)
from vasoanalyzer.ui.plots.pyqtgraph_style import apply_selection_box_style, get_pyqtgraph_style

log = logging.getLogger(__name__)
DEFAULT_WHEEL_PAN_FRACTION = 0.05


class SmoothPanViewBox(PanOnlyViewBox):
    """PanOnlyViewBox with inertia and clean boundary clamping."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._xrange_source_callback = None
        self._request_pan_x: Callable[[float, str], None] | None = None
        self._request_zoom_x: Callable[[float, float | None, str], None] | None = None
        self._request_window: Callable[[float, float, str], None] | None = None
        self._get_current_xrange: Callable[[], tuple[float, float]] | None = None
        self._momentum_timer = QTimer()
        self._momentum_timer.setInterval(16)
        self._momentum_timer.timeout.connect(self._on_momentum_tick)

        self._velocity = 0.0
        self._last_input_ts: float | None = None
        self._momentum_ts: float | None = None
        self._drag_active = False
        self._last_drag_ts: float | None = None
        self._last_drag_center: float | None = None
        self._drag_last_pos: QPointF | None = None

        self._friction = 6.0
        self._min_velocity = 1e-4

        with contextlib.suppress(Exception):
            style = get_pyqtgraph_style()
            apply_selection_box_style(self, style.selection_box)

    def set_xrange_source_callback(self, callback) -> None:
        """Register a callback to tag x-range updates for debugging."""
        self._xrange_source_callback = callback

    def set_time_window_requesters(
        self,
        *,
        pan_x: Callable[[float, str], None] | None = None,
        zoom_x: Callable[[float, float | None, str], None] | None = None,
        set_window: Callable[[float, float, str], None] | None = None,
        get_window: Callable[[], tuple[float, float]] | None = None,
    ) -> None:
        """Attach host-driven navigation callbacks.

        - pan_x(dt_seconds, reason): request pan by dt seconds
        - zoom_x(factor, anchor_x, reason): request zoom by factor anchored at x (seconds)
        - set_window(x0, x1, reason): request absolute window
        """
        self._request_pan_x = pan_x
        self._request_zoom_x = zoom_x
        self._request_window = set_window
        self._get_current_xrange = get_window

    def request_set_window(self, x0: float, x1: float, reason: str = "external") -> bool:
        """Request a host-controlled X window set."""
        if self._request_window is None:
            return False
        self._request_window(float(x0), float(x1), str(reason))
        return True

    def _is_host_driven_xmode(self) -> bool:
        return (
            self._request_pan_x is not None
            or self._request_zoom_x is not None
            or self._request_window is not None
        )

    def _current_center(self) -> float:
        (x_min, x_max), _ = self.viewRange()
        return 0.5 * (x_min + x_max)

    def _apply_pan(self, shift: float) -> bool:
        if self._is_host_driven_xmode():
            log.warning("Blocked direct X-range mutation in host-driven mode.")
            return False
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

    def _apply_y_pan(self, shift: float) -> bool:
        _, (y_min, y_max) = self.viewRange()
        span = y_max - y_min
        if span <= 0:
            return False
        new_y_min = y_min + shift
        new_y_max = y_max + shift
        self.setYRange(new_y_min, new_y_max, padding=0.0, update=True)
        return True

    def _zoom_x_at(self, anchor_x: float | None, factor: float) -> bool:
        if self._is_host_driven_xmode():
            log.warning("Blocked direct X-range mutation in host-driven mode.")
            return False
        (x_min, x_max), (y_min, y_max) = self.viewRange()
        new_x_min, new_x_max = zoomed_range(
            x_min,
            x_max,
            anchor_x,
            factor,
            min_span=self._min_x_range,
            max_span=self._max_x_range,
        )
        new_x_min, new_x_max = self._clamp_x_range(new_x_min, new_x_max)
        if math.isclose(new_x_min, x_min, rel_tol=0.0, abs_tol=1e-12) and math.isclose(
            new_x_max, x_max, rel_tol=0.0, abs_tol=1e-12
        ):
            return False

        self._push_zoom_history(new_x_min, new_x_max, y_min, y_max)
        self.setXRange(new_x_min, new_x_max, padding=0.0, update=True)
        return True

    def zoom_x_at(self, anchor_x: float | None, factor: float) -> bool:
        """Public wrapper for cursor-anchored X zoom."""
        return self._zoom_x_at(anchor_x, factor)

    def set_x_range_with_history(self, x_min: float, x_max: float) -> None:
        """Set X range while pushing a zoom history entry."""
        if self._is_host_driven_xmode():
            log.warning("Blocked direct X-range mutation in host-driven mode.")
            return
        _, (y_min, y_max) = self.viewRange()
        self._push_zoom_history(x_min, x_max, y_min, y_max)
        self.setXRange(float(x_min), float(x_max), padding=0.0, update=True)

    def _zoom_y_at(self, anchor_y: float | None, factor: float) -> bool:
        _, (y_min, y_max) = self.viewRange()
        new_y_min, new_y_max = zoomed_range(
            y_min,
            y_max,
            anchor_y,
            factor,
            min_span=1e-9,
            max_span=None,
        )
        if math.isclose(new_y_min, y_min, rel_tol=0.0, abs_tol=1e-12) and math.isclose(
            new_y_max, y_max, rel_tol=0.0, abs_tol=1e-12
        ):
            return False
        self.setYRange(new_y_min, new_y_max, padding=0.0, update=True)
        return True

    def _push_zoom_history(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        try:
            span_x = max(float(x_max) - float(x_min), 1e-9)
            span_y = max(float(y_max) - float(y_min), 1e-9)
            new_rect = QRectF(float(x_min), float(y_min), span_x, span_y)

            if self.axHistoryPointer < 0:
                (cur_x_min, cur_x_max), (cur_y_min, cur_y_max) = self.viewRange()
                cur_span_x = max(float(cur_x_max) - float(cur_x_min), 1e-9)
                cur_span_y = max(float(cur_y_max) - float(cur_y_min), 1e-9)
                current_rect = QRectF(float(cur_x_min), float(cur_y_min), cur_span_x, cur_span_y)
                self.axHistory = [current_rect]
                self.axHistoryPointer = 0

            if self.axHistoryPointer < len(self.axHistory) - 1:
                self.axHistory = self.axHistory[: self.axHistoryPointer + 1]

            self.axHistory.append(new_rect)
            self.axHistoryPointer = len(self.axHistory) - 1
        except Exception:
            return

    def _wheel_steps(self, ev: QGraphicsSceneWheelEvent) -> float:
        angle_delta = 0
        try:
            angle_delta = ev.angleDelta().y()
        except Exception:
            try:
                angle_delta = ev.delta()
            except Exception:
                angle_delta = 0
        if angle_delta == 0:
            try:
                angle_delta = ev.pixelDelta().y()
            except Exception:
                angle_delta = 0
        if angle_delta == 0:
            return 0.0
        return float(angle_delta) / 120.0

    def _anchor_from_event(self, ev: QGraphicsSceneWheelEvent) -> QPointF | None:
        try:
            scene_pos = ev.scenePos()
        except Exception:
            return None
        try:
            return self.mapSceneToView(scene_pos)
        except Exception:
            return None

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
        steps = self._wheel_steps(ev)
        if steps == 0:
            ev.accept()
            return

        modifiers = Qt.NoModifier
        with contextlib.suppress(Exception):
            modifiers = ev.modifiers()
        ctrl_or_cmd = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        shift = bool(modifiers & Qt.ShiftModifier)
        alt = bool(modifiers & Qt.AltModifier)

        if ctrl_or_cmd:
            factor = (ZOOM_STEP_IN ** abs(steps)) if steps > 0 else (ZOOM_STEP_OUT ** abs(steps))
            anchor = self._anchor_from_event(ev)
            anchor_x = anchor.x() if anchor is not None else None
            if self._xrange_source_callback is not None:
                with contextlib.suppress(Exception):
                    self._xrange_source_callback("wheel.ctrl_zoom", None)
            if self._request_zoom_x is not None:
                self._request_zoom_x(
                    float(factor),
                    float(anchor_x) if anchor_x is not None else None,
                    "wheel.ctrl_zoom",
                )
            else:
                self._zoom_x_at(anchor_x, factor)
        elif alt:
            factor = (ZOOM_STEP_IN ** abs(steps)) if steps > 0 else (ZOOM_STEP_OUT ** abs(steps))
            anchor = self._anchor_from_event(ev)
            anchor_y = anchor.y() if anchor is not None else None
            self._zoom_y_at(anchor_y, factor)
        elif shift:
            _, (y_min, y_max) = self.viewRange()
            span = y_max - y_min
            if span > 0:
                direction = -1 if steps > 0 else 1
                shift_amount = direction * pan_step(span, 0.05) * abs(steps)
                self._apply_y_pan(shift_amount)
        else:
            x_min: float
            x_max: float
            if self._request_pan_x is not None and self._get_current_xrange is not None:
                try:
                    x_min, x_max = self._get_current_xrange()
                except Exception:
                    (x_min, x_max), _ = self.viewRange()
            else:
                (x_min, x_max), _ = self.viewRange()
            span = x_max - x_min
            if span > 0:
                direction = -1 if steps > 0 else 1
                shift = direction * pan_step(span, DEFAULT_WHEEL_PAN_FRACTION) * abs(steps)
                if self._request_pan_x is not None:
                    self._request_pan_x(float(shift), "wheel.pan")
                else:
                    self._apply_pan(shift)

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
        if getattr(self, "state", {}).get("mouseMode") == self.RectMode:
            if ev.isStart():
                self._stop_momentum()
                if self._xrange_source_callback is not None:
                    with contextlib.suppress(Exception):
                        self._xrange_source_callback("box_zoom", None)
            super().mouseDragEvent(ev, axis=axis)
            if ev.isFinish() and self._request_window is not None:
                (x_min, x_max), _ = self.viewRange()
                with contextlib.suppress(Exception):
                    self._request_window(float(x_min), float(x_max), "box_zoom.finish")
            if ev.isFinish():
                self._drag_active = False
            return

        if self._request_pan_x is not None:
            self._stop_momentum()
            self._drag_active = False
            self._velocity = 0.0
            if ev.isStart():
                try:
                    self._drag_last_pos = ev.lastPos()
                except Exception:
                    self._drag_last_pos = None
                ev.accept()
                return

            if self._drag_last_pos is None:
                try:
                    self._drag_last_pos = ev.lastPos()
                except Exception:
                    self._drag_last_pos = None
                ev.accept()
                return

            try:
                cur = ev.pos()
                last = self._drag_last_pos
                dx = float(cur.x() - last.x())
                self._drag_last_pos = cur
            except Exception:
                dx = 0.0

            if self._get_current_xrange is not None:
                try:
                    x_min, x_max = self._get_current_xrange()
                except Exception:
                    (x_min, x_max), _ = self.viewRange()
            else:
                (x_min, x_max), _ = self.viewRange()
            span = float(x_max - x_min)
            width = float(self.boundingRect().width())
            if width > 0.0 and span > 0.0:
                seconds_per_px = span / width
                dt = -dx * seconds_per_px
                if self._xrange_source_callback is not None:
                    with contextlib.suppress(Exception):
                        self._xrange_source_callback("drag.pan", None)
                self._request_pan_x(float(dt), "drag.pan")

            ev.accept()
            if ev.isFinish():
                self._drag_last_pos = None
            return

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
