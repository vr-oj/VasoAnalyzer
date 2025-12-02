"""Core orchestration for stacked trace plotting."""

from __future__ import annotations

import contextlib
import math
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from matplotlib.axes import Axes
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.text import Annotation, Text
from PyQt5.QtCore import QTimer

from vasoanalyzer.app.flags import is_enabled
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.event_labels import EventLabeler, LayoutOptions
from vasoanalyzer.ui.event_labels_v3 import (
    EventEntryV3,
    EventLabelerV3,
    LayoutOptionsV3,
)
from vasoanalyzer.ui.plots.channel_track import ChannelTrack, ChannelTrackSpec
from vasoanalyzer.ui.plots.gesture_canvas import GestureCanvas
from vasoanalyzer.ui.plots.overlays import (
    AnnotationLane,
    AnnotationSpec,
    EventHighlightOverlay,
    TimeCursorOverlay,
)
from vasoanalyzer.ui.simple_epoch_renderer import SimpleEpoch, SimpleEpochRenderer
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["LayoutState", "PlotHost"]


@dataclass
class LayoutState:
    """Serializable layout snapshot."""

    order: list[str]
    height_ratios: dict[str, float]
    visibility: dict[str, bool]


class PlotHost:
    """Host figure with stacked channel tracks sharing a common time axis."""

    def __init__(self, *, dpi: int) -> None:
        self.figure = Figure(
            figsize=(8, 4),
            facecolor=CURRENT_THEME["window_bg"],
            dpi=dpi,
            constrained_layout=False,
        )
        self.canvas = GestureCanvas(self.figure)
        self.figure.subplots_adjust(left=0.12, right=0.96, top=0.96, bottom=0.12)
        self._channel_specs: list[ChannelTrackSpec] = []
        self._tracks: dict[str, ChannelTrack] = {}
        self._axes_map: dict[Axes, ChannelTrack] = {}
        self._model: TraceModel | None = None
        self._current_window: tuple[float, float] | None = None
        self._event_times: list[float] = []
        self._event_colors: list[str] | None = None
        self._event_labels: list[str] = []
        self._event_label_meta: list[dict[str, Any]] = []
        self._event_labeler: EventLabeler | None = None
        self._event_label_v2_artists: list[Any] = []
        self._use_track_event_lines: bool = True
        self._xlim_cid: int | None = None
        self._ylim_cid: int | None = None
        self._last_xlim: tuple[float, float] | None = None
        self._last_ylim: tuple[float, float] | None = None
        self._event_label_mode: str = "vertical"
        self._event_lines_visible: bool = True
        self._event_labels_visible: bool = False
        self._event_label_gap_px: int = 22
        self._feature_flags: dict[str, bool] = {
            "event_labels_v3": is_enabled("event_labels_v3", default=True)
        }
        self._event_helper_v3: EventLabelerV3 | None = None
        self._event_entries_v3: list[EventEntryV3] = []
        self._event_label_host_ax: Axes | None = None
        self._max_labels_per_cluster: int = 1
        self._cluster_style_policy: str = "first"
        self._event_label_lanes: int = 3
        self._belt_baseline_enabled: bool = True
        self._span_event_lines_across_siblings: bool = True
        self._auto_event_label_mode: bool = True
        self._density_threshold_compact: float = 0.8
        self._density_threshold_belt: float = 0.25
        self._label_outline_enabled: bool = True
        self._label_outline_width: float = 2.0
        self._label_outline_color: tuple[float, float, float, float] | None = (
            1.0,
            1.0,
            1.0,
            0.9,
        )
        self._label_tooltips_enabled: bool = True
        self._tooltip_proximity_px: int = 10
        self._compact_legend_enabled: bool = False
        self._compact_legend_location: str = "upper right"
        # Base event label style (applied to all labels before priority/category enhancements)
        self._event_font_family: str = "Arial"
        self._event_font_size: float = 15.0
        self._event_font_bold: bool = False
        self._event_font_italic: bool = False
        self._event_color: str = "#000000"
        self._cid_motion: int | None = None
        self._hover_annot: Annotation | None = None
        self._last_hover_text: Text | None = None
        self._annotation_lane = AnnotationLane()
        self._time_cursor_overlay = TimeCursorOverlay()
        self._event_highlight_overlay = EventHighlightOverlay()
        self._simple_epoch_renderer = SimpleEpochRenderer()
        self._simple_epochs: list[SimpleEpoch] = []
        self._simple_epochs_visible: bool = False
        self._annotation_entries: list[AnnotationSpec] = []
        self._event_highlight_alpha: float = self._event_highlight_overlay.alpha()
        self._event_highlight_color: str = CURRENT_THEME.get(
            "event_highlight",
            CURRENT_THEME.get("accent", "#1D5CFF"),
        )
        self._event_highlight_time: float | None = None
        self._event_highlight_visible: bool = False
        self._last_draw_ts: float = 0.0
        self._min_draw_interval: float = 1.0 / 60.0
        self._pending_draw_timer: QTimer | None = None
        self._batch_mode: bool = False
        self._batch_needs_draw: bool = False
        # Tooltip hover debouncing
        self._hover_debounce_timer: QTimer | None = None
        self._pending_hover_event = None

    def apply_theme(self) -> None:
        """Reapply theme colors to figure, axes, and overlays."""

        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text = CURRENT_THEME.get("text", "#000000")
        grid_color = CURRENT_THEME.get("grid_color", "#CCCCCC")

        self.figure.set_facecolor(bg)
        self.canvas.figure.set_facecolor(bg)

        for ax in self.axes():
            try:
                ax.set_facecolor(bg)
                ax.tick_params(colors=text)
                ax.yaxis.label.set_color(text)
                ax.xaxis.label.set_color(text)
                ax.title.set_color(text)
                grid_lines = list(ax.get_xgridlines()) + list(ax.get_ygridlines())
                if any(line.get_visible() for line in grid_lines):
                    ax.grid(True, color=grid_color)
            except Exception:
                continue

        # Refresh overlay styling without overriding user-configured colors
        self._event_highlight_overlay.set_style(
            color=self._event_highlight_color,
            alpha=self._event_highlight_alpha,
        )
        self._event_highlight_overlay.refresh()

        self.canvas.draw_idle()

    def add_channel(self, spec: ChannelTrackSpec) -> ChannelTrack:
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
            # Update stored specs (e.g., new height ratios) without rebuilding axes.
            self._channel_specs = desired
            for spec in desired:
                track = self._tracks.get(spec.track_id)
                if track:
                    track.height_ratio = spec.height_ratio
            return

        self._channel_specs = desired
        self._rebuild_tracks()

    def _rebuild_tracks(self) -> None:
        """Recreate axes and channel wrappers to match specs."""

        self._destroy_event_labeler()
        self.figure.clf()
        self.figure.subplots_adjust(left=0.12, right=0.96, top=0.96, bottom=0.12)
        self._tracks.clear()
        self._axes_map.clear()
        if not self._channel_specs:
            self._schedule_draw()
            return

        specs = self._channel_specs
        height_ratios: list[float] = [max(spec.height_ratio, 0.05) for spec in specs]
        row_count = len(height_ratios)
        # Eliminate gap between tracks for cleaner appearance - dividers provide separation
        hspace = 0.0
        gs = self.figure.add_gridspec(
            nrows=row_count,
            ncols=1,
            height_ratios=height_ratios,
            hspace=hspace,
        )

        shared_ax = None
        track_axes: list[tuple[Axes, str]] = []
        for index, spec in enumerate(specs):
            ax = self.figure.add_subplot(gs[index, 0], sharex=shared_ax)
            if shared_ax is None:
                shared_ax = ax
            else:
                ax.tick_params(labelbottom=False)
                ax.set_xlabel("")  # Clear xlabel for non-bottom tracks
            ax.tick_params(colors=CURRENT_THEME["text"])
            ax.yaxis.label.set_color(CURRENT_THEME["text"])
            ax.xaxis.label.set_color(CURRENT_THEME["text"])
            ax.title.set_color(CURRENT_THEME["text"])
            ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))

            # Configure tick label and axis title font sizes based on number of visible tracks
            # These sizes scale with available vertical space
            if row_count == 1:
                tick_fontsize = 14
                ylabel_fontsize = 24
            elif row_count == 2:
                tick_fontsize = 14
                ylabel_fontsize = 22
            elif row_count == 3:
                tick_fontsize = 14
                ylabel_fontsize = 20
            else:  # 4 or more tracks
                tick_fontsize = 14
                ylabel_fontsize = 16

            # Set tick label and Y-axis title font sizes
            ax.tick_params(labelsize=tick_fontsize)
            ax.yaxis.label.set_fontsize(ylabel_fontsize)

            spine_color = CURRENT_THEME.get(
                "border_soft", CURRENT_THEME.get("grid_color", "#CCCCCC")
            )
            for spine in ax.spines.values():
                spine.set_color(spine_color)
            track = ChannelTrack(spec, ax, self.canvas)
            self._tracks[spec.track_id] = track
            self._register_track_axes(track)
            track_axes.append((ax, spec.track_id))

        divider_color = CURRENT_THEME.get("text", "#000000")
        for (upper_ax, _), (lower_ax, _) in zip(track_axes, track_axes[1:], strict=False):
            upper_spine = upper_ax.spines["bottom"]
            upper_spine.set_visible(True)
            upper_spine.set_color(divider_color)
            upper_spine.set_linewidth(1.8)
            lower_ax.spines["top"].set_visible(False)

        if self._model is not None:
            for track in self._tracks.values():
                track.set_model(self._model)
                self._register_track_axes(track)
            if self._current_window is not None:
                x0, x1 = self._current_window
                self.set_time_window(x0, x1)
        self._time_cursor_overlay.sync_tracks(self._tracks.values())
        self._event_highlight_overlay.sync_tracks(self._tracks.values())
        if self._event_highlight_time is not None:
            self._event_highlight_overlay.set_time(self._event_highlight_time)
            self._event_highlight_overlay.set_visible(
                self._event_highlight_visible and self._event_highlight_time is not None
            )
        else:
            self._event_highlight_overlay.clear()
        self._push_events_to_tracks()
        self._rebuild_event_labeler()
        self._apply_shared_x_layout()
        bottom_ax = self.bottom_axis()
        self._annotation_lane.attach(bottom_ax)
        if self._annotation_entries:
            self._annotation_lane.set_entries(self._annotation_entries)
        else:
            self._annotation_lane.clear()
        self._schedule_draw()

    def set_trace_model(self, model: TraceModel) -> None:
        """Attach a shared TraceModel to all tracks."""

        self._model = model
        for track in self._tracks.values():
            track.set_model(model)
            self._register_track_axes(track)
        if self._current_window is None:
            self._current_window = model.full_range
        self.set_time_window(*self._current_window)
        self._time_cursor_overlay.sync_tracks(self._tracks.values())
        self._event_highlight_overlay.sync_tracks(self._tracks.values())
        if self._event_highlight_time is not None:
            self._event_highlight_overlay.set_time(self._event_highlight_time)
            self._event_highlight_overlay.set_visible(
                self._event_highlight_visible and self._event_highlight_time is not None
            )
        self._apply_shared_x_layout()

    def set_time_window(self, x0: float, x1: float) -> None:
        """Update tracks to render the requested time range."""

        if self._model is not None:
            x0, x1 = self._clamp_window(x0, x1)
        self._current_window = (float(x0), float(x1))
        for track in self._tracks.values():
            track.ax.set_xlim(x0, x1)
            track.update_window(x0, x1)
        self._time_cursor_overlay.refresh()
        self._event_highlight_overlay.refresh()
        self._redraw_event_labels()
        self._schedule_draw()

    def is_user_range_change_active(self) -> bool:
        """Return True if the current time-window change was initiated by the user."""
        return False

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        label_meta: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Propagate event markers (and labels) to all tracks and the gutter."""

        normalized_times: list[float] = []
        normalized_colors: list[str] = []
        normalized_labels: list[str] = []

        color_list = list(colors) if colors is not None else None
        label_list = list(labels) if labels is not None else None

        for idx, raw_time in enumerate(times):
            try:
                time_value = float(raw_time)
            except (TypeError, ValueError):
                continue
            normalized_times.append(time_value)
            if color_list is not None and idx < len(color_list):
                normalized_colors.append(str(color_list[idx]))
            if label_list is not None and idx < len(label_list):
                normalized_labels.append(str(label_list[idx]))

        self._event_times = normalized_times
        if color_list is not None and normalized_colors:
            self._event_colors = normalized_colors
        else:
            self._event_colors = None
        if label_list is not None:
            self._event_labels = normalized_labels
        else:
            self._event_labels = []

        self._assign_event_label_meta(label_meta, len(self._event_times))

        self._push_events_to_tracks()
        self._rebuild_event_labeler()
        self._schedule_draw()

    def _assign_event_label_meta(
        self,
        meta: Sequence[Mapping[str, Any]] | None,
        count: int,
    ) -> None:
        if count <= 0:
            self._event_label_meta = []
            return
        if not meta:
            self._event_label_meta = [dict() for _ in range(count)]
            return
        normalised: list[dict[str, Any]] = []
        for idx in range(count):
            payload: Any = {}
            try:
                payload = meta[idx]
            except Exception:
                payload = {}
            if isinstance(payload, Mapping):
                normalised.append(dict(payload))
            else:
                normalised.append({})
        self._event_label_meta = normalised

    def set_event_label_meta(self, meta: Sequence[Mapping[str, Any]]) -> None:
        self._assign_event_label_meta(meta, len(self._event_times))
        if self._event_labels_visible:
            self._rebuild_event_labeler()
            self._schedule_draw()

    def set_annotation_entries(self, entries: Sequence[AnnotationSpec]) -> None:
        """Populate the shared annotation lane above the primary track."""

        self._annotation_entries = list(entries)
        if self._annotation_entries:
            self._annotation_lane.set_entries(self._annotation_entries)
        else:
            self._annotation_lane.clear()
        self._schedule_draw()

    def annotation_text_objects(self) -> list[tuple[Text, float, str]]:
        """Expose active annotation artists for downstream styling helpers."""

        # Return v3 text objects if v3 is enabled
        if self._feature_flags.get("event_labels_v3", False) and self._event_helper_v3 is not None:
            text_objects: list[tuple[Text, float, str]] = []
            texts, cluster_map = self._event_helper_v3.annotation_text_objects()
            for text_artist in texts:
                cluster = cluster_map.get(text_artist)
                if cluster is not None:
                    # Return (Text, time, label) tuple
                    text_objects.append((text_artist, cluster.x, cluster.text))
            return text_objects

        # Fall back to v2 annotation lane
        text_objects = []
        for entry, artist in self._annotation_lane.entries_with_artists():
            text_objects.append((artist, entry.time_s, entry.label))
        return text_objects

    def set_simple_epochs(self, epochs: list[SimpleEpoch]) -> None:
        """Set protocol timeline epochs to render above traces.

        Args:
            epochs: List of SimpleEpoch objects to display
        """
        self._simple_epochs = epochs
        if self._simple_epochs_visible:
            self._simple_epoch_renderer.set_epochs(epochs)
            self._schedule_draw()

    def set_simple_epochs_visible(self, visible: bool) -> None:
        """Toggle simple epoch timeline visibility.

        Args:
            visible: Whether to show epoch bars
        """
        self._simple_epochs_visible = visible
        if visible:
            self._simple_epoch_renderer.set_epochs(self._simple_epochs)
            # Attach to top axis
            top_ax = self.top_axis()
            if top_ax is not None:
                self._simple_epoch_renderer.attach(top_ax)
        else:
            self._simple_epoch_renderer.clear()
            self._simple_epoch_renderer.attach(None)
        self._schedule_draw()

    def simple_epochs_visible(self) -> bool:
        """Check if simple epochs are currently visible."""
        return self._simple_epochs_visible

    def set_time_cursor(self, time_s: float | None, *, visible: bool | None = None) -> None:
        """Update the global 'now' cursor position (unused when None)."""

        self._time_cursor_overlay.set_time(time_s)
        if visible is not None:
            self._time_cursor_overlay.set_visible(visible)
        self._schedule_draw()

    def highlight_event(self, time_s: float | None, *, visible: bool = True) -> None:
        """Highlight a selected event across all tracks."""

        if time_s is None:
            self._event_highlight_time = None
            self._event_highlight_visible = bool(visible)
            self._event_highlight_overlay.clear()
            self._schedule_draw()
            return
        self._event_highlight_time = float(time_s)
        self._event_highlight_visible = bool(visible)
        self._event_highlight_overlay.set_alpha(self._event_highlight_alpha)
        self._event_highlight_overlay.set_time(self._event_highlight_time)
        self._event_highlight_overlay.set_visible(self._event_highlight_visible)
        self._schedule_draw()

    def clear_event_highlight(self) -> None:
        """Remove any active event highlight."""

        self._event_highlight_time = None
        self._event_highlight_visible = False
        self._event_highlight_overlay.clear()
        self._schedule_draw()

    def set_event_highlight_style(
        self,
        *,
        color: str | None = None,
        alpha: float | None = None,
        linewidth: float | None = None,
        linestyle: str | None = None,
    ) -> None:
        if color is not None:
            self._event_highlight_color = str(color)
        if alpha is not None:
            self._event_highlight_alpha = max(0.0, min(float(alpha), 1.0))
        style_kwargs = {
            "color": self._event_highlight_color,
            "alpha": self._event_highlight_alpha,
        }
        if linewidth is not None:
            style_kwargs["linewidth"] = float(linewidth)
        if linestyle is not None:
            style_kwargs["linestyle"] = str(linestyle)
        self._event_highlight_overlay.set_style(**style_kwargs)
        self._schedule_draw()

    def set_event_highlight_alpha(self, alpha: float) -> None:
        self._event_highlight_alpha = max(0.0, min(float(alpha), 1.0))
        self._event_highlight_overlay.set_alpha(self._event_highlight_alpha)
        self._schedule_draw()

    def event_highlight_alpha(self) -> float:
        return self._event_highlight_alpha

    def set_channel_visibility(self, track_id: str, visible: bool) -> None:
        track = self._tracks.get(track_id)
        if not track:
            return
        track.set_visible(visible)
        self._schedule_draw()

    def track(self, track_id: str) -> ChannelTrack | None:
        return self._tracks.get(track_id)

    def current_window(self) -> tuple[float, float] | None:
        return self._current_window

    def full_range(self) -> tuple[float, float] | None:
        if self._model is None:
            return None
        return cast(tuple[float, float], self._model.full_range)

    def axes(self) -> list[Axes]:
        return [track.ax for track in self._tracks.values()]

    def primary_axis(self):
        specs_map = {spec.track_id: idx for idx, spec in enumerate(self._channel_specs)}
        if not specs_map:
            return None
        first_id = self._channel_specs[0].track_id
        track = self._tracks.get(first_id)
        return None if track is None else track.ax

    def top_axis(self):
        """Alias for the top-most axes."""
        return self.primary_axis()

    def bottom_axis(self):
        if not self._channel_specs:
            return None
        last_id = self._channel_specs[-1].track_id
        track = self._tracks.get(last_id)
        return None if track is None else track.ax

    def layout_state(self) -> LayoutState:
        return LayoutState(
            order=[spec.track_id for spec in self._channel_specs],
            height_ratios={spec.track_id: spec.height_ratio for spec in self._channel_specs},
            visibility={track.id: track.is_visible() for track in self._tracks.values()},
        )

    def clear(self) -> None:
        self._destroy_event_labeler()
        self.figure.clf()
        self._tracks.clear()
        self._channel_specs.clear()
        self._axes_map.clear()
        self._model = None
        self._current_window = None
        self._event_times = []
        self._event_colors = None
        self._event_labels = []
        self._event_label_meta = []
        self._event_labeler = None
        self._use_track_event_lines = True
        self._xlim_cid = None
        self._ylim_cid = None
        self._last_xlim = None
        self._last_ylim = None
        self._event_lines_visible = True
        self._event_labels_visible = False
        self._event_label_gap_px = 22
        self._event_label_mode = "vertical"  # LOCKED TO VERTICAL ONLY
        self._feature_flags["event_labels_v3"] = is_enabled("event_labels_v3", default=True)
        self._event_helper_v3 = None
        self._event_entries_v3 = []
        self._event_label_host_ax = None
        self._max_labels_per_cluster = 1
        self._cluster_style_policy = "first"
        self._event_label_lanes = 3
        self._belt_baseline_enabled = True
        self._span_event_lines_across_siblings = True
        self._auto_event_label_mode = False  # Auto mode disabled - always vertical
        self._density_threshold_compact = 0.8
        self._density_threshold_belt = 0.25
        self._label_outline_enabled = True
        self._label_outline_width = 2.0
        self._label_outline_color = (1.0, 1.0, 1.0, 0.9)
        self._label_tooltips_enabled = True
        self._tooltip_proximity_px = 10
        self._compact_legend_enabled = False
        self._compact_legend_location = "upper right"
        self._event_font_family = "Arial"
        self._event_font_size = 15.0
        self._event_font_bold = False
        self._event_font_italic = False
        self._event_color = "#000000"
        self._disconnect_event_label_tooltips()
        self._annotation_lane.attach(None)
        self._annotation_entries.clear()
        self._time_cursor_overlay.clear()
        self._event_highlight_overlay.clear()
        self._event_highlight_time = None
        self._event_highlight_visible = False
        if self._pending_draw_timer is not None:
            self._pending_draw_timer.stop()
            self._pending_draw_timer = None
        self._schedule_draw()

    def scroll_by(self, delta: float) -> None:
        """Scroll the current time window by delta seconds."""

        if self._current_window is None:
            return
        x0, x1 = self._current_window
        self.set_time_window(x0 + delta, x1 + delta)

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

    def set_time_span(self, center: float, span: float) -> None:
        half = span / 2.0
        self.set_time_window(center - half, center + half)

    def autoscale_track(self, track_id: str, *, margin: float = 0.05) -> None:
        track = self._tracks.get(track_id)
        if track is None:
            return
        limits = track.autoscale(margin=margin)
        if limits is not None:
            self._schedule_draw()

    def autoscale_all(self, *, margin: float = 0.05) -> None:
        changed = False
        for track in self._tracks.values():
            if track.autoscale(margin=margin) is not None:
                changed = True
        if changed:
            self._schedule_draw()

    def tracks(self) -> list[ChannelTrack]:
        return list(self._tracks.values())

    def channel_specs(self) -> list[ChannelTrackSpec]:
        return [replace(spec) for spec in self._channel_specs]

    def track_for_axes(self, axes: Axes) -> ChannelTrack | None:
        return self._axes_map.get(axes)

    def _register_track_axes(self, track: ChannelTrack) -> None:
        for axes in track.axes():
            self._axes_map[axes] = track

    def _clamp_window(self, x0: float, x1: float) -> tuple[float, float]:
        if self._model is None:
            return float(x0), float(x1)
        lo_full, hi_full = self._model.full_range
        span = max(x1 - x0, 1e-6)
        if span >= (hi_full - lo_full):
            return lo_full, hi_full
        new_x0 = max(min(x0, hi_full - span), lo_full)
        new_x1 = new_x0 + span
        if new_x1 > hi_full:
            new_x1 = hi_full
            new_x0 = new_x1 - span
        return float(new_x0), float(new_x1)

    def _apply_shared_x_layout(self) -> None:
        if not self._channel_specs:
            return
        tracks = [self._tracks.get(spec.track_id) for spec in self._channel_specs]
        tracks = [track for track in tracks if track is not None]
        if not tracks:
            return
        channel_tracks = cast(list[ChannelTrack], tracks)
        visible_tracks = [track for track in channel_tracks if track.is_visible()]
        layout_tracks = visible_tracks if visible_tracks else channel_tracks
        bottom_track = layout_tracks[-1]

        # Determine X-axis title font size based on number of visible tracks
        num_visible = len(layout_tracks)
        if num_visible == 1:
            xlabel_fontsize = 24
        elif num_visible == 2:
            xlabel_fontsize = 22
        elif num_visible == 3:
            xlabel_fontsize = 20
        else:  # 4 or more tracks
            xlabel_fontsize = 20

        for track in channel_tracks:
            ax = track.ax
            if track is bottom_track:
                ax.tick_params(bottom=True, labelbottom=True)
                # Set X-axis title font size on bottom track only
                ax.xaxis.label.set_fontsize(xlabel_fontsize)
            else:
                ax.tick_params(bottom=False, labelbottom=False)
                ax.set_xlabel("")

    def set_shared_xlabel(self, text: str) -> None:
        axes = self.axes()
        if not axes:
            return
        bottom_axis = self.bottom_axis()
        if bottom_axis is None:
            bottom_axis = axes[-1]
        for axis in axes:
            if axis is bottom_axis:
                axis.set_xlabel(text)
            else:
                axis.set_xlabel("")

    def _schedule_draw(self) -> None:
        # If in batch mode, defer the draw until resume is called
        if self._batch_mode:
            self._batch_needs_draw = True
            return

        now = time.perf_counter()
        if now - self._last_draw_ts >= self._min_draw_interval:
            self.canvas.draw_idle()
            self._last_draw_ts = now
            if self._pending_draw_timer is not None:
                self._pending_draw_timer.stop()
                self._pending_draw_timer = None
        else:
            remaining = self._min_draw_interval - (now - self._last_draw_ts)
            delay_ms = max(int(remaining * 1000), 1)
            if self._pending_draw_timer is None:
                self._pending_draw_timer = QTimer(self.canvas)
                self._pending_draw_timer.setSingleShot(True)
                self._pending_draw_timer.timeout.connect(self._flush_pending_draw)
            else:
                self._pending_draw_timer.stop()
            self._pending_draw_timer.start(delay_ms)

    def _flush_pending_draw(self) -> None:
        if self._pending_draw_timer is not None:
            self._pending_draw_timer.stop()
            self._pending_draw_timer = None
        self.canvas.draw_idle()
        self._last_draw_ts = time.perf_counter()

    def suspend_updates(self) -> None:
        """Suspend draw calls to batch multiple setter operations."""
        self._batch_mode = True
        self._batch_needs_draw = False

    def resume_updates(self) -> None:
        """Resume draw calls and trigger a draw if any setters were called during batch mode."""
        self._batch_mode = False
        if self._batch_needs_draw:
            self._batch_needs_draw = False
            self._schedule_draw()

    def use_track_event_lines(self, flag: bool) -> None:
        """When False, clear per-track LineCollections; the helper will draw shared lines."""
        desired = bool(flag)
        if desired == self._use_track_event_lines:
            return
        self._use_track_event_lines = desired
        self._push_events_to_tracks()
        self._schedule_draw()

    def set_event_labeler(self, helper: EventLabeler | None) -> None:
        # Clean teardown of existing helper
        current = self._event_labeler
        if helper is current:
            return
        if current is not None:
            self._detach_view_callbacks()
            with contextlib.suppress(Exception):
                current.destroy(remove_belt=True)
        else:
            self._detach_view_callbacks()
        self._event_labeler = helper
        if helper is None:
            self._last_xlim = None
            self._last_ylim = None

    def _push_events_to_tracks(self) -> None:
        if not self._tracks:
            return
        if not self._event_lines_visible or not self._use_track_event_lines:
            for track in self._tracks.values():
                with contextlib.suppress(Exception):
                    track.set_events([], None, None)
            return
        colors = self._event_colors
        labels_payload = self._event_labels if self._event_labels else None
        for track in self._tracks.values():
            track.set_events(self._event_times, colors, labels_payload)

    def set_event_lines_visible(self, visible: bool) -> None:
        self._event_lines_visible = bool(visible)
        self._push_events_to_tracks()
        self._rebuild_event_labeler()
        self._schedule_draw()

    def set_event_labels_visible(self, visible: bool) -> None:
        new_state = bool(visible)
        if new_state == self._event_labels_visible:
            if new_state:
                self._rebuild_event_labeler()
            else:
                self._destroy_event_labeler()
                self.use_track_event_lines(True)
            self._schedule_draw()
            return
        self._event_labels_visible = new_state
        if new_state:
            self.use_track_event_lines(False)
            self._rebuild_event_labeler()
        else:
            self._destroy_event_labeler()
            self.use_track_event_lines(True)
        self._schedule_draw()

    def set_event_label_gap(self, pixels: int) -> None:
        self._event_label_gap_px = max(int(pixels), 1)
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def event_labels_v3_enabled(self) -> bool:
        return bool(self._feature_flags.get("event_labels_v3", False))

    def max_labels_per_cluster(self) -> int:
        return int(self._max_labels_per_cluster)

    def cluster_style_policy(self) -> str:
        return self._cluster_style_policy

    def event_label_lanes(self) -> int:
        return int(self._event_label_lanes)

    def belt_baseline_enabled(self) -> bool:
        return bool(self._belt_baseline_enabled)

    def span_event_lines_across_siblings(self) -> bool:
        return bool(self._span_event_lines_across_siblings)

    def auto_event_label_mode(self) -> bool:
        return bool(self._auto_event_label_mode)

    def label_density_thresholds(self) -> tuple[float, float]:
        return (
            float(self._density_threshold_compact),
            float(self._density_threshold_belt),
        )

    def label_outline_settings(
        self,
    ) -> tuple[bool, float, tuple[float, float, float, float] | None]:
        return (
            bool(self._label_outline_enabled),
            float(self._label_outline_width),
            self._label_outline_color,
        )

    def label_tooltips_enabled(self) -> bool:
        return bool(self._label_tooltips_enabled)

    def tooltip_proximity(self) -> int:
        return int(self._tooltip_proximity_px)

    def compact_legend_enabled(self) -> bool:
        return bool(self._compact_legend_enabled)

    def compact_legend_location(self) -> str:
        return self._compact_legend_location

    def set_max_labels_per_cluster(self, count: int) -> None:
        value = max(1, int(count))
        if value == self._max_labels_per_cluster:
            return
        self._max_labels_per_cluster = value
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_cluster_style_policy(self, policy: str) -> None:
        allowed = {"first", "most_common", "priority", "blend_color"}
        normalized = str(policy).lower()
        if normalized not in allowed:
            normalized = "first"
        if normalized == self._cluster_style_policy:
            return
        self._cluster_style_policy = normalized
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_label_lanes(self, lanes: int) -> None:
        value = max(1, min(int(lanes), 12))
        if value == self._event_label_lanes:
            return
        self._event_label_lanes = value
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_belt_baseline(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._belt_baseline_enabled:
            return
        self._belt_baseline_enabled = flag
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_event_label_span_siblings(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._span_event_lines_across_siblings:
            return
        self._span_event_lines_across_siblings = flag
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_event_labels_v3_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if self._feature_flags.get("event_labels_v3", False) == flag:
            return
        self._feature_flags["event_labels_v3"] = flag
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_auto_event_label_mode(self, enabled: bool) -> None:
        # LOCKED: Auto mode permanently disabled - always use vertical
        flag = False  # Ignore enabled parameter, always False
        if flag == self._auto_event_label_mode:
            return
        self._auto_event_label_mode = flag
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_label_density_thresholds(
        self, *, compact: float | None = None, belt: float | None = None
    ) -> None:
        new_compact = float(compact) if compact is not None else self._density_threshold_compact
        new_belt = float(belt) if belt is not None else self._density_threshold_belt
        new_compact = max(0.0, new_compact)
        new_belt = max(0.0, min(new_belt, new_compact))
        if math.isclose(
            new_compact, self._density_threshold_compact, rel_tol=1e-6
        ) and math.isclose(new_belt, self._density_threshold_belt, rel_tol=1e-6):
            return
        self._density_threshold_compact = new_compact
        self._density_threshold_belt = new_belt
        if self._event_labels_visible and self._auto_event_label_mode:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_label_outline_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._label_outline_enabled:
            return
        self._label_outline_enabled = flag
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_label_outline(
        self, width: float, color: Sequence[float] | tuple[float, ...] | str
    ) -> None:
        if isinstance(color, str):
            rgba_tuple = self._parse_hex_rgba(color)
            if rgba_tuple is None:
                raise ValueError("Invalid outline color format")
        else:
            rgba_values = tuple(float(component) for component in color)
            if len(rgba_values) == 3:
                rgba_tuple = (*rgba_values, 1.0)
            elif len(rgba_values) == 4:
                rgba_tuple = rgba_values
            else:
                raise ValueError("Outline color must have 3 or 4 components")
        rgba = tuple(max(0.0, min(1.0, component)) for component in rgba_tuple)
        width_value = max(float(width), 0.0)
        changed = (
            not math.isclose(width_value, self._label_outline_width, rel_tol=1e-6)
            or self._label_outline_color != rgba
        )
        if not changed:
            return
        self._label_outline_width = width_value
        self._label_outline_color = rgba  # type: ignore[assignment]
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def pin_event(self, index: int, pinned: bool = True) -> None:
        if not (0 <= index < len(self._event_times)):
            return
        while len(self._event_label_meta) < len(self._event_times):
            self._event_label_meta.append({})
        current = dict(self._event_label_meta[index] or {})
        if current.get("pinned") == bool(pinned):
            return
        current["pinned"] = bool(pinned)
        self._event_label_meta[index] = current
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_event_priority(self, index: int, priority: int) -> None:
        if not (0 <= index < len(self._event_times)):
            return
        while len(self._event_label_meta) < len(self._event_times):
            self._event_label_meta.append({})
        current = dict(self._event_label_meta[index] or {})
        priority_value = int(priority)
        if current.get("priority") == priority_value:
            return
        current["priority"] = priority_value
        self._event_label_meta[index] = current
        if self._event_labels_visible:
            self._rebuild_event_labeler()
        self._schedule_draw()

    def set_label_tooltips_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._label_tooltips_enabled:
            return
        self._label_tooltips_enabled = flag
        if not flag:
            self._disconnect_event_label_tooltips()
        elif self._event_labels_visible:
            self._connect_event_label_tooltips()

    def set_tooltip_proximity(self, pixels: int) -> None:
        value = max(1, int(pixels))
        if value == self._tooltip_proximity_px:
            return
        self._tooltip_proximity_px = value

    def set_compact_legend_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._compact_legend_enabled:
            return
        self._compact_legend_enabled = flag
        if not flag and self._event_helper_v3 is not None:
            anchor_ax = self._event_helper_v3.ax_host
            self._event_helper_v3.draw_compact_legend(anchor_ax, {})
        elif flag and self._event_labels_visible:
            self._update_compact_legend()

    def set_compact_legend_location(self, location: str) -> None:
        normalized = str(location).lower().strip() or "upper right"
        valid = {
            "upper right",
            "upper left",
            "lower left",
            "lower right",
            "center right",
            "center left",
            "center",
            "upper center",
            "lower center",
        }
        if normalized not in valid:
            normalized = "upper right"
        if normalized == self._compact_legend_location:
            return
        self._compact_legend_location = normalized
        if self._compact_legend_enabled and self._event_labels_visible:
            self._update_compact_legend()

    def set_event_base_style(
        self,
        *,
        font_family: str | None = None,
        font_size: float | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        color: str | None = None,
    ) -> None:
        """Set the base event label style (applied before priority/category enhancements)."""
        changed = False
        if font_family is not None and font_family != self._event_font_family:
            self._event_font_family = str(font_family)
            changed = True
        if font_size is not None and font_size != self._event_font_size:
            self._event_font_size = float(font_size)
            changed = True
        if bold is not None and bold != self._event_font_bold:
            self._event_font_bold = bool(bold)
            changed = True
        if italic is not None and italic != self._event_font_italic:
            self._event_font_italic = bool(italic)
            changed = True
        if color is not None and color != self._event_color:
            self._event_color = str(color)
            changed = True
        if changed and self._event_labels_visible:
            self._rebuild_event_labeler()

    def _connect_event_label_tooltips(self) -> None:
        if not self._label_tooltips_enabled or self._event_helper_v3 is None:
            return
        canvas = self.canvas
        if canvas is None:
            return
        if hasattr(canvas, "get_renderer"):
            try:
                renderer = canvas.get_renderer()
            except Exception:
                # Don't force a synchronous draw - tooltips can wait
                renderer = None
        else:
            renderer = None
        texts, mapping = self._event_helper_v3.annotation_text_objects()
        if not texts:
            self._disconnect_event_label_tooltips()
            return

        if self._cid_motion is not None:
            canvas.mpl_disconnect(self._cid_motion)
            self._cid_motion = None

        proximity = max(1, int(self._tooltip_proximity_px))
        self._last_hover_text = None

        def process_hover_event(evt):
            """Process hover event (called after debounce delay)."""
            if evt.inaxes is None or not texts:
                self._hide_tooltip()
                return
            # Try to get renderer, but don't block if unavailable
            try:
                current_renderer = renderer or canvas.get_renderer()
            except Exception:
                return  # Defer tooltip until renderer is available
            nearest: Text | None = None
            best_dist = float("inf")
            for text_artist in texts:
                try:
                    bbox = text_artist.get_window_extent(renderer=current_renderer)
                except Exception:
                    continue
                cx = bbox.x0 + bbox.width / 2.0
                cy = bbox.y0 + bbox.height / 2.0
                dx = evt.x - cx
                dy = evt.y - cy
                dist2 = (dx * dx) + (dy * dy)
                if dist2 < best_dist:
                    best_dist = dist2
                    nearest = text_artist
            if nearest is None or best_dist > (proximity * proximity):
                self._hide_tooltip()
                return

            if self._last_hover_text is nearest:
                return

            cluster = mapping.get(nearest)
            if cluster is None or not cluster.items:
                self._hide_tooltip()
                return

            self._last_hover_text = nearest
            lines = ["<b>Events in cluster</b>"]
            for entry in cluster.items:
                label = entry.meta.get("text_override") or entry.text
                color = entry.meta.get("color")
                rgba = self._normalize_color(color)
                css = self._color_to_css(rgba)
                badge = (
                    '<span style="display:inline-block;width:10px;height:10px;'
                    "border-radius:2px;"
                    f'background:{css};margin-right:6px;"></span>'
                )
                lines.append(f"<div>{badge}{label}</div>")
            html = "".join(lines)
            self._show_qt_tooltip(evt, html)

        def on_motion(evt):
            """Debounced motion handler - schedules hover processing."""
            self._pending_hover_event = evt
            if self._hover_debounce_timer is None:
                self._hover_debounce_timer = QTimer(canvas)
                self._hover_debounce_timer.setSingleShot(True)
                self._hover_debounce_timer.timeout.connect(
                    lambda: (
                        process_hover_event(self._pending_hover_event)
                        if self._pending_hover_event
                        else None
                    )
                )
            self._hover_debounce_timer.start(16)  # 16ms = ~60fps, smooth but responsive

        self._cid_motion = canvas.mpl_connect("motion_notify_event", on_motion)

    def _disconnect_event_label_tooltips(self) -> None:
        canvas = self.canvas
        if self._cid_motion is not None and canvas is not None:
            with contextlib.suppress(Exception):
                canvas.mpl_disconnect(self._cid_motion)
        self._cid_motion = None
        self._hide_tooltip()

    def _show_qt_tooltip(self, evt, html: str) -> None:
        try:
            from PyQt5.QtGui import QCursor
            from PyQt5.QtWidgets import QToolTip

            QToolTip.showText(QCursor.pos(), html)
        except Exception:
            ax = evt.inaxes
            if ax is None:
                return
            if self._hover_annot is None:
                self._hover_annot = ax.annotate(
                    "",
                    xy=(0, 0),
                    xytext=(10, 10),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round", fc="#F8F8F8", ec="#CCCCCC", lw=1.0, alpha=0.95),
                    zorder=100,
                )
            hover = self._hover_annot
            hover.set_visible(True)
            hover.xy = (evt.xdata, evt.ydata)
            hover.set_text(self._strip_html(html))
            ax.figure.canvas.draw_idle()

    def _hide_tooltip(self) -> None:
        self._last_hover_text = None
        try:
            from PyQt5.QtWidgets import QToolTip

            QToolTip.hideText()
        except Exception:
            pass
        if self._hover_annot is not None:
            hover = self._hover_annot
            hover.set_visible(False)
            axes = getattr(hover, "axes", None)
            if axes is not None and getattr(axes, "figure", None) is not None:
                axes.figure.canvas.draw_idle()

    @staticmethod
    def _strip_html(value: str) -> str:
        return re.sub("<[^<]+?>", "", value)

    def _update_compact_legend(self) -> None:
        helper = self._event_helper_v3
        if helper is None:
            return
        ax = helper.ax_host
        if ax is None:
            return
        if not self._compact_legend_enabled:
            helper.draw_compact_legend(ax, {})
            return
        try:
            x0, x1 = ax.get_xlim()
        except Exception:
            return

        categories: dict[str, tuple[int, tuple[float, float, float, float]]] = {}
        for idx, time_value in enumerate(self._event_times):
            if time_value < x0 or time_value > x1:
                continue
            meta: dict[str, Any] = {}
            if idx < len(self._event_label_meta):
                candidate = self._event_label_meta[idx] or {}
                if isinstance(candidate, Mapping):
                    meta = dict(candidate)
            if not bool(meta.get("visible", True)):
                continue
            cat = (
                meta.get("category")
                or meta.get("group")
                or (self._event_labels[idx] if idx < len(self._event_labels) else "Event")
            )
            color = self._normalize_color(meta.get("color"))
            if cat in categories:
                count, existing_color = categories[cat]
                categories[cat] = (count + 1, existing_color)
            else:
                categories[cat] = (1, color)

        helper.draw_compact_legend(
            ax, categories, title="Events", loc=self._compact_legend_location
        )

    def _normalize_color(self, color: Any) -> tuple[float, float, float, float]:
        parsed = self._parse_hex_rgba(color) if isinstance(color, str) else None
        if parsed is not None:
            return parsed
        try:
            rgba = to_rgba(color)
            return (float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
        except Exception:
            pass
        if isinstance(color, Sequence):
            try:
                values = [float(component) for component in color]
            except (TypeError, ValueError):
                values = []
            while len(values) < 4:
                values.append(1.0 if len(values) == 3 else 1.0)
            return (
                max(0.0, min(1.0, values[0])),
                max(0.0, min(1.0, values[1])),
                max(0.0, min(1.0, values[2])),
                max(0.0, min(1.0, values[3] if len(values) > 3 else 1.0)),
            )
        return (0.0, 0.0, 0.0, 1.0)

    @staticmethod
    def _color_to_css(color: tuple[float, float, float, float]) -> str:
        r = int(round(color[0] * 255))
        g = int(round(color[1] * 255))
        b = int(round(color[2] * 255))
        a = max(0.0, min(1.0, color[3]))
        return f"rgba({r},{g},{b},{a:.2f})"

    @staticmethod
    def _parse_hex_rgba(value: str | None) -> tuple[float, float, float, float] | None:
        if not value:
            return None
        hex_value = value.strip().lstrip("#")
        if len(hex_value) == 6:
            hex_value = "FF" + hex_value
        if len(hex_value) != 8:
            return None
        try:
            a = int(hex_value[0:2], 16) / 255.0
            r = int(hex_value[2:4], 16) / 255.0
            g = int(hex_value[4:6], 16) / 255.0
            b = int(hex_value[6:8], 16) / 255.0
            return (r, g, b, a)
        except ValueError:
            return None

    def set_event_label_mode(self, mode: str) -> None:
        # LOCKED TO VERTICAL MODE ONLY - ignore any other mode setting
        normalized = "vertical"  # Force vertical mode always

        previous_mode = self._event_label_mode
        already_active = normalized == previous_mode and self._event_labeler is not None
        self._event_label_mode = normalized
        self._event_labels_visible = True

        self.use_track_event_lines(False)

        if already_active:
            self._rebuild_event_labeler()
            self._schedule_draw()
            return

        self._rebuild_event_labeler()
        self._schedule_draw()

    def _normalized_event_labels(self) -> list[str]:
        if not self._event_times:
            return []
        if not self._event_labels:
            return []
        labels = list(self._event_labels[: len(self._event_times)])
        if len(labels) < len(self._event_times):
            labels.extend([""] * (len(self._event_times) - len(labels)))
        return labels

    def _clear_event_label_v2(self) -> None:
        if not self._event_label_v2_artists:
            return
        for artist in self._event_label_v2_artists:
            with contextlib.suppress(Exception):
                artist.remove()
        self._event_label_v2_artists = []

    def _clear_event_helper_v3(self) -> None:
        helper = self._event_helper_v3
        if helper is not None:
            with contextlib.suppress(Exception):
                helper.clear()
            if self._event_labeler is None:
                self._detach_view_callbacks()
        self._event_helper_v3 = None
        self._event_entries_v3 = []
        self._disconnect_event_label_tooltips()

    def _draw_event_labels_v3(self, labels: list[str]) -> bool:
        if not self._feature_flags.get("event_labels_v3", False):
            return False
        if not self._event_times:
            return False
        self._clear_event_label_v2()

        anchor_ax: Axes | None = self.primary_axis() or self.bottom_axis()
        if anchor_ax is None:
            tracks = list(self._tracks.values())
            anchor_ax = tracks[0].ax if tracks else None
        if anchor_ax is None:
            return False

        siblings: list[Axes] = []
        if self._span_event_lines_across_siblings:
            for track in self._tracks.values():
                if track.ax not in siblings:
                    siblings.append(track.ax)
        else:
            siblings.append(anchor_ax)
        if anchor_ax not in siblings:
            siblings.append(anchor_ax)

        # LOCKED TO VERTICAL MODE ONLY - ignore all mode logic
        layout_mode = "vertical"
        compact_counts = False
        rotation_deg = 90.0
        max_labels = max(1, int(self._max_labels_per_cluster))
        lanes = max(1, int(self._event_label_lanes))

        # Auto mode and all other modes disabled - always vertical

        options = LayoutOptionsV3(
            mode=layout_mode,
            min_px=max(1, int(self._event_label_gap_px)),
            max_labels_per_cluster=max_labels,
            style_policy=self._cluster_style_policy,
            span_siblings=self._span_event_lines_across_siblings,
            lanes=lanes,
            belt_baseline=bool(self._belt_baseline_enabled),
            rotation_deg=rotation_deg,
            outline_enabled=self._label_outline_enabled,
            outline_width=self._label_outline_width,
            outline_color=self._label_outline_color,
            compact_counts=compact_counts,
        )

        entries: list[EventEntryV3] = []
        for idx, time_value in enumerate(self._event_times):
            label_value = labels[idx] if idx < len(labels) else ""
            # Start with base event style
            meta_payload: dict[str, Any] = {
                "fontfamily": self._event_font_family,
                "fontsize": self._event_font_size,
                "fontweight": "bold" if self._event_font_bold else "normal",
                "fontstyle": "italic" if self._event_font_italic else "normal",
                "color": self._event_color,
            }
            # Overlay user-specified metadata (can override base style)
            if idx < len(self._event_label_meta):
                candidate = self._event_label_meta[idx] or {}
                if isinstance(candidate, Mapping):
                    meta_payload.update(dict(candidate))
            priority = meta_payload.get("priority", meta_payload.get("rank", 0))
            try:
                priority_value = int(priority)
            except (TypeError, ValueError):
                priority_value = 0
            category = meta_payload.get("category")
            pinned = bool(meta_payload.get("pinned", False))
            entries.append(
                EventEntryV3(
                    t=float(time_value),
                    text=str(label_value),
                    meta=meta_payload,
                    priority=priority_value,
                    category=str(category) if isinstance(category, str) else None,
                    pinned=pinned,
                )
            )

        if not entries:
            return False

        self._clear_event_helper_v3()
        helper = EventLabelerV3(anchor_ax, siblings, options)
        helper.draw(entries)
        self._event_helper_v3 = helper
        self._event_entries_v3 = entries
        self.set_event_labeler(None)
        self._attach_view_callbacks(anchor_ax)
        if self._label_tooltips_enabled:
            self._connect_event_label_tooltips()
        else:
            self._disconnect_event_label_tooltips()
        if self._compact_legend_enabled:
            self._update_compact_legend()
        else:
            helper.draw_compact_legend(anchor_ax, {})
        return True

    def _resolve_density_mode(self, ax: Axes) -> str:
        try:
            x0, x1 = ax.get_xlim()
        except Exception:
            if not self._event_times:
                return "full"
            x0 = min(self._event_times)
            x1 = max(self._event_times)
        if x0 > x1:
            x0, x1 = x1, x0
        try:
            width_px = float(ax.bbox.width)
        except Exception:
            width_px = float(ax.figure.bbox.width if getattr(ax, "figure", None) else 0.0)
        dpi = float(getattr(ax.figure, "dpi", 96.0))
        width_in = width_px / dpi if dpi > 0 else 0.0
        visible_count = 0
        if x1 > x0:
            span = x1 - x0
            pad = 0.02 * span
            lo = x0 - pad
            hi = x1 + pad
            visible_count = sum(1 for value in self._event_times if lo <= value <= hi)
        effective_width = max(width_in, 1e-3)
        density = visible_count / (effective_width * 100.0)
        if density >= self._density_threshold_compact:
            return "compact"
        if density >= self._density_threshold_belt:
            return "belt"
        return "full"

    def _draw_event_labels_v2(self) -> bool:
        # Compact numeric counters are experimental; keep them opt-in.
        if not is_enabled("event_labels_v2", default=False):
            self._clear_event_label_v2()
            return False
        # Only delegate to V2 for the vertical label presentation.
        if self._event_label_mode != "vertical" or not self._event_labels_visible:
            self._clear_event_label_v2()
            return True
        if not self._event_times:
            self._clear_event_label_v2()
            return True

        anchor_ax: Axes | None = self.primary_axis() or self.bottom_axis()
        if anchor_ax is None:
            self._clear_event_label_v2()
            return True

        try:
            renderer = self.canvas.get_renderer()
        except Exception:
            # Don't force a synchronous draw - use fallback dimensions
            renderer = None

        try:
            if renderer is not None:
                bbox = anchor_ax.get_window_extent(renderer)
                ax_width_px = max(int(bbox.width), 1)
            else:
                # Fallback to canvas dimensions if renderer unavailable
                ax_width_px = max(int(self.canvas.width()), 1)
        except Exception:
            ax_width_px = max(int(self.canvas.width()), 1)

        from vasoanalyzer.core.events.cluster import cluster_events
        from vasoanalyzer.ui.plots.event_label_layer import draw_event_labels

        clusters = cluster_events(
            self._event_times,
            anchor_ax.get_xlim(),
            ax_width_px,
            min_gap_px=max(self._event_label_gap_px, 1),
            max_visible_per_cluster=1,
        )

        self._clear_event_label_v2()
        self.set_event_labeler(None)
        self._event_label_v2_artists = draw_event_labels(
            anchor_ax,
            clusters,
            anchor_ax.get_xlim(),
            mode=self._event_label_mode,
        )
        self._disconnect_event_label_tooltips()
        return True

    def _destroy_event_labeler(self) -> None:
        self._clear_event_label_v2()
        self._clear_event_helper_v3()
        self.set_event_labeler(None)

    def _rebuild_event_labeler(self) -> None:
        if not self._event_labels_visible:
            self._destroy_event_labeler()
            return
        if not getattr(self, "_event_times", None):
            self._destroy_event_labeler()
            return
        labels = self._normalized_event_labels()
        if not labels:
            self._destroy_event_labeler()
            return

        if self._draw_event_labels_v3(labels):
            return

        self._clear_event_helper_v3()
        if self._draw_event_labels_v2():
            return
        options = LayoutOptions(
            span_siblings=True,
            label_host="auto_top",
            min_px=self._event_label_gap_px,
            max_labels_per_cluster=1,
            top_pad_axes=0.05,
            vertical_side="right",
            vertical_x_pad_px=6,
            max_lanes=2,
            show_lines=self._event_lines_visible,
            live=False,
        )

        anchor_ax: Axes | None = self.primary_axis() or self.bottom_axis()
        if anchor_ax is None:
            tracks = list(self._tracks.values())
            anchor_ax = tracks[0].ax if tracks else None
        if anchor_ax is None:
            self.set_event_labeler(None)
            return

        events_payload: list[dict[str, Any]] = []
        for idx, time_value in enumerate(self._event_times):
            label_value = labels[idx] if idx < len(labels) else ""
            meta_payload: dict[str, Any] = {}
            if idx < len(self._event_label_meta):
                candidate = self._event_label_meta[idx] or {}
                if isinstance(candidate, Mapping):
                    meta_payload = dict(candidate)
            events_payload.append({"time": time_value, "label": label_value, "meta": meta_payload})

        if not events_payload:
            self.set_event_labeler(None)
            return

        helper = EventLabeler(
            anchor_ax, events_payload, mode=self._event_label_mode, options=options
        )
        helper.draw()

        self.set_event_labeler(helper)
        self._attach_view_callbacks(helper.host_axes)

    def _attach_view_callbacks(self, host_ax: Axes) -> None:
        self._detach_view_callbacks()
        if host_ax is None:
            return
        self._event_label_host_ax = host_ax
        try:
            self._last_xlim = cast(tuple[float, float], host_ax.get_xlim())
            self._last_ylim = cast(tuple[float, float], host_ax.get_ylim())
        except Exception:
            self._last_xlim = None
            self._last_ylim = None
        self._xlim_cid = host_ax.callbacks.connect("xlim_changed", self._on_view_changed)
        self._ylim_cid = host_ax.callbacks.connect("ylim_changed", self._on_view_changed)

    def _detach_view_callbacks(self) -> None:
        host_ax = self._event_label_host_ax
        if host_ax is not None:
            if self._xlim_cid is not None:
                with contextlib.suppress(Exception):
                    host_ax.callbacks.disconnect(self._xlim_cid)
            if self._ylim_cid is not None:
                with contextlib.suppress(Exception):
                    host_ax.callbacks.disconnect(self._ylim_cid)
        self._event_label_host_ax = None
        self._xlim_cid = None
        self._ylim_cid = None
        self._last_xlim = None
        self._last_ylim = None

    def _on_view_changed(self, ax: Axes) -> None:
        if ax is None:
            return
        try:
            xlim = cast(tuple[float, float], ax.get_xlim())
            ylim = cast(tuple[float, float], ax.get_ylim())
        except Exception:
            return
        if xlim == self._last_xlim and ylim == self._last_ylim:
            return
        self._last_xlim = xlim
        self._last_ylim = ylim
        handled = False
        if self._feature_flags.get("event_labels_v3", False):
            if self._auto_event_label_mode:
                labels = self._normalized_event_labels()
                handled = self._draw_event_labels_v3(labels)
            elif self._event_helper_v3 is not None:
                try:
                    self._event_helper_v3.draw(self._event_entries_v3)
                    handled = True
                except Exception:
                    handled = False
        if not handled and self._event_labeler is not None:
            try:
                self._event_labeler.draw()
                handled = True
            except Exception:
                handled = False
        if handled:
            if self._label_tooltips_enabled and self._event_helper_v3 is not None:
                self._connect_event_label_tooltips()
            else:
                self._disconnect_event_label_tooltips()
            if self._compact_legend_enabled:
                self._update_compact_legend()
        if not handled:
            return
        fig = ax.figure
        if fig is not None and getattr(fig, "canvas", None) is not None:
            fig.canvas.draw_idle()

    def _redraw_event_labels(self) -> None:
        if self._event_helper_v3 is not None and self._feature_flags.get("event_labels_v3", False):
            self._event_helper_v3.draw(self._event_entries_v3)
        elif self._event_labeler is not None:
            self._event_labeler.draw()
