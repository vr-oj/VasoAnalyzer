"""Matplotlib Line2D compatibility wrapper for PyQtGraph PlotDataItem.

This wrapper provides matplotlib-like methods on PyQtGraph PlotDataItem
to enable gradual migration of code from matplotlib to PyQtGraph.
"""

from __future__ import annotations

import pyqtgraph as pg
from PyQt5.QtGui import QColor

__all__ = ["PyQtGraphLineCompat"]


class PyQtGraphLineCompat:
    """Wrapper around PyQtGraph PlotDataItem providing matplotlib Line2D interface.

    This allows code written for matplotlib Line2D to work with PyQtGraph
    PlotDataItem without modification, enabling gradual migration.
    """

    def __init__(self, plot_data_item: pg.PlotDataItem | None) -> None:
        """Initialize line compatibility wrapper.

        Args:
            plot_data_item: PyQtGraph PlotDataItem to wrap (can be None)
        """
        self._item = plot_data_item

    def set_visible(self, visible: bool) -> None:
        """Set line visibility (matplotlib compatibility)."""
        if self._item is not None:
            self._item.setVisible(visible)

    def get_visible(self) -> bool:
        """Get line visibility (matplotlib compatibility)."""
        if self._item is None:
            return False
        return self._item.isVisible()

    def set_linewidth(self, width: float) -> None:
        """Set line width (matplotlib compatibility)."""
        if self._item is not None:
            pen = self._item.opts.get('pen', pg.mkPen())
            if pen is not None:
                pen = pg.mkPen(pen)
                pen.setWidthF(width)
                self._item.setPen(pen)

    def get_linewidth(self) -> float:
        """Get line width (matplotlib compatibility)."""
        if self._item is None:
            return 1.0
        pen = self._item.opts.get('pen')
        if pen is None:
            return 1.0
        return pen.widthF()

    def set_color(self, color: str | tuple | QColor) -> None:
        """Set line color (matplotlib compatibility).

        Args:
            color: Color as hex string, RGB/RGBA tuple, or QColor object
        """
        if self._item is not None:
            pen = self._item.opts.get('pen', pg.mkPen())
            if pen is not None:
                pen = pg.mkPen(pen)
                if isinstance(color, QColor):
                    pen.setColor(color)
                elif isinstance(color, str):
                    pen.setColor(QColor(color))
                else:
                    # Assume RGB or RGBA tuple
                    if len(color) == 3:
                        pen.setColor(QColor(int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)))
                    elif len(color) == 4:
                        pen.setColor(QColor(int(color[0] * 255), int(color[1] * 255), int(color[2] * 255), int(color[3] * 255)))
                self._item.setPen(pen)

    def get_color(self) -> str:
        """Get line color (matplotlib compatibility)."""
        if self._item is None:
            return '#000000'
        pen = self._item.opts.get('pen')
        if pen is None:
            return '#000000'
        color = pen.color()
        return color.name()

    def set_linestyle(self, style: str | int) -> None:
        """Set line style (matplotlib compatibility).

        Args:
            style: Line style as string ('-', '--', '-.', ':', 'solid', 'dashed',
                   'dashdot', 'dotted') or Qt.PenStyle enum value
        """
        if self._item is not None:
            pen = self._item.opts.get('pen', pg.mkPen())
            if pen is not None:
                pen = pg.mkPen(pen)

                # If already a Qt enum value, use it directly
                if isinstance(style, int):
                    pen.setStyle(style)
                else:
                    # Map matplotlib styles to Qt styles
                    style_map = {
                        '-': pg.QtCore.Qt.SolidLine,
                        'solid': pg.QtCore.Qt.SolidLine,
                        '--': pg.QtCore.Qt.DashLine,
                        'dashed': pg.QtCore.Qt.DashLine,
                        '-.': pg.QtCore.Qt.DashDotLine,
                        'dashdot': pg.QtCore.Qt.DashDotLine,
                        ':': pg.QtCore.Qt.DotLine,
                        'dotted': pg.QtCore.Qt.DotLine,
                    }
                    qt_style = style_map.get(style, pg.QtCore.Qt.SolidLine)
                    pen.setStyle(qt_style)
                self._item.setPen(pen)

    def get_linestyle(self) -> str:
        """Get line style (matplotlib compatibility)."""
        if self._item is None:
            return '-'
        pen = self._item.opts.get('pen')
        if pen is None:
            return '-'

        # Map Qt styles to matplotlib styles
        qt_style = pen.style()
        style_map = {
            pg.QtCore.Qt.SolidLine: '-',
            pg.QtCore.Qt.DashLine: '--',
            pg.QtCore.Qt.DashDotLine: '-.',
            pg.QtCore.Qt.DotLine: ':',
        }
        return style_map.get(qt_style, '-')

    def set_alpha(self, alpha: float) -> None:
        """Set line alpha/transparency (matplotlib compatibility)."""
        if self._item is not None:
            pen = self._item.opts.get('pen', pg.mkPen())
            if pen is not None:
                pen = pg.mkPen(pen)
                color = pen.color()
                color.setAlphaF(alpha)
                pen.setColor(color)
                self._item.setPen(pen)

    def get_alpha(self) -> float:
        """Get line alpha/transparency (matplotlib compatibility)."""
        if self._item is None:
            return 1.0
        pen = self._item.opts.get('pen')
        if pen is None:
            return 1.0
        return pen.color().alphaF()

    def __getattr__(self, name: str):
        """Delegate unknown attributes to wrapped PlotDataItem.

        This allows direct access to PyQtGraph PlotDataItem methods
        when needed while providing matplotlib compatibility layer.
        """
        if self._item is None:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        return getattr(self._item, name)

    def __bool__(self) -> bool:
        """Check if the wrapped item exists."""
        return self._item is not None
