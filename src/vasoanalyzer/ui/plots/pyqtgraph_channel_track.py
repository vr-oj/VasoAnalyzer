"""PyQtGraph-based channel track for high-performance rendering."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pyqtgraph as pg

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_axes_compat import PyQtGraphAxesCompat
from vasoanalyzer.ui.plots.pyqtgraph_line_compat import PyQtGraphLineCompat
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import PyQtGraphTraceView

__all__ = ["PyQtGraphChannelTrack"]


_log = logging.getLogger(__name__)


class PyQtGraphChannelTrack:
    """PyQtGraph-based channel track with GPU-accelerated rendering.

    Mirrors the interface of matplotlib-based ChannelTrack but uses
    PyQtGraph for improved interactive performance.
    """

    def __init__(
        self,
        spec: ChannelTrackSpec,
        enable_opengl: bool = True,
    ) -> None:
        self.spec: ChannelTrackSpec = spec
        mode = (
            spec.component
            if spec.component in {"inner", "outer", "dual", "avg_pressure", "set_pressure"}
            else "inner"
        )
        self.view: PyQtGraphTraceView = PyQtGraphTraceView(
            mode=mode,
            y_label=spec.label,
            enable_opengl=enable_opengl,
        )
        self._model: TraceModel | None = None
        self._height_ratio: float = max(float(spec.height_ratio), 0.05)
        self._visible = True
        self._events: Sequence[float] | None = None
        self._event_colors: Sequence[str] | None = None
        self._event_labels: Sequence[str] | None = None
        self._event_label_meta: Sequence[dict[str, Any]] | None = None
        self._auto_margin: float = 0.05
        self._sticky_ylim: tuple[float, float] | None = None
        self._last_time_span: float | None = None
        self._current_window: tuple[float, float] | None = None

        # Create matplotlib-compatible axes wrapper
        self._ax_compat: PyQtGraphAxesCompat | None = None

        # Create matplotlib-compatible line wrapper
        self._line_compat: PyQtGraphLineCompat | None = None

        # Disable autoscale by default (user can enable in Plot Settings)
        self.view.set_autoscale_y(False)

    @property
    def id(self) -> str:
        return str(self.spec.track_id)

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

    def set_xlim(self, xmin: float, xmax: float) -> None:
        """Set the visible X range for this track."""
        self.view.set_xlim(xmin, xmax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        """Set the visible Y range for this track."""
        self.view.set_ylim(ymin, ymax)

    def set_grid_visible(self, visible: bool) -> None:
        """Toggle grid visibility for this track."""
        self.view.set_grid_visible(visible)

    def clear_pins(self) -> None:
        """Remove all pinned markers/labels."""
        self.view.clear_pins()

    def add_pin(self, x: float, y: float, text: str):
        """Add a pin marker/label."""
        return self.view.add_pin(x, y, text)

    def set_primary_line_style(
        self,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
    ) -> None:
        """Apply styling to the primary trace line."""
        self.view.set_primary_line_style(color=color, width=width, style=style)

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
        self.view.set_autoscale_y(False)

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

        # Set axis labels
        if self.spec.component == "outer":
            label = self.spec.label or "Outer Diameter (µm)"
            self.view.set_ylabel(label)
        elif self.spec.component == "inner":
            label = self.spec.label or "Inner Diameter (µm)"
            self.view.set_ylabel(label)
        elif self.spec.component == "avg_pressure":
            label = self.spec.label or "Avg Pressure (mmHg)"
            self.view.set_ylabel(label)
        elif self.spec.component == "set_pressure":
            label = self.spec.label or "Set Pressure (mmHg)"
            self.view.set_ylabel(label)

        # Apply events if already set
        if self._events is not None:
            self.view.set_events(
                self._events,
                self._event_colors,
                self._event_labels,
                self._event_label_meta,
            )

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

        track_id = getattr(self, "id", None) or getattr(self, "name", None) or repr(self)
        _log.debug(
            "update_window track=%s x0=%.6f x1=%.6f span=%.6f span_changed=%s",
            track_id,
            x0,
            x1,
            span,
            span_changed,
        )

        self.view.update_window(x0, x1, pixel_width=pixel_width)
        self._current_window = (x0, x1)
        self._apply_auto_y(span_changed)

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        label_meta: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        """Set event markers."""
        self._events = list(times)
        self._event_colors = None if colors is None else list(colors)
        self._event_labels = None if labels is None else list(labels)
        self._event_label_meta = None if label_meta is None else list(label_meta)
        self.view.set_events(times, colors, labels, self._event_label_meta)

    def set_visible(self, visible: bool) -> None:
        """Show/hide this track."""
        self._visible = bool(visible)
        widget = self.view.get_widget()
        widget.setVisible(self._visible)

    def set_click_handler(self, handler) -> None:
        """Assign click handler callback for this track's view."""
        self.view.set_click_handler(handler)

    def is_visible(self) -> bool:
        """Check if track is visible."""
        return self._visible

    def set_line_width(self, width: float) -> None:
        """Set the line width for the primary trace.

        Args:
            width: Line width in pixels
        """
        if self.primary_line:
            self.primary_line.set_linewidth(width)

    def data_limits(self) -> tuple[float, float] | None:
        """Get Y-axis data limits for current window."""
        limits = self.view.data_limits()
        if limits is None:
            return None
        ymin, ymax = limits
        return float(ymin), float(ymax)

    def autoscale(self, margin: float = 0.05) -> tuple[float, float] | None:
        """Autoscale the Y axis using the current data window."""
        padded = self._compute_padded_limits(margin=margin)
        if padded is None:
            return None

        ymin, ymax = padded
        self._auto_margin = float(margin)
        self.view.set_ylim(ymin, ymax)
        self.view.set_autoscale_y(True)
        return (ymin, ymax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        """Set Y-axis limits manually."""
        self._sticky_ylim = (float(ymin), float(ymax))
        self.view.set_autoscale_y(False)
        self.view.set_ylim(ymin, ymax)

    def pan_y(self, delta: float) -> None:
        """Pan the Y-axis by a delta amount."""
        ymin, ymax = self.view.get_ylim()
        new_min = ymin + delta
        new_max = ymax + delta
        self._sticky_ylim = (float(new_min), float(new_max))
        self.view.set_autoscale_y(False)
        self.view.set_ylim(new_min, new_max)

    def zoom_y(self, center: float, factor: float) -> None:
        """Zoom the Y-axis around a center point."""
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

        self._sticky_ylim = (float(new_min), float(new_max))
        self.view.set_autoscale_y(False)
        self.view.set_ylim(new_min, new_max)

    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits."""
        x_min, x_max = self.view.get_xlim()
        return float(x_min), float(x_max)

    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits."""
        y_min, y_max = self.view.get_ylim()
        return float(y_min), float(y_max)

    # ------------------------------------------------------------------ helpers
    def _compute_padded_limits(self, *, margin: float | None = None) -> tuple[float, float] | None:
        """Compute Y limits with padding."""
        track_id = getattr(self, "id", None) or getattr(self, "name", None) or repr(self)

        limits = self._window_data_limits()
        if limits is not None:
            ymin, ymax = limits
            _log.debug(
                "compute_padded_limits track=%s using window_limits ymin=%.6f ymax=%.6f",
                track_id,
                ymin,
                ymax,
            )
        else:
            _log.debug(
                "compute_padded_limits track=%s: window limits unavailable, falling back to data_limits",
                track_id,
            )
            limits = self.data_limits()
            if limits is None:
                _log.warning(
                    "compute_padded_limits track=%s: no limits from data_limits()",
                    track_id,
                )
                return None
            ymin, ymax = limits
            _log.debug(
                "compute_padded_limits track=%s using data_limits ymin=%.6f ymax=%.6f",
                track_id,
                ymin,
                ymax,
            )

        if not math.isfinite(ymin) or not math.isfinite(ymax):
            _log.warning(
                "compute_padded_limits track=%s: non-finite limits ymin=%r ymax=%r",
                track_id,
                ymin,
                ymax,
            )
            return None

        span = ymax - ymin
        if span <= 0:
            span = max(abs(ymin), abs(ymax), 1.0)

        fraction = self._auto_margin if margin is None else float(margin)
        pad = span * max(fraction, 0.0)
        padded_min = ymin - pad
        padded_max = ymax + pad
        _log.debug(
            "padded_limits track=%s ymin=%.6f ymax=%.6f",
            track_id,
            padded_min,
            padded_max,
        )
        return padded_min, padded_max

    def _window_data_limits(self) -> tuple[float, float] | None:
        """Return limits for the currently visible window, if available."""
        track_id = getattr(self, "id", None) or getattr(self, "name", None) or repr(self)
        try:
            limits = self.view.data_limits()
        except Exception as exc:
            _log.debug("window_limits track=%s unavailable: exception=%r", track_id, exc)
            return None
        if limits is None:
            _log.debug("window_limits track=%s unavailable: data_limits() returned None", track_id)
            return None

        ymin, ymax = limits
        if ymin is None or ymax is None:
            _log.debug(
                "window_limits track=%s unavailable: ymin/ymax is None (%r, %r)",
                track_id,
                ymin,
                ymax,
            )
            return None
        if not math.isfinite(ymin) or not math.isfinite(ymax):
            _log.debug(
                "window_limits track=%s unavailable: non-finite limits ymin=%r ymax=%r",
                track_id,
                ymin,
                ymax,
            )
            return None
        if math.isclose(ymin, ymax, rel_tol=1e-12, abs_tol=1e-12):
            _log.debug(
                "window_limits track=%s unavailable: degenerate span ymin=%.6f ymax=%.6f",
                track_id,
                ymin,
                ymax,
            )
            return None

        _log.debug("window_limits track=%s ymin=%.6f ymax=%.6f", track_id, ymin, ymax)
        return float(ymin), float(ymax)

    def _apply_auto_y(self, span_changed: bool) -> None:
        """Apply automatic Y-axis scaling."""
        track_id = getattr(self, "id", None) or getattr(self, "name", None) or repr(self)
        autoscale_enabled = bool(self.view.is_autoscale_enabled())
        _log.debug(
            "apply_auto_y track=%s autoscale_enabled=%s span_changed=%s",
            track_id,
            autoscale_enabled,
            span_changed,
        )

        if not autoscale_enabled:
            if self._sticky_ylim is None and self._model is not None:
                limits = self._compute_padded_limits()
                if limits is not None:
                    ymin, ymax = limits
                    if math.isclose(ymin, ymax, rel_tol=1e-6, abs_tol=1e-6):
                        margin = abs(ymin) if ymin else 1.0
                        ymin -= margin
                        ymax += margin
                    self._sticky_ylim = (float(ymin), float(ymax))
                    _log.debug(
                        "apply_auto_y track=%s primed sticky ylim ymin=%.6f ymax=%.6f",
                        track_id,
                        ymin,
                        ymax,
                    )

            if self._sticky_ylim is not None:
                ymin, ymax = self._sticky_ylim
                self.view.set_ylim(ymin, ymax)
                _log.debug(
                    "apply_auto_y track=%s using sticky ylim ymin=%.6f ymax=%.6f",
                    track_id,
                    ymin,
                    ymax,
                )
            else:
                _log.debug("apply_auto_y track=%s skipped: autoscale disabled", track_id)
            return

        if self._model is None or self.spec.component == "dual":
            _log.debug("apply_auto_y track=%s skipped: model missing or dual component", track_id)
            return

        limits = self._compute_padded_limits()
        if limits is None:
            _log.debug(
                "apply_auto_y track=%s: _compute_padded_limits returned None",
                track_id,
            )
            return

        ymin, ymax = limits
        if not math.isfinite(ymin) or not math.isfinite(ymax):
            _log.warning(
                "apply_auto_y track=%s: non-finite limits ymin=%r ymax=%r",
                track_id,
                ymin,
                ymax,
            )
            return

        if math.isclose(ymin, ymax, rel_tol=1e-6, abs_tol=1e-6):
            margin = abs(ymin) if ymin else 1.0
            ymin -= margin
            ymax += margin

        _log.debug(
            "apply_auto_y track=%s setting ylim ymin=%.6f ymax=%.6f",
            track_id,
            ymin,
            ymax,
        )
        self.view.set_ylim(ymin, ymax)
