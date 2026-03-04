"""Event marker layer for PyQtGraph traces."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3
from vasoanalyzer.ui.plots.event_display_mode import (
    EventDisplayMode,
    coerce_event_display_mode,
)
from vasoanalyzer.ui.plots.pyqtgraph_style import get_pyqtgraph_style
from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)

__all__ = ["PyQtGraphEventMarkerLayer"]


@dataclass
class _MarkerItem:
    entry: EventEntryV3
    line: pg.InfiniteLine
    label: pg.TextItem | None = field(default=None)


class PyQtGraphEventMarkerLayer:
    """Manages per-event dashed marker lines for a PlotItem.

    Each event is rendered as a dashed vertical InfiniteLine spanning the
    full channel height.  The selected or hovered event switches to a solid
    line for visual emphasis.

    An *optional* vertical text label can be shown next to each line via
    ``set_channel_labels_visible(True)``.  Labels are off by default.
    Event index numbers are surfaced exclusively in the shared top-lane
    strip above all channels (PyQtGraphEventStripTrack).
    """

    def __init__(self, plot_item: pg.PlotItem) -> None:
        self._plot_item = plot_item
        self._items: list[_MarkerItem] = []
        self._display_mode: EventDisplayMode = EventDisplayMode.NAMES_ON_HOVER
        self._selected_index: int | None = None
        self._hovered_index: int | None = None
        self._last_view: tuple[float, float, int] | None = None
        self._channel_labels_visible: bool = False

        style = get_pyqtgraph_style()
        self._line_style = style.event_marker
        self._line_color_override: str | None = None
        self._line_width_override: float | None = None
        self._line_style_override = None
        self._line_alpha_override: float | None = None

        self._font_family = str(style.font_family or "Arial")
        self._font_size = float(style.tick_font_size or 9.0)
        self._font = self._make_font(bold=False)
        self._label_color = self._resolve_label_color()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear(self) -> None:
        for item in self._items:
            try:
                self._plot_item.removeItem(item.line)
            except Exception:
                log.debug("Failed to remove event marker line", exc_info=True)
            if item.label is not None:
                try:
                    self._plot_item.removeItem(item.label)
                except Exception:
                    log.debug("Failed to remove event marker label", exc_info=True)
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
                pen=self._make_line_pen(entry, selected=False, hovered=False),
                movable=False,
            )
            line.setZValue(5)
            tooltip = self._event_tooltip(entry)
            with contextlib.suppress(Exception):
                line.setToolTip(tooltip)

            # Vertical text label — hidden by default, enabled by
            # set_channel_labels_visible(True).  anchor=(0, 1) with
            # rotation=-90° places the right edge of the rotated text at the
            # set position (x=entry.t), so text sits entirely to the left of
            # the dashed line and reads upward from y_bottom near the x-axis.
            label = pg.TextItem(
                text="",
                color=self._label_color,
                anchor=(0, 1),
            )
            label.setFont(self._font)
            label.setRotation(-90)
            label.setZValue(6)
            label.setVisible(False)
            with contextlib.suppress(Exception):
                label.setToolTip(tooltip)

            self._plot_item.addItem(line)
            self._plot_item.addItem(label)
            self._items.append(_MarkerItem(entry=entry, line=line, label=label))

        self._apply_line_styles()

    def set_channel_labels_visible(self, visible: bool) -> None:
        """Show or hide the optional vertical text labels in channel tracks."""
        self._channel_labels_visible = bool(visible)
        if self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)
        else:
            for item in self._items:
                if item.label is not None:
                    item.label.setVisible(False)

    def set_label_font_size(self, size_pt: float) -> None:
        """Set the point size for vertical channel event text labels."""
        self._font_size = max(float(size_pt), 5.0)
        self._font = self._make_font(bold=False)
        self._apply_label_styles()
        if self._channel_labels_visible and self._last_view is not None:
            x_min, x_max, pixel_width = self._last_view
            self.refresh_for_view(x_min, x_max, pixel_width)

    def set_display_mode(self, mode: EventDisplayMode | str) -> None:
        self._display_mode = coerce_event_display_mode(mode)

    def set_label_mode(self, mode: str) -> None:
        """Compatibility shim — channel labels controlled via set_channel_labels_visible."""

    def set_labels_visible(self, visible: bool) -> None:
        """Compatibility shim — channel labels controlled via set_channel_labels_visible."""

    def set_selected_event(self, index: int | None) -> None:
        self._selected_index = None if index is None else int(index)
        self._apply_line_styles()

    def set_hovered_event(self, index: int | None) -> None:
        resolved = None if index is None else int(index)
        if resolved == self._hovered_index:
            return
        self._hovered_index = resolved
        self._apply_line_styles()

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
        self._label_color = self._resolve_label_color()
        self._apply_line_styles()
        self._apply_label_styles()

    # ------------------------------------------------------------------
    # Per-frame layout
    # ------------------------------------------------------------------

    def refresh_for_view(self, x_min: float, x_max: float, pixels_width: int) -> None:
        if not self._items:
            return

        x_min = float(x_min)
        x_max = float(x_max)
        self._last_view = (x_min, x_max, max(int(pixels_width), 1))
        self._apply_line_styles()

        # Hide all labels first.
        for item in self._items:
            if item.label is not None:
                item.label.setVisible(False)

        if not self._channel_labels_visible:
            return

        # Determine bottom-of-channel y in data coordinates.
        view_range = self._plot_item.viewRange()
        if not view_range or len(view_range) < 2:
            return
        y_min_raw, y_max_raw = view_range[1]
        y_span = max(float(y_max_raw - y_min_raw), 1e-9)
        # Place label text starting very close to the x-axis (bottom edge).
        y_bottom = float(y_min_raw) + y_span * 0.01

        for item in self._items:
            if item.label is None:
                continue
            if not (x_min <= item.entry.t <= x_max):
                continue
            text = self._channel_label_text(item)
            if not text:
                continue
            item.label.setText(text)
            item.label.setPos(float(item.entry.t), y_bottom)
            item.label.setVisible(True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_line_styles(self) -> None:
        for item in self._items:
            is_sel = self._is_selected(item)
            is_hov = self._is_hovered(item)
            pen = self._make_line_pen(item.entry, selected=is_sel, hovered=is_hov)
            item.line.setPen(pen)

    def _apply_label_styles(self) -> None:
        for item in self._items:
            if item.label is not None:
                item.label.setColor(self._label_color)
                item.label.setFont(self._font)

    def _channel_label_text(self, item: _MarkerItem) -> str:
        """Event text displayed as a vertical label inside the channel."""
        text_val = str(item.entry.text or "").strip()
        return text_val

    def _event_tooltip(self, entry: EventEntryV3) -> str:
        text_val = str(entry.text or "").strip()
        if not text_val and entry.index is not None:
            text_val = f"Event {int(entry.index)}"
        if not text_val:
            text_val = "Event"
        try:
            time_text = f"{float(entry.t):.3f} s"
        except Exception:
            time_text = "--"
        return f"{text_val}\nTime: {time_text}"

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

    def _make_font(self, *, bold: bool = False) -> QFont:
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

    # Highlight colors for selected / hovered events.
    # Deliberately differ from the red time-cursor (#DC2626) so users
    # cannot confuse the two.
    _SELECTED_COLOR = "#1976D2"   # solid blue — confirmed selection
    _HOVERED_COLOR  = "#42A5F5"   # lighter blue — hover preview

    def _make_line_pen(self, entry: EventEntryV3, *, selected: bool, hovered: bool = False):
        style = self._line_style
        if selected:
            qcolor = QColor(self._SELECTED_COLOR)
            qcolor.setAlphaF(1.0)
            return pg.mkPen(color=qcolor, width=2.5, style=Qt.SolidLine)
        if hovered:
            qcolor = QColor(self._HOVERED_COLOR)
            qcolor.setAlphaF(0.85)
            return pg.mkPen(color=qcolor, width=2.0, style=Qt.SolidLine)
        color = self._line_color_override or self._entry_color(entry) or style.color
        qcolor = QColor(color)
        if not qcolor.isValid():
            qcolor = QColor(style.color)
        alpha = self._line_alpha_override if self._line_alpha_override is not None else style.alpha
        qcolor.setAlphaF(max(0.0, min(float(alpha), 1.0)))
        width = self._line_width_override if self._line_width_override is not None else style.width
        pen_style = (
            self._line_style_override
            if self._line_style_override is not None
            else Qt.DashLine
        )
        return pg.mkPen(color=qcolor, width=float(width), style=pen_style)
