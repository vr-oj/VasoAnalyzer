"""PyQtGraph-based plot host for high-performance trace visualization."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterable
from typing import Any, cast

import pyqtgraph as pg
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.event_labels_v3 import LayoutOptionsV3
from vasoanalyzer.ui.plots.canvas_compat import PyQtGraphCanvasCompat
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.export_bridge import ExportViewState, MatplotlibExportRenderer
from vasoanalyzer.ui.plots.plot_host import LayoutState
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_overlays import (
    PyQtGraphEventHighlightOverlay,
    PyQtGraphTimeCursorOverlay,
)
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PyQtGraphPlotHost"]

log = logging.getLogger(__name__)


class PyQtGraphPlotHost:
    """GPU-accelerated plot host using PyQtGraph.

    Provides high-performance alternative to matplotlib-based PlotHost
    while maintaining a compatible interface for easy integration.
    """

    def __init__(self, *, dpi: int = 100, enable_opengl: bool = True) -> None:
        """Initialize PyQtGraph plot host.

        Args:
            dpi: Display DPI (maintained for compatibility, not used by PyQtGraph)
            enable_opengl: Enable GPU acceleration
        """
        self._dpi = dpi
        self._enable_opengl = enable_opengl

        # Create main widget with vertical layout for stacked tracks
        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)  # Small gap between tracks

        # Apply theme
        bg_color = CURRENT_THEME.get("window_bg", "#FFFFFF")
        self.widget.setStyleSheet(f"background-color: {bg_color};")

        # Create matplotlib-compatible canvas wrapper for event handling
        # The wrapper contains self.widget and provides mpl_connect() for toolbar
        self.canvas = PyQtGraphCanvasCompat(self.widget)

        # Channel management
        self._channel_specs: list[ChannelTrackSpec] = []
        self._tracks: dict[str, PyQtGraphChannelTrack] = {}

        # Data model and state
        self._model: TraceModel | None = None
        self._current_window: tuple[float, float] | None = None
        self._event_times: list[float] = []
        self._event_colors: list[str] | None = None
        self._event_labels: list[str] = []
        self._event_label_meta: list[dict[str, Any]] | None = None

        # Interaction state
        self._pan_active: bool = False
        self._pan_start_x: float | None = None
        self._pan_start_window: tuple[float, float] | None = None

        # Performance throttling
        self._min_draw_interval: float = 1.0 / 120.0  # 120 FPS cap
        self._last_draw_ts: float = 0.0

        # Overlays
        self._time_cursor_overlay = PyQtGraphTimeCursorOverlay()
        self._event_highlight_overlay = PyQtGraphEventHighlightOverlay()
        self._event_label_options = LayoutOptionsV3()
        self._event_labels_enabled = True
        self._auto_event_label_mode = True
        self._label_density_thresholds: dict[str, float | None] = {"compact": None, "belt": None}
        self._hover_tooltip_enabled = True
        self._hover_tooltip_precision = 3
        self._tooltip_proximity = 10.0
        self._axis_font_family: str = "Arial"
        self._axis_font_size: float = 20.0
        self._tick_font_size: float = 16.0
        self._default_line_width: float = 4.0
        self._compact_legend_enabled: bool = False
        self._compact_legend_location: str = "upper right"
        self._time_window_listeners: list[Callable[[float, float], None]] = []

    def add_channel(self, spec: ChannelTrackSpec) -> PyQtGraphChannelTrack:
        """Add a channel to the stack and rebuild the layout."""
        existing_ids = {s.track_id for s in self._channel_specs}
        if spec.track_id in existing_ids:
            raise ValueError(f"Channel '{spec.track_id}' already exists")

        self._channel_specs.append(spec)
        self._rebuild_tracks()
        return self._tracks[spec.track_id]

    def ensure_channels(self, specs: Iterable[ChannelTrackSpec]) -> None:
        """Ensure the provided set of channels (ordered) exist."""
        desired = list(specs)
        current_ids = [spec.track_id for spec in self._channel_specs]
        desired_ids = [spec.track_id for spec in desired]

        if current_ids == desired_ids:
            # Update stored specs without rebuilding
            self._channel_specs = desired
            for spec in desired:
                track = self._tracks.get(spec.track_id)
                if track:
                    track.height_ratio = spec.height_ratio
            return

        self._channel_specs = desired
        self._rebuild_tracks()

    def _rebuild_tracks(self) -> None:
        """Recreate tracks to match specs."""
        # Clear existing tracks
        for _track_id, track in self._tracks.items():
            widget = track.widget
            self.layout.removeWidget(widget)
            widget.setParent(None)

        self._tracks.clear()

        if not self._channel_specs:
            return

        # Create new tracks
        plot_items = []

        for idx, spec in enumerate(self._channel_specs):
            track = PyQtGraphChannelTrack(spec, enable_opengl=self._enable_opengl)

            # Add to layout with stretch factor based on height ratio
            stretch = max(int(spec.height_ratio * 100), 1)
            self.layout.addWidget(track.widget, stretch)

            self._tracks[spec.track_id] = track

            plot_item = track.view.get_widget().getPlotItem()
            plot_items.append(plot_item)

            # Configure X-axis visibility: only show on bottom track
            is_bottom_track = idx == len(self._channel_specs) - 1
            bottom_axis = plot_item.getAxis("bottom")

            if not is_bottom_track:
                # Hide all components of the bottom axis for non-bottom tracks
                plot_item.hideAxis("bottom")
                bottom_axis.setLabel("")  # Remove label text
                bottom_axis.setStyle(showValues=False)  # Hide tick labels
                bottom_axis.setTicks([])  # Remove ticks
                bottom_axis.setHeight(0)  # Collapse the axis height
                # Hide the label item completely
                if hasattr(bottom_axis, "label"):
                    bottom_axis.label.hide()
                if hasattr(bottom_axis, "showLabel"):
                    bottom_axis.showLabel(False)
            else:
                # Ensure bottom track shows complete x-axis with ticks and label
                plot_item.showAxis("bottom")
                bottom_axis.setStyle(showValues=True)
                bottom_axis.setLabel("Time", units="s")
                # Reset height to default for bottom track
                bottom_axis.setHeight(None)

            # Add subtle border around each plot's ViewBox for visual separation
            view_box = plot_item.getViewBox()
            view_box.setBorder(pg.mkPen(color=(180, 180, 180), width=0.5))

            # Ensure Y-axes are aligned by setting consistent width
            left_axis = plot_item.getAxis("left")
            left_axis.setWidth(80)  # Fixed width for alignment

            # Apply model if already set
            if self._model is not None:
                track.set_model(self._model)

                # Re-apply bottom axis hiding after set_model (which resets the label)
                if not is_bottom_track:
                    plot_item.hideAxis("bottom")
                    bottom_axis.setLabel("")
                    bottom_axis.setStyle(showValues=False)
                    bottom_axis.setTicks([])
                    # Hide the label item completely
                    if hasattr(bottom_axis, "label"):
                        bottom_axis.label.hide()
                    if hasattr(bottom_axis, "showLabel"):
                        bottom_axis.showLabel(False)

            # Apply events if already set
            if self._event_times:
                track.set_events(
                    self._event_times,
                    self._event_colors,
                    self._event_labels,
                    label_meta=self._event_label_meta,
                )

            # Connect signals for synchronized interactions
            self._connect_track_signals(track)
            is_top_track = idx == 0
            self._configure_track_defaults(track, is_top_track=is_top_track)

        # Set row spacing between tracks for visual separation
        # Note: QVBoxLayout spacing is set in __init__, but we can adjust per-item spacing
        self.layout.setSpacing(5)  # 5px spacing between tracks

        # Sync overlays with new tracks
        self._time_cursor_overlay.sync_tracks(plot_items)
        self._event_highlight_overlay.sync_tracks(plot_items)

        # Update window if already set
        if self._current_window is not None:
            x0, x1 = self._current_window
            self.set_time_window(x0, x1)

    def _connect_track_signals(self, track: PyQtGraphChannelTrack) -> None:
        """Connect track signals for synchronized pan/zoom."""
        plot_item = track.view.get_widget().getPlotItem()

        # Connect view range changed signal
        plot_item.sigRangeChanged.connect(self._on_track_range_changed)

    def _configure_track_defaults(
        self, track: PyQtGraphChannelTrack, is_top_track: bool = False
    ) -> None:
        track.view.enable_hover_tooltip(
            self._hover_tooltip_enabled, precision=self._hover_tooltip_precision
        )
        # Only enable event labels on the top track
        enable_labels = self._event_labels_enabled and is_top_track
        track.view.enable_event_labels(
            enable_labels,
            options=self._event_label_options if enable_labels else None,
        )
        if track.primary_line:
            track.set_line_width(self._default_line_width)
        self._apply_axis_font_to_track(track)
        self._apply_axis_font_to_track(track)

    def _apply_event_label_options(self) -> None:
        if not self._tracks:
            return
        ordered_tracks = [
            self._tracks[spec.track_id]
            for spec in self._channel_specs
            if spec.track_id in self._tracks
        ] or list(self._tracks.values())
        for idx, track in enumerate(ordered_tracks):
            enable = self._event_labels_enabled and idx == 0
            track.view.enable_event_labels(
                enable,
                options=self._event_label_options if enable else None,
            )

    def _apply_tooltip_settings(self) -> None:
        for track in self._tracks.values():
            track.view.enable_hover_tooltip(
                self._hover_tooltip_enabled, precision=self._hover_tooltip_precision
            )

    def set_axis_font(self, *, family: str | None = None, size: float | None = None) -> None:
        changed = False
        if family and family != self._axis_font_family:
            self._axis_font_family = str(family)
            changed = True
        if size is not None and float(size) != self._axis_font_size:
            self._axis_font_size = float(size)
            changed = True
        if changed:
            for track in self._tracks.values():
                self._apply_axis_font_to_track(track)

    def axis_font(self) -> tuple[str, float]:
        return self._axis_font_family, self._axis_font_size

    def set_tick_font_size(self, size: float) -> None:
        value = float(size)
        if value == self._tick_font_size:
            return
        self._tick_font_size = value
        for track in self._tracks.values():
            self._apply_axis_font_to_track(track)

    def tick_font_size(self) -> float:
        return self._tick_font_size

    def set_default_line_width(self, width: float) -> None:
        value = float(width)
        if value == self._default_line_width:
            return
        self._default_line_width = value
        for track in self._tracks.values():
            track.set_line_width(self._default_line_width)

    def _apply_axis_font_to_track(self, track: PyQtGraphChannelTrack) -> None:
        plot_item = track.view.get_widget().getPlotItem()

        # Set fixed font sizes based on number of visible tracks
        # These sizes provide optimal readability as vertical space changes
        track_count = len(self._channel_specs)
        if track_count == 1:
            tick_size = 14
            ylabel_size = 24
            xlabel_size = 24
        elif track_count == 2:
            tick_size = 14
            ylabel_size = 22
            xlabel_size = 22
        elif track_count == 3:
            tick_size = 14
            ylabel_size = 20
            xlabel_size = 20
        else:  # 4 or more tracks
            tick_size = 14
            ylabel_size = 16
            xlabel_size = 20

        ylabel_font = QFont(self._axis_font_family, ylabel_size)
        xlabel_font = QFont(self._axis_font_family, xlabel_size)
        tick_font = QFont(self._axis_font_family, tick_size)

        left_axis = plot_item.getAxis("left")
        left_axis.label.setFont(ylabel_font)
        with contextlib.suppress(AttributeError):
            left_axis.setTickFont(tick_font)

        is_bottom = not self._channel_specs or track.id == self._channel_specs[-1].track_id
        if is_bottom:
            bottom_axis = plot_item.getAxis("bottom")
            bottom_axis.label.setFont(xlabel_font)
            with contextlib.suppress(AttributeError):
                bottom_axis.setTickFont(tick_font)

    def _normalize_color_tuple(self, color: Any) -> tuple[float, float, float, float] | None:
        if color is None:
            return None
        if (
            isinstance(color, tuple)
            and 3 <= len(color) <= 4
            or isinstance(color, list)
            and 3 <= len(color) <= 4
        ):
            comps = list(color)
        elif isinstance(color, str):
            qcolor = QColor(color)
            if not qcolor.isValid():
                return None
            comps = [qcolor.redF(), qcolor.greenF(), qcolor.blueF(), qcolor.alphaF()]
        else:
            return None
        if len(comps) == 3:
            comps.append(1.0)
        try:
            normalized: list[float] = []
            for value in comps[:4]:
                val = float(value)
                normalized_val = (
                    max(0.0, min(255.0, val)) / 255.0 if val > 1.0 else max(0.0, min(1.0, val))
                )
                normalized.append(normalized_val)
            normalized_tuple = cast(tuple[float, float, float, float], tuple(normalized))
            return normalized_tuple
        except Exception:
            return None

    def add_time_window_listener(self, callback: Callable[[float, float], None]) -> None:
        """Register a callback for time window changes."""
        if callback in self._time_window_listeners:
            return
        self._time_window_listeners.append(callback)

    def remove_time_window_listener(self, callback: Callable[[float, float], None]) -> None:
        """Unregister a previously added time window listener."""
        with contextlib.suppress(ValueError):
            self._time_window_listeners.remove(callback)

    def _notify_time_window_changed(self) -> None:
        if self._current_window is None:
            return
        listeners = list(self._time_window_listeners)
        for listener in listeners:
            try:
                listener(*self._current_window)
            except Exception:
                log.exception("Time window listener failed")

    def _on_track_range_changed(self, view_box) -> None:
        """Handle range change from any track (synchronize all tracks)."""
        # Get the new X range
        x_range = view_box.viewRange()[0]
        x0, x1 = float(x_range[0]), float(x_range[1])

        # Update internal state
        self._current_window = (x0, x1)

        # Synchronize all other tracks (block signals to avoid recursion)
        for track in self._tracks.values():
            plot_item = track.view.get_widget().getPlotItem()
            with contextlib.suppress(Exception):
                plot_item.sigRangeChanged.disconnect(self._on_track_range_changed)
            track.update_window(x0, x1)
            plot_item.setXRange(x0, x1, padding=0)
            plot_item.sigRangeChanged.connect(self._on_track_range_changed)

        self._notify_time_window_changed()

    def set_model(self, model: TraceModel) -> None:
        """Set the trace data model for all tracks."""
        self._model = model

        # Get ordered track IDs to determine which is bottom
        ordered_ids = [spec.track_id for spec in self._channel_specs]
        bottom_track_id = ordered_ids[-1] if ordered_ids else None

        for track in self._tracks.values():
            track.set_model(model)

            # Re-hide bottom axis for non-bottom tracks (set_model resets the label)
            is_bottom = track.id == bottom_track_id
            if not is_bottom:
                plot_item = track.view.get_widget().getPlotItem()
                bottom_axis = plot_item.getAxis("bottom")
                plot_item.hideAxis("bottom")
                bottom_axis.setLabel("")
                bottom_axis.setStyle(showValues=False)
                bottom_axis.setTicks([])
                if hasattr(bottom_axis, "label"):
                    bottom_axis.label.hide()
                if hasattr(bottom_axis, "showLabel"):
                    bottom_axis.showLabel(False)

        # Set initial window to full range
        if model is not None:
            x0, x1 = model.full_range
            self.set_time_window(x0, x1)

    def set_time_window(self, x0: float, x1: float) -> None:
        """Set the visible time window for all tracks."""
        self._current_window = (x0, x1)

        for track in self._tracks.values():
            # Block signals temporarily
            plot_item = track.view.get_widget().getPlotItem()
            with contextlib.suppress(Exception):
                plot_item.sigRangeChanged.disconnect(self._on_track_range_changed)

            track.update_window(x0, x1)
            plot_item.setXRange(x0, x1, padding=0)

            # Reconnect signals
            plot_item.sigRangeChanged.connect(self._on_track_range_changed)

        self._notify_time_window_changed()

    def set_events(
        self,
        times: list[float],
        colors: list[str] | None = None,
        labels: list[str] | None = None,
        label_meta: list[dict[str, Any]] | None = None,
    ) -> None:
        """Set event markers for all tracks.

        Args:
            times: Event timestamps
            colors: Event colors (optional)
            labels: Event labels (optional)
            label_meta: Event label metadata (matplotlib PlotHost compatibility, ignored)
        """
        self._event_times = list(times)
        self._event_colors = None if colors is None else list(colors)
        self._event_labels = [] if labels is None else list(labels)
        self._event_label_meta = None if label_meta is None else list(label_meta)

        for track in self._tracks.values():
            track.set_events(times, colors, labels, label_meta=self._event_label_meta)
        self._apply_event_label_options()

    def get_track(self, track_id: str) -> PyQtGraphChannelTrack | None:
        """Get track by ID."""
        return self._tracks.get(track_id)

    def track(self, track_id: str) -> PyQtGraphChannelTrack | None:
        """Get track by ID (matplotlib PlotHost compatibility)."""
        return self.get_track(track_id)

    def all_tracks(self) -> list[PyQtGraphChannelTrack]:
        """Get all tracks in order."""
        return [
            self._tracks[spec.track_id]
            for spec in self._channel_specs
            if spec.track_id in self._tracks
        ]

    def autoscale_all_tracks(self, margin: float = 0.05) -> None:
        """Autoscale Y-axis for all tracks."""
        for track in self._tracks.values():
            track.autoscale(margin=margin)

    def get_widget(self) -> QWidget:
        """Get the main widget for embedding in UI."""
        return self.widget

    def get_render_backend(self) -> str:
        """Get the rendering backend identifier."""
        return "pyqtgraph"

    # Compatibility properties/methods for matplotlib PlotHost interface
    @property
    def figure(self):
        """Compatibility property - PyQtGraph doesn't use matplotlib figure."""
        return None

    def bottom_axis(self):
        """Get the bottom axis (last track's plot item).

        Returns:
            PyQtGraphAxesCompat wrapper with matplotlib-compatible interface
        """
        if not self._channel_specs:
            return None
        last_track_id = self._channel_specs[-1].track_id
        track = self._tracks.get(last_track_id)
        if track:
            # Return the wrapped axes object, not the raw AxisItem
            return track.ax
        return None

    def apply_style(self, style: dict[str, Any]) -> None:
        """Apply visual styling to all tracks."""
        for track in self._tracks.values():
            track.view.apply_style(style)

        # Update widget background
        if "background_color" in style:
            bg = style["background_color"]
            self.widget.setStyleSheet(f"background-color: {bg};")

    def _schedule_draw(self) -> None:
        """Schedule a draw (compatibility method - PyQtGraph updates automatically)."""
        # PyQtGraph handles drawing automatically, so this is a no-op
        pass

    def set_event_highlight_style(self, color: str | None = None, alpha: float = 0.2) -> None:
        """Set event highlight style.

        Args:
            color: Highlight color
            alpha: Transparency (0-1)
        """
        self._event_highlight_overlay.set_style(color=color, alpha=alpha)

    def set_time_cursor(self, time: float | None, visible: bool = True) -> None:
        """Set time cursor position and visibility.

        Args:
            time: Time value to position cursor at (None to hide)
            visible: Whether cursor should be visible
        """
        if time is None:
            self._time_cursor_overlay.set_visible(False)
        else:
            self._time_cursor_overlay.set_time(time)
            self._time_cursor_overlay.set_visible(visible)

    def set_event_highlight(self, time: float | None, visible: bool = True) -> None:
        """Set event highlight position and visibility.

        Args:
            time: Time value to highlight (None to clear)
            visible: Whether highlight should be visible
        """
        if time is None:
            self._event_highlight_overlay.clear()
        else:
            self._event_highlight_overlay.set_time(time)
            self._event_highlight_overlay.set_visible(visible)

    def clear_event_highlight(self) -> None:
        """Clear event highlight."""
        self._event_highlight_overlay.clear()

    def highlight_event(self, time_s: float | None, *, visible: bool = True) -> None:
        """Highlight a selected event across all tracks (matplotlib PlotHost compatibility).

        Args:
            time_s: Time value to highlight (None to clear)
            visible: Whether highlight should be visible
        """
        self.set_event_highlight(time_s, visible)

    def primary_axis(self):
        """Get the primary (first) axis (matplotlib PlotHost compatibility)."""
        if not self._channel_specs:
            return None
        first_id = self._channel_specs[0].track_id
        track = self._tracks.get(first_id)
        return None if track is None else track.ax

    def set_trace_model(self, model: TraceModel) -> None:
        """Set trace model (matplotlib PlotHost compatibility - alias for set_model)."""
        self.set_model(model)

    def set_shared_xlabel(self, text: str) -> None:
        """Set xlabel on bottom axis (matplotlib PlotHost compatibility)."""
        if not self._channel_specs:
            return
        last_track_id = self._channel_specs[-1].track_id
        track = self._tracks.get(last_track_id)
        if track:
            track.view.get_widget().getPlotItem().setLabel("bottom", text)

    def set_event_lines_visible(self, visible: bool) -> None:
        """Set event line visibility (matplotlib PlotHost compatibility).

        Note: PyQtGraph tracks handle event visibility internally.
        This is a no-op for compatibility.
        """
        # TODO: Implement event line visibility control if needed
        pass

    def set_annotation_entries(self, entries: list) -> None:
        """Set annotation entries (matplotlib PlotHost compatibility).

        Note: PyQtGraph doesn't use annotation lanes yet.
        This is a no-op for compatibility.
        """
        # TODO: Implement annotation lane if needed
        pass

    def annotation_text_objects(self) -> list:
        """Get annotation text objects (matplotlib PlotHost compatibility).

        Returns:
            Empty list (PyQtGraph uses different annotation system)
        """
        # TODO: Return PyQtGraph text items if needed
        return []

    # Event label configuration methods (matplotlib PlotHost compatibility)
    # These are stubs for now - PyQtGraph uses different event labeling system

    def set_event_highlight_alpha(self, alpha: float) -> None:
        """Set event highlight alpha transparency."""
        alpha = max(0.0, min(float(alpha), 1.0))
        self._event_highlight_overlay.set_style(alpha=alpha)

    def event_highlight_alpha(self) -> float:
        """Get current event highlight alpha."""
        return float(self._event_highlight_overlay.alpha())

    def current_window(self) -> tuple[float, float] | None:
        """Get current time window."""
        return self._current_window

    def full_range(self) -> tuple[float, float] | None:
        """Get full time range from model."""
        if self._model is None:
            return None
        start, end = self._model.full_range
        return float(start), float(end)

    def axes(self) -> list:
        """Get all axes (matplotlib PlotHost compatibility)."""
        return [track.ax for track in self._tracks.values()]

    def layout_state(self) -> LayoutState:
        """Get layout state snapshot."""
        return LayoutState(
            order=[spec.track_id for spec in self._channel_specs],
            height_ratios={spec.track_id: spec.height_ratio for spec in self._channel_specs},
            visibility={track.id: track.is_visible() for track in self._tracks.values()},
        )

    def channel_specs(self) -> list[ChannelTrackSpec]:
        """Get channel specifications."""
        from copy import copy

        return [copy(spec) for spec in self._channel_specs]

    def autoscale_all(self, *, margin: float = 0.05) -> None:
        """Autoscale all tracks."""
        self.autoscale_all_tracks(margin=margin)

    def set_autoscale_y_enabled(self, enabled: bool) -> None:
        """Enable/disable Y-axis autoscaling for all tracks."""
        for track in self._tracks.values():
            track.view.set_autoscale_y(enabled)

    def is_autoscale_y_enabled(self) -> bool:
        """Check if Y-axis autoscaling is enabled (checks first track)."""
        if not self._tracks:
            return True  # Default to enabled
        first_track = next(iter(self._tracks.values()))
        return bool(first_track.view.is_autoscale_enabled())

    def use_track_event_lines(self, flag: bool) -> None:
        """Control whether tracks draw their own event lines (compatibility stub)."""
        # PyQtGraph tracks always handle their own event rendering
        pass

    def set_event_labels_visible(self, visible: bool) -> None:
        """Set event labels visibility."""
        self._event_labels_enabled = bool(visible)
        self._apply_event_label_options()

    def set_event_labels_v3_enabled(self, enabled: bool) -> None:
        self.set_event_labels_visible(enabled)

    def set_event_label_mode(self, mode: str) -> None:
        normalized = str(mode or "").lower()
        mapping = {
            "vertical": "vertical",
            "horizontal": "h_inside",
            "horizontal_outside": "h_belt",
            "h_inside": "h_inside",
            "h_belt": "h_belt",
        }
        self._event_label_options.mode = mapping.get(normalized, "vertical")
        self._apply_event_label_options()

    def set_max_labels_per_cluster(self, max_labels: int) -> None:
        self._event_label_options.max_labels_per_cluster = max(1, int(max_labels))
        self._apply_event_label_options()

    def set_cluster_style_policy(self, policy: str) -> None:
        normalized = str(policy or "").lower()
        valid = {"first", "most_common", "priority", "blend_color"}
        if normalized not in valid:
            normalized = "first"
        self._event_label_options.style_policy = normalized
        self._apply_event_label_options()

    def set_label_lanes(self, lanes: int) -> None:
        self._event_label_options.lanes = max(1, int(lanes))
        self._apply_event_label_options()

    def set_belt_baseline(self, baseline: bool) -> None:
        self._event_label_options.belt_baseline = bool(baseline)
        self._apply_event_label_options()

    def set_event_label_span_siblings(self, span: bool) -> None:
        self._event_label_options.span_siblings = bool(span)
        self._apply_event_label_options()

    def set_event_label_gap(self, pixels: int) -> None:
        self._event_label_options.min_px = max(1, int(pixels))
        self._apply_event_label_options()

    def set_auto_event_label_mode(self, auto_mode: bool) -> None:
        self._auto_event_label_mode = bool(auto_mode)

    def set_label_density_thresholds(
        self, *, compact: float | None = None, belt: float | None = None
    ) -> None:
        self._label_density_thresholds = {"compact": compact, "belt": belt}

    def set_label_outline_enabled(self, enabled: bool) -> None:
        self._event_label_options.outline_enabled = bool(enabled)
        self._apply_event_label_options()

    def set_label_outline(self, width: float, color: Any) -> None:
        self._event_label_options.outline_width = max(0.0, float(width))
        self._event_label_options.outline_color = self._normalize_color_tuple(color)
        self._apply_event_label_options()

    def set_label_tooltips_enabled(self, enabled: bool) -> None:
        self._hover_tooltip_enabled = bool(enabled)
        self._apply_tooltip_settings()

    def set_tooltip_proximity(self, proximity: float) -> None:
        self._tooltip_proximity = float(proximity)
        # Placeholder - PyQtGraph tooltips currently ignore proximity

    def set_tooltip_precision(self, precision: int) -> None:
        self._hover_tooltip_precision = max(0, int(precision))
        self._apply_tooltip_settings()

    def set_compact_legend_enabled(self, enabled: bool) -> None:
        self._compact_legend_enabled = bool(enabled)

    def set_compact_legend_location(self, location: str) -> None:
        self._compact_legend_location = str(location)

    def set_event_base_style(self, **kwargs) -> None:
        """Set event base style from keyword arguments."""
        font_family = kwargs.get("font_family")
        if font_family:
            self._event_label_options.font_family = str(font_family)
        font_size = kwargs.get("font_size")
        if font_size is not None:
            self._event_label_options.font_size = float(font_size)
        if "bold" in kwargs:
            self._event_label_options.font_bold = bool(kwargs["bold"])
        if "italic" in kwargs:
            self._event_label_options.font_italic = bool(kwargs["italic"])
        color = kwargs.get("color")
        if color:
            self._event_label_options.font_color = str(color)
        if "show_numbers_only" in kwargs:
            self._event_label_options.show_numbers_only = bool(kwargs["show_numbers_only"])
        self._apply_event_label_options()

    # Additional core PlotHost methods for full compatibility

    def clear(self) -> None:
        """Clear all tracks and reset to initial state."""
        # Clear all tracks
        for _track_id, track in list(self._tracks.items()):
            widget = track.widget
            self.layout.removeWidget(widget)
            widget.setParent(None)

        self._tracks.clear()
        self._channel_specs.clear()
        self._model = None
        self._current_window = None
        self._event_times = []
        self._event_colors = None
        self._event_labels = []
        self._event_label_meta = None

    def tracks(self) -> list[PyQtGraphChannelTrack]:
        """Get all tracks as a list."""
        return list(self._tracks.values())

    def suspend_updates(self) -> None:
        """Suspend updates for batching operations (compatibility stub)."""
        # PyQtGraph updates automatically, so this is a no-op
        pass

    def resume_updates(self) -> None:
        """Resume updates after batching (compatibility stub)."""
        # PyQtGraph updates automatically, so this is a no-op
        pass

    def track_for_axes(self, axes) -> PyQtGraphChannelTrack | None:
        """Get track for given axes (matplotlib PlotHost compatibility)."""
        # In PyQtGraph, we can try to match by the axes object
        for track in self._tracks.values():
            if track.ax == axes or track.view.get_widget().getPlotItem() == axes:
                return track
        return None

    def zoom_at(self, center: float, factor: float) -> None:
        """Zoom around a given time coordinate."""
        if self._current_window is None:
            return
        x0, x1 = self._current_window
        span = x1 - x0
        if span <= 0:
            return
        new_span = max(span * factor, 1e-6)
        half = new_span / 2.0
        new_x0 = center - half
        new_x1 = center + half
        self.set_time_window(new_x0, new_x1)

    def scroll_by(self, delta: float) -> None:
        """Scroll the current time window by delta seconds."""
        if self._current_window is None:
            return
        x0, x1 = self._current_window
        self.set_time_window(x0 + delta, x1 + delta)

    # Event label configuration getters (return defaults for PyQtGraph)

    def event_labels_v3_enabled(self) -> bool:
        """Get whether v3 event labels are enabled."""
        return False  # PyQtGraph uses its own labeling

    def max_labels_per_cluster(self) -> int:
        """Get max labels per cluster."""
        return 1

    def cluster_style_policy(self) -> str:
        """Get cluster style policy."""
        return "first"

    def event_label_lanes(self) -> int:
        """Get number of label lanes."""
        return 3

    def belt_baseline_enabled(self) -> bool:
        """Get whether belt baseline is enabled."""
        return True

    def span_event_lines_across_siblings(self) -> bool:
        """Get whether event lines span across siblings."""
        return True

    def auto_event_label_mode(self) -> bool:
        """Get whether auto event label mode is enabled."""
        return False

    def label_density_thresholds(self) -> tuple[float, float]:
        """Get label density thresholds."""
        return (0.8, 0.25)

    def label_outline_settings(
        self,
    ) -> tuple[bool, float, tuple[float, float, float, float] | None]:
        """Get label outline settings."""
        return (True, 2.0, (1.0, 1.0, 1.0, 0.9))

    def label_tooltips_enabled(self) -> bool:
        """Get whether label tooltips are enabled."""
        return True

    def tooltip_proximity(self) -> int:
        """Get tooltip proximity in pixels."""
        return 10

    def compact_legend_enabled(self) -> bool:
        """Get whether compact legend is enabled."""
        return False

    def compact_legend_location(self) -> str:
        """Get compact legend location."""
        return "upper right"

    def capture_view_state(self) -> ExportViewState:
        """Capture current view state for export.

        Returns:
            ExportViewState with all current view parameters
        """
        # Get current view range from first visible track
        xlim = (0.0, 1.0)
        ylim = (0.0, 1.0)
        if self._tracks:
            first_track = next(iter(self._tracks.values()))
            xlim = first_track.get_xlim()
            ylim = first_track.get_ylim()

        # Get height ratios
        height_ratios = {spec.track_id: spec.height_ratio for spec in self._channel_specs}

        # Get visible tracks
        visible_tracks = [
            track_id for track_id, track in self._tracks.items() if track.is_visible()
        ]

        # Capture style (basic for now)
        style = {
            "show_uncertainty": False,  # Can be configured
            "background_color": CURRENT_THEME.get("window_bg", "#FFFFFF"),
        }

        return ExportViewState(
            trace_model=self._model,
            xlim=xlim,
            ylim=ylim,
            channel_specs=self._channel_specs,
            visible_tracks=visible_tracks,
            event_times=self._event_times,
            event_colors=self._event_colors,
            event_labels=self._event_labels,
            style=style,
            height_ratios=height_ratios,
            show_grid=True,
            show_legend=False,
        )

    def export_to_file(
        self,
        filename: str,
        *,
        dpi: int = 600,
        figsize: tuple[float, float] | None = None,
        format: str | None = None,
        **kwargs,
    ) -> None:
        """Export current view to file using matplotlib for high quality.

        Args:
            filename: Output filename
            dpi: Export DPI (default: 600 for publication quality)
            figsize: Figure size in inches (width, height)
            format: File format (auto-detected from filename if None)
            **kwargs: Additional arguments for savefig
        """
        # Capture current view state
        view_state = self.capture_view_state()

        # Create export renderer
        renderer = MatplotlibExportRenderer(dpi=dpi)

        # Render with matplotlib
        renderer.render(view_state, figsize=figsize)

        # Save to file
        renderer.save(filename, format=format, **kwargs)

        # Cleanup
        renderer.close()

    def create_export_figure(
        self,
        dpi: int = 300,
        figsize: tuple[float, float] | None = None,
    ):
        """Create a matplotlib Figure for export preview or customization.

        Args:
            dpi: Export DPI
            figsize: Figure size in inches

        Returns:
            Matplotlib Figure
        """
        view_state = self.capture_view_state()
        renderer = MatplotlibExportRenderer(dpi=dpi)
        return renderer.render(view_state, figsize=figsize)
