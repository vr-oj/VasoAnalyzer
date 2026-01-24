"""Event marker layer for PyQtGraph traces."""

from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg
from PyQt5.QtGui import QColor, QFont, QFontMetricsF

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3
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
        self._label_mode: str = "label_vertical"
        self._labels_visible: bool = True
        self._selected_index: int | None = None
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
                anchor=(0.5, 0.0),
            )
            label.setFont(self._font)
            label.setZValue(6)
            label.setVisible(False)

            self._plot_item.addItem(line)
            self._plot_item.addItem(label)
            self._items.append(_MarkerItem(entry=entry, line=line, label=label))

        self._apply_line_styles()
        self._apply_label_styles()

    def set_label_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized in {"none", "off", "hidden", "disable", "disabled"}:
            normalized = "none"
        if normalized not in {"label_vertical", "none"}:
            normalized = "label_vertical"
        self._label_mode = normalized
        self._apply_label_styles()
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)

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

    def refresh_for_view(self, x_min: float, x_max: float, pixels_width: int) -> None:
        if not self._items:
            return

        x_min = float(x_min)
        x_max = float(x_max)
        pixel_width = max(int(pixels_width), 1)
        self._last_view = (x_min, x_max, pixel_width)
        self._apply_line_styles()

        if not self._labels_visible or self._label_mode == "none":
            for item in self._items:
                item.label.setVisible(False)
            return

        visible_items = [item for item in self._items if x_min <= item.entry.t <= x_max]
        if not visible_items:
            for item in self._items:
                item.label.setVisible(False)
            return

        sorted_items = sorted(visible_items, key=lambda item: item.entry.t)

        for item in sorted_items:
            label_text = self._label_text(item)
            item.label.setText(label_text)
            font = self._font_bold if self._is_selected(item) else self._font
            item.label.setFont(font)
            rotation = 90.0 if self._label_mode == "label_vertical" else 0.0
            item.label.setRotation(rotation)
            item.label.setAnchor((0.5, 0.0))
            text_len_px = self._text_pixel_length(font, label_text)
            y_pos = self._label_y_position(text_len_px)
            item.label.setPos(float(item.entry.t), y_pos)

        span = max(x_max - x_min, 1e-9)
        max_labels = int(max(6, min(16, pixel_width / 120.0)))
        min_spacing = span / max_labels

        visible_flags = [False] * len(sorted_items)
        last_shown_time: float | None = None
        for idx, item in enumerate(sorted_items):
            if self._is_selected(item):
                visible_flags[idx] = True
                last_shown_time = float(item.entry.t)
                continue
            if last_shown_time is None or float(item.entry.t) - last_shown_time >= min_spacing:
                visible_flags[idx] = True
                last_shown_time = float(item.entry.t)

        previous_rect = None
        previous_item: _MarkerItem | None = None
        for idx, item in enumerate(sorted_items):
            if not visible_flags[idx]:
                item.label.setVisible(False)
                continue
            item.label.setVisible(True)
            try:
                rect = item.label.mapRectToScene(item.label.boundingRect())
            except Exception:
                rect = None
            if rect is not None and previous_rect is not None and rect.intersects(previous_rect):
                if self._is_selected(item) and previous_item is not None:
                    if not self._is_selected(previous_item):
                        previous_item.label.setVisible(False)
                        previous_rect = rect
                        previous_item = item
                        continue
                if not self._is_selected(item):
                    item.label.setVisible(False)
                    visible_flags[idx] = False
                    continue
            previous_rect = rect
            previous_item = item

        for item in self._items:
            if item not in visible_items:
                item.label.setVisible(False)

    def _apply_line_styles(self) -> None:
        for item in self._items:
            pen = self._make_line_pen(item.entry, selected=self._is_selected(item))
            item.line.setPen(pen)

    def _apply_label_styles(self) -> None:
        for item in self._items:
            item.label.setColor(self._label_color)
            if self._is_selected(item):
                item.label.setFont(self._font_bold)
            else:
                item.label.setFont(self._font)

    def _label_text(self, item: _MarkerItem) -> str:
        if self._label_mode == "none":
            return ""
        text_val = str(item.entry.text or "").strip()
        if text_val:
            return text_val
        return ""

    def _is_selected(self, item: _MarkerItem) -> bool:
        if self._selected_index is None:
            return False
        index = item.entry.index
        if index is None:
            return False
        return int(index) - 1 == int(self._selected_index)

    def _label_y_position(self, text_len_px: float) -> float:
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
        pad_px = (text_len_px / 2.0) + 4.0
        pad_data = (pad_px / pixel_height) * span
        pad_data = min(pad_data, span)
        return y_max - pad_data

    def _text_pixel_length(self, font: QFont, text: str) -> float:
        metrics = QFontMetricsF(font)
        try:
            advance = float(metrics.horizontalAdvance(text))
        except AttributeError:
            advance = float(metrics.width(text))
        return max(advance, 0.0)

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
