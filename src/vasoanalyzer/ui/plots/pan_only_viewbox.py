"""ViewBox subclass that converts wheel scrolling to horizontal panning only."""

from __future__ import annotations

import logging

import pyqtgraph as pg
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsSceneWheelEvent


log = logging.getLogger(__name__)


class PanOnlyViewBox(pg.ViewBox):
    """ViewBox that converts any wheel/trackpad scrolling into horizontal panning.

    Zoom via wheel is completely disabled. Left-drag rectangle zoom is preserved
    (default VB behavior) when in RectMode. Toolbar zoom buttons work independently.
    """

    sigWheelEvent = pyqtSignal(object)
    sigMousePressEvent = pyqtSignal(object)
    sigMouseReleaseEvent = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._x_limits: tuple[float, float] | None = None
        self._min_x_range: float | None = None
        self._max_x_range: float | None = None

        # Default to horizontal panning only.
        self.setMouseMode(pg.ViewBox.PanMode)
        self.setMouseEnabled(x=True, y=False)
        self.enableAutoRange(x=False, y=False)

    def set_time_limits(
        self,
        x_min: float | None,
        x_max: float | None,
        *,
        min_x_range: float | None = None,
        max_x_range: float | None = None,
    ) -> None:
        """Configure horizontal limits and zoom constraints using public APIs."""

        if x_min is not None and x_max is not None:
            self._x_limits = (float(x_min), float(x_max))
        elif x_min is not None:
            self._x_limits = (float(x_min), float("inf"))
        elif x_max is not None:
            self._x_limits = (float("-inf"), float(x_max))

        self._min_x_range = min_x_range if min_x_range is None else float(min_x_range)
        self._max_x_range = max_x_range if max_x_range is None else float(max_x_range)

        limits_kwargs: dict[str, float] = {}
        if x_min is not None:
            limits_kwargs["xMin"] = float(x_min)
        if x_max is not None:
            limits_kwargs["xMax"] = float(x_max)
        if min_x_range is not None:
            limits_kwargs["minXRange"] = float(min_x_range)
        if max_x_range is not None:
            limits_kwargs["maxXRange"] = float(max_x_range)

        if limits_kwargs:
            self.setLimits(**limits_kwargs)

    def _clamp_x_range(self, x_min: float, x_max: float) -> tuple[float, float]:
        if self._x_limits is None:
            return x_min, x_max

        lo, hi = self._x_limits
        span = max(x_max - x_min, 0.0)
        if span <= 0:
            return lo, hi

        if x_min < lo:
            x_min = lo
            x_max = x_min + span
        if x_max > hi:
            x_max = hi
            x_min = x_max - span
        return x_min, x_max

    def wheelEvent(self, ev: QGraphicsSceneWheelEvent, axis=None, **_ignored) -> None:
        """Pan horizontally on wheel/trackpad using public APIs only."""
        try:
            angle_delta = ev.angleDelta().y()  # Qt >=5
        except Exception:
            try:
                angle_delta = ev.delta()
            except Exception:
                angle_delta = 0

        if angle_delta == 0:
            ev.accept()
            return

        (x_min, x_max), _ = self.viewRange()
        span = x_max - x_min
        if span <= 0:
            ev.accept()
            return

        direction = -1 if angle_delta > 0 else 1
        shift = direction * 0.10 * span

        new_x_min = x_min + shift
        new_x_max = x_max + shift
        new_x_min, new_x_max = self._clamp_x_range(new_x_min, new_x_max)

        log.debug(
            "PanOnlyViewBox.wheelEvent: delta=%r xRange_before=%r xRange_after=%r",
            angle_delta,
            (x_min, x_max),
            (new_x_min, new_x_max),
        )

        self.setXRange(new_x_min, new_x_max, padding=0.0, update=True)

        try:
            self.sigWheelEvent.emit(ev)
        except Exception:
            log.exception("Error emitting sigWheelEvent from PanOnlyViewBox")

        ev.accept()

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent) -> None:
        super().mousePressEvent(ev)
        self.sigMousePressEvent.emit(ev)

    def mouseReleaseEvent(self, ev: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(ev)
        self.sigMouseReleaseEvent.emit(ev)
