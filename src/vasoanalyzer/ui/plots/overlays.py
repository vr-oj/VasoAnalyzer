"""Shared plot overlays (annotation lane, time cursor, event highlights)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.text import Text

from vasoanalyzer.ui.theme import CURRENT_THEME, FONTS, css_rgba_to_mpl

__all__ = [
    "AnnotationSpec",
    "AnnotationLane",
    "TimeCursorOverlay",
    "EventHighlightOverlay",
]


@dataclass
class AnnotationSpec:
    """Description for a single timeline annotation label."""

    time_s: float
    label: str
    color: str | None = None
    category: str | None = None


class AnnotationLane:
    """Top-of-plot annotation renderer fed by event metadata."""

    def __init__(self) -> None:
        self._axes: Axes | None = None
        self._entries: list[AnnotationSpec] = []
        self._artists: list = []
        self._y_offset = 1.02  # axis-relative offset above the top spine

    # ------------------------------------------------------------------ lifecycle
    def attach(self, axes: Axes | None) -> None:
        """Attach to the primary axes (or detach when None)."""

        if self._axes is axes:
            return
        self._clear_artists()
        self._axes = axes
        if axes is not None:
            self._redraw()

    def clear(self) -> None:
        self._entries.clear()
        self._clear_artists()

    # ------------------------------------------------------------------ data update
    def set_entries(self, entries: Sequence[AnnotationSpec]) -> None:
        """Replace the displayed annotations."""

        normalized: list[AnnotationSpec] = []
        for entry in entries:
            if isinstance(entry, AnnotationSpec):
                normalized.append(entry)
            elif isinstance(entry, dict):
                normalized.append(AnnotationSpec(**entry))
            else:
                raise TypeError("Annotation entries must be AnnotationSpec or mapping")
        self._entries = sorted(normalized, key=lambda item: item.time_s)
        self._redraw()

    # ------------------------------------------------------------------ internals
    def _clear_artists(self) -> None:
        for artist in self._artists:
            with contextlib.suppress(Exception):
                artist.remove()
        self._artists.clear()

    def _redraw(self) -> None:
        axes = self._axes
        if axes is None:
            return
        self._clear_artists()
        if not self._entries:
            return

        transform = axes.get_xaxis_transform()
        default_color = CURRENT_THEME.get("text", "#000000")
        fontsize = FONTS.get("event_size", 10)
        placements: list[tuple[AnnotationSpec, Text]] = []
        for entry in sorted(self._entries, key=lambda item: item.time_s):
            text = axes.text(
                entry.time_s,
                self._y_offset,
                entry.label,
                transform=transform,
                fontsize=fontsize,
                color=entry.color or default_color,
                va="bottom",
                ha="center",
                rotation=90,
                clip_on=False,
                zorder=30,
                bbox=dict(
                    boxstyle="square,pad=0.15",
                    fc=css_rgba_to_mpl(CURRENT_THEME.get("window_bg", "#FFFFFF")),
                    ec="none",
                    alpha=0.7,
                ),
            )
            placements.append((entry, text))
            self._artists.append(text)

        canvas = getattr(axes.figure, "canvas", None)
        renderer = canvas.get_renderer() if canvas is not None else None
        if renderer is None:
            if canvas is not None and not getattr(canvas, "_is_drawing", False):
                canvas.draw_idle()
            return
        last_center = -float("inf")
        min_px = 14.0
        for _, text in placements:
            bbox = text.get_window_extent(renderer=renderer)
            center_x = bbox.x0 + (bbox.width / 2.0)
            if center_x - last_center < min_px:
                text.set_visible(False)
            else:
                text.set_visible(True)
                last_center = center_x

    def entries_with_artists(self) -> list[tuple[AnnotationSpec, Text]]:
        """Return paired (entry, artist) tuples for downstream styling."""

        pairs: list[tuple[AnnotationSpec, Text]] = []
        for entry, artist in zip(self._entries, self._artists, strict=False):
            if isinstance(artist, Text):
                pairs.append((entry, artist))
        return pairs


class TimeCursorOverlay:
    """Single shared time cursor replicated across tracks."""

    def __init__(self) -> None:
        self._lines: dict[str, Line2D] = {}
        self._time: float | None = None
        self._visible = True
        self._line_kwargs = dict(
            color=CURRENT_THEME.get("time_cursor", "#C62828"),
            linewidth=1.6,
            linestyle=(0, (5, 3)),
            alpha=0.9,
            zorder=25,
        )

    # ------------------------------------------------------------------ layout
    def sync_tracks(self, tracks: Iterable) -> None:
        """Ensure one cursor line per track axes."""

        seen: set[str] = set()
        for track in tracks:
            track_id = getattr(track, "id", None)
            axes: Axes | None = getattr(track, "ax", None)
            if track_id is None or axes is None:
                continue
            seen.add(track_id)
            line = self._lines.get(track_id)
            if line is not None:
                if line.axes is axes:
                    continue
                with contextlib.suppress(Exception):
                    line.remove()
            self._lines[track_id] = axes.axvline(0.0, visible=False, **self._line_kwargs)

        for track_id in list(self._lines.keys()):
            if track_id in seen:
                continue
            line = self._lines.pop(track_id)
            with contextlib.suppress(Exception):
                line.remove()

        self._apply_time()
        self._apply_visibility()

    # ------------------------------------------------------------------ public API
    def set_time(self, time_s: float | None) -> None:
        self._time = None if time_s is None else float(time_s)
        self._apply_time()

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._apply_visibility()

    def clear(self) -> None:
        self._time = None
        for line in self._lines.values():
            line.set_visible(False)

    def refresh(self) -> None:
        """Reapply state to existing artists after an external update."""

        self._apply_time()

    # ------------------------------------------------------------------ helpers
    def _apply_time(self) -> None:
        has_time = self._time is not None
        for line in self._lines.values():
            if has_time:
                time_value = cast(float, self._time)
                line.set_xdata([time_value, time_value])
            line.set_visible(has_time and self._visible)

    def _apply_visibility(self) -> None:
        has_time = self._time is not None
        for line in self._lines.values():
            line.set_visible(has_time and self._visible)


class EventHighlightOverlay:
    """Highlighted event marker replicated across tracks."""

    def __init__(self) -> None:
        self._lines: dict[str, Line2D] = {}
        self._time: float | None = None
        self._visible: bool = False
        self._color = CURRENT_THEME.get("event_highlight", CURRENT_THEME.get("accent", "#1D5CFF"))
        self._alpha: float = 0.95
        self._linewidth: float = 2.0
        self._linestyle: str = "--"
        self._line_kwargs = dict(
            color=self._color,
            linewidth=self._linewidth,
            linestyle=self._linestyle,
            alpha=self._alpha,
            zorder=26,
        )

    # ------------------------------------------------------------------ layout
    def sync_tracks(self, tracks: Iterable) -> None:
        """Ensure one highlight line per track axes."""

        seen: set[str] = set()
        for track in tracks:
            track_id = getattr(track, "id", None)
            axes: Axes | None = getattr(track, "ax", None)
            if track_id is None or axes is None:
                continue
            seen.add(track_id)
            line = self._lines.get(track_id)
            if line is not None:
                if line.axes is axes:
                    continue
                with contextlib.suppress(Exception):
                    line.remove()
            line = axes.axvline(0.0, visible=False, **self._line_kwargs)
            self._lines[track_id] = line
            self._apply_style(line)

        for track_id in list(self._lines.keys()):
            if track_id in seen:
                continue
            line = self._lines.pop(track_id)
            with contextlib.suppress(Exception):
                line.remove()

        self._apply_time()
        self._apply_visibility()

    # ------------------------------------------------------------------ public API
    def set_time(self, time_s: float | None) -> None:
        self._time = None if time_s is None else float(time_s)
        self._apply_time()

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._apply_visibility()

    def clear(self) -> None:
        self._time = None
        for line in self._lines.values():
            line.set_visible(False)

    def refresh(self) -> None:
        """Reapply state to existing artists after an external update."""

        self._apply_style()
        self._apply_time()

    def apply_theme(self) -> None:
        """Reapply styling to existing lines after a theme change."""

        self._apply_style()
        self._apply_time()

    # ------------------------------------------------------------------ helpers
    def _apply_time(self) -> None:
        has_time = self._time is not None
        for line in self._lines.values():
            if has_time:
                time_value = cast(float, self._time)
                line.set_xdata([time_value, time_value])
            line.set_visible(has_time and self._visible)

    def _apply_visibility(self) -> None:
        has_time = self._time is not None
        for line in self._lines.values():
            line.set_visible(has_time and self._visible)

    def _apply_style(self, target: Line2D | None = None) -> None:
        lines = [target] if target is not None else list(self._lines.values())
        for line in lines:
            if line is None:
                continue
            line.set_color(self._color)
            line.set_linewidth(self._linewidth)
            line.set_linestyle(self._linestyle)
            line.set_alpha(self._alpha)

    # ------------------------------------------------------------------ styling api
    def set_style(
        self,
        *,
        color: str | None = None,
        alpha: float | None = None,
        linewidth: float | None = None,
        linestyle: str | None = None,
    ) -> None:
        if color is not None:
            self._color = str(color)
        if alpha is not None:
            self._alpha = max(0.0, min(float(alpha), 1.0))
        if linewidth is not None:
            self._linewidth = max(0.1, float(linewidth))
        if linestyle is not None:
            self._linestyle = linestyle
        self._apply_style()

    def set_alpha(self, alpha: float) -> None:
        self._alpha = max(0.0, min(float(alpha), 1.0))
        self._apply_style()

    def alpha(self) -> float:
        return self._alpha
