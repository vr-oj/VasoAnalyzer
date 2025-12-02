"""ViewBox subclass that converts wheel scrolling to horizontal panning only."""

from __future__ import annotations

import pyqtgraph as pg
from PyQt5.QtWidgets import QGraphicsSceneWheelEvent


class PanOnlyViewBox(pg.ViewBox):
    """ViewBox that converts any wheel/trackpad scrolling into horizontal panning.

    Zoom via wheel is completely disabled. Left-drag rectangle zoom is preserved
    (default VB behavior) when in RectMode. Toolbar zoom buttons work independently.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def wheelEvent(self, ev: QGraphicsSceneWheelEvent, axis=None, **_ignored) -> None:
        """Override wheel event to pan horizontally instead of zooming.

        Consume the event here so ViewBox's default zoom logic never runs.
        Map vertical scroll to horizontal pan. The amount is proportional to current view width.
        QGraphicsSceneWheelEvent only provides delta(), not angleDelta/pixelDelta.
        """
        # PyQtGraph AxisItem passes axis; ignore it and pan horizontally.
        # QGraphicsSceneWheelEvent uses delta() - returns degrees * 8
        # Typical mouse: 120 units (15 degrees * 8) per notch
        delta = ev.delta()
        steps = delta / 120.0

        # Sign convention: scrolling down moves forward in time (to the right)
        # This is the "natural" document scrolling feel
        frac_per_step = 0.10  # 10% of visible window per "step"
        frac = steps * frac_per_step

        # Current x-range
        view_range = self.state["viewRange"]
        (x0, x1), (y0, y1) = view_range
        width = x1 - x0
        if width <= 0:
            ev.accept()
            return

        dx = -frac * width  # minus to map "scroll down" -> move timeline right

        # Clamp to any limits set on the ViewBox
        lims = self.state.get("limits", {})
        x_limits = lims.get("xLimits", [None, None])
        x_min_lim = x_limits[0]
        x_max_lim = x_limits[1]

        new_x0 = x0 + dx
        new_x1 = x1 + dx

        # Clamp to limits if they exist
        if x_min_lim is not None and new_x0 < x_min_lim:
            shift = x_min_lim - new_x0
            new_x0 += shift
            new_x1 += shift
        if x_max_lim is not None and new_x1 > x_max_lim:
            shift = x_max_lim - new_x1
            new_x0 += shift
            new_x1 += shift

        # Apply pan
        self.setXRange(new_x0, new_x1, padding=0)
        ev.accept()
