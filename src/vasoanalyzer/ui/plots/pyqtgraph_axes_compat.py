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

    def set_xlim(self, left: float | tuple[float, float] | list[float] | None = None, right: float | None = None) -> None:
        """Set X-axis limits (matplotlib compatibility).

        Args:
            left: Left limit, or tuple/list of (left, right) limits
            right: Right limit (only used if left is not a tuple/list)
        """
        # Handle tuple/list argument: ax.set_xlim((left, right)) or ax.set_xlim([left, right])
        if isinstance(left, (tuple, list)) and len(left) == 2:
            self._viewbox.setXRange(float(left[0]), float(left[1]), padding=0)
            return

        # Handle two separate arguments: ax.set_xlim(left, right)
        if left is not None and right is not None:
            self._viewbox.setXRange(float(left), float(right), padding=0)
        elif left is not None:
            current_right = self.get_xlim()[1]
            self._viewbox.setXRange(float(left), current_right, padding=0)
        elif right is not None:
            current_left = self.get_xlim()[0]
            self._viewbox.setXRange(current_left, float(right), padding=0)

    def set_ylim(self, bottom: float | tuple[float, float] | list[float] | None = None, top: float | None = None) -> None:
        """Set Y-axis limits (matplotlib compatibility).

        Args:
            bottom: Bottom limit, or tuple/list of (bottom, top) limits
            top: Top limit (only used if bottom is not a tuple/list)
        """
        # Handle tuple/list argument: ax.set_ylim((bottom, top)) or ax.set_ylim([bottom, top])
        if isinstance(bottom, (tuple, list)) and len(bottom) == 2:
            self._viewbox.setYRange(float(bottom[0]), float(bottom[1]), padding=0)
            return

        # Handle two separate arguments: ax.set_ylim(bottom, top)
        if bottom is not None and top is not None:
            self._viewbox.setYRange(float(bottom), float(top), padding=0)
        elif bottom is not None:
            current_top = self.get_ylim()[1]
            self._viewbox.setYRange(float(bottom), current_top, padding=0)
        elif top is not None:
            current_bottom = self.get_ylim()[0]
            self._viewbox.setYRange(current_bottom, float(top), padding=0)

    def set_xlabel(self, label: str) -> None:
        """Set X-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel('bottom', label)

    def get_xlabel(self) -> str:
        """Get X-axis label (matplotlib compatibility)."""
        axis = self._plot_item.getAxis('bottom')
        if axis and hasattr(axis, 'labelText'):
            return axis.labelText
        return ""

    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel('left', label)

    def get_ylabel(self) -> str:
        """Get Y-axis label (matplotlib compatibility)."""
        axis = self._plot_item.getAxis('left')
        if axis and hasattr(axis, 'labelText'):
            return axis.labelText
        return ""

    def grid(self, visible: bool = True, **kwargs) -> None:
        """Show/hide grid (matplotlib compatibility)."""
        self._plot_item.showGrid(x=visible, y=visible)

    @property
    def lines(self) -> list:
        """Get all line items (matplotlib Axes.lines compatibility).

        Returns:
            List of PlotDataItem objects in the plot
        """
        # Get all items in the plot
        items = self._plot_item.listDataItems()
        # Filter for PlotDataItem (line plots)
        return [item for item in items if isinstance(item, pg.PlotDataItem)]

    def __getattr__(self, name: str):
        """Delegate unknown attributes to wrapped PlotItem.

        This allows direct access to PyQtGraph PlotItem methods
        when needed while providing matplotlib compatibility layer.
        """
        return getattr(self._plot_item, name)
