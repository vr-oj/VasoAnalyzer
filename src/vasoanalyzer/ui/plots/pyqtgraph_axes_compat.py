"""Matplotlib Axes compatibility wrapper for PyQtGraph PlotItem.

This wrapper provides matplotlib-like methods on PyQtGraph PlotItem
to enable gradual migration of code from matplotlib to PyQtGraph.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
        self._grid_callback: Callable[[bool], None] | None = None

    def get_xlim(self) -> tuple[float, float]:
        """Get X-axis limits (matplotlib compatibility)."""
        x_range, _ = self._viewbox.viewRange()
        return (float(x_range[0]), float(x_range[1]))

    def get_ylim(self) -> tuple[float, float]:
        """Get Y-axis limits (matplotlib compatibility)."""
        _, y_range = self._viewbox.viewRange()
        return (float(y_range[0]), float(y_range[1]))

    def set_xlim(
        self,
        left: float | tuple[float, float] | list[float] | None = None,
        right: float | None = None,
    ) -> None:
        """Set X-axis limits (matplotlib compatibility).

        Args:
            left: Left limit, or tuple/list of (left, right) limits
            right: Right limit (only used if left is not a tuple/list)
        """
        # Handle tuple/list argument: ax.set_xlim((left, right)) or ax.set_xlim([left, right])
        if isinstance(left, tuple | list):
            if len(left) != 2:
                msg = "left tuple/list must contain exactly two elements"
                raise ValueError(msg)
            left_val = float(left[0])
            right_val = float(left[1])
            self._viewbox.setXRange(left_val, right_val, padding=0)
            return

        left_value = float(left) if left is not None else None
        right_value = float(right) if right is not None else None

        # Handle two separate arguments: ax.set_xlim(left, right)
        if left_value is not None and right_value is not None:
            self._viewbox.setXRange(left_value, right_value, padding=0)
        elif left_value is not None:
            current_right = self.get_xlim()[1]
            self._viewbox.setXRange(left_value, current_right, padding=0)
        elif right_value is not None:
            current_left = self.get_xlim()[0]
            self._viewbox.setXRange(current_left, right_value, padding=0)

    def set_ylim(
        self,
        bottom: float | tuple[float, float] | list[float] | None = None,
        top: float | None = None,
    ) -> None:
        """Set Y-axis limits (matplotlib compatibility).

        Args:
            bottom: Bottom limit, or tuple/list of (bottom, top) limits
            top: Top limit (only used if bottom is not a tuple/list)
        """
        # Handle tuple/list argument: ax.set_ylim((bottom, top)) or ax.set_ylim([bottom, top])
        if isinstance(bottom, tuple | list):
            if len(bottom) != 2:
                msg = "bottom tuple/list must contain exactly two elements"
                raise ValueError(msg)
            bottom_val = float(bottom[0])
            top_val = float(bottom[1])
            self._viewbox.setYRange(bottom_val, top_val, padding=0)
            return

        bottom_value = float(bottom) if bottom is not None else None
        top_value = float(top) if top is not None else None

        # Handle two separate arguments: ax.set_ylim(bottom, top)
        if bottom_value is not None and top_value is not None:
            self._viewbox.setYRange(bottom_value, top_value, padding=0)
        elif bottom_value is not None:
            current_top = self.get_ylim()[1]
            self._viewbox.setYRange(bottom_value, current_top, padding=0)
        elif top_value is not None:
            current_bottom = self.get_ylim()[0]
            self._viewbox.setYRange(current_bottom, top_value, padding=0)

    def set_xlabel(self, label: str) -> None:
        """Set X-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel("bottom", label)

    def get_xlabel(self) -> str:
        """Get X-axis label (matplotlib compatibility)."""
        axis = self._plot_item.getAxis("bottom")
        if axis is not None and hasattr(axis, "labelText"):
            label = axis.labelText
            if label is None:
                return ""
            return str(label)
        return ""

    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label (matplotlib compatibility)."""
        self._plot_item.setLabel("left", label)

    def get_ylabel(self) -> str:
        """Get Y-axis label (matplotlib compatibility)."""
        axis = self._plot_item.getAxis("left")
        if axis is not None and hasattr(axis, "labelText"):
            label = axis.labelText
            if label is None:
                return ""
            return str(label)
        return ""

    def grid(self, visible: bool = True, **kwargs: object) -> None:
        """Show/hide grid (matplotlib compatibility)."""
        self._plot_item.showGrid(x=visible, y=visible)
        if self._grid_callback is not None:
            self._grid_callback(bool(visible))

    def set_grid_callback(self, callback: Callable[[bool], None] | None) -> None:
        """Register a callback fired when grid() is invoked on this wrapper."""
        self._grid_callback = callback

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

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to wrapped PlotItem.

        This allows direct access to PyQtGraph PlotItem methods
        when needed while providing matplotlib compatibility layer.
        """
        return getattr(self._plot_item, name)
