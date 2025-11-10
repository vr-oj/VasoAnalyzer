"""PyQtGraph-based plot host for high-performance trace visualization."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pyqtgraph as pg
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.canvas_compat import PyQtGraphCanvasCompat
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PyQtGraphPlotHost"]


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

        # Interaction state
        self._pan_active: bool = False
        self._pan_start_x: float | None = None
        self._pan_start_window: tuple[float, float] | None = None

        # Performance throttling
        self._min_draw_interval: float = 1.0 / 120.0  # 120 FPS cap
        self._last_draw_ts: float = 0.0

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
        for track_id, track in self._tracks.items():
            widget = track.widget
            self.layout.removeWidget(widget)
            widget.setParent(None)

        self._tracks.clear()

        if not self._channel_specs:
            return

        # Create new tracks
        for spec in self._channel_specs:
            track = PyQtGraphChannelTrack(spec, enable_opengl=self._enable_opengl)

            # Add to layout with stretch factor based on height ratio
            stretch = max(int(spec.height_ratio * 100), 1)
            self.layout.addWidget(track.widget, stretch)

            self._tracks[spec.track_id] = track

            # Apply model if already set
            if self._model is not None:
                track.set_model(self._model)

            # Apply events if already set
            if self._event_times:
                track.set_events(
                    self._event_times, self._event_colors, self._event_labels
                )

            # Connect signals for synchronized interactions
            self._connect_track_signals(track)

        # Update window if already set
        if self._current_window is not None:
            x0, x1 = self._current_window
            self.set_time_window(x0, x1)

    def _connect_track_signals(self, track: PyQtGraphChannelTrack) -> None:
        """Connect track signals for synchronized pan/zoom."""
        plot_item = track.view.get_widget().getPlotItem()

        # Connect view range changed signal
        plot_item.sigRangeChanged.connect(self._on_track_range_changed)

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
            plot_item.sigRangeChanged.disconnect(self._on_track_range_changed)
            track.update_window(x0, x1)
            plot_item.setXRange(x0, x1, padding=0)
            plot_item.sigRangeChanged.connect(self._on_track_range_changed)

    def set_model(self, model: TraceModel) -> None:
        """Set the trace data model for all tracks."""
        self._model = model

        for track in self._tracks.values():
            track.set_model(model)

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
            plot_item.sigRangeChanged.disconnect(self._on_track_range_changed)

            track.update_window(x0, x1)
            plot_item.setXRange(x0, x1, padding=0)

            # Reconnect signals
            plot_item.sigRangeChanged.connect(self._on_track_range_changed)

    def set_events(
        self,
        times: list[float],
        colors: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> None:
        """Set event markers for all tracks."""
        self._event_times = list(times)
        self._event_colors = None if colors is None else list(colors)
        self._event_labels = [] if labels is None else list(labels)

        for track in self._tracks.values():
            track.set_events(times, colors, labels)

    def get_track(self, track_id: str) -> PyQtGraphChannelTrack | None:
        """Get track by ID."""
        return self._tracks.get(track_id)

    def track(self, track_id: str) -> PyQtGraphChannelTrack | None:
        """Get track by ID (matplotlib PlotHost compatibility)."""
        return self.get_track(track_id)

    def all_tracks(self) -> list[PyQtGraphChannelTrack]:
        """Get all tracks in order."""
        return [self._tracks[spec.track_id] for spec in self._channel_specs if spec.track_id in self._tracks]

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
        """Get the bottom axis (last track's plot item)."""
        if not self._channel_specs:
            return None
        last_track_id = self._channel_specs[-1].track_id
        track = self._tracks.get(last_track_id)
        if track:
            return track.view.get_widget().getPlotItem().getAxis('bottom')
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
        """Set event highlight style (compatibility stub).

        TODO: Implement event highlighting for PyQtGraph renderer.
        """
        # Stub - event highlighting will be implemented in Phase 1 Week 3
        pass
