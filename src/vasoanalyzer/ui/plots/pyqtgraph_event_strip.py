"""Thin event strip track for PyQtGraph event annotations."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass

import pyqtgraph as pg
from PyQt5.QtGui import QFont, QFontMetricsF
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.event_display_mode import (
    EventDisplayMode,
    coerce_event_display_mode,
)
from vasoanalyzer.ui.plots.event_label_layout import (
    PlacedLabel,
    choose_event_label_lod,
    layout_labels,
)
from vasoanalyzer.ui.theme import CURRENT_THEME, hex_to_pyqtgraph_color

log = logging.getLogger(__name__)

_LABEL_MAX_CHARS = 12
_LABEL_ELLIPSIS = "..."
_TOOLTIP_TIME_DECIMALS = 3


def _truncate_event_label(text: str, *, max_chars: int = _LABEL_MAX_CHARS) -> str:
    """Return a compact single-line label for dense strip rendering."""
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    limit = max(int(max_chars), len(_LABEL_ELLIPSIS) + 1)
    if len(normalized) <= limit:
        return normalized
    keep = max(limit - len(_LABEL_ELLIPSIS), 1)
    return normalized[:keep].rstrip() + _LABEL_ELLIPSIS


@dataclass
class _StripItem:
    event_id: int
    entry: EventEntryV3
    line: pg.PlotDataItem
    label: pg.TextItem
    label_text: str


class PyQtGraphEventStripTrack:
    """
    Lightweight track that renders event markers + labels in a thin strip.

    The strip owns its own PlotItem with a fixed y-range (0..1),
    hidden axes/grid, and a linked x-axis (configured by the host).
    """

    def __init__(self, plot_item: pg.PlotItem):
        self._plot_item = plot_item
        self._items_by_id: dict[int, _StripItem] = {}
        self._event_order: list[int] = []
        self._options: LayoutOptionsV3 | None = None
        self._last_signature: tuple | None = None
        self._font: QFont | None = None
        self._font_metrics: QFontMetricsF | None = None
        self._display_mode = EventDisplayMode.NAMES_ALWAYS
        self._selected_event_id: int | None = None
        self._hovered_event_id: int | None = None

        def _mute_axis(axis, *, height: float | None = None) -> None:
            if axis is None:
                return
            try:
                axis.setStyle(showValues=False, tickLength=0)
            except Exception:
                pass
            try:
                axis.setLabel("")
            except Exception:
                pass
            with contextlib.suppress(Exception):
                axis.setTicks([])
            with contextlib.suppress(Exception):
                axis.label.hide()
                axis.showLabel(False)
            transparent = pg.mkPen((0, 0, 0, 0))
            with contextlib.suppress(Exception):
                axis.setPen(transparent)
            with contextlib.suppress(Exception):
                axis.setTextPen(transparent)
            if height is not None:
                with contextlib.suppress(Exception):
                    axis.setHeight(height)

        vb = self._plot_item.getViewBox()
        vb.setYRange(0.0, 1.0, padding=0.0)
        vb.disableAutoRange(axis=pg.ViewBox.XAxis)
        vb.disableAutoRange(axis=pg.ViewBox.YAxis)
        vb.setMouseMode(pg.ViewBox.PanMode)
        vb.setMouseEnabled(x=False, y=False)
        # Ignore wheel/trackpad on the strip; main trace handles panning.
        try:
            vb.wheelEvent = lambda ev: ev.accept()
        except Exception:
            pass
        self._plot_item.hideButtons()

        self._plot_item.showAxis("left")
        self._plot_item.showAxis("bottom")
        _mute_axis(self._plot_item.getAxis("left"))
        _mute_axis(self._plot_item.getAxis("bottom"), height=0)
        layout = getattr(self._plot_item, "layout", None)
        if layout is not None:
            with contextlib.suppress(Exception):
                layout.setContentsMargins(0, 0, 0, 0)
            with contextlib.suppress(Exception):
                layout.setHorizontalSpacing(0)
            with contextlib.suppress(Exception):
                layout.setVerticalSpacing(0)
        self._plot_item.showGrid(x=False, y=False)
        # Match app theme background - use plot_bg for white content area
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        bg_rgb = hex_to_pyqtgraph_color(bg)
        with contextlib.suppress(Exception):
            vb.setBackgroundColor(bg_rgb)
        with contextlib.suppress(Exception):
            vb.sigRangeChanged.connect(lambda *_args: self._refresh_from_current_view())

    @property
    def plot_item(self) -> pg.PlotItem:
        return self._plot_item

    def set_visible(self, visible: bool) -> None:
        self._plot_item.setVisible(visible)

    def clear(self) -> None:
        for item in list(self._items_by_id.values()):
            with contextlib.suppress(Exception):
                self._plot_item.removeItem(item.label)
            with contextlib.suppress(Exception):
                self._plot_item.removeItem(item.line)
        self._items_by_id.clear()
        self._event_order.clear()

    def set_display_mode(self, mode: EventDisplayMode | str) -> None:
        resolved = coerce_event_display_mode(mode)
        if resolved == self._display_mode:
            return
        self._display_mode = resolved
        self._refresh_from_current_view()

    def set_selected_event(self, index: int | None) -> None:
        self._selected_event_id = None if index is None else (int(index) + 1)
        self._refresh_from_current_view()

    def set_hovered_event(self, index: int | None) -> None:
        self._hovered_event_id = None if index is None else (int(index) + 1)
        self._refresh_from_current_view()

    def _build_font(self, options: LayoutOptionsV3) -> QFont | None:
        try:
            font_size = float(getattr(options, "font_size", 10.0) or 10.0)
            font_family = getattr(options, "font_family", "Arial") or "Arial"
            font = QFont(font_family)
            font.setPointSizeF(font_size)
            if getattr(options, "font_bold", False):
                font.setBold(True)
            if getattr(options, "font_italic", False):
                font.setItalic(True)
            return font
        except Exception:
            return None

    def _default_text_color(self, options: LayoutOptionsV3) -> str:
        theme_text = CURRENT_THEME.get("text", "#000000")
        color = options.font_color or theme_text
        if (
            isinstance(color, str)
            and color.strip().lower() == "#000000"
            and theme_text.lower() != "#000000"
        ):
            return str(theme_text)
        return str(color)

    def set_events(self, entries: Iterable[EventEntryV3], options: LayoutOptionsV3) -> None:
        """Rebuild markers and labels from the given events."""

        t0 = time.perf_counter()
        try:
            entries_list = list(entries)
            # Simple signature to avoid redundant rebuilds
            signature = (
                len(entries_list),
                getattr(options, "font_family", None),
                getattr(options, "font_size", None),
                getattr(options, "font_bold", None),
                getattr(options, "font_italic", None),
                getattr(options, "font_color", None),
                bool(getattr(options, "show_numbers_only", False)),
                tuple(
                    (e.t, e.text, e.index, tuple(sorted((e.meta or {}).items())))
                    for e in entries_list
                ),
            )
            if self._last_signature == signature:
                return
            self._last_signature = signature

            self._options = options
            self._font = self._build_font(options)
            self._font_metrics = QFontMetricsF(self._font) if self._font is not None else None

            color_default = self._default_text_color(options)
            stale_ids = set(self._items_by_id.keys())
            event_order: list[int] = []
            for fallback_id, entry in enumerate(entries_list, start=1):
                event_id = int(entry.index) if entry.index is not None else fallback_id
                event_order.append(event_id)
                meta_color = None
                if isinstance(entry.meta, dict):
                    meta_color = entry.meta.get("color") or entry.meta.get("event_color")
                color = meta_color or color_default
                label_text = str(entry.index) if entry.index is not None else str(event_id)

                strip_item = self._items_by_id.get(event_id)
                if strip_item is None:
                    line = self._plot_item.plot([0.0, 0.0], [0.0, 0.2], pen=color)
                    line.setZValue(5)
                    text_item = pg.TextItem(text=label_text, color=color, anchor=(0.5, 0.5))
                    text_item.setZValue(6)
                    self._plot_item.addItem(text_item)
                    strip_item = _StripItem(
                        event_id=event_id,
                        entry=entry,
                        line=line,
                        label=text_item,
                        label_text=label_text,
                    )
                    self._items_by_id[event_id] = strip_item

                strip_item.entry = entry
                strip_item.label_text = label_text
                x = float(entry.t)
                strip_item.line.setData([x, x], [0.0, 0.2])
                strip_item.line.setPen(color)
                strip_item.label.setText(self._display_label_text(strip_item))
                strip_item.label.setColor(color)
                if self._font is not None:
                    strip_item.label.setFont(self._font)
                tooltip = self._tooltip_text(strip_item)
                with contextlib.suppress(Exception):
                    strip_item.line.setToolTip(tooltip)
                with contextlib.suppress(Exception):
                    strip_item.label.setToolTip(tooltip)

                stale_ids.discard(event_id)

            for stale_id in stale_ids:
                stale_item = self._items_by_id.pop(stale_id, None)
                if stale_item is None:
                    continue
                with contextlib.suppress(Exception):
                    self._plot_item.removeItem(stale_item.label)
                with contextlib.suppress(Exception):
                    self._plot_item.removeItem(stale_item.line)
            self._event_order = event_order
            self._refresh_from_current_view()
        finally:
            log.debug(
                "PyQtGraphEventStrip.set_events completed in %.3f s",
                time.perf_counter() - t0,
            )

    def apply_style(self, options: LayoutOptionsV3) -> None:
        """Reapply font/color to existing labels without rebuilding."""

        self._options = options
        color = self._default_text_color(options)
        self._font = self._build_font(options)
        self._font_metrics = QFontMetricsF(self._font) if self._font is not None else None

        for item in self._items_by_id.values():
            item.line.setPen(color)
            item.label.setColor(color)
            if self._font is not None:
                item.label.setFont(self._font)
        # Force signature refresh next time style changes
        self._last_signature = None
        self._refresh_from_current_view()

    @staticmethod
    def _interval_overlaps(a: PlacedLabel, b: PlacedLabel, *, gap: float) -> bool:
        return not (a.x_px1 + gap <= b.x_px0 or b.x_px1 + gap <= a.x_px0)

    def _x_to_px_mapper(self, x_min: float, x_max: float, pixels_width: int):
        span = max(float(x_max - x_min), 1e-9)
        px_width = max(int(pixels_width), 1)

        def map_x(x_data: float) -> float:
            return ((float(x_data) - x_min) / span) * float(px_width)

        return map_x

    def refresh_for_view(self, x_min: float, x_max: float, pixels_width: int) -> None:
        if not self._items_by_id:
            return

        x_min = float(x_min)
        x_max = float(x_max)
        pixel_width = max(int(pixels_width), 1)
        max_lanes = 3
        if self._options is not None:
            max_lanes = max(2, min(3, int(getattr(self._options, "lanes", 3) or 3)))
        min_gap = float(
            getattr(self._options, "min_px", 6) if self._options is not None else 6.0
        )

        visible_ids = []
        for event_id in self._event_order:
            item = self._items_by_id.get(event_id)
            if item is None:
                continue
            x_val = float(item.entry.t)
            in_view = x_min <= x_val <= x_max
            item.line.setVisible(in_view)
            if in_view:
                visible_ids.append(event_id)

        if self._display_mode != EventDisplayMode.INDICES:
            for item in self._items_by_id.values():
                item.label.setVisible(False)
        if self._display_mode == EventDisplayMode.OFF or not visible_ids:
            return

        lod_mode = choose_event_label_lod(
            visible_event_count=len(visible_ids),
            pixel_width=pixel_width,
            min_spacing_px=max(14.0, min_gap * 1.25),
        )
        if lod_mode == "markers_only":
            for item in self._items_by_id.values():
                item.label.setVisible(False)
            return

        x_to_px = self._x_to_px_mapper(x_min, x_max, pixel_width)
        if self._font_metrics is None and self._font is not None:
            self._font_metrics = QFontMetricsF(self._font)

        def text_width_px(text: str) -> float:
            if self._font_metrics is None:
                return max(8.0, float(len(text)) * 7.0)
            try:
                return float(self._font_metrics.horizontalAdvance(text))
            except AttributeError:
                return float(self._font_metrics.width(text))

        if self._display_mode == EventDisplayMode.NAMES_ON_HOVER:
            candidate_ids = list(
                dict.fromkeys(
                    event_id
                    for event_id in (self._selected_event_id, self._hovered_event_id)
                    if event_id in visible_ids
                )
            )
        else:
            candidate_ids = list(visible_ids)

        event_payload = []
        for event_id in candidate_ids:
            item = self._items_by_id.get(event_id)
            if item is None:
                continue
            label_text = self._display_label_text(item)
            if not label_text:
                continue
            event_payload.append((event_id, float(item.entry.t), label_text))
        placements = layout_labels(
            events=event_payload,
            x_to_px=x_to_px,
            text_width_px=text_width_px,
            max_lanes=max_lanes,
            min_gap_px=min_gap,
            hide_if_no_space=True,
        )
        by_id: dict[int, PlacedLabel] = {placement.event_id: placement for placement in placements}

        forced_ids = {
            event_id
            for event_id in (self._selected_event_id, self._hovered_event_id)
            if event_id in by_id
        }
        for forced_id in forced_ids:
            placement = by_id.get(forced_id)
            if placement is None or placement.visible:
                continue
            forced_lane = max(0, min(placement.lane, max_lanes - 1))
            forced = PlacedLabel(
                event_id=placement.event_id,
                x_data=placement.x_data,
                lane=forced_lane,
                visible=True,
                x_px0=placement.x_px0,
                x_px1=placement.x_px1,
            )
            for other_id, other in list(by_id.items()):
                if other_id == forced_id or not other.visible or other.lane != forced_lane:
                    continue
                if self._interval_overlaps(forced, other, gap=min_gap):
                    by_id[other_id] = PlacedLabel(
                        event_id=other.event_id,
                        x_data=other.x_data,
                        lane=other.lane,
                        visible=False,
                        x_px0=other.x_px0,
                        x_px1=other.x_px1,
                    )
            by_id[forced_id] = forced

        lane_step = 0.16
        lane_base = 0.45
        for event_id in visible_ids:
            item = self._items_by_id.get(event_id)
            if item is None:
                continue
            placement = by_id.get(event_id)
            if placement is None or not placement.visible:
                item.label.setVisible(False)
                continue
            item.label.setText(self._display_label_text(item))
            y = lane_base + (lane_step * float(placement.lane))
            y = max(0.2, min(0.92, y))
            item.label.setPos(float(item.entry.t), y)
            item.label.setVisible(True)

        for event_id, item in self._items_by_id.items():
            if event_id not in visible_ids:
                item.label.setVisible(False)

    def _full_label_text(self, item: _StripItem) -> str:
        text = str(item.entry.text or "").strip()
        if text:
            return text
        if item.entry.index is not None:
            return f"Event {int(item.entry.index)}"
        return f"Event {int(item.event_id)}"

    def _short_label_text(self, item: _StripItem) -> str:
        text = str(item.entry.text or "").strip()
        if text:
            return _truncate_event_label(text, max_chars=_LABEL_MAX_CHARS)
        if item.entry.index is not None:
            return str(int(item.entry.index))
        return str(int(item.event_id))

    def _tooltip_text(self, item: _StripItem) -> str:
        label = self._full_label_text(item)
        time_s = float(item.entry.t)
        return f"{label}\nTime: {time_s:.{_TOOLTIP_TIME_DECIMALS}f} s"

    def _display_label_text(self, item: _StripItem) -> str:
        return self._short_label_text(item)

    def _refresh_from_current_view(self) -> None:
        if not self._items_by_id:
            return
        vb = self._plot_item.getViewBox()
        if vb is None:
            return
        view_range = self._plot_item.viewRange()
        if not view_range or len(view_range) < 1:
            return
        x_min_raw, x_max_raw = view_range[0]
        try:
            pixel_width = int(max(vb.width(), 1))
        except Exception:
            pixel_width = 1
        self.refresh_for_view(float(x_min_raw), float(x_max_raw), pixel_width)

    def apply_theme(self) -> None:
        """Refresh background and label colors from CURRENT_THEME."""

        vb = self._plot_item.getViewBox()
        # Use plot_bg for white content area in light mode
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        bg_rgb = hex_to_pyqtgraph_color(bg)
        with contextlib.suppress(Exception):
            vb.setBackgroundColor(bg_rgb)

        if self._options is not None:
            self.apply_style(self._options)

        # Force immediate visual update
        try:
            self._plot_item.update()
            QApplication.processEvents()
        except Exception:
            pass
