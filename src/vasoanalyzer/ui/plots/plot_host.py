"""Core orchestration for stacked trace plotting."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.text import Text
from PyQt5.QtCore import QTimer

from vasoanalyzer.app.flags import is_enabled
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.event_labels import EventLabeler, LayoutOptions
from vasoanalyzer.ui.plots.channel_track import ChannelTrack, ChannelTrackSpec
from vasoanalyzer.ui.plots.overlays import (
    AnnotationLane,
    AnnotationSpec,
    EventHighlightOverlay,
    TimeCursorOverlay,
)
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
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.figure.subplots_adjust(left=0.095, right=0.985, top=0.985, bottom=0.115)
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
        self._annotation_lane = AnnotationLane()
        self._time_cursor_overlay = TimeCursorOverlay()
        self._event_highlight_overlay = EventHighlightOverlay()
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
        self.figure.subplots_adjust(left=0.095, right=0.985, top=0.985, bottom=0.115)
        self._tracks.clear()
        self._axes_map.clear()
        if not self._channel_specs:
            self._schedule_draw()
            return

        specs = self._channel_specs
        height_ratios: list[float] = [max(spec.height_ratio, 0.05) for spec in specs]
        row_count = len(height_ratios)
        gs = self.figure.add_gridspec(
            nrows=row_count,
            ncols=1,
            height_ratios=height_ratios,
            hspace=0.0,
        )

        shared_ax = None
        track_axes: list[tuple[Axes, str]] = []
        for index, spec in enumerate(specs):
            ax = self.figure.add_subplot(gs[index, 0], sharex=shared_ax)
            if shared_ax is None:
                shared_ax = ax
            else:
                ax.tick_params(labelbottom=False)
            ax.tick_params(colors=CURRENT_THEME["text"])
            ax.yaxis.label.set_color(CURRENT_THEME["text"])
            ax.xaxis.label.set_color(CURRENT_THEME["text"])
            ax.title.set_color(CURRENT_THEME["text"])
            ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
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

        text_objects: list[tuple[Text, float, str]] = []
        for entry, artist in self._annotation_lane.entries_with_artists():
            text_objects.append((artist, entry.time_s, entry.label))
        return text_objects

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
        self._event_label_mode = "vertical"
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
        for track in channel_tracks:
            ax = track.ax
            if track is bottom_track:
                ax.tick_params(bottom=True, labelbottom=True)
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

    def set_event_label_mode(self, mode: str) -> None:
        normalized = str(mode).lower()
        alias = {"auto": "vertical", "all": "horizontal_outside"}
        normalized = alias.get(normalized, normalized)
        if normalized not in {"vertical", "horizontal", "horizontal_outside"}:
            normalized = "vertical"

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
            self.canvas.draw()
            renderer = self.canvas.get_renderer()

        try:
            bbox = anchor_ax.get_window_extent(renderer)
            ax_width_px = max(int(bbox.width), 1)
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
        return True

    def _destroy_event_labeler(self) -> None:
        self._clear_event_label_v2()
        self.set_event_labeler(None)

    def _rebuild_event_labeler(self) -> None:
        if not self._event_labels_visible:
            self.set_event_labeler(None)
            return
        if not getattr(self, "_event_times", None):
            self.set_event_labeler(None)
            return
        labels = self._normalized_event_labels()
        if not labels:
            self.set_event_labeler(None)
            return
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
        try:
            self._last_xlim = cast(tuple[float, float], host_ax.get_xlim())
            self._last_ylim = cast(tuple[float, float], host_ax.get_ylim())
        except Exception:
            self._last_xlim = None
            self._last_ylim = None
        self._xlim_cid = host_ax.callbacks.connect("xlim_changed", self._on_view_changed)
        self._ylim_cid = host_ax.callbacks.connect("ylim_changed", self._on_view_changed)

    def _detach_view_callbacks(self) -> None:
        host_ax = self._event_labeler.host_axes if self._event_labeler else None
        if host_ax is not None:
            if self._xlim_cid is not None:
                with contextlib.suppress(Exception):
                    host_ax.callbacks.disconnect(self._xlim_cid)
            if self._ylim_cid is not None:
                with contextlib.suppress(Exception):
                    host_ax.callbacks.disconnect(self._ylim_cid)
        self._xlim_cid = None
        self._ylim_cid = None
        self._last_xlim = None
        self._last_ylim = None

    def _on_view_changed(self, ax: Axes) -> None:
        if not self._event_labeler or ax is None:
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
        try:
            self._event_labeler.draw()
        except Exception:
            return
        fig = ax.figure
        if fig is not None and getattr(fig, "canvas", None) is not None:
            fig.canvas.draw_idle()

    def _redraw_event_labels(self) -> None:
        if self._event_labeler is not None:
            self._event_labeler.draw()
