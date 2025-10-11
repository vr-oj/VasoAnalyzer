"""Core orchestration for stacked trace plotting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import time

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.transforms import blended_transform_factory
from PyQt5.QtCore import QTimer

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.event_labels import EventLabelGutter
from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.tracks import ChannelTrack, ChannelTrackSpec
from vasoanalyzer.ui.overlays import (
    AnnotationLane,
    AnnotationSpec,
    EventHighlightOverlay,
    TimeCursorOverlay,
)


@dataclass
class LayoutState:
    """Serializable layout snapshot."""

    order: List[str]
    height_ratios: Dict[str, float]
    visibility: Dict[str, bool]


class PlotHost:
    """Host figure with stacked channel tracks sharing a common time axis."""

    def __init__(self, *, dpi: int) -> None:
        self.figure = Figure(
            figsize=(8, 4),
            facecolor=CURRENT_THEME["window_bg"],
            dpi=dpi,
            constrained_layout=False,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.figure.subplots_adjust(left=0.095, right=0.985, top=0.985, bottom=0.115)
        self._channel_specs: List[ChannelTrackSpec] = []
        self._tracks: Dict[str, ChannelTrack] = {}
        self._axes_map: Dict[Axes, ChannelTrack] = {}
        self._model: Optional[TraceModel] = None
        self._current_window: Optional[Tuple[float, float]] = None
        self._event_gutter_ax: Optional[Axes] = None
        self._event_gutter_pair: Optional[Tuple[str, str]] = None
        self._event_times: List[float] = []
        self._event_colors: Optional[List[str]] = None
        self._event_labels: List[str] = []
        self._event_gutter_collection: Optional[LineCollection] = None
        self._event_label_gutter: Optional[EventLabelGutter] = None
        self._gutter_xlim_cid: Optional[int] = None
        self._event_lines_visible: bool = True
        self._event_labels_visible: bool = False
        self._event_label_gap_px: int = 22
        self._annotation_lane = AnnotationLane()
        self._time_cursor_overlay = TimeCursorOverlay()
        self._event_highlight_overlay = EventHighlightOverlay()
        self._annotation_entries: List[AnnotationSpec] = []
        self._event_highlight_alpha: float = self._event_highlight_overlay.alpha()
        self._event_highlight_color: str = CURRENT_THEME.get(
            "event_highlight",
            CURRENT_THEME.get("accent", "#1D5CFF"),
        )
        self._event_highlight_time: Optional[float] = None
        self._event_highlight_visible: bool = False
        self._last_draw_ts: float = 0.0
        self._min_draw_interval: float = 1.0 / 60.0
        self._pending_draw_timer: Optional[QTimer] = None

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

        self._dispose_event_gutter()
        self.figure.clf()
        self.figure.subplots_adjust(left=0.095, right=0.985, top=0.985, bottom=0.115)
        self._tracks.clear()
        self._axes_map.clear()
        self._event_gutter_ax = None
        self._event_gutter_pair = None
        if not self._channel_specs:
            self._schedule_draw()
            return

        specs = self._channel_specs
        gutter_index: Optional[int] = None
        include_event_gutter = self._event_labels_visible and len(specs) >= 2
        if include_event_gutter:
            for idx in range(len(specs) - 1):
                left = specs[idx]
                right = specs[idx + 1]
                if left.track_id == "inner" and right.track_id == "outer":
                    gutter_index = idx + 1
                    break

        gutter_ratio = 0.12 if include_event_gutter else 0.0
        height_ratios: List[float] = []
        for idx, spec in enumerate(specs):
            height_ratios.append(max(spec.height_ratio, 0.05))
            if gutter_index is not None and idx == gutter_index - 1:
                height_ratios.append(gutter_ratio)

        row_count = len(height_ratios)
        gs = self.figure.add_gridspec(
            nrows=row_count,
            ncols=1,
            height_ratios=height_ratios,
            hspace=0.0,
        )

        shared_ax = None
        row_cursor = 0
        event_gutter_ax: Optional[Axes] = None
        gutter_pair: Optional[Tuple[str, str]] = None
        track_axes: List[Tuple[Axes, str]] = []
        for index, spec in enumerate(specs):
            ax = self.figure.add_subplot(gs[row_cursor, 0], sharex=shared_ax)
            if shared_ax is None:
                shared_ax = ax
            else:
                ax.tick_params(labelbottom=False)
            ax.tick_params(colors=CURRENT_THEME["text"])
            ax.yaxis.label.set_color(CURRENT_THEME["text"])
            ax.xaxis.label.set_color(CURRENT_THEME["text"])
            ax.title.set_color(CURRENT_THEME["text"])
            ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
            spine_color = CURRENT_THEME.get("border_soft", CURRENT_THEME.get("grid_color", "#CCCCCC"))
            for spine in ax.spines.values():
                spine.set_color(spine_color)
            track = ChannelTrack(spec, ax, self.canvas)
            self._tracks[spec.track_id] = track
            self._register_track_axes(track)
            track_axes.append((ax, spec.track_id))
            row_cursor += 1

            if gutter_index is not None and index == gutter_index - 1:
                gutter = self.figure.add_subplot(gs[row_cursor, 0], sharex=shared_ax)
                gutter.set_ylim(0, 1)
                gutter.tick_params(left=False, right=False, labelleft=False)
                gutter.tick_params(bottom=False, top=False, labelbottom=False)
                gutter.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
                for spine in gutter.spines.values():
                    spine.set_visible(False)
                gutter.patch.set_alpha(0.0)
                event_gutter_ax = gutter
                gutter_pair = (specs[index].track_id, specs[index + 1].track_id)
                row_cursor += 1

            if gutter_index is not None and index == gutter_index - 1:
                # Hide the touching spines so vertical lines look continuous.
                ax.spines["bottom"].set_visible(False)
            if gutter_index is not None and index == gutter_index:
                ax.spines["top"].set_visible(False)

        divider_color = CURRENT_THEME.get("text", "#000000")
        for (upper_ax, upper_id), (lower_ax, lower_id) in zip(track_axes, track_axes[1:]):
            if gutter_pair is not None and (upper_id, lower_id) == gutter_pair:
                continue
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
        self._event_gutter_ax = event_gutter_ax
        self._event_gutter_pair = gutter_pair
        self._configure_event_gutter()
        self._push_events_to_tracks()
        self._push_events_to_gutter()
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
        self._push_events_to_gutter()
        self._schedule_draw()

    def set_events(
        self,
        times: Sequence[float],
        colors: Optional[Sequence[str]] = None,
        labels: Optional[Sequence[str]] = None,
    ) -> None:
        """Propagate event markers (and labels) to all tracks and the gutter."""

        normalized_times: List[float] = []
        normalized_colors: List[str] = []
        normalized_labels: List[str] = []

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

        self._push_events_to_tracks()
        self._refresh_event_label_gutter_data()
        self._push_events_to_gutter()
        self._schedule_draw()

    def set_annotation_entries(self, entries: Sequence[AnnotationSpec]) -> None:
        """Populate the shared annotation lane above the primary track."""

        self._annotation_entries = list(entries)
        if self._annotation_entries:
            self._annotation_lane.set_entries(self._annotation_entries)
        else:
            self._annotation_lane.clear()
        self._schedule_draw()

    def annotation_text_objects(self) -> List[Tuple[Text, float, str]]:
        """Expose active annotation artists for downstream styling helpers."""

        text_objects: List[Tuple[Text, float, str]] = []
        for entry, artist in self._annotation_lane.entries_with_artists():
            text_objects.append((artist, entry.time_s, entry.label))
        return text_objects

    def set_time_cursor(self, time_s: Optional[float], *, visible: Optional[bool] = None) -> None:
        """Update the global 'now' cursor position (unused when None)."""

        self._time_cursor_overlay.set_time(time_s)
        if visible is not None:
            self._time_cursor_overlay.set_visible(visible)
        self._schedule_draw()

    def highlight_event(self, time_s: Optional[float], *, visible: bool = True) -> None:
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
        color: Optional[str] = None,
        alpha: Optional[float] = None,
        linewidth: Optional[float] = None,
        linestyle: Optional[str] = None,
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
        self._update_event_gutter_visibility()
        self._schedule_draw()

    def track(self, track_id: str) -> Optional[ChannelTrack]:
        return self._tracks.get(track_id)

    def current_window(self) -> Optional[Tuple[float, float]]:
        return self._current_window

    def full_range(self) -> Optional[Tuple[float, float]]:
        if self._model is None:
            return None
        return self._model.full_range

    def axes(self) -> List:
        return [track.ax for track in self._tracks.values()]

    def primary_axis(self):
        specs_map = {spec.track_id: idx for idx, spec in enumerate(self._channel_specs)}
        if not specs_map:
            return None
        first_id = self._channel_specs[0].track_id
        track = self._tracks.get(first_id)
        return None if track is None else track.ax

    def bottom_axis(self):
        if not self._channel_specs:
            return None
        last_id = self._channel_specs[-1].track_id
        track = self._tracks.get(last_id)
        return None if track is None else track.ax

    def event_gutter_axis(self) -> Optional[Axes]:
        return self._event_gutter_ax

    def layout_state(self) -> LayoutState:
        return LayoutState(
            order=[spec.track_id for spec in self._channel_specs],
            height_ratios={spec.track_id: spec.height_ratio for spec in self._channel_specs},
            visibility={track.id: track.is_visible() for track in self._tracks.values()},
        )

    def clear(self) -> None:
        self._dispose_event_gutter()
        self.figure.clf()
        self._tracks.clear()
        self._channel_specs.clear()
        self._axes_map.clear()
        self._model = None
        self._current_window = None
        self._event_gutter_ax = None
        self._event_gutter_pair = None
        self._event_times = []
        self._event_colors = None
        self._event_labels = []
        self._event_lines_visible = True
        self._event_labels_visible = True
        self._event_label_gap_px = 22
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

    def tracks(self) -> List[ChannelTrack]:
        return list(self._tracks.values())

    def channel_specs(self) -> List[ChannelTrackSpec]:
        return [replace(spec) for spec in self._channel_specs]

    def track_for_axes(self, axes: Axes) -> Optional[ChannelTrack]:
        return self._axes_map.get(axes)

    def _register_track_axes(self, track: ChannelTrack) -> None:
        for axes in track.axes():
            self._axes_map[axes] = track

    def _clamp_window(self, x0: float, x1: float) -> Tuple[float, float]:
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
        visible_tracks = [track for track in tracks if track.is_visible()]
        layout_tracks = visible_tracks if visible_tracks else tracks
        bottom_track = layout_tracks[-1]
        for track in tracks:
            ax = track.ax
            if track is bottom_track:
                ax.tick_params(bottom=True, labelbottom=True)
            else:
                ax.tick_params(bottom=False, labelbottom=False)
                ax.set_xlabel("")
        self._update_event_gutter_visibility()

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

    def _update_event_gutter_visibility(self) -> None:
        if self._event_gutter_ax is None or self._event_gutter_pair is None:
            return
        left_id, right_id = self._event_gutter_pair
        left_track = self._tracks.get(left_id)
        right_track = self._tracks.get(right_id)
        should_show = (
            left_track is not None
            and right_track is not None
            and left_track.is_visible()
            and right_track.is_visible()
        )
        self._event_gutter_ax.set_visible(should_show)

    def _dispose_event_gutter(self) -> None:
        if self._event_label_gutter is not None:
            self._event_label_gutter.dispose()
            self._event_label_gutter = None
        self._event_gutter_collection = None
        if self._event_gutter_ax is not None and self._gutter_xlim_cid is not None:
            try:
                self._event_gutter_ax.callbacks.disconnect(self._gutter_xlim_cid)
            except Exception:
                pass
        self._gutter_xlim_cid = None

    def _configure_event_gutter(self) -> None:
        if self._event_gutter_ax is None:
            self._event_gutter_collection = None
            self._event_label_gutter = None
            self._gutter_xlim_cid = None
            return
        transform = blended_transform_factory(
            self._event_gutter_ax.transData, self._event_gutter_ax.transAxes
        )
        collection = LineCollection(
            [],
            colors=[CURRENT_THEME.get("event_line", "#8A8A8A")],
            linewidths=0.8,
            linestyles=[(0, (4, 4))],
            alpha=0.7,
            transform=transform,
            zorder=1,
        )
        self._event_gutter_ax.add_collection(collection)
        self._event_gutter_collection = collection
        if self._gutter_xlim_cid is not None:
            try:
                self._event_gutter_ax.callbacks.disconnect(self._gutter_xlim_cid)
            except Exception:
                pass
        self._gutter_xlim_cid = self._event_gutter_ax.callbacks.connect(
            "xlim_changed", self._on_gutter_xlim_changed
        )
        if self._event_label_gutter is not None:
            self._event_label_gutter.dispose()
        self._event_label_gutter = EventLabelGutter(
            self._event_gutter_ax,
            self._event_times,
            self._normalized_event_labels(),
            lanes_initial=2,
            min_gap_px=self._event_label_gap_px,
            fontsize=8,
        )
        if not self._event_labels_visible:
            self._event_label_gutter.set_events([], [])
        self._refresh_event_label_gutter_data()

    def _refresh_event_label_gutter_data(self) -> None:
        if self._event_label_gutter is None:
            return
        if not self._event_labels_visible:
            self._event_label_gutter.set_events([], [])
            return
        self._event_label_gutter.set_events(
            self._event_times,
            self._normalized_event_labels(),
        )

    def _push_events_to_tracks(self) -> None:
        if not self._tracks:
            return
        colors = self._event_colors
        labels_payload = self._event_labels if self._event_labels else None
        for track in self._tracks.values():
            track.set_events(self._event_times, colors, labels_payload)

    def _push_events_to_gutter(self) -> None:
        if self._event_gutter_collection is None or self._event_gutter_ax is None:
            return
        times = np.asarray(self._event_times, dtype=float)
        if times.size == 0:
            self._event_gutter_collection.set_segments([])
            if self._event_label_gutter is not None:
                self._event_label_gutter.set_events([], [])
            return
        x0, x1 = self._event_gutter_ax.get_xlim()
        mask = (times >= x0) & (times <= x1)
        indices = np.flatnonzero(mask)
        if indices.size:
            ordered = indices[np.argsort(times[indices])]
            segments = [((float(times[idx]), 0.0), (float(times[idx]), 1.0)) for idx in ordered]
        else:
            ordered = np.array([], dtype=int)
            segments = []
        if self._event_lines_visible:
            self._event_gutter_collection.set_segments(segments)
            if self._event_colors and len(self._event_colors) == len(self._event_times):
                active_colors = [self._event_colors[idx] for idx in ordered]
                if active_colors:
                    self._event_gutter_collection.set_colors(active_colors)
                else:
                    self._event_gutter_collection.set_colors(
                        [CURRENT_THEME.get("event_line", "#8A8A8A")]
                    )
            else:
                self._event_gutter_collection.set_colors(
                    [CURRENT_THEME.get("event_line", "#8A8A8A")]
                )
        else:
            self._event_gutter_collection.set_segments([])
        if self._event_label_gutter is not None:
            self._event_label_gutter.layout()

    def set_event_lines_visible(self, visible: bool) -> None:
        self._event_lines_visible = bool(visible)
        if self._event_gutter_collection is None:
            return
        if visible:
            self._push_events_to_gutter()
        else:
            self._event_gutter_collection.set_segments([])
            self._schedule_draw()

    def set_event_labels_visible(self, visible: bool) -> None:
        new_state = bool(visible)
        if new_state == self._event_labels_visible:
            if new_state and self._event_label_gutter is not None:
                self._refresh_event_label_gutter_data()
            elif not new_state and self._event_label_gutter is not None:
                self._event_label_gutter.set_events([], [])
                self._schedule_draw()
            return
        self._event_labels_visible = new_state
        self._rebuild_tracks()

    def set_event_label_gap(self, pixels: int) -> None:
        self._event_label_gap_px = max(int(pixels), 1)
        if self._event_label_gutter is not None:
            self._event_label_gutter.set_min_gap(self._event_label_gap_px)

    def _on_gutter_xlim_changed(self, _axes) -> None:
        self._push_events_to_gutter()

    def _normalized_event_labels(self) -> List[str]:
        if not self._event_times:
            return []
        if not self._event_labels:
            return []
        labels = list(self._event_labels[: len(self._event_times)])
        if len(labels) < len(self._event_times):
            labels.extend([""] * (len(self._event_times) - len(labels)))
        return labels
