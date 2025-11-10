"""Matplotlib Axes compatibility wrapper for PyQtGraph PlotItem.

This wrapper provides matplotlib-like methods on PyQtGraph PlotItem
to enable gradual migration of code from matplotlib to PyQtGraph.
"""

from __future__ import annotations

import pyqtgraph as pg

__all__ = ["PyQtGraphAxesCompat"]


class PyQtGraphAxesCompat:
    """Wrapper around PyQtGraph PlotItem providing matplotlib Axes interface.

    This allows code written for matplotlib Axes to work with PyQtGraph
    PlotItem without modification, enabling gradual migration.
    """

    def __init__(self, plot_item: pg.PlotItem) -> None:
        """Initialize axes compatibility wrapper.

        Args:
            plot_item: PyQtGraph PlotItem to wrap
        """
        self._plot_item = plot_item
        self._viewbox = plot_item.getViewBox()

    def get_xlim(self) -> tuple[float, float]:
        """Get X-axis limits (matplotlib compatibility)."""
        x_range, _ = self._viewbox.viewRange()
        return (float(x_range[0]), float(x_range[1]))

    def get_ylim(self) -> tuple[float, float]:
        """Get Y-axis limits (matplotlib compatibility)."""
        _, y_range = self._viewbox.viewRange()
        return (float(y_range[0]), float(y_range[1]))

    def set_xlim(self, left: float | None = None, right: float | None = None) -> None:
        """Set X-axis limits (matplotlib compatibility)."""
        if left is not None and right is not None:
            self._viewbox.setXRange(left, right, padding=0)
        elif left is not None:
            current_right = self.get_xlim()[1]
            self._viewbox.setXRange(left, current_right, padding=0)
        elif right is not None:
            current_left = self.get_xlim()[0]
            self._viewbox.setXRange(current_left, right, padding=0)

    def set_ylim(self, bottom: float | None = None, top: float | None = None) -> None:
        """Set Y-axis limits (matplotlib compatibility)."""
        if bottom is not None and top is not None:
            self._viewbox.setYRange(bottom, top, padding=0)
        elif bottom is not None:
            current_top = self.get_ylim()[1]
            self._viewbox.setYRange(bottom, current_top, padding=0)
        elif top is not None:
            current_bottom = self.get_ylim()[0]
            self._viewbox.setYRange(current_bottom, top, padding=0)

    def set_xlabel(self, label: str) -> None:
        """Set X-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel('bottom', label)

    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel('left', label)

    def grid(self, visible: bool = True, **kwargs) -> None:
        """Show/hide grid (matplotlib compatibility)."""
        self._plot_item.showGrid(x=visible, y=visible)

    def __getattr__(self, name: str):
        """Delegate unknown attributes to wrapped PlotItem.

        This allows direct access to PyQtGraph PlotItem methods
        when needed while providing matplotlib compatibility layer.
        """
        return getattr(self._plot_item, name)
