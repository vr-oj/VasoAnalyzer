"""PyQtGraph-based plot host for high-performance trace visualization."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterable
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.canvas_compat import PyQtGraphCanvasCompat
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.export_bridge import ExportViewState, MatplotlibExportRenderer
from vasoanalyzer.ui.plots.plot_host import LayoutState
from vasoanalyzer.ui.plots.interactions_base import (
    ClickContext,
    InteractionHost,
    MoveContext,
    ScrollContext,
)
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_event_strip import PyQtGraphEventStripTrack
from vasoanalyzer.ui.plots.pyqtgraph_overlays import (
    PyQtGraphEventHighlightOverlay,
    PyQtGraphTimeCursorOverlay,
)
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PyQtGraphPlotHost"]

log = logging.getLogger(__name__)


class PyQtGraphPlotHost(InteractionHost):
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
        self._widget = QWidget()
        self.layout = QVBoxLayout(self._widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)  # Small gap between tracks

        # Create graphics layout for tracks
        # Tracks are managed as individual widgets stacked vertically.

        # Apply theme - use plot_bg for white content area in light mode
        bg_color = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        self._widget.setStyleSheet(f"background-color: {bg_color};")

        # Create matplotlib-compatible canvas wrapper for event handling
        # The wrapper contains self.widget and provides mpl_connect() for toolbar
        self.canvas = PyQtGraphCanvasCompat(self._widget)

        # Channel management
        self._channel_specs: list[ChannelTrackSpec] = []
        self._tracks: dict[str, PyQtGraphChannelTrack] = {}
        self._channel_visible: dict[str, bool] = {}
        self._current_layout_signature: tuple | None = None
        self._bottom_visible_track_id: str | None = None

        # Data model and state
        self._model: TraceModel | None = None
        self._current_window: tuple[float, float] | None = None
        self._data_t_min: float | None = None
        self._data_t_max: float | None = None
        self._min_window_span: float = 1e-6
        self._event_times: list[float] = []
        self._event_colors: list[str] | None = None
        self._event_labels: list[str] = []
        self._event_label_meta: list[dict[str, Any]] | None = None
        self._event_label_options = LayoutOptionsV3(mode="h_belt", show_numbers_only=True)
        self._event_entries: list[EventEntryV3] = []
        self._event_strip_track: PyQtGraphEventStripTrack | None = None
        self._event_strip_widget: pg.PlotWidget | None = None

        # Interaction state
        self._pan_active: bool = False
        self._pan_start_x: float | None = None
        self._pan_start_window: tuple[float, float] | None = None
        self._mouse_mode: str = "pan"  # "pan" or "rect" (box zoom)

        # Performance throttling
        self._min_draw_interval: float = 1.0 / 120.0  # 120 FPS cap
        self._last_draw_ts: float = 0.0

        # Overlays
        self._time_cursor_overlay = PyQtGraphTimeCursorOverlay()
        self._event_highlight_overlay = PyQtGraphEventHighlightOverlay()
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
        self._selection_region: pg.LinearRegionItem | None = None
        self._window_bg_color: tuple[int, int, int] | None = None
        self._plot_bg_color: tuple[int, int, int] | None = None
        self._compact_legend_enabled: bool = False
        self._compact_legend_location: str = "upper right"
        self._time_window_listeners: list[Callable[[float, float], None]] = []
        self._range_change_user_driven: bool = False
        self._click_handler: Callable[[str, float, float, int, Any], None] | None = None
        border_color = CURRENT_THEME.get(
            "hover_label_border",
            CURRENT_THEME.get("text", "#000000"),
        )
        self._lane_border_pen = pg.mkPen(
            color=border_color,
            width=1,
            cosmetic=True,
        )
        self._x_grid_visible: bool = True
        self._y_grid_visible: bool = True
        self._grid_alpha: float = 0.10
        self._click_handlers: list[Callable[[ClickContext], None]] = []
        self._move_handlers: list[Callable[[MoveContext], None]] = []
        self._scroll_handlers: list[Callable[[ScrollContext], None]] = []
        self._sampling_mode_active: bool = False

        # Install resize event filter to refresh axes/fonts when geometry changes
        self._resize_filter = _ResizeEventFilter(self)
        self._widget.installEventFilter(self._resize_filter)

    # ------------------------------------------------------------------ InteractionHost
    def on_click(self, handler: Callable[[ClickContext], None]) -> None:
        self._click_handlers.append(handler)

    def on_move(self, handler: Callable[[MoveContext], None]) -> None:
        self._move_handlers.append(handler)

    def on_scroll(self, handler: Callable[[ScrollContext], None]) -> None:
        self._scroll_handlers.append(handler)

    def apply_theme(self) -> None:
        """Refresh plot host colors from the active theme."""
        print(f"[THEME-DEBUG] PyQtGraphPlotHost.apply_theme called, id(self)={id(self)}")

        # Use plot_bg for white content area in light mode (not window_bg which is gray toolbar)
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        border_color = CURRENT_THEME.get(
            "hover_label_border",
            CURRENT_THEME.get("text", "#000000"),
        )
        self._widget.setStyleSheet(f"background-color: {bg};")
        self._lane_border_pen = pg.mkPen(color=border_color, width=1, cosmetic=True)

        for track in self._tracks.values():
            try:
                track.view.apply_theme()
                plot_item = track.view.get_widget().getPlotItem()
                plot_item.getViewBox().setBorder(self._lane_border_pen)
            except Exception:
                pass

        if self._event_strip_track is not None:
            try:
                self._event_strip_track.apply_theme()
                vb = self._event_strip_track.plot_item.getViewBox()
                vb.setBorder(self._lane_border_pen)
            except Exception:
                pass

        for overlay in (
            getattr(self, "_time_cursor_overlay", None),
            getattr(self, "_event_highlight_overlay", None),
        ):
            apply_method = getattr(overlay, "apply_theme", None)
            if callable(apply_method):
                with contextlib.suppress(Exception):
                    apply_method()
        style = self._widget.styleSheet() if hasattr(self, "_widget") else ""
        print(
            f"[THEME-DEBUG] PyQtGraphPlotHost styleSheet length={len(style) if style is not None else 0}"
        )

        # Refresh axis fonts and labels after theme change
        self.refresh_axes_and_fonts(reason="theme-changed")

    # ------------------------------------------------------------------ visibility helpers
    def set_channel_visible(self, channel_kind: str, visible: bool) -> None:
        """Set visibility for a given channel kind.

        Keeps tracks instantiated; only toggles their visibility state.
        If the track exists, apply visibility directly. If a spec exists but the
        track hasn't been built yet, the stored flag is applied when tracks are created.
        """

        kind = str(channel_kind)
        self._channel_visible[kind] = bool(visible)

        track = self._tracks.get(kind)
        if track is not None:
            track.set_visible(bool(visible))

        # Refresh axis ownership and fonts after visibility change
        self.refresh_axes_and_fonts(reason="channel-visible-changed")

    def set_click_handler(self, handler: Callable[[str, float, float, int, Any], None] | None):
        """Assign a global click handler for all tracks."""
        self._click_handler = handler
        for track_id, track in self._tracks.items():
            track.set_click_handler(
                lambda x, y, button, _mode, ev, tid=track_id: self._emit_click(
                    tid, x, y, button, ev
                )
            )

    def set_sampling_mode(self, enabled: bool) -> None:
        """Enable/disable sampling mode visual feedback.

        Args:
            enabled: Whether sampling mode is active
        """
        self._sampling_mode_active = enabled

        if enabled:
            # Add visual indicators for sampling mode
            # TODO: Add plot border glow, cursor change, badge overlay
            pass
        else:
            # Remove visual indicators
            # TODO: Remove border glow, restore cursor, hide badge
            pass

    def set_review_mode_highlighting(self, enabled: bool) -> None:
        """Enable/disable enhanced highlighting for review mode.

        Args:
            enabled: Whether to use animated review mode highlighting
        """
        if hasattr(self, "_event_highlight_overlay"):
            self._event_highlight_overlay.set_animated(enabled)

    def show_sampling_crosshair(self, time_sec: float, id_val: float | None = None, od_val: float | None = None) -> None:
        """Display sampling crosshair at the given time and values.

        Args:
            time_sec: Time position for vertical line
            id_val: ID value for horizontal line on ID track
            od_val: OD value for horizontal line on OD track
        """
        # Find ID and OD tracks
        id_track = self._tracks.get("ID")
        od_track = self._tracks.get("OD")

        # Show crosshair on ID track
        if id_track is not None and id_val is not None:
            self._show_track_crosshair(id_track, time_sec, id_val)

        # Show crosshair on OD track
        if od_track is not None and od_val is not None:
            self._show_track_crosshair(od_track, time_sec, od_val)

        # Auto-hide after 2 seconds
        QTimer.singleShot(2000, self.hide_sampling_crosshair)

    def hide_sampling_crosshair(self) -> None:
        """Hide sampling crosshair markers."""
        for track in self._tracks.values():
            self._hide_track_crosshair(track)

    def _show_track_crosshair(self, track: PyQtGraphChannelTrack, time_sec: float, value: float) -> None:
        """Show crosshair lines on a specific track.

        Args:
            track: Track to show crosshair on
            time_sec: Time position for vertical line
            value: Value position for horizontal line
        """
        plot_item = track.view.get_widget().getPlotItem()

        # Create or update vertical line
        if not hasattr(track, "_sampling_vline"):
            track._sampling_vline = pg.InfiniteLine(
                pos=time_sec,
                angle=90,
                pen=pg.mkPen(color="#1D5CFF", width=1, style=Qt.DashLine),
                movable=False,
            )
            track._sampling_vline.setZValue(10)
            plot_item.addItem(track._sampling_vline)
        else:
            track._sampling_vline.setPos(time_sec)
            track._sampling_vline.show()

        # Create or update horizontal line
        if not hasattr(track, "_sampling_hline"):
            track._sampling_hline = pg.InfiniteLine(
                pos=value,
                angle=0,
                pen=pg.mkPen(color="#1D5CFF", width=1, style=Qt.DashLine),
                movable=False,
            )
            track._sampling_hline.setZValue(10)
            plot_item.addItem(track._sampling_hline)
        else:
            track._sampling_hline.setPos(value)
            track._sampling_hline.show()

    def _hide_track_crosshair(self, track: PyQtGraphChannelTrack) -> None:
        """Hide crosshair lines on a specific track.

        Args:
            track: Track to hide crosshair on
        """
        if hasattr(track, "_sampling_vline"):
            track._sampling_vline.hide()
        if hasattr(track, "_sampling_hline"):
            track._sampling_hline.hide()

    def is_channel_visible(self, channel_kind: str) -> bool:
        """Return visibility flag for a channel kind (defaults to True)."""

        return bool(self._channel_visible.get(str(channel_kind), True))

    def iter_channels(self) -> Iterable[ChannelTrackSpec]:
        """Yield channel specs for currently configured channels."""

        return list(self._channel_specs)

    def debug_dump_state(self, label: str) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        window = self._current_window
        if window is None:
            window_repr = "None"
            span_repr = "None"
        else:
            x0, x1 = window
            window_repr = f"({x0:.6f}, {x1:.6f})"
            span_repr = f"{(x1 - x0):.6f}"
        log.debug(
            "[PLOT DEBUG] label=%s backend=pyqtgraph window=%s span=%s tracks=%d",
            label,
            window_repr,
            span_repr,
            len(self._tracks),
        )
        for track_id, track in self._tracks.items():
            try:
                visible = track.is_visible()
            except Exception:
                visible = None
            try:
                autoscale = bool(track.view.is_autoscale_enabled())
            except Exception:
                autoscale = None
            try:
                ylim = track.view.get_ylim()
            except Exception:
                ylim = None
            sticky = getattr(track, "_sticky_ylim", None)
            event_labels = getattr(track.view, "_event_labels_visible", None)
            log.debug(
                "[PLOT DEBUG] track=%s visible=%s autoscale=%s ylim=%s sticky=%s event_labels=%s",
                track_id,
                visible,
                autoscale,
                ylim,
                sticky,
                event_labels,
            )

    def log_data_and_view_ranges(self, label: str) -> None:
        """
        Debug helper: log raw data ranges from the TraceModel and current view ranges.
        """
        if not log.isEnabledFor(logging.DEBUG):
            return
        model = getattr(self, "_model", None)
        window = getattr(self, "_current_window", None)
        if model is None:
            log.debug(
                "[RANGE DEBUG] label=%s backend=pyqtgraph model=None window=%s",
                label,
                window,
            )
            return
        log.debug(
            "[RANGE DEBUG] label=%s backend=pyqtgraph window=%s",
            label,
            window,
        )
        time_full = getattr(model, "time_full", None)
        raw_x = None
        if time_full is not None:
            try:
                raw_x = (float(np.nanmin(time_full)), float(np.nanmax(time_full)))
            except Exception:
                raw_x = None
        tracks = getattr(self, "_tracks", None)
        if not tracks:
            return
        iterable = tracks.values() if isinstance(tracks, dict) else tracks
        component_attr = {
            "inner": "inner_full",
            "outer": "outer_full",
            "avg_pressure": "avg_pressure_full",
            "set_pressure": "set_pressure_full",
            "dual": "inner_full",
        }
        for track in iterable:
            try:
                spec = getattr(track, "spec", None)
                component = getattr(spec, "component", None) if spec is not None else None
                track_id = getattr(spec, "track_id", None) if spec is not None else None
                if track_id is None:
                    track_id = getattr(track, "id", None)
                if track_id is None:
                    track_id = repr(track)
                raw_y = None
                attr_name = component_attr.get(str(component))
                if attr_name is not None:
                    series = getattr(model, attr_name, None)
                    if series is not None:
                        try:
                            raw_y = (float(np.nanmin(series)), float(np.nanmax(series)))
                        except Exception:
                            raw_y = None
                view = getattr(track, "view", None)
                view_y = None
                if view is not None and hasattr(view, "get_ylim"):
                    try:
                        view_y = view.get_ylim()
                    except Exception:
                        view_y = None
                log.debug(
                    "[RANGE DEBUG] track=%s component=%s raw_x=%s raw_y=%s view_x=%s view_y=%s",
                    track_id,
                    component,
                    raw_x,
                    raw_y,
                    window,
                    view_y,
                )
            except Exception:
                log.debug("[RANGE DEBUG] track=%r failed to compute ranges", track)

    def add_channel(self, spec: ChannelTrackSpec) -> PyQtGraphChannelTrack:
        """Add a channel to the stack and rebuild the layout."""
        existing_ids = {s.track_id for s in self._channel_specs}
        if spec.track_id in existing_ids:
            raise ValueError(f"Channel '{spec.track_id}' already exists")

        self._channel_specs.append(spec)
        self._rebuild_tracks()
        self._current_layout_signature = self._layout_signature(self._channel_specs)
        return self._tracks[spec.track_id]

    def ensure_channels(self, specs: Iterable[ChannelTrackSpec]) -> None:
        """Ensure the provided set of channels (ordered) exist."""
        desired = list(specs)
        new_signature = self._layout_signature(desired)
        if (
            self._current_layout_signature is not None
            and new_signature == self._current_layout_signature
            and self._tracks
        ):
            # Layout already matches; skip rebuild to avoid jank.
            self._channel_specs = desired
            return

        self._channel_specs = desired
        self._rebuild_tracks()
        self._current_layout_signature = new_signature

    def _layout_signature(self, specs: Iterable[ChannelTrackSpec]) -> tuple:
        """Return a hashable signature for the current layout specification."""
        return tuple(
            (spec.track_id, spec.component, float(spec.height_ratio), spec.label) for spec in specs
        )

    def _rebuild_tracks(self) -> None:
        """Recreate tracks to match specs."""
        # Clear existing widgets/layout but keep track objects we can reuse
        for _track_id, track in list(self._tracks.items()):
            widget = track.widget
            self.layout.removeWidget(widget)
            widget.setParent(None)

        # Recreate tracks and re-add widgets in desired order
        new_tracks: dict[str, PyQtGraphChannelTrack] = {}
        if not self._channel_specs:
            self._tracks = new_tracks
            self._current_layout_signature = None
            return

        primary_plot_item: pg.PlotItem | None = None
        primary_track: PyQtGraphChannelTrack | None = None
        # Ensure event strip exists and sits at top
        if self._event_strip_track is None:
            self._event_strip_widget = pg.PlotWidget()
            self._event_strip_widget.setMaximumHeight(40 if self._event_labels_enabled else 0)
            self._event_strip_widget.setVisible(self._event_labels_enabled)
            self._event_strip_track = PyQtGraphEventStripTrack(
                self._event_strip_widget.getPlotItem()
            )
            self.layout.insertWidget(
                0, self._event_strip_widget, 5 if self._event_labels_enabled else 0
            )

        plot_items = []

        # Determine which track should own the bottom X-axis.
        # Prefer the lowest visible track; if none are visible, fall back to the last spec.
        visible_specs = [
            spec for spec in self._channel_specs if self.is_channel_visible(spec.track_id)
        ]
        if visible_specs:
            bottom_visible_id = visible_specs[-1].track_id
        else:
            bottom_visible_id = self._channel_specs[-1].track_id

        for idx, spec in enumerate(self._channel_specs):
            track = self._tracks.get(spec.track_id)
            if track is None:
                track = PyQtGraphChannelTrack(spec, enable_opengl=self._enable_opengl)
            else:
                track.spec = spec
            track.height_ratio = spec.height_ratio

            # Initialize visibility flag default if unseen
            self._channel_visible.setdefault(spec.track_id, True)

            # Add to layout with stretch factor based on height ratio
            stretch = max(int(spec.height_ratio * 100), 1)
            self.layout.addWidget(track.widget, stretch)

            new_tracks[spec.track_id] = track

            plot_item = track.view.get_widget().getPlotItem()
            plot_items.append(plot_item)

            if primary_plot_item is None:
                primary_plot_item = plot_item
                primary_track = track
            else:
                # Link X-axis to the primary plot item to avoid manual range writes
                plot_item.setXLink(primary_plot_item)

            # Configure X-axis visibility: only show labels on the bottom-visible track
            is_bottom_track = spec.track_id == bottom_visible_id
            self._configure_bottom_axis(plot_item, is_bottom_track=is_bottom_track)

            # Add subtle border around each plot's ViewBox for visual separation
            view_box = plot_item.getViewBox()
            view_box.setBorder(self._lane_border_pen)

            # Ensure Y-axes are aligned by setting consistent width
            left_axis = plot_item.getAxis("left")
            left_axis.setWidth(80)  # Fixed width for alignment

            axes_wrapper = track.ax
            if hasattr(axes_wrapper, "set_grid_callback"):
                axes_wrapper.set_grid_callback(self._handle_axis_grid_request)

            # Apply model if already set
            if self._model is not None:
                track.set_model(self._model)

            # Link strip X-axis to first track
            if idx == 0 and self._event_strip_track is not None:
                self._event_strip_track.plot_item.setXLink(plot_item)

            # Apply events if already set
            if self._event_times:
                track.set_events(
                    self._event_times,
                    self._event_colors,
                    self._event_labels,
                    label_meta=self._event_label_meta,
                )

            # Apply stored visibility state for this track
            track.set_visible(self.is_channel_visible(spec.track_id))

            self._connect_track_signals(track, bind_range=False)

            if self._click_handler is not None:
                track.set_click_handler(
                    lambda x, y, button, _mode, ev, tid=spec.track_id: self._emit_click(
                        tid, x, y, button, ev
                    )
                )

        self._tracks = new_tracks

        # Prune visibility flags for channels that no longer exist
        for key in list(self._channel_visible.keys()):
            if key not in self._tracks:
                self._channel_visible.pop(key, None)

            # Connect signals for synchronized interactions
            self._connect_track_signals(track, bind_range=False)
            is_top_track = idx == 0
            self._configure_track_defaults(track, is_top_track=is_top_track)

        # Set row spacing between tracks for visual separation
        # Note: QVBoxLayout spacing is set in __init__, but we can adjust per-item spacing
        self.layout.setSpacing(5)  # 5px spacing between tracks

        # Sync overlays with new tracks
        self._time_cursor_overlay.sync_tracks(plot_items)
        self._event_highlight_overlay.sync_tracks(plot_items)
        self._apply_grid_to_all_tracks()

        # Only listen to range changes from the primary plot to avoid feedback loops.
        for track in self._tracks.values():
            plot_item = track.view.get_widget().getPlotItem()
            with contextlib.suppress(Exception):
                plot_item.sigRangeChanged.disconnect(self._on_track_range_changed)
            setattr(track, "_range_bound", False)
        if primary_track is not None:
            self._connect_track_signals(primary_track, bind_range=True)

        # Update window if already set
        if self._current_window is not None:
            x0, x1 = self._current_window
            self.set_time_window(x0, x1)
        # Reapply the stored mouse mode (pan vs box zoom) to all tracks
        self.set_mouse_mode(self._mouse_mode)
        self._current_layout_signature = self._layout_signature(self._channel_specs)

    def _connect_track_signals(
        self, track: PyQtGraphChannelTrack, *, bind_range: bool = True
    ) -> None:
        """Connect track signals for synchronized pan/zoom."""
        if bind_range and not getattr(track, "_range_bound", False):
            plot_item = track.view.get_widget().getPlotItem()
            plot_item.sigRangeChanged.connect(self._on_track_range_changed)
            setattr(track, "_range_bound", True)
        self._bind_interaction_signals(track)

    def _bind_interaction_signals(self, track: PyQtGraphChannelTrack) -> None:
        """Hook raw Qt/PyQtGraph signals for interaction dispatch."""
        if getattr(track, "_interaction_bound", False):
            return

        widget = track.view.get_widget()
        scene = widget.scene()
        view_box = track.view.view_box()

        if scene is not None:
            scene.sigMouseMoved.connect(
                lambda pos, t=track: self._handle_track_mouse_moved(t, pos)
            )
        if hasattr(view_box, "sigMousePressEvent"):
            view_box.sigMousePressEvent.connect(
                lambda ev, t=track: self._handle_track_mouse_pressed(t, ev)
            )
        if hasattr(view_box, "sigMouseReleaseEvent"):
            view_box.sigMouseReleaseEvent.connect(
                lambda ev, t=track: self._handle_track_mouse_released(t, ev)
            )

        setattr(track, "_interaction_bound", True)

    def _handle_track_mouse_moved(self, track: PyQtGraphChannelTrack, scene_pos: QPointF) -> None:
        ctx = self._build_move_context(track, scene_pos)
        if ctx is None:
            return
        self._dispatch_move(ctx)

    def _handle_track_mouse_pressed(self, track: PyQtGraphChannelTrack, event) -> None:
        ctx = self._build_click_context(track, event, pressed=True)
        if ctx is None:
            return
        self._dispatch_click(ctx)

    def _handle_track_mouse_released(self, track: PyQtGraphChannelTrack, event) -> None:
        ctx = self._build_click_context(track, event, pressed=False)
        if ctx is None:
            return
        self._dispatch_click(ctx)

    def _handle_wheel_event(self, track: PyQtGraphChannelTrack, event) -> None:
        ctx = self._build_scroll_context(track, event)
        if ctx is None:
            return
        self._dispatch_scroll(ctx)

    def _build_move_context(
        self, track: PyQtGraphChannelTrack, scene_pos: QPointF
    ) -> MoveContext | None:
        if not self._point_in_track(track, scene_pos):
            return None
        data_pos = self._map_scene_to_data(track, scene_pos)
        if data_pos is None:
            return None
        ctx = MoveContext(
            x_data=data_pos.x(),
            y_data=data_pos.y(),
            track_id=track.id,
        )
        ctx.x_px = float(scene_pos.x())  # type: ignore[attr-defined]
        ctx.y_px = float(scene_pos.y())  # type: ignore[attr-defined]
        ctx.buttons = QApplication.mouseButtons()  # type: ignore[attr-defined]
        return ctx

    def _build_click_context(
        self, track: PyQtGraphChannelTrack, event, *, pressed: bool
    ) -> ClickContext | None:
        try:
            scene_pos = event.scenePos()
        except Exception:
            return None
        if not self._point_in_track(track, scene_pos):
            return None
        data_pos = self._map_scene_to_data(track, scene_pos)
        if data_pos is None:
            return None
        button = self._button_name_from_qt(getattr(event, "button", lambda: None)())
        ctx = ClickContext(
            x_data=data_pos.x(),
            y_data=data_pos.y(),
            button=button,
            modifiers=self._modifiers_from_event(event),
            track_id=track.id,
            in_gutter=self._is_in_gutter(track, scene_pos),
            double=bool(getattr(event, "double", lambda: False)()),
        )
        ctx.x_px = float(scene_pos.x())  # type: ignore[attr-defined]
        ctx.y_px = float(scene_pos.y())  # type: ignore[attr-defined]
        ctx.pressed = bool(pressed)  # type: ignore[attr-defined]
        try:
            ctx.buttons = event.buttons()  # type: ignore[attr-defined]
        except Exception:
            ctx.buttons = None  # type: ignore[attr-defined]
        return ctx

    def _build_scroll_context(
        self, track: PyQtGraphChannelTrack, event
    ) -> ScrollContext | None:
        try:
            scene_pos = event.scenePos()
        except Exception:
            return None
        if not self._point_in_track(track, scene_pos):
            return None
        data_pos = self._map_scene_to_data(track, scene_pos)
        if data_pos is None:
            return None
        angle_delta = None
        if hasattr(event, "angleDelta"):
            try:
                angle_delta = event.angleDelta().y()
            except Exception:
                angle_delta = None
        if angle_delta is None and hasattr(event, "delta"):
            try:
                angle_delta = event.delta()
            except Exception:
                angle_delta = None
        if angle_delta is None:
            angle_delta = 0

        ctx = ScrollContext(
            x_data=data_pos.x(),
            y_data=data_pos.y(),
            delta_y=float(angle_delta),
            track_id=track.id,
            modifiers=self._modifiers_from_event(event),
        )
        ctx.x_px = float(scene_pos.x())  # type: ignore[attr-defined]
        ctx.y_px = float(scene_pos.y())  # type: ignore[attr-defined]
        return ctx

    def _dispatch_click(self, ctx: ClickContext) -> None:
        for handler in list(self._click_handlers):
            try:
                handler(ctx)
            except Exception:
                continue

    def _dispatch_move(self, ctx: MoveContext) -> None:
        for handler in list(self._move_handlers):
            try:
                handler(ctx)
            except Exception:
                continue

    def _dispatch_scroll(self, ctx: ScrollContext) -> None:
        for handler in list(self._scroll_handlers):
            try:
                handler(ctx)
            except Exception:
                continue

    def _map_scene_to_data(self, track: PyQtGraphChannelTrack, scene_pos: QPointF):
        view_box = track.view.view_box()
        if view_box is None:
            return None
        try:
            return view_box.mapSceneToView(scene_pos)
        except Exception:
            return None

    def _point_in_track(self, track: PyQtGraphChannelTrack, scene_pos: QPointF) -> bool:
        view_box = track.view.view_box()
        if view_box is None:
            return False
        try:
            rect = view_box.sceneBoundingRect()
        except Exception:
            return False
        return rect.contains(scene_pos)

    def _is_in_gutter(self, track: PyQtGraphChannelTrack, scene_pos: QPointF) -> bool:
        view_box = track.view.view_box()
        if view_box is None:
            return False
        try:
            rect = view_box.sceneBoundingRect()
        except Exception:
            return False
        margin_px = 18.0
        left = float(rect.left())
        right = float(rect.right())
        x_coord = float(scene_pos.x())
        return (x_coord < left + margin_px) or (x_coord > right - margin_px)

    def _modifiers_from_event(self, event) -> set[str]:
        mods: set[str] = set()
        try:
            qt_mods = event.modifiers()
        except Exception:
            qt_mods = None
        if qt_mods is None:
            return mods
        if qt_mods & Qt.ShiftModifier:
            mods.add("shift")
        if qt_mods & Qt.ControlModifier:
            mods.add("control")
        if qt_mods & Qt.AltModifier:
            mods.add("alt")
        if qt_mods & Qt.MetaModifier:
            mods.add("meta")
        return mods

    def _button_name_from_qt(self, button: Qt.MouseButton) -> str:
        if button == Qt.LeftButton:
            return "left"
        if button == Qt.MiddleButton:
            return "middle"
        if button == Qt.RightButton:
            return "right"
        return str(button)


    def _configure_track_defaults(
        self, track: PyQtGraphChannelTrack, is_top_track: bool = False
    ) -> None:
        track.view.enable_hover_tooltip(
            self._hover_tooltip_enabled, precision=self._hover_tooltip_precision
        )
        # Only enable per-track labels when strip is absent
        enable_labels = (
            self._event_labels_enabled and is_top_track and self._event_strip_track is None
        )
        # Fill in safe defaults without clobbering any user-provided settings
        options = self._event_label_options
        if getattr(options, "mode", None) is None:
            options.mode = "h_belt"
        if getattr(options, "show_numbers_only", None) is None:
            options.show_numbers_only = True
        track.view.enable_event_labels(
            enable_labels,
            options=options if enable_labels else None,
        )
        if track.primary_line:
            track.set_line_width(self._default_line_width)
        self._apply_axis_font_to_track(track)

    def _configure_bottom_axis(
        self,
        plot_item: pg.PlotItem,
        *,
        is_bottom_track: bool,
    ) -> None:
        """Ensure only the bottom track shows X-axis labels/ticks."""
        bottom_axis = plot_item.getAxis("bottom")
        if bottom_axis is None:
            return
        plot_item.showAxis("bottom")
        with contextlib.suppress(AttributeError):
            bottom_axis.enableAutoSIPrefix(False)
        bottom_axis.setVisible(True)
        if is_bottom_track:
            bottom_axis.setStyle(showValues=True)
            bottom_axis.setLabel("Time (s)")
            with contextlib.suppress(AttributeError):
                bottom_axis.setTickLength(5, 0)
            bottom_axis.setHeight(None)
            with contextlib.suppress(AttributeError):
                bottom_axis.label.show()
                bottom_axis.showLabel(True)
        else:
            bottom_axis.setStyle(showValues=False, tickLength=0)
            bottom_axis.setLabel("")
            bottom_axis.setHeight(12)
            with contextlib.suppress(AttributeError):
                bottom_axis.label.hide()
                bottom_axis.showLabel(False)

    def _update_bottom_axis_assignments(self) -> None:
        """Reapply bottom X-axis ownership based on current visibility.

        Ensures that the lowest visible channel track owns the X-axis labels.
        If no tracks are currently visible, falls back to the last spec so that
        styling stays consistent once a track is shown again.
        """

        if not self._tracks or not self._channel_specs:
            return

        visible_ids = []
        for spec in self._channel_specs:
            track = self._tracks.get(spec.track_id)
            if track is None:
                continue
            try:
                is_visible = track.is_visible()
            except Exception:
                is_visible = self.is_channel_visible(spec.track_id)
            if is_visible:
                visible_ids.append(spec.track_id)
        if visible_ids:
            bottom_visible_id = visible_ids[-1]
        else:
            # If nothing is marked visible, pick the last existing track so the X-axis is still shown.
            bottom_visible_id = next(
                (
                    spec.track_id
                    for spec in reversed(self._channel_specs)
                    if spec.track_id in self._tracks
                ),
                None,
            )
            if bottom_visible_id is None:
                return

        # Store as single source of truth for bottom track
        self._bottom_visible_track_id = bottom_visible_id

        for spec in self._channel_specs:
            track = self._tracks.get(spec.track_id)
            if track is None:
                continue
            plot_item = track.view.get_widget().getPlotItem()
            self._configure_bottom_axis(
                plot_item,
                is_bottom_track=(spec.track_id == bottom_visible_id),
            )

    def refresh_axes_and_fonts(self, *, reason: str = "") -> None:
        """Reapply bottom-axis ownership and axis fonts after layout/theme changes.

        This ensures axis labels, fonts, and tick styling stay consistent when:
        - Window is resized
        - Track visibility changes
        - Theme changes
        - Font settings change
        - Layout reflows (splitter, event strip, etc.)

        Args:
            reason: Optional debug label for why refresh was triggered
        """
        if not self._tracks:
            return

        # Update bottom-visible tracking (single source of truth)
        self._update_bottom_axis_assignments()

        # Reapply fonts based on current geometry
        for track in self._tracks.values():
            self._apply_axis_font_to_track(track)

    def _apply_event_label_options(self) -> None:
        if not self._tracks:
            return
        # Ensure defaults are present unless explicitly set by user/settings
        if getattr(self._event_label_options, "mode", None) is None:
            self._event_label_options.mode = "h_belt"
        if getattr(self._event_label_options, "show_numbers_only", None) is None:
            self._event_label_options.show_numbers_only = True
        ordered_tracks = [
            self._tracks[spec.track_id]
            for spec in self._channel_specs
            if spec.track_id in self._tracks
        ] or list(self._tracks.values())
        label_track: PyQtGraphChannelTrack | None = None
        for track in ordered_tracks:
            if getattr(track, "is_visible", lambda: True)():
                label_track = track
                break
        if label_track is None and ordered_tracks:
            label_track = ordered_tracks[0]
        for track in ordered_tracks:
            enable = (
                self._event_strip_track is None
                and self._event_labels_enabled
                and track is label_track
            )
            track.view.enable_event_labels(
                enable,
                options=self._event_label_options if enable else None,
            )
        if self._event_strip_track is not None and self._event_strip_widget is not None:
            if self._event_labels_enabled:
                self._event_strip_widget.setMaximumHeight(40)
                self._event_strip_widget.setVisible(True)
                self._event_strip_track.set_visible(True)
                if self._event_entries:
                    self._event_strip_track.set_events(
                        self._event_entries, self._event_label_options
                    )
            else:
                self._event_strip_widget.setMaximumHeight(0)
                self._event_strip_widget.setVisible(False)
                self._event_strip_track.set_visible(False)

    def _apply_tooltip_settings(self) -> None:
        for track in self._tracks.values():
            track.view.enable_hover_tooltip(
                self._hover_tooltip_enabled, precision=self._hover_tooltip_precision
            )

    def _apply_grid_to_all_tracks(
        self,
        *,
        x_enabled: bool | None = None,
        y_enabled: bool | None = None,
        alpha: float | None = None,
    ) -> None:
        """Apply the current grid visibility/settings to every track."""
        if x_enabled is not None:
            self._x_grid_visible = bool(x_enabled)
        if y_enabled is not None:
            self._y_grid_visible = bool(y_enabled)
        if alpha is not None:
            self._grid_alpha = max(0.0, min(float(alpha), 1.0))

        tracks = self.all_tracks()
        if not tracks:
            return

        last_index = len(tracks) - 1
        for idx, track in enumerate(tracks):
            plot_item = track.view.get_widget().getPlotItem()
            plot_item.showGrid(
                x=self._x_grid_visible,
                y=self._y_grid_visible,
                alpha=self._grid_alpha,
            )
            self._configure_bottom_axis(plot_item, is_bottom_track=(idx == last_index))

    def _handle_axis_grid_request(self, visible: bool) -> None:
        """Normalize grid toggles triggered through matplotlib-compatible axes."""
        desired = bool(visible)
        if desired == self._x_grid_visible and desired == self._y_grid_visible:
            return
        self.set_grid_visible(desired)

    def set_axis_font(self, *, family: str | None = None, size: float | None = None) -> None:
        changed = False
        if family and family != self._axis_font_family:
            self._axis_font_family = str(family)
            changed = True
        if size is not None and float(size) != self._axis_font_size:
            self._axis_font_size = float(size)
            changed = True
        if changed:
            self.refresh_axes_and_fonts(reason="axis-font-changed")

    def axis_font(self) -> tuple[str, float]:
        return self._axis_font_family, self._axis_font_size

    def set_tick_font_size(self, size: float) -> None:
        value = float(size)
        if value == self._tick_font_size:
            return
        self._tick_font_size = value
        self.refresh_axes_and_fonts(reason="tick-font-changed")

    def tick_font_size(self) -> float:
        return self._tick_font_size

    def set_grid_visible(self, enabled: bool, *, alpha: float | None = None) -> None:
        """Show/hide the shared grid across all tracks."""
        self._apply_grid_to_all_tracks(x_enabled=enabled, y_enabled=enabled, alpha=alpha)

    def grid_visible(self) -> bool:
        """Return whether the shared grid is currently visible."""
        return self._x_grid_visible

    def grid_state(self) -> tuple[bool, bool, float]:
        """Return current grid visibility flags and alpha."""
        return self._x_grid_visible, self._y_grid_visible, self._grid_alpha

    def set_window_background_color(self, color: tuple[int, int, int]) -> None:
        if color is None:
            self._window_bg_color = None
            return
        r, g, b = (int(c) for c in color)
        self._window_bg_color = (r, g, b)
        self._widget.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")

    def window_background_color(self) -> tuple[int, int, int] | None:
        return self._window_bg_color

    def set_plot_background_color(self, color: tuple[int, int, int]) -> None:
        if color is None:
            self._plot_bg_color = None
            return
        r, g, b = (int(c) for c in color)
        self._plot_bg_color = (r, g, b)
        for track in self._tracks.values():
            plot_widget = track.view.get_widget()
            plot_widget.setBackground(self._plot_bg_color)

    def plot_background_color(self) -> tuple[int, int, int] | None:
        return self._plot_bg_color

    def set_default_line_width(self, width: float) -> None:
        value = float(width)
        if value == self._default_line_width:
            return
        self._default_line_width = value
        for track in self._tracks.values():
            track.set_line_width(self._default_line_width)

    def _count_visible_tracks(self) -> int:
        """Count currently visible channel tracks."""
        count = 0
        for spec in self._channel_specs:
            track = self._tracks.get(spec.track_id)
            if track is not None and track.is_visible():
                count += 1
        return count

    def _estimate_track_height(self, track: PyQtGraphChannelTrack) -> float:
        """Approximate the pixel height of a track widget."""

        # First try the real widget height if available
        try:
            widget = track.view.get_widget()
            actual_height = float(widget.height())
            if actual_height > 0:
                return actual_height
        except Exception:
            pass

        # Fallback: estimate using layout geometry and height ratios
        container_height = float(max(self._widget.height(), self.layout.geometry().height(), 1))
        visible_specs = [
            spec for spec in self._channel_specs if self.is_channel_visible(spec.track_id)
        ]
        total_ratio = float(sum(max(spec.height_ratio, 0.05) for spec in visible_specs) or 1.0)
        track_spec = getattr(track, "spec", None)
        ratio = max(float(getattr(track_spec, "height_ratio", 1.0)), 0.05)
        spacing = float(max(self.layout.spacing(), 0))
        gap_per_track = spacing * max(len(visible_specs) - 1, 0) / max(len(visible_specs), 1)
        estimated = container_height * (ratio / total_ratio) - gap_per_track
        return max(1.0, estimated)

    def _recenter_axis_label(self, axis, track_height: float) -> None:
        """Position the axis label so it remains vertically centered within the track."""
        if axis is None or not hasattr(axis, "label"):
            return
        try:
            label = axis.label
            br = label.boundingRect()
            height = track_height if track_height > 0 else float(axis.size().height())
            nudge = 5
            y = height / 2.0 + br.width() / 2.0
            if getattr(axis, "orientation", "") == "left":
                x = -nudge
            elif getattr(axis, "orientation", "") == "right":
                x = float(axis.size().width()) - br.height() + nudge
            else:
                return
            label.setPos(x, y)
            axis.picture = None
        except Exception:
            with contextlib.suppress(Exception):
                axis.resizeEvent()

    def _recenter_bottom_label(self, axis) -> None:
        """Center the bottom axis label horizontally."""
        if axis is None or not hasattr(axis, "label"):
            return
        try:
            label = axis.label
            br = label.boundingRect()
            width = float(axis.size().width())
            height = float(axis.size().height())
            nudge = 5
            x = width / 2.0 - br.width() / 2.0
            y = height - br.height() + nudge
            label.setPos(x, y)
            axis.picture = None
        except Exception:
            with contextlib.suppress(Exception):
                axis.resizeEvent()

    def _apply_axis_font_to_track(self, track: PyQtGraphChannelTrack) -> None:
        plot_item = track.view.get_widget().getPlotItem()

        height_px = self._estimate_track_height(track)

        # Scale fonts to the available track height; clamp to readable bounds
        def _clamp(value: float, lo: int, hi: int) -> int:
            return int(max(lo, min(hi, round(value))))

        tick_size = _clamp(height_px * 0.045, 10, 18)
        ylabel_size = _clamp(height_px * 0.06, 12, 28)
        xlabel_size = int(self._axis_font_size)  # Keep x-axis title a steady, readable size

        ylabel_font = QFont(self._axis_font_family, ylabel_size)
        xlabel_font = QFont(self._axis_font_family, xlabel_size)
        tick_font = QFont(self._axis_font_family, tick_size)

        left_axis = plot_item.getAxis("left")
        left_axis.label.setFont(ylabel_font)
        with contextlib.suppress(AttributeError):
            left_axis.setTickFont(tick_font)
            left_axis.setTickLength(5, 0)
        self._recenter_axis_label(left_axis, height_px)

        # Use cached bottom track ID (single source of truth)
        bottom_visible_id = self._bottom_visible_track_id or track.id
        is_bottom = track.id == bottom_visible_id
        if is_bottom:
            bottom_axis = plot_item.getAxis("bottom")
            bottom_axis.label.setFont(xlabel_font)
            with contextlib.suppress(AttributeError):
                bottom_axis.setTickFont(tick_font)
            self._recenter_bottom_label(bottom_axis)

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

        # Update internal state only (avoid writing back the range here)
        self._current_window = (x0, x1)

        previous_flag = self._range_change_user_driven
        self._range_change_user_driven = True
        try:
            self._notify_time_window_changed()
        finally:
            self._range_change_user_driven = previous_flag
        self.debug_dump_state("range_changed")

    def set_model(self, model: TraceModel) -> None:
        """Set the trace data model for all tracks."""
        self._model = model
        self._data_t_min = None
        self._data_t_max = None

        for track in self._tracks.values():
            track.set_model(model)
        self._apply_grid_to_all_tracks()

        # Set initial window to full range
        if model is not None:
            x0, x1 = model.full_range
            self._data_t_min = float(x0)
            self._data_t_max = float(x1)
            self.set_time_window(x0, x1)
        self.debug_dump_state("set_trace_model (after)")

    def set_time_window(self, x0: float, x1: float) -> None:
        """Set the visible time window for all tracks."""
        x0 = float(x0)
        x1 = float(x1)
        log.debug(
            "PyQtGraphPlotHost.set_time_window: requested=(%r, %r) data_span=(%r, %r)",
            x0,
            x1,
            self._data_t_min,
            self._data_t_max,
        )
        x0, x1 = self._clamp_time_window(x0, x1)
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

        previous_flag = self._range_change_user_driven
        self._range_change_user_driven = False
        try:
            self._notify_time_window_changed()
        finally:
            self._range_change_user_driven = previous_flag
        self.debug_dump_state("set_time_window (after)")
        self.log_data_and_view_ranges("time_window_changed")

    def _clamp_time_window(self, x0: float, x1: float) -> tuple[float, float]:
        """Clamp the requested window to known data bounds using public APIs."""
        if self._data_t_min is None or self._data_t_max is None:
            return x0, x1

        data_min = float(self._data_t_min)
        data_max = float(self._data_t_max)
        data_span = data_max - data_min
        if data_span <= 0:
            return x0, x1

        span = max(float(x1 - x0), self._min_window_span)
        # If requested span exceeds data span, snap to full data.
        if span >= data_span:
            return data_min, data_max

        if x0 < data_min:
            x0 = data_min
            x1 = x0 + span
        if x1 > data_max:
            x1 = data_max
            x0 = x1 - span
        return x0, x1

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

        entries: list[EventEntryV3] = []
        for idx, t in enumerate(self._event_times):
            text = ""
            if self._event_labels and idx < len(self._event_labels):
                text = self._event_labels[idx]
            if not text:
                text = str(idx + 1)
            meta_payload = {}
            if self._event_label_meta and idx < len(self._event_label_meta):
                candidate = self._event_label_meta[idx]
                if isinstance(candidate, dict):
                    meta_payload.update(candidate)
            if colors and idx < len(colors):
                meta_payload.setdefault("color", colors[idx])
            entries.append(
                EventEntryV3(
                    t=float(t),
                    text=str(text),
                    meta=meta_payload,
                    index=idx + 1,
                )
            )
        self._event_entries = entries

        for track in self._tracks.values():
            track.set_events(times, colors, labels, label_meta=self._event_label_meta)
        if self._event_strip_track is not None and self._event_strip_widget is not None:
            if self._event_labels_enabled:
                self._event_strip_widget.setMaximumHeight(40)
                self._event_strip_widget.setVisible(True)
                self._event_strip_track.set_visible(True)
                self._event_strip_track.set_events(entries, self._event_label_options)
            else:
                self._event_strip_widget.setMaximumHeight(0)
                self._event_strip_widget.setVisible(False)
                self._event_strip_track.set_visible(False)
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
        return self._widget

    def widget(self) -> QWidget:
        """Alias for embedding compatibility."""
        return self._widget

    def get_render_backend(self) -> str:
        """Get the rendering backend identifier."""
        return "pyqtgraph"

    def redraw(self) -> None:
        """Request a repaint of the root widget."""
        with contextlib.suppress(Exception):
            self._widget.update()

    def is_user_range_change_active(self) -> bool:
        """Return True if the latest time-window update originated from user input."""
        return bool(self._range_change_user_driven)

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
            self._widget.setStyleSheet(f"background-color: {bg};")

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

    def get_trace_view_range(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return current (x_range, y_range) from the primary track view."""
        if not self._channel_specs:
            return None
        first_id = self._channel_specs[0].track_id
        track = self._tracks.get(first_id)
        if track is None:
            return None
        try:
            plot_item = track.view.get_widget().getPlotItem()
            x_range, y_range = plot_item.viewRange()
            x_tuple = (float(x_range[0]), float(x_range[1]))
            y_tuple = (float(y_range[0]), float(y_range[1]))
            log.debug("PyQtGraphPlotHost.get_trace_view_range x=%s y=%s", x_tuple, y_tuple)
            return x_tuple, y_tuple
        except Exception:
            log.exception("Failed to fetch trace view range from PyQtGraphPlotHost")
            return None

    def set_trace_model(self, model: TraceModel) -> None:
        """Set trace model (matplotlib PlotHost compatibility - alias for set_model)."""
        self.set_model(model)
        self.debug_dump_state("set_trace_model (alias)")

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

    def set_mouse_mode(self, mode: str = "pan") -> None:
        """Set interaction mode for all track ViewBoxes (pan or rectangle zoom)."""
        normalized = "rect" if str(mode).lower() == "rect" else "pan"
        self._mouse_mode = normalized
        for track in self._tracks.values():
            try:
                track.view.set_mouse_mode(normalized)
            except Exception:
                log.debug("Failed to set mouse mode on track %s", track.id, exc_info=True)

    def mouse_mode(self) -> str:
        """Return current interaction mode ("pan" or "rect")."""
        return getattr(self, "_mouse_mode", "pan")

    def _primary_plot_item(self) -> pg.PlotItem | None:
        """Return the first track's PlotItem."""
        if not self._channel_specs:
            return None
        first_id = self._channel_specs[0].track_id
        track = self._tracks.get(first_id)
        return None if track is None else track.view.get_widget().getPlotItem()

    def set_range_selection_visible(self, visible: bool, *, default_span: float = 5.0) -> None:
        """Show or hide a movable X-range selector on the primary track."""
        if not visible:
            self.clear_range_selection()
            return

        plot_item = self._primary_plot_item()
        if plot_item is None:
            return

        if self._selection_region is None:
            window = self.current_window() or self.full_range()
            if window is None:
                window = (0.0, default_span)
            x0, x1 = window
            if x1 <= x0:
                x1 = x0 + default_span
            region = pg.LinearRegionItem(
                values=(x0, x1),
                orientation=pg.LinearRegionItem.Vertical,
                movable=True,
            )
            region.setZValue(5)
            region.setBrush(pg.mkBrush(0, 0, 0, 30))
            region.sigRegionChanged.connect(self._on_selection_region_changed)
            self._selection_region = region
            plot_item.addItem(region)
        else:
            with contextlib.suppress(Exception):
                self._selection_region.setVisible(True)

    def _on_selection_region_changed(self) -> None:
        """Normalize region bounds on change."""
        region = self._selection_region
        if region is None:
            return
        try:
            x0, x1 = region.getRegion()
        except Exception:
            return
        if x1 < x0:
            region.setRegion((x1, x0))

    def selected_range(self) -> tuple[float, float] | None:
        """Return the currently selected X-range, if any."""
        if self._selection_region is None:
            return None
        try:
            x0, x1 = self._selection_region.getRegion()
            return float(min(x0, x1)), float(max(x0, x1))
        except Exception:
            return None

    def set_selection_range(self, x0: float, x1: float) -> None:
        """Programmatically set the selection range."""
        plot_item = self._primary_plot_item()
        if plot_item is None:
            return
        if self._selection_region is None:
            self.set_range_selection_visible(True, default_span=abs(x1 - x0) or 1.0)
        region = self._selection_region
        if region is None:
            return
        try:
            region.setRegion((float(x0), float(x1)))
        except Exception:
            log.debug("Failed to set selection region", exc_info=True)

    def clear_range_selection(self) -> None:
        """Remove the selection region if present."""
        if self._selection_region is None:
            return
        try:
            if self._selection_region.scene() is not None:
                self._selection_region.scene().removeItem(self._selection_region)
        except Exception:
            log.debug("Failed to remove selection region", exc_info=True)
        self._selection_region = None

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
        self.debug_dump_state(f"set_autoscale_y_enabled (request={enabled})")
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

    def event_labels_visible(self) -> bool:
        """Return whether event labels are currently enabled."""
        return bool(self._event_labels_enabled)

    def event_label_options(self) -> LayoutOptionsV3:
        """Return current event label layout options."""
        return self._event_label_options

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
        self._current_layout_signature = None
        self.clear_range_selection()

    def tracks(self) -> tuple[PyQtGraphChannelTrack, ...]:
        """Get all tracks as an immutable tuple."""
        return tuple(self._tracks.values())

    def iter_tracks(self):
        """Yield tracks without exposing the internal mapping."""
        return iter(self._tracks.values())

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

    def _emit_click(self, track_id: str, x: float, y: float, button: int, event: Any) -> None:
        handler = self._click_handler
        if callable(handler):
            try:
                handler(track_id, x, y, button, event)
            except Exception:
                log.debug("Click handler failed for track %s", track_id, exc_info=True)

    def zoom_at(self, center: float, factor: float) -> None:
        """Zoom X-axis around current view center using viewRange() + setXRange().

        This is the canonical approach per PyQtGraph docs: read current range
        with viewRange(), calculate new range, then apply with setXRange().

        Args:
            center: Center point (unused - zoom is always around current center)
            factor: Scale factor where:
                - factor < 1.0 zooms in (e.g., 0.5 = 2x zoom in)
                - factor > 1.0 zooms out (e.g., 2.0 = 2x zoom out)
        """
        if not self._tracks:
            return

        # Get current X range from the first (primary) track using viewRange()
        first_track = next(iter(self._tracks.values()))
        plot_item = first_track.view.get_widget().getPlotItem()
        view_box = plot_item.getViewBox()
        (x_min, x_max), _ = view_box.viewRange()

        # Calculate new X range: zoom around the current center
        x_center = 0.5 * (x_min + x_max)
        half_span = 0.5 * (x_max - x_min) * factor
        new_x_min = x_center - half_span
        new_x_max = x_center + half_span

        # Apply new X range to the primary ViewBox using setXRange()
        # X-links will propagate this to all other tracks automatically
        view_box.setXRange(new_x_min, new_x_max, padding=0.0)

        # Update internal state
        self._current_window = (new_x_min, new_x_max)

        # Notify listeners about the window change
        self._notify_time_window_changed()

    def scroll_by(self, delta: float) -> None:
        """Scroll the current time window by delta seconds."""
        if self._current_window is None:
            return
        x0, x1 = self._current_window
        self.set_time_window(x0 + delta, x1 + delta)

    def center_on_time(self, time_value: float) -> None:
        """Recenter the current window around ``time_value`` without changing span."""
        # Determine current span
        window = self.current_window()
        if window is None:
            window = self.full_range()
        full_range = self.full_range()
        if window is None or full_range is None:
            return

        x0, x1 = window
        span = x1 - x0
        fr_min, fr_max = full_range
        fr_span = fr_max - fr_min
        if fr_span <= 0:
            return
        if span <= 0:
            span = fr_span

        half = span / 2.0
        new_start = time_value - half
        new_end = time_value + half

        if span >= fr_span:
            new_start, new_end = fr_min, fr_max
        else:
            if new_start < fr_min:
                new_start = fr_min
                new_end = fr_min + span
            elif new_end > fr_max:
                new_end = fr_max
                new_start = fr_max - span

        self.set_time_window(new_start, new_end)

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
        return bool(getattr(self, "_hover_tooltip_enabled", True))

    def tooltip_proximity(self) -> int:
        """Get tooltip proximity in pixels."""
        return int(getattr(self, "_tooltip_proximity", 10))

    def tooltip_precision(self) -> int:
        """Get tooltip precision in decimals."""
        return int(getattr(self, "_hover_tooltip_precision", 3))

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


class _ResizeEventFilter(QObject):
    """Event filter to refresh axes/fonts when plot host widget is resized.

    This ensures that axis labels, fonts, and tick styling stay consistent
    when the window is resized, the splitter is adjusted, or the layout reflows.
    """

    def __init__(self, plot_host: PyQtGraphPlotHost) -> None:
        """Initialize resize event filter.

        Args:
            plot_host: The plot host to refresh when resize occurs
        """
        super().__init__()
        self._plot_host = plot_host
        self._pending_refresh = False

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API uses camelCase
        """Filter resize events and schedule axis/font refresh."""
        if event.type() == QEvent.Resize:
            # Schedule refresh after layout has stabilized
            # Use QTimer.singleShot(0, ...) to ensure refresh happens after
            # Qt has updated widget geometry and layout metrics
            if not self._pending_refresh:
                self._pending_refresh = True
                QTimer.singleShot(0, self._do_refresh)
        return False  # Don't block the event

    def _do_refresh(self) -> None:
        """Execute the deferred refresh."""
        self._pending_refresh = False
        if self._plot_host is not None:
            with contextlib.suppress(Exception):
                self._plot_host.refresh_axes_and_fonts(reason="resize")
