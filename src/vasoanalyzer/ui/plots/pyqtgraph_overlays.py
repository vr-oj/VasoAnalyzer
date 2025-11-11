"""PyQtGraph-based overlays for cursor, event highlighting, and annotations."""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

__all__ = [
    "PyQtGraphTimeCursorOverlay",
    "PyQtGraphEventHighlightOverlay",
]


class PyQtGraphTimeCursorOverlay:
    """Vertical cursor line that spans all tracks.

    Provides visual feedback for the current time position.
    """

    def __init__(self) -> None:
        self._cursor_lines: list[pg.InfiniteLine] = []
        self._visible: bool = False
        self._time: float | None = None
        self._color: str = "#FF0000"
        self._width: float = 1.5

    def sync_tracks(self, plot_items: list[pg.PlotItem]) -> None:
        """Synchronize cursor across multiple tracks.

        Args:
            plot_items: List of PyQtGraph PlotItems to show cursor on
        """
        # Remove old cursor lines (safely handle deleted Qt objects)
        for line in self._cursor_lines:
            try:
                if line.scene() is not None:
                    line.scene().removeItem(line)
            except RuntimeError:
                # Qt object already deleted
                pass
        self._cursor_lines.clear()

        # Create new cursor lines for each plot item
        for plot_item in plot_items:
            line = pg.InfiniteLine(
                pos=self._time if self._time is not None else 0,
                angle=90,
                pen=pg.mkPen(color=self._color, width=self._width),
                movable=False,
            )
            line.setZValue(15)  # Above event lines
            line.setVisible(self._visible)
            plot_item.addItem(line)
            self._cursor_lines.append(line)

    def set_time(self, time: float) -> None:
        """Set cursor time position.

        Args:
            time: Time value to position cursor at
        """
        self._time = time
        for line in self._cursor_lines:
            try:
                line.setPos(time)
            except RuntimeError:
                # Qt object already deleted
                pass

    def set_visible(self, visible: bool) -> None:
        """Show/hide cursor.

        Args:
            visible: Whether cursor should be visible
        """
        self._visible = visible
        for line in self._cursor_lines:
            try:
                line.setVisible(visible)
            except RuntimeError:
                # Qt object already deleted
                pass

    def set_style(self, color: str | None = None, width: float | None = None) -> None:
        """Set cursor visual style.

        Args:
            color: Line color
            width: Line width in pixels
        """
        if color is not None:
            self._color = color
        if width is not None:
            self._width = width

        # Update existing lines
        for line in self._cursor_lines:
            try:
                pen = pg.mkPen(color=self._color, width=self._width)
                line.setPen(pen)
            except RuntimeError:
                # Qt object already deleted
                pass


class PyQtGraphEventHighlightOverlay:
    """Vertical highlight region for selected events.

    Provides visual feedback when an event is selected.
    """

    def __init__(self) -> None:
        self._highlight_regions: list[pg.LinearRegionItem] = []
        self._visible: bool = False
        self._time: float | None = None
        self._color: str = "#1D5CFF"
        self._alpha: float = 0.2
        self._width: float = 2.0  # Width in data units

    def sync_tracks(self, plot_items: list[pg.PlotItem]) -> None:
        """Synchronize highlight across multiple tracks.

        Args:
            plot_items: List of PyQtGraph PlotItems to show highlight on
        """
        # Remove old highlight regions (safely handle deleted Qt objects)
        for region in self._highlight_regions:
            try:
                if region.scene() is not None:
                    region.scene().removeItem(region)
            except RuntimeError:
                # Qt object already deleted
                pass
        self._highlight_regions.clear()

        # Create new highlight regions for each plot item
        for plot_item in plot_items:
            if self._time is not None:
                region = pg.LinearRegionItem(
                    values=(self._time - self._width / 2, self._time + self._width / 2),
                    orientation=pg.LinearRegionItem.Vertical,
                    movable=False,
                )

                # Set brush color with alpha
                qcolor = QColor(self._color)
                qcolor.setAlphaF(self._alpha)
                region.setBrush(qcolor)

                # No border
                region.setZValue(3)  # Below event lines but above traces
                region.setVisible(self._visible)
                plot_item.addItem(region)
                self._highlight_regions.append(region)

    def set_time(self, time: float) -> None:
        """Set highlight time position.

        Args:
            time: Time value to center highlight at
        """
        self._time = time
        for region in self._highlight_regions:
            try:
                region.setRegion((time - self._width / 2, time + self._width / 2))
            except RuntimeError:
                # Qt object already deleted
                pass

    def set_visible(self, visible: bool) -> None:
        """Show/hide highlight.

        Args:
            visible: Whether highlight should be visible
        """
        self._visible = visible
        for region in self._highlight_regions:
            try:
                region.setVisible(visible)
            except RuntimeError:
                # Qt object already deleted
                pass

    def clear(self) -> None:
        """Clear highlight (hide and reset time)."""
        self._time = None
        self.set_visible(False)

    def set_style(
        self,
        color: str | None = None,
        alpha: float | None = None,
        width: float | None = None,
    ) -> None:
        """Set highlight visual style.

        Args:
            color: Highlight color
            alpha: Transparency (0-1)
            width: Width in data units
        """
        if color is not None:
            self._color = color
        if alpha is not None:
            self._alpha = max(0.0, min(1.0, alpha))
        if width is not None:
            self._width = max(0.1, width)

        # Update existing regions
        qcolor = QColor(self._color)
        qcolor.setAlphaF(self._alpha)

        for region in self._highlight_regions:
            try:
                region.setBrush(qcolor)
                if self._time is not None:
                    region.setRegion((self._time - self._width / 2, self._time + self._width / 2))
            except RuntimeError:
                # Qt object already deleted
                pass

    def alpha(self) -> float:
        """Get current alpha value.

        Returns:
            Alpha transparency value (0-1)
        """
        return self._alpha
