"""PyQtGraph-based channel track for high-performance rendering."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import pyqtgraph as pg

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.pyqtgraph_axes_compat import PyQtGraphAxesCompat
from vasoanalyzer.ui.plots.pyqtgraph_line_compat import PyQtGraphLineCompat
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import PyQtGraphTraceView

__all__ = ["PyQtGraphChannelTrack"]


class PyQtGraphChannelTrack:
    """PyQtGraph-based channel track with GPU-accelerated rendering.

    Mirrors the interface of matplotlib-based ChannelTrack but uses
    PyQtGraph for improved interactive performance.
    """

    def __init__(
        self,
        spec,  # ChannelTrackSpec
        enable_opengl: bool = True,
    ) -> None:
        self.spec = spec
        mode = spec.component if spec.component in {"inner", "outer", "dual"} else "inner"
        self.view = PyQtGraphTraceView(
            mode=mode,
            y_label=spec.label,
            enable_opengl=enable_opengl,
        )
        self._model: TraceModel | None = None
        self._height_ratio = max(spec.height_ratio, 0.05)
        self._visible = True
        self._events: Sequence[float] | None = None
        self._event_colors: Sequence[str] | None = None
        self._event_labels: Sequence[str] | None = None
        self._auto_margin: float = 0.05
        self._sticky_ylim: tuple[float, float] | None = None
        self._last_time_span: float | None = None

        # Create matplotlib-compatible axes wrapper
        self._ax_compat: PyQtGraphAxesCompat | None = None

        # Create matplotlib-compatible line wrapper
        self._line_compat: PyQtGraphLineCompat | None = None

        # Enable autoscale by default
        self.view.set_autoscale_y(True)

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
    def widget(self) -> pg.PlotWidget:
        """Get the PyQtGraph widget for layout."""
        return self.view.get_widget()

    @property
    def ax(self):
        """Get the plot axes (matplotlib compatibility).

        Returns a matplotlib-compatible wrapper around PyQtGraph PlotItem
        that provides Axes-like methods (get_xlim, get_ylim, etc.).
        """
        if self._ax_compat is None:
            plot_item = self.view.get_widget().getPlotItem()
            self._ax_compat = PyQtGraphAxesCompat(plot_item)
        return self._ax_compat

    @property
    def primary_line(self):
        """Get the primary trace line (matplotlib ChannelTrack compatibility).

        Returns:
            Wrapped PlotDataItem with matplotlib Line2D-compatible interface
        """
        if self._line_compat is None:
            self._line_compat = PyQtGraphLineCompat(self.view.inner_curve)
        return self._line_compat

    def set_model(self, model: TraceModel) -> None:
        """Attach the shared TraceModel to this track."""
        self._model = model
        self._sticky_ylim = None
        self._last_time_span = None
        self.view.set_autoscale_y(True)

        if self.spec.component == "outer" and model.outer_full is None:
            self.set_visible(False)
            return

        self.view.set_model(model)

        # Set axis labels
        if self.spec.component == "outer":
            label = self.spec.label or "Outer Diameter (µm)"
            self.view.set_ylabel(label)
        elif self.spec.component == "inner":
            label = self.spec.label or "Inner Diameter (µm)"
            self.view.set_ylabel(label)

        # Apply events if already set
        if self._events is not None:
            self.view.set_events(self._events, self._event_colors, self._event_labels)

    def update_window(self, x0: float, x1: float) -> None:
        """Update the visible time window."""
        if self._model is None:
            return

        # Get pixel width from widget
        widget = self.view.get_widget()
        pixel_width = max(int(widget.width()), 400)

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
        """Set event markers."""
        self._events = list(times)
        self._event_colors = None if colors is None else list(colors)
        self._event_labels = None if labels is None else list(labels)
        self.view.set_events(times, colors, labels)

    def set_visible(self, visible: bool) -> None:
        """Show/hide this track."""
        self._visible = bool(visible)
        widget = self.view.get_widget()
        widget.setVisible(self._visible)

    def is_visible(self) -> bool:
        """Check if track is visible."""
        return self._visible

    def data_limits(self) -> tuple[float, float] | None:
        """Get Y-axis data limits for current window."""
        return self.view.data_limits()

    def autoscale(self, margin: float = 0.05) -> tuple[float, float] | None:
        """Autoscale the Y axis using the current data window."""
        padded = self._compute_padded_limits(margin=margin)
        if padded is None:
            return None

        ymin, ymax = padded
        self._auto_margin = float(margin)
        self._sticky_ylim = (ymin, ymax)
        self.view.set_ylim(ymin, ymax)
        self.view.set_autoscale_y(True)
        return (ymin, ymax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        """Set Y-axis limits manually."""
        self._sticky_ylim = None
        self.view.set_ylim(ymin, ymax)
        self.view.set_autoscale_y(False)

    def pan_y(self, delta: float) -> None:
        """Pan the Y-axis by a delta amount."""
        self._sticky_ylim = None
        ymin, ymax = self.view.get_ylim()
        new_min = ymin + delta
        new_max = ymax + delta
        self.view.set_ylim(new_min, new_max)
        self.view.set_autoscale_y(False)

    def zoom_y(self, center: float, factor: float) -> None:
        """Zoom the Y-axis around a center point."""
        self._sticky_ylim = None
        ymin, ymax = self.view.get_ylim()
        span = ymax - ymin

        if span <= 0:
            span = abs(ymin) if abs(ymin) > 1e-3 else 1.0

        new_span = max(span * factor, 1e-6)

        if not math.isfinite(center):
            center = (ymin + ymax) / 2.0

        half = new_span / 2.0
        new_min = center - half
        new_max = center + half

        self.view.set_ylim(new_min, new_max)
        self.view.set_autoscale_y(False)

    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits."""
        return self.view.get_xlim()

    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits."""
        return self.view.get_ylim()

    # ------------------------------------------------------------------ helpers
    def _compute_padded_limits(
        self, *, margin: float | None = None
    ) -> tuple[float, float] | None:
        """Compute Y limits with padding."""
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
        """Apply automatic Y-axis scaling."""
        if self._model is None or self.spec.component == "dual":
            return

        if self._sticky_ylim is not None and not span_changed:
            ymin, ymax = self._sticky_ylim
            self.view.set_ylim(ymin, ymax)
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

        self.view.set_ylim(ymin, ymax)
