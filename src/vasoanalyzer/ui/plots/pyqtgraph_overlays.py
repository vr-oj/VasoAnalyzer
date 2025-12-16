"""PyQtGraph-based overlays for cursor, event highlighting, and annotations."""

from __future__ import annotations

import contextlib
import math
import time
from typing import Any

import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from vasoanalyzer.ui.theme import CURRENT_THEME

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
            with contextlib.suppress(RuntimeError):
                if line.scene() is not None:
                    line.scene().removeItem(line)
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
            with contextlib.suppress(RuntimeError):
                line.setPos(time)

    def set_visible(self, visible: bool) -> None:
        """Show/hide cursor.

        Args:
            visible: Whether cursor should be visible
        """
        self._visible = visible
        for line in self._cursor_lines:
            with contextlib.suppress(RuntimeError):
                line.setVisible(visible)

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
            with contextlib.suppress(RuntimeError):
                pen = pg.mkPen(color=self._color, width=self._width)
                line.setPen(pen)

    def apply_theme(self) -> None:
        """Reapply cursor styling from the current theme."""

        color = CURRENT_THEME.get("time_cursor", self._color)
        self.set_style(color=color, width=self._width)


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
        self._base_alpha: float = 0.2  # Base alpha for pulsing
        self._width: float = 2.0  # Width in data units
        self._animated: bool = False
        self._pulse_timer: QTimer | None = None
        self._pulse_start_time: float = 0.0

    def sync_tracks(self, plot_items: list[pg.PlotItem]) -> None:
        """Synchronize highlight across multiple tracks.

        Args:
            plot_items: List of PyQtGraph PlotItems to show highlight on
        """
        # Remove old highlight regions (safely handle deleted Qt objects)
        for region in self._highlight_regions:
            with contextlib.suppress(RuntimeError):
                if region.scene() is not None:
                    region.scene().removeItem(region)
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
            with contextlib.suppress(RuntimeError):
                region.setRegion((time - self._width / 2, time + self._width / 2))

    def set_visible(self, visible: bool) -> None:
        """Show/hide highlight.

        Args:
            visible: Whether highlight should be visible
        """
        self._visible = visible
        for region in self._highlight_regions:
            with contextlib.suppress(RuntimeError):
                region.setVisible(visible)

        # Start/stop animation based on visibility
        if visible and self._animated:
            self._start_pulse_animation()
        elif not visible:
            self._stop_pulse_animation()

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
            with contextlib.suppress(RuntimeError):
                region.setBrush(qcolor)
                if self._time is not None:
                    region.setRegion((self._time - self._width / 2, self._time + self._width / 2))

    def alpha(self) -> float:
        """Get current alpha value.

        Returns:
            Alpha transparency value (0-1)
        """
        return self._alpha

    def set_animated(self, enabled: bool) -> None:
        """Enable/disable pulsing animation.

        Args:
            enabled: Whether to animate the highlight
        """
        self._animated = enabled

        if enabled and self._visible:
            self._start_pulse_animation()
        else:
            self._stop_pulse_animation()

    def _start_pulse_animation(self) -> None:
        """Start the pulsing animation."""
        if self._pulse_timer is not None:
            return  # Already running

        self._pulse_start_time = time.time()
        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self._pulse_step)
        self._pulse_timer.start(50)  # 20 FPS

    def _stop_pulse_animation(self) -> None:
        """Stop the pulsing animation."""
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None

        # Restore base alpha
        self.set_style(alpha=self._base_alpha)

    def _pulse_step(self) -> None:
        """Execute one step of the pulse animation."""
        if not self._animated or not self._visible:
            self._stop_pulse_animation()
            return

        # Calculate pulsing alpha (0.3 → 0.5 → 0.3 over 2 seconds)
        elapsed = time.time() - self._pulse_start_time
        phase = (elapsed % 2.0) / 2.0  # 0 to 1 over 2 seconds

        # Use sine wave for smooth pulsing
        alpha = 0.3 + 0.2 * abs(math.sin(phase * math.pi))

        # Update alpha without changing color or width
        if alpha != self._alpha:
            self.set_style(alpha=alpha)

    def apply_theme(self) -> None:
        """Reapply highlight styling from the current theme."""

        color = CURRENT_THEME.get("event_highlight", CURRENT_THEME.get("accent", self._color))
        alpha = self._alpha
        try:
            alpha = float(alpha)
        except Exception:
            alpha = self._alpha
        self.set_style(color=color, alpha=alpha, width=self._width)
