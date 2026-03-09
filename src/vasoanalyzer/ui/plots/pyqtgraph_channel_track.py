"""PyQtGraph-based channel track for high-performance rendering."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from typing import Any

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QVBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_axes_compat import PyQtGraphAxesCompat
from vasoanalyzer.ui.plots.pyqtgraph_line_compat import PyQtGraphLineCompat
from vasoanalyzer.ui.plots.pyqtgraph_style import PLOT_AXIS_LABELS
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import PyQtGraphTraceView
from vasoanalyzer.ui.plots.track_frame import TrackFrame
from vasoanalyzer.ui.plots.y_axis_controls import YAxisControls, required_outer_gutter_px

__all__ = ["PyQtGraphChannelTrack"]


_log = logging.getLogger(__name__)

Y_ZOOM_IN_FACTOR = 0.8
Y_ZOOM_OUT_FACTOR = 1.25


class _TrackGutterWidget(QWidget):
    """Fixed-width gutter that hosts Y-axis controls and the channel label."""

    _LABEL_MIN_TRACK_HEIGHT_PX = 36
    _SHOW_COMPACT_GUTTER_LABEL = False

    def __init__(self, *, label: str, width_px: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ChannelTrackGutter")
        self.setFixedWidth(max(int(width_px), 0))
        self.setContentsMargins(0, 0, 0, 0)
        self.setAttribute(Qt.WA_PaintUnclipped, False)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._menu_layout = QHBoxLayout()
        self._menu_layout.setContentsMargins(0, 0, 0, 0)
        self._menu_layout.setSpacing(0)

        self._scale_layout = QHBoxLayout()
        self._scale_layout.setContentsMargins(0, 0, 0, 0)
        self._scale_layout.setSpacing(0)

        self._channel_label = QLabel(str(label or ""), self)
        self._channel_label.setObjectName("ChannelTrackGutterLabel")
        self._channel_label.setAlignment(Qt.AlignCenter)
        self._channel_label.setWordWrap(False)
        font = self._channel_label.font()
        font.setPointSizeF(8.0)
        self._channel_label.setFont(font)
        self._channel_label.hide()

        self._root_layout.addLayout(self._menu_layout, 0)
        self._root_layout.addLayout(self._scale_layout, 0)
        self._root_layout.addStretch(1)

    @staticmethod
    def _rebuild_centered_row(layout: QHBoxLayout, widget: QWidget | None) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        layout.addStretch(1)
        if widget is not None:
            layout.addWidget(widget, 0, Qt.AlignHCenter | Qt.AlignTop)
        layout.addStretch(1)

    def attach_control_widgets(
        self,
        *,
        menu_widget: QWidget | None,
        scale_widget: QWidget | None,
        controls_widget: QWidget | None,
    ) -> None:
        self._rebuild_centered_row(self._menu_layout, menu_widget)
        self._rebuild_centered_row(self._scale_layout, scale_widget)
        if controls_widget is not None:
            controls_widget.hide()
        self.layout_channel_label()

    def set_channel_label(self, text: str) -> None:
        self._channel_label.setText(str(text or ""))
        self.layout_channel_label()

    def layout_channel_label(self) -> None:
        if not self._SHOW_COMPACT_GUTTER_LABEL:
            self._channel_label.hide()
            return
        track_height = max(int(self.height()), 0)
        text = str(self._channel_label.text() or "").strip()
        if track_height < self._LABEL_MIN_TRACK_HEIGHT_PX or not text:
            self._channel_label.hide()
            return
        self._channel_label.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.layout_channel_label()


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
        y_label = PLOT_AXIS_LABELS.get(spec.component)
        self.view: PyQtGraphTraceView = PyQtGraphTraceView(
            mode=mode,
            y_label=y_label,
            enable_opengl=enable_opengl,
        )
        self.view.set_left_outer_gutter_px(0)
        self._gutter_width_px = int(required_outer_gutter_px())
        self._container = QWidget()
        self._container_layout = QHBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)
        self._gutter_widget = _TrackGutterWidget(
            label=str(spec.label or spec.track_id),
            width_px=self._gutter_width_px,
            parent=self._container,
        )
        self._container_layout.addWidget(self._gutter_widget, 0)
        self._container_layout.addWidget(self.view.get_widget(), 1)
        self._frame = TrackFrame(self._container)

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
        self._autoscale_shrink_since: float | None = None
        self._autoscale_shrink_ratio: float = 0.85
        self._autoscale_shrink_delay_s: float = 0.3

        # Create matplotlib-compatible axes wrapper
        self._ax_compat: PyQtGraphAxesCompat | None = None

        # Create matplotlib-compatible line wrapper
        self._line_compat: PyQtGraphLineCompat | None = None
        self._track_label: str = str(self.spec.label or self.id)

        self._y_axis_controls = YAxisControls(
            parent=self._gutter_widget,
            get_state=lambda: bool(self.view.is_autoscale_enabled()),
            set_state=self._set_continuous_autoscale,
            autoscale_once=self.autoscale_y_once,
            zoom_out_scale=self._zoom_out_y_scale_step,
            zoom_in_scale=self._zoom_in_y_scale_step,
            set_scale_dialog=self._prompt_set_y_scale,
            reset_scale=self._reset_y_scale,
        )
        self.view.set_y_axis_controls_host(self._gutter_widget)
        self.view.install_y_axis_controls(self._y_axis_controls)
        self.view.set_y_axis_interaction_handlers(
            autoscale_once=self.autoscale_y_once,
            open_menu=self._open_y_axis_menu_at,
            scale_about=self.scale_y_about,
            pan_y=self.pan_y,
            drag_started=self._on_y_axis_drag_started,
            drag_finished=self._on_y_axis_drag_finished,
        )

        # Disable autoscale by default (user can enable in Plot Settings)
        self.view.set_autoscale_y(False)
        self.refresh_header()

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
    def widget(self) -> QWidget:
        """Get the container widget for layout."""
        return self._frame

    @property
    def gutter_widget(self) -> QWidget:
        """Get the fixed-width gutter widget for this track."""
        return self._gutter_widget

    def gutter_width_px(self) -> int:
        """Return gutter width in logical pixels."""
        width = int(self._gutter_widget.width())
        return width if width > 0 else int(self._gutter_width_px)

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
        self._autoscale_shrink_since = None
        self.view.set_autoscale_y(False)
        self._sync_header_state()

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
        label = PLOT_AXIS_LABELS.get(self.spec.component) or self.spec.label
        if label:
            self.view.set_ylabel(label)
        self.refresh_header()

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
        self._frame.setVisible(self._visible)

    def set_divider_visible(self, visible: bool) -> None:
        """Show/hide the bottom divider line."""
        self._frame.set_divider_visible(bool(visible))

    def divider_visible(self) -> bool:
        """Return whether the bottom divider line is visible."""
        return self._frame.divider_visible()

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

    def refresh_header(self) -> None:
        """Refresh track metadata and Y-control state for the current spec."""
        label = (self.spec.label or self.id).strip()
        if not label:
            label = self.id
        self._track_label = label
        self._y_axis_controls.setAccessibleName(f"{label} Y scale controls")
        self._gutter_widget.set_channel_label(label)
        self._gutter_widget.layout_channel_label()
        self._sync_header_state()

    def autoscale_y_once(self, *, margin: float = 0.05) -> None:
        """Autoscale this track Y-axis once (does not enable continuous autoscale)."""
        self.view.set_autoscale_y(False)
        self._autoscale_shrink_since = None
        self.autoscale(margin=margin)
        self._sync_header_state()

    def _set_continuous_autoscale(self, enabled: bool) -> None:
        self.view.set_autoscale_y(bool(enabled))
        if enabled:
            self._sticky_ylim = None
            self._autoscale_shrink_since = None
        else:
            self._autoscale_shrink_since = None
        self._sync_header_state()

    def _prompt_set_y_scale(self) -> None:
        current = self.get_ylim()
        y_min, ok_min = QInputDialog.getDouble(
            self._container,
            "Set Y Scale",
            "Y minimum:",
            float(current[0]),
            decimals=6,
        )
        if not ok_min:
            return
        y_max, ok_max = QInputDialog.getDouble(
            self._container,
            "Set Y Scale",
            "Y maximum:",
            float(current[1]),
            decimals=6,
        )
        if not ok_max:
            return
        if not math.isfinite(y_min) or not math.isfinite(y_max):
            return
        if y_max <= y_min:
            return
        self.set_ylim(float(y_min), float(y_max))
        self._sync_header_state()

    def _zoom_out_y_scale_step(self) -> None:
        self.scale_y_about(None, Y_ZOOM_OUT_FACTOR)

    def _zoom_in_y_scale_step(self) -> None:
        self.scale_y_about(None, Y_ZOOM_IN_FACTOR)

    def _reset_y_scale(self) -> None:
        self._sticky_ylim = None
        self._autoscale_shrink_since = None
        self.autoscale_y_once()

    def _open_y_axis_menu_at(self, global_pos: QPoint) -> None:
        self._y_axis_controls.popup_menu(global_pos)

    def _on_y_axis_drag_started(self) -> None:
        self._autoscale_shrink_since = None

    def _on_y_axis_drag_finished(self) -> None:
        self._sync_header_state()

    def _sync_header_state(self) -> None:
        self.view.refresh_y_axis_controls()

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
        # Lock in these limits as the sticky Y range so that subsequent window
        # updates (scroll, pan, event jumps) do not overwrite the user's scale.
        self._sticky_ylim = (float(ymin), float(ymax))
        self.view.set_ylim(ymin, ymax, preserve_autoscale=True)
        return (ymin, ymax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        """Set Y-axis limits manually."""
        self._sticky_ylim = (float(ymin), float(ymax))
        self._autoscale_shrink_since = None
        self.view.set_autoscale_y(False)
        self.view.set_ylim(ymin, ymax)
        self._sync_header_state()

    def pan_y(self, delta: float) -> None:
        """Pan the Y-axis by a delta amount."""
        ymin, ymax = self.view.get_ylim()
        new_min = ymin + delta
        new_max = ymax + delta
        self._sticky_ylim = (float(new_min), float(new_max))
        self._autoscale_shrink_since = None
        self.view.set_autoscale_y(False)
        self.view.set_ylim(new_min, new_max)
        self._sync_header_state()

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
        self._autoscale_shrink_since = None
        self.view.set_autoscale_y(False)
        self.view.set_ylim(new_min, new_max)
        self._sync_header_state()

    def pan_y(self, delta: float) -> None:
        """Translate the Y range by *delta* data-space units."""
        if not math.isfinite(float(delta)):
            return
        if self.view.is_autoscale_enabled():
            self.view.set_autoscale_y(False)
        ymin, ymax = self.view.get_ylim()
        new_min = float(ymin) + float(delta)
        new_max = float(ymax) + float(delta)
        self._sticky_ylim = (new_min, new_max)
        self._autoscale_shrink_since = None
        self.view.set_ylim(new_min, new_max)
        self._sync_header_state()

    def scale_y_about(self, center: float | None, factor: float) -> None:
        """Scale Y around a center point; used by axis drag and scale-step actions."""
        if not math.isfinite(float(factor)) or float(factor) <= 0.0:
            return
        if self.view.is_autoscale_enabled():
            self.view.set_autoscale_y(False)
        ymin, ymax = self.view.get_ylim()
        span = float(ymax - ymin)
        if span <= 0.0:
            span = max(abs(float(ymin)), abs(float(ymax)), 1.0)
        center_value = float(center) if center is not None and math.isfinite(float(center)) else None
        if center_value is None:
            center_value = (float(ymin) + float(ymax)) / 2.0
        new_span = max(span * float(factor), 1e-6)
        half = new_span * 0.5
        new_min = center_value - half
        new_max = center_value + half
        self._sticky_ylim = (float(new_min), float(new_max))
        self._autoscale_shrink_since = None
        self.view.set_ylim(new_min, new_max)
        self._sync_header_state()

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
        self._sync_header_state()
        _log.debug(
            "apply_auto_y track=%s autoscale_enabled=%s span_changed=%s",
            track_id,
            autoscale_enabled,
            span_changed,
        )

        if not autoscale_enabled:
            self._autoscale_shrink_since = None
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

        cur_min, cur_max = self.view.get_ylim()
        cur_span = max(float(cur_max - cur_min), 1e-9)
        new_span = max(float(ymax - ymin), 1e-9)
        expands = float(ymin) < float(cur_min) or float(ymax) > float(cur_max)

        if expands:
            self._autoscale_shrink_since = None
            _log.debug(
                "apply_auto_y track=%s expand ylim=(%.6f, %.6f) from current=(%.6f, %.6f)",
                track_id,
                ymin,
                ymax,
                cur_min,
                cur_max,
            )
            self.view.set_ylim(ymin, ymax)
            return

        if new_span < (cur_span * self._autoscale_shrink_ratio):
            now = time.monotonic()
            if self._autoscale_shrink_since is None:
                self._autoscale_shrink_since = now
                _log.debug(
                    "apply_auto_y track=%s shrink candidate started current_span=%.6f new_span=%.6f",
                    track_id,
                    cur_span,
                    new_span,
                )
                return
            if (now - self._autoscale_shrink_since) < self._autoscale_shrink_delay_s:
                _log.debug(
                    "apply_auto_y track=%s shrink deferred elapsed=%.3f required=%.3f",
                    track_id,
                    now - self._autoscale_shrink_since,
                    self._autoscale_shrink_delay_s,
                )
                return
            self._autoscale_shrink_since = None
            _log.debug(
                "apply_auto_y track=%s shrink apply ylim=(%.6f, %.6f)",
                track_id,
                ymin,
                ymax,
            )
            self.view.set_ylim(ymin, ymax)
            return

        self._autoscale_shrink_since = None
