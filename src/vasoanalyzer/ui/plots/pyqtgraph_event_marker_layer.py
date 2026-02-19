"""Event marker layer for PyQtGraph traces."""

from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg
from PyQt5.QtGui import QColor, QFont, QFontMetricsF

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3
from vasoanalyzer.ui.plots.event_display_mode import (
    EventDisplayMode,
    coerce_event_display_mode,
)
from vasoanalyzer.ui.plots.event_label_layout import PlacedLabel, layout_labels
from vasoanalyzer.ui.plots.pyqtgraph_style import get_pyqtgraph_style
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PyQtGraphEventMarkerLayer"]


@dataclass
class _MarkerItem:
    entry: EventEntryV3
    line: pg.InfiniteLine
    label: pg.TextItem


class PyQtGraphEventMarkerLayer:
    """Manages per-event marker lines and labels for a PlotItem."""

    def __init__(self, plot_item: pg.PlotItem) -> None:
        self._plot_item = plot_item
        self._items: list[_MarkerItem] = []
        self._display_mode: EventDisplayMode = EventDisplayMode.NAMES_ON_HOVER
        self._labels_visible: bool = True
        self._selected_index: int | None = None
        self._hovered_index: int | None = None
        self._last_view: tuple[float, float, int] | None = None

        style = get_pyqtgraph_style()
        self._line_style = style.event_marker
        self._line_color_override: str | None = None
        self._line_width_override: float | None = None
        self._line_style_override = None
        self._line_alpha_override: float | None = None

        self._font_family = str(style.font_family or "Arial")
        self._font_size = float(style.tick_font_size or 9.0)
        self._font = self._make_font(bold=False)
        self._font_bold = self._make_font(bold=True)
        self._label_color = self._resolve_label_color()
        self._max_label_lanes = 3
        self._min_label_gap_px = 6.0

    def clear(self) -> None:
        for item in self._items:
            try:
                self._plot_item.removeItem(item.line)
            except Exception:
                pass
            try:
                self._plot_item.removeItem(item.label)
            except Exception:
                pass
        self._items.clear()
        self._last_view = None

    def set_events(self, entries: list[EventEntryV3]) -> None:
        self.clear()
        if not entries:
            return

        for entry in entries:
            line = pg.InfiniteLine(
                pos=float(entry.t),
                angle=90,
                pen=self._make_line_pen(entry, selected=False),
                movable=False,
            )
            line.setZValue(5)

            label = pg.TextItem(
                text="",
                color=self._label_color,
                anchor=(0.5, 1.0),
            )
            label.setFont(self._font)
            label.setZValue(6)
            label.setVisible(False)

            self._plot_item.addItem(line)
            self._plot_item.addItem(label)
            self._items.append(_MarkerItem(entry=entry, line=line, label=label))

        self._apply_line_styles()
        self._apply_label_styles()

    def set_display_mode(self, mode: EventDisplayMode | str) -> None:
        resolved = coerce_event_display_mode(mode)
        if resolved == self._display_mode:
            return
        self._display_mode = resolved
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)

    def set_label_mode(self, mode: str) -> None:
        """Compatibility shim for legacy label mode API."""

        normalized = str(mode or "").strip().lower()
        if normalized in {"none", "off", "hidden", "disable", "disabled"}:
            self.set_display_mode(EventDisplayMode.OFF)
            return
        self.set_display_mode(EventDisplayMode.NAMES_ALWAYS)

    def set_labels_visible(self, visible: bool) -> None:
        self._labels_visible = bool(visible)
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)
        else:
            for item in self._items:
                item.label.setVisible(False)

    def set_selected_event(self, index: int | None) -> None:
        self._selected_index = None if index is None else int(index)
        self._apply_line_styles()
        self._apply_label_styles()
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)

    def set_hovered_event(self, index: int | None) -> None:
        resolved = None if index is None else int(index)
        if resolved == self._hovered_index:
            return
        self._hovered_index = resolved
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)

    def set_line_style(
        self,
        *,
        width: float | None = None,
        style=None,
        color: str | None = None,
        alpha: float | None = None,
    ) -> None:
        if width is not None:
            self._line_width_override = float(width)
        if style is not None:
            self._line_style_override = style
        if color is not None:
            self._line_color_override = str(color)
        if alpha is not None:
            self._line_alpha_override = float(alpha)
        self._apply_line_styles()

    def apply_theme(self) -> None:
        style = get_pyqtgraph_style()
        self._line_style = style.event_marker
        self._font_family = str(style.font_family or "Arial")
        self._font_size = float(style.tick_font_size or 9.0)
        self._font = self._make_font(bold=False)
        self._font_bold = self._make_font(bold=True)
        self._label_color = self._resolve_label_color()
        self._apply_line_styles()
        self._apply_label_styles()

    def _x_to_px_mapper(self, x_min: float, x_max: float, pixels_width: int):
        span = max(float(x_max - x_min), 1e-9)
        px_width = max(int(pixels_width), 1)

        def map_x(x_data: float) -> float:
            return ((float(x_data) - x_min) / span) * float(px_width)

        return map_x

    @staticmethod
    def _interval_overlaps(a: PlacedLabel, b: PlacedLabel, *, gap: float) -> bool:
        return not (a.x_px1 + gap <= b.x_px0 or b.x_px1 + gap <= a.x_px0)

    def refresh_for_view(self, x_min: float, x_max: float, pixels_width: int) -> None:
        if not self._items:
            return

        x_min = float(x_min)
        x_max = float(x_max)
        pixel_width = max(int(pixels_width), 1)
        self._last_view = (x_min, x_max, pixel_width)
        self._apply_line_styles()

        if not self._labels_visible or self._display_mode == EventDisplayMode.OFF:
            for item in self._items:
                item.label.setVisible(False)
            return

        visible_items = [item for item in self._items if x_min <= item.entry.t <= x_max]
        if not visible_items:
            for item in self._items:
                item.label.setVisible(False)
            return

        mode = self._display_mode
        if mode == EventDisplayMode.NAMES_ALWAYS:
            candidates = list(visible_items)
        else:
            candidates = [
                item for item in visible_items if self._is_selected(item) or self._is_hovered(item)
            ]

        if not candidates:
            for item in self._items:
                item.label.setVisible(False)
            return

        x_to_px = self._x_to_px_mapper(x_min, x_max, pixel_width)

        text_cache: dict[int, str] = {}

        def text_for(item: _MarkerItem) -> str:
            item_id = id(item)
            cached = text_cache.get(item_id)
            if cached is not None:
                return cached
            label_text = self._label_text(item)
            text_cache[item_id] = label_text
            return label_text

        metrics = QFontMetricsF(self._font_bold)

        def text_width(text: str) -> float:
            try:
                return max(0.0, float(metrics.horizontalAdvance(text)))
            except AttributeError:
                return max(0.0, float(metrics.width(text)))

        events_payload: list[tuple[int, float, str]] = []
        item_by_id: dict[int, _MarkerItem] = {}
        for item in sorted(candidates, key=lambda entry: float(entry.entry.t)):
            event_id = int(item.entry.index or 0)
            if event_id <= 0:
                continue
            text = text_for(item)
            if not text:
                continue
            events_payload.append((event_id, float(item.entry.t), text))
            item_by_id[event_id] = item

        if not events_payload:
            for item in self._items:
                item.label.setVisible(False)
            return

        placements = layout_labels(
            events=events_payload,
            x_to_px=x_to_px,
            text_width_px=text_width,
            max_lanes=self._max_label_lanes,
            min_gap_px=self._min_label_gap_px,
            hide_if_no_space=True,
        )
        by_id: dict[int, PlacedLabel] = {placement.event_id: placement for placement in placements}

        forced_ids = {
            int(item.entry.index or 0)
            for item in candidates
            if self._is_selected(item) or self._is_hovered(item)
        }
        forced_ids.discard(0)
        for forced_id in forced_ids:
            placement = by_id.get(forced_id)
            if placement is None or placement.visible:
                continue
            lane = max(0, min(placement.lane, self._max_label_lanes - 1))
            forced = PlacedLabel(
                event_id=placement.event_id,
                x_data=placement.x_data,
                lane=lane,
                visible=True,
                x_px0=placement.x_px0,
                x_px1=placement.x_px1,
            )
            for other_id, other in list(by_id.items()):
                if other_id == forced_id or not other.visible or other.lane != lane:
                    continue
                if self._interval_overlaps(forced, other, gap=self._min_label_gap_px):
                    by_id[other_id] = PlacedLabel(
                        event_id=other.event_id,
                        x_data=other.x_data,
                        lane=other.lane,
                        visible=False,
                        x_px0=other.x_px0,
                        x_px1=other.x_px1,
                    )
            by_id[forced_id] = forced

        for item in self._items:
            item.label.setVisible(False)
        for event_id, placement in by_id.items():
            marker = item_by_id.get(event_id)
            if marker is None or not placement.visible:
                continue
            text = text_for(marker)
            marker.label.setText(text)
            marker.label.setRotation(0.0)
            marker.label.setAnchor((0.5, 1.0))
            marker.label.setFont(self._font_bold if self._is_selected(marker) else self._font)
            marker.label.setPos(float(marker.entry.t), self._label_y_position(placement.lane))
            marker.label.setVisible(True)

    def _apply_line_styles(self) -> None:
        for item in self._items:
            pen = self._make_line_pen(item.entry, selected=self._is_selected(item))
            item.line.setPen(pen)

    def _apply_label_styles(self) -> None:
        for item in self._items:
            item.label.setColor(self._label_color)
            item.label.setFont(self._font_bold if self._is_selected(item) else self._font)

    def _label_text(self, item: _MarkerItem) -> str:
        text_val = str(item.entry.text or "").strip()
        if text_val:
            return text_val
        if item.entry.index is not None:
            return f"Event {int(item.entry.index)}"
        return ""

    def _is_selected(self, item: _MarkerItem) -> bool:
        if self._selected_index is None:
            return False
        index = item.entry.index
        if index is None:
            return False
        return int(index) - 1 == int(self._selected_index)

    def _is_hovered(self, item: _MarkerItem) -> bool:
        if self._hovered_index is None:
            return False
        index = item.entry.index
        if index is None:
            return False
        return int(index) - 1 == int(self._hovered_index)

    def _label_y_position(self, lane: int) -> float:
        view_range = self._plot_item.viewRange()
        if not view_range or len(view_range) < 2:
            return 0.0
        y_min_raw, y_max_raw = view_range[1]
        y_min = float(y_min_raw)
        y_max = float(y_max_raw)
        span = max(y_max - y_min, 1e-9)
        vb = self._plot_item.getViewBox()
        if vb is None:
            return y_max
        try:
            pixel_height = float(vb.height())
        except Exception:
            return y_max
        if pixel_height <= 0.0:
            return y_max

        metrics = QFontMetricsF(self._font)
        lane_height_px = metrics.height() + 3.0
        total_top_pad_px = (lane + 1) * lane_height_px
        total_top_pad_px = min(total_top_pad_px, pixel_height - 2.0)
        pad_data = (total_top_pad_px / pixel_height) * span
        return y_max - pad_data

    def _make_font(self, *, bold: bool) -> QFont:
        font = QFont(self._font_family)
        font.setPointSizeF(self._font_size)
        font.setBold(bold)
        return font

    def _resolve_label_color(self) -> str:
        color = CURRENT_THEME.get("text", "#000000")
        return str(color) if color else "#000000"

    def _entry_color(self, entry: EventEntryV3) -> str | None:
        if isinstance(entry.meta, dict):
            candidate = entry.meta.get("color") or entry.meta.get("event_color")
            if candidate:
                if isinstance(candidate, QColor):
                    return candidate.name()
                if isinstance(candidate, (tuple, list)) and len(candidate) >= 3:
                    try:
                        qcolor = QColor(*candidate[:3])
                        return qcolor.name() if qcolor.isValid() else None
                    except Exception:
                        return None
                return str(candidate)
        return None

    def _make_line_pen(self, entry: EventEntryV3, *, selected: bool):
        style = self._line_style
        color = self._line_color_override or self._entry_color(entry) or style.color
        qcolor = QColor(color)
        if not qcolor.isValid():
            qcolor = QColor(style.color)
        alpha = self._line_alpha_override
        if alpha is None:
            alpha = style.alpha
        qcolor.setAlphaF(max(0.0, min(float(alpha), 1.0)))
        width = self._line_width_override if self._line_width_override is not None else style.width
        if selected:
            width = float(width) + 1.0
        pen_style = self._line_style_override or style.style
        return pg.mkPen(color=qcolor, width=float(width), style=pen_style)
