"""Channel track rendering primitives for stacked plots."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.trace_view import TraceView

__all__ = ["ChannelTrackSpec", "ChannelTrack"]


@dataclass
class ChannelTrackSpec:
    """Description of a plotted channel."""

    track_id: str
    component: str  # "inner", "outer", "dual", "avg_pressure", or "set_pressure"
    label: str | None = None
    height_ratio: float = 1.0


class ChannelTrack:
    """Wrap a TraceView together with axis metadata."""

    def __init__(
        self,
        spec: ChannelTrackSpec,
        ax: Axes,
        canvas: FigureCanvasQTAgg,
    ) -> None:
        self.spec = spec
        self.ax = ax
        self.canvas = canvas
        mode = spec.component if spec.component in {"inner", "outer", "dual", "avg_pressure", "set_pressure"} else "inner"
        self.view = TraceView(ax, canvas, mode=mode, y_label=spec.label)
        self._model: TraceModel | None = None
        self._height_ratio = max(spec.height_ratio, 0.05)
        self._visible = True
        self._events: Sequence[float] | None = None
        self._event_colors: Sequence[str] | None = None
        self._event_labels: Sequence[str] | None = None
        self.ax.set_autoscaley_on(True)
        self._auto_margin: float = 0.05
        self._sticky_ylim: tuple[float, float] | None = None
        self._last_time_span: float | None = None

    @property
    def id(self) -> str:
        return self.spec.track_id

    @property
    def height_ratio(self) -> float:
        return self._height_ratio

    @height_ratio.setter
    def height_ratio(self, value: float) -> None:
        self._height_ratio = max(float(value), 0.05)

    @property
    def primary_line(self):
        return self.view.inner_line

    def set_model(self, model: TraceModel) -> None:
        """Attach the shared TraceModel to this track."""

        self._model = model
        self._sticky_ylim = None
        self._last_time_span = None
        self.ax.set_autoscaley_on(True)

        # Check if component data is available, hide if not
        if self.spec.component == "outer" and model.outer_full is None:
            self.set_visible(False)
            return
        if self.spec.component == "avg_pressure" and model.avg_pressure_full is None:
            self.set_visible(False)
            return
        if self.spec.component == "set_pressure" and model.set_pressure_full is None:
            self.set_visible(False)
            return

        self.view.set_model(model)

        # Set appropriate label based on component
        if self.spec.component == "outer":
            label = self.spec.label or "Outer Diameter (µm)"
            self.ax.set_ylabel(label)
        elif self.spec.component == "inner":
            label = self.spec.label or "Inner Diameter (µm)"
            self.ax.set_ylabel(label)
        elif self.spec.component == "avg_pressure":
            label = self.spec.label or "Avg Pressure (mmHg)"
            self.ax.set_ylabel(label)
        elif self.spec.component == "set_pressure":
            label = self.spec.label or "Set Pressure (mmHg)"
            self.ax.set_ylabel(label)

        if self._events is not None:
            self.view.set_events(self._events, self._event_colors, self._event_labels)

    def update_window(self, x0: float, x1: float) -> None:
        if self._model is None:
            return
        # Try to get bounding box, fall back to canvas width if renderer unavailable
        try:
            renderer = getattr(self.canvas, "renderer", None)
            if renderer is None:
                renderer = self.canvas.get_renderer()
            bbox = self.ax.get_window_extent(renderer=renderer)
            pixel_width = max(int(bbox.width), 1)
        except Exception:
            # Fallback if renderer not available - don't force synchronous draw
            pixel_width = max(int(self.canvas.width()), 400)  # 400px reasonable default
        span = float(x1 - x0)
        span_changed = self._last_time_span is None or not math.isclose(
            span, self._last_time_span, rel_tol=1e-9, abs_tol=1e-9
        )
        self._last_time_span = span
        self.view.update_window(x0, x1, pixel_width=pixel_width)
        self._apply_auto_y(span_changed)

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
    ) -> None:
        self._events = list(times)
        self._event_colors = None if colors is None else list(colors)
        self._event_labels = None if labels is None else list(labels)
        self.view.set_events(times, colors, labels)

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self.ax.set_visible(self._visible)

    def is_visible(self) -> bool:
        return self._visible

    def refresh_background(self) -> None:
        self.view.refresh_background()

    def axes(self) -> tuple[Axes, ...]:
        candidates = [self.ax]
        if getattr(self.view, "ax2", None) is not None:
            candidates.append(self.view.ax2)
        return tuple(candidate for candidate in candidates if candidate is not None)

    def data_limits(self) -> tuple[float, float] | None:
        limits = self.view.data_limits()
        return cast(tuple[float, float] | None, limits)

    def autoscale(self, margin: float = 0.05) -> tuple[float, float] | None:
        """Autoscale the Y axis using the current data window."""

        padded = self._compute_padded_limits(margin=margin)
        if padded is None:
            return None
        ymin, ymax = padded
        self._auto_margin = float(margin)
        self._sticky_ylim = (ymin, ymax)
        self.ax.set_autoscaley_on(True)
        self.ax.set_ylim(ymin, ymax)
        ax2 = self.view.ax2
        if ax2 is not None:
            set_auto = getattr(ax2, "set_autoscaley_on", None)
            if callable(set_auto):
                set_auto(True)
            ax2.set_ylim(ymin, ymax)
        return (ymin, ymax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        self.ax.set_autoscaley_on(False)
        self._sticky_ylim = None
        self.ax.set_ylim(ymin, ymax)
        ax2 = self.view.ax2
        if ax2 is not None:
            set_auto = getattr(ax2, "set_autoscaley_on", None)
            if callable(set_auto):
                set_auto(False)
            ax2.set_ylim(ymin, ymax)

    def pan_y(self, delta: float) -> None:
        self.ax.set_autoscaley_on(False)
        self._sticky_ylim = None
        ymin, ymax = self.ax.get_ylim()
        new_min = ymin + delta
        new_max = ymax + delta
        self.ax.set_ylim(new_min, new_max)
        ax2 = self.view.ax2
        if ax2 is not None:
            set_auto = getattr(ax2, "set_autoscaley_on", None)
            if callable(set_auto):
                set_auto(False)
            ax2.set_ylim(new_min, new_max)

    def zoom_y(self, center: float, factor: float) -> None:
        self.ax.set_autoscaley_on(False)
        self._sticky_ylim = None
        ymin, ymax = self.ax.get_ylim()
        span = ymax - ymin
        if span <= 0:
            span = abs(ymin) if abs(ymin) > 1e-3 else 1.0
        new_span = max(span * factor, 1e-6)
        if not math.isfinite(center):
            center = (ymin + ymax) / 2.0
        half = new_span / 2.0
        new_min = center - half
        new_max = center + half
        self.ax.set_ylim(new_min, new_max)
        ax2 = self.view.ax2
        if ax2 is not None:
            set_auto = getattr(ax2, "set_autoscaley_on", None)
            if callable(set_auto):
                set_auto(False)
            ax2.set_ylim(new_min, new_max)

    # ------------------------------------------------------------------ helpers
    def _compute_padded_limits(self, *, margin: float | None = None) -> tuple[float, float] | None:
        limits = self.data_limits()
        if limits is None:
            return None
        ymin, ymax = limits
        span = ymax - ymin
        if span <= 0:
            span = max(abs(ymin), abs(ymax), 1.0)
        fraction = self._auto_margin if margin is None else float(margin)
        pad = span * max(fraction, 0.0)
        return ymin - pad, ymax + pad

    def _apply_auto_y(self, span_changed: bool) -> None:
        if self._model is None or self.spec.component == "dual":
            return
        get_auto = getattr(self.ax, "get_autoscaley_on", None)
        axis_auto = True if get_auto is None else bool(get_auto())
        if not axis_auto:
            return
        if self._sticky_ylim is not None and not span_changed:
            ymin, ymax = self._sticky_ylim
            self.ax.set_ylim(ymin, ymax)
            ax2 = self.view.ax2
            if ax2 is not None and getattr(ax2, "get_autoscaley_on", lambda: True)():
                set_auto = getattr(ax2, "set_autoscaley_on", None)
                if callable(set_auto):
                    set_auto(False)
                ax2.set_ylim(ymin, ymax)
            return

        limits = self._compute_padded_limits()
        if limits is None:
            return
        ymin, ymax = limits
        if not math.isfinite(ymin) or not math.isfinite(ymax):
            return
        if math.isclose(ymin, ymax, rel_tol=1e-6, abs_tol=1e-6):
            margin = abs(ymin) if ymin else 1.0
            ymin -= margin
            ymax += margin
        self.ax.set_ylim(ymin, ymax)
        ax2 = self.view.ax2
        if ax2 is not None and getattr(ax2, "get_autoscaley_on", lambda: True)():
            set_auto = getattr(ax2, "set_autoscaley_on", None)
            if callable(set_auto):
                set_auto(False)
            ax2.set_ylim(ymin, ymax)
