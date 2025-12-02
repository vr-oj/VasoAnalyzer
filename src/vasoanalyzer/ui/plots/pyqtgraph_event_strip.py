"""Thin event strip track for PyQtGraph that shows numbered event labels."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable

import pyqtgraph as pg

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.theme import CURRENT_THEME


class PyQtGraphEventStripTrack:
    """
    Lightweight track that renders event markers + labels in a thin strip.

    The strip owns its own PlotItem with a fixed y-range (0..1),
    hidden axes/grid, and a linked x-axis (configured by the host).
    """

    def __init__(self, plot_item: pg.PlotItem):
        self._plot_item = plot_item
        self._labels: list[pg.TextItem] = []
        self._lines: list[pg.InfiniteLine] = []
        self._options: LayoutOptionsV3 | None = None
        self._last_signature: tuple | None = None

        vb = self._plot_item.getViewBox()
        vb.setYRange(0.0, 1.0, padding=0.0)
        vb.disableAutoRange(axis=pg.ViewBox.XAxis)
        vb.disableAutoRange(axis=pg.ViewBox.YAxis)
        self._plot_item.hideButtons()

        self._plot_item.hideAxis("left")
        self._plot_item.hideAxis("bottom")
        self._plot_item.showGrid(x=False, y=False)
        # Match app theme background
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        with contextlib.suppress(Exception):
            vb.setBackgroundColor(bg)

    @property
    def plot_item(self) -> pg.PlotItem:
        return self._plot_item

    def set_visible(self, visible: bool) -> None:
        self._plot_item.setVisible(visible)

    def clear(self) -> None:
        for item in self._labels:
            self._plot_item.removeItem(item)
        for line in self._lines:
            self._plot_item.removeItem(line)
        self._labels.clear()
        self._lines.clear()

    def set_events(self, entries: Iterable[EventEntryV3], options: LayoutOptionsV3) -> None:
        """Rebuild markers and labels from the given events."""

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
                (e.t, e.text, e.index, tuple(sorted((e.meta or {}).items()))) for e in entries_list
            ),
        )
        if self._last_signature == signature:
            return
        self._last_signature = signature

        self.clear()
        self._options = options

        theme_text = CURRENT_THEME.get("text", "#000000")
        color_default = options.font_color or theme_text
        if (
            isinstance(color_default, str)
            and color_default.strip().lower() == "#000000"
            and theme_text.lower() != "#000000"
        ):
            color_default = theme_text
        show_numbers_only = bool(getattr(options, "show_numbers_only", False))
        font = None
        try:
            from PyQt5.QtGui import QFont

            font_size = float(getattr(options, "font_size", 10.0) or 10.0)
            font_family = getattr(options, "font_family", "Arial") or "Arial"
            font = QFont(font_family)
            font.setPointSizeF(font_size)
            if getattr(options, "font_bold", False):
                font.setBold(True)
            if getattr(options, "font_italic", False):
                font.setItalic(True)
        except Exception:
            font = None

        for entry in entries_list:
            x = float(entry.t)
            meta_color = None
            if isinstance(entry.meta, dict):
                meta_color = entry.meta.get("color") or entry.meta.get("event_color")
            color = meta_color or color_default
            label_text = str(entry.index)
            text_val = getattr(entry, "text", None)
            if not show_numbers_only and text_val and str(text_val).strip():
                label_text = str(text_val)

            # Short vertical tick (bottom to just below the label)
            y_bottom = 0.0
            y_top = 0.2
            line = self._plot_item.plot([x, x], [y_bottom, y_top], pen=color)
            line.setZValue(5)
            self._lines.append(line)

            # Text centered vertically in strip
            text_item = pg.TextItem(text=label_text, color=color, anchor=(0.5, 0.5))
            if font is not None:
                text_item.setFont(font)
            text_item.setPos(x, 0.5)
            text_item.setZValue(6)
            self._plot_item.addItem(text_item)
            self._labels.append(text_item)

    def apply_style(self, options: LayoutOptionsV3) -> None:
        """Reapply font/color to existing labels without rebuilding."""

        self._options = options
        theme_text = CURRENT_THEME.get("text", "#000000")
        color = options.font_color or theme_text
        if (
            isinstance(color, str)
            and color.strip().lower() == "#000000"
            and theme_text.lower() != "#000000"
        ):
            color = theme_text
        font = None
        try:
            from PyQt5.QtGui import QFont

            font_size = float(getattr(options, "font_size", 10.0) or 10.0)
            font_family = getattr(options, "font_family", "Arial") or "Arial"
            font = QFont(font_family)
            font.setPointSizeF(font_size)
            if getattr(options, "font_bold", False):
                font.setBold(True)
            if getattr(options, "font_italic", False):
                font.setItalic(True)
        except Exception:
            font = None

        for line in self._lines:
            line.setPen(color)
        for text_item in self._labels:
            text_item.setColor(color)
            if font is not None:
                text_item.setFont(font)
        # Force signature refresh next time style changes
        self._last_signature = None

    def apply_theme(self) -> None:
        """Refresh background and label colors from CURRENT_THEME."""

        vb = self._plot_item.getViewBox()
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        with contextlib.suppress(Exception):
            vb.setBackgroundColor(bg)

        if self._options is not None:
            self.apply_style(self._options)
