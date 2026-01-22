# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Custom timeline slider for the TIFF viewer v2."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


class SnapshotTimelineSlider(QtWidgets.QSlider):
    """Timeline slider with a high-contrast scrub line."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(QtCore.Qt.Horizontal, parent)
        self.setObjectName("SnapshotTimeline")
        self.setFixedHeight(20)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.setRange(0, 0)

    def _accent_color(self) -> QtGui.QColor:
        color = self.palette().highlight().color()
        if color.alpha() < 220:
            color.setAlpha(235)
        return color

    def _outline_color(self, accent: QtGui.QColor) -> QtGui.QColor:
        base = self.palette().base().color()
        window = self.palette().window().color()
        if _contrast(base, accent) >= _contrast(window, accent):
            return base
        return window

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        option = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QtWidgets.QStyle.CC_Slider,
            option,
            QtWidgets.QStyle.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QtWidgets.QStyle.CC_Slider,
            option,
            QtWidgets.QStyle.SC_SliderHandle,
            self,
        )
        if groove.isNull():
            groove = self.rect().adjusted(6, 6, -6, -6)

        accent = self._accent_color()
        line_x = handle.center().x()
        pen = QtGui.QPen(accent, 2)
        pen.setCapStyle(QtCore.Qt.FlatCap)
        painter.setPen(pen)
        painter.drawLine(
            QtCore.QPointF(line_x, groove.top() - 1),
            QtCore.QPointF(line_x, groove.bottom() + 1),
        )

        thumb_radius = max(3, min(6, int(groove.height() / 2) + 1))
        outline = self._outline_color(accent)
        painter.setBrush(accent)
        painter.setPen(QtGui.QPen(outline, 1))
        painter.drawEllipse(
            QtCore.QPointF(line_x, groove.center().y()),
            thumb_radius,
            thumb_radius,
        )
        painter.end()


def _contrast(first: QtGui.QColor, second: QtGui.QColor) -> int:
    return abs(first.lightness() - second.lightness())


__all__ = ["SnapshotTimelineSlider"]
