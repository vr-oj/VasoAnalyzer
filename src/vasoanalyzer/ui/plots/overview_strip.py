"""Overview strip widget showing full recording with current view window."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence

import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.theme import CURRENT_THEME, hex_to_pyqtgraph_color


class OverviewStrip(QFrame):
    """Mini-map overview strip with drag-to-scroll and click-to-jump."""

    timeWindowRequested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OverviewStrip")
        self.setFixedHeight(80)
        self._model: TraceModel | None = None
        self._full_range: tuple[float, float] | None = None
        self._current_window: tuple[float, float] | None = None
        self._syncing_region = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot_widget = pg.PlotWidget()
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.setMenuEnabled(False)
        self._plot_item.hideAxis("left")
        self._plot_item.hideAxis("bottom")
        self._plot_item.showGrid(x=False, y=False)
        self._plot_item.setMouseEnabled(x=False, y=False)
        vb = self._plot_item.getViewBox()
        with contextlib.suppress(Exception):
            vb.wheelEvent = lambda ev: ev.accept()

        self._curve = self._plot_item.plot([], [])
        self._min_curve = self._plot_item.plot([], [])
        self._max_curve = self._plot_item.plot([], [])
        self._band = pg.FillBetweenItem(self._min_curve, self._max_curve)
        self._plot_item.addItem(self._band)

        self._event_lines: list[pg.InfiniteLine] = []

        self._region = pg.LinearRegionItem(values=(0.0, 1.0), movable=True)
        for line in self._region.lines:
            line.setMovable(False)
        self._plot_item.addItem(self._region)
        self._region.sigRegionChanged.connect(self._on_region_changed)
        self._region.sigRegionChangeFinished.connect(self._on_region_changed)

        scene = self._plot_widget.scene()
        if scene is not None:
            scene.sigMouseClicked.connect(self._on_scene_clicked)

        layout.addWidget(self._plot_widget, 1)
        self.apply_theme()

    def apply_theme(self) -> None:
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        text = CURRENT_THEME.get("text", "#000000")
        grid = CURRENT_THEME.get("grid_color", "#D0D0D0")
        accent = CURRENT_THEME.get("accent", text)
        event_line = CURRENT_THEME.get("event_line", grid)
        vb = self._plot_item.getViewBox()
        with contextlib.suppress(Exception):
            vb.setBackgroundColor(hex_to_pyqtgraph_color(bg))

        pen = pg.mkPen(color=text, width=1, cosmetic=True)
        minmax_pen = pg.mkPen(color=text, width=1, cosmetic=True)
        band_brush = pg.mkBrush(color=self._alpha_color(text, 0.2))
        self._curve.setPen(pen)
        self._min_curve.setPen(minmax_pen)
        self._max_curve.setPen(minmax_pen)
        self._band.setBrush(band_brush)
        self._band.setPen(None)

        region_brush = pg.mkBrush(color=self._alpha_color(accent, 0.25))
        region_pen = pg.mkPen(color=accent, width=1)
        with contextlib.suppress(Exception):
            self._region.setBrush(region_brush)
        for line in getattr(self._region, "lines", []):
            with contextlib.suppress(Exception):
                line.setPen(region_pen)

        for line in self._event_lines:
            line.setPen(pg.mkPen(color=event_line, width=1))

        self.setStyleSheet(
            f"""
QFrame#OverviewStrip {{
    border: 1px solid {grid};
    border-radius: 10px;
}}
"""
        )

    @staticmethod
    def _alpha_color(color: str, alpha: float) -> QColor:
        qcolor = QColor(color)
        if not qcolor.isValid():
            qcolor = QColor("#000000")
        qcolor.setAlphaF(max(0.0, min(1.0, float(alpha))))
        return qcolor

    def clear(self) -> None:
        self._model = None
        self._full_range = None
        self._current_window = None
        self._curve.setData([], [])
        self._min_curve.setData([], [])
        self._max_curve.setData([], [])
        self._clear_events()

    def _clear_events(self) -> None:
        for line in self._event_lines:
            self._plot_item.removeItem(line)
        self._event_lines.clear()

    def set_trace_model(self, model: TraceModel | None) -> None:
        self._model = model
        if model is None:
            self.clear()
            return

        level = model.levels[-1] if model.levels else None
        if level is None:
            self.clear()
            return

        time = level.time_centers
        inner_mean = level.inner_mean
        inner_min = level.inner_min
        inner_max = level.inner_max

        if time is None or inner_mean is None or time.size == 0:
            self.clear()
            return

        self._curve.setData(time, inner_mean)
        if inner_min is not None and inner_max is not None:
            self._min_curve.setData(time, inner_min)
            self._max_curve.setData(time, inner_max)
        else:
            self._min_curve.setData([], [])
            self._max_curve.setData([], [])

        self.set_full_range(*model.full_range)
        self._plot_item.enableAutoRange(axis=pg.ViewBox.YAxis)

    def set_full_range(self, start: float | None, end: float | None) -> None:
        if start is None or end is None:
            self._full_range = None
            return
        self._full_range = (float(start), float(end))
        self._plot_item.setXRange(self._full_range[0], self._full_range[1], padding=0.0)
        self._region.setBounds(self._full_range)

    def set_time_window(self, x0: float | None, x1: float | None) -> None:
        if x0 is None or x1 is None:
            self._current_window = None
            return
        self._current_window = (float(x0), float(x1))
        self._syncing_region = True
        try:
            self._region.setRegion([self._current_window[0], self._current_window[1]])
        finally:
            self._syncing_region = False

    def set_events(self, times: Sequence[float] | None) -> None:
        self._clear_events()
        if not times:
            return

        color = CURRENT_THEME.get("event_line", CURRENT_THEME.get("grid_color", "#888888"))
        for t in times:
            try:
                x = float(t)
            except (TypeError, ValueError):
                continue
            line = pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(color=color, width=1))
            line.setZValue(5)
            self._plot_item.addItem(line)
            self._event_lines.append(line)

    def _on_region_changed(self) -> None:
        if self._syncing_region:
            return
        region = self._region.getRegion()
        if region is None or len(region) != 2:
            return
        x0, x1 = float(region[0]), float(region[1])
        if self._full_range is not None:
            fr0, fr1 = self._full_range
            span = max(x1 - x0, 1e-9)
            if x0 < fr0:
                x0 = fr0
                x1 = fr0 + span
            if x1 > fr1:
                x1 = fr1
                x0 = fr1 - span
        self.timeWindowRequested.emit(x0, x1)

    def _on_scene_clicked(self, ev) -> None:
        try:
            if ev.isAccepted():
                return
        except Exception:
            pass
        if ev.button() != Qt.LeftButton:
            return
        if self._full_range is None:
            return
        vb = self._plot_item.getViewBox()
        pos = ev.scenePos()
        data_pos = vb.mapSceneToView(pos)
        if data_pos is None:
            return
        x = float(data_pos.x())

        if self._current_window is not None:
            span = max(self._current_window[1] - self._current_window[0], 1e-9)
        else:
            fr0, fr1 = self._full_range
            span = max((fr1 - fr0) * 0.1, 1e-6)

        x0 = x - span * 0.5
        x1 = x + span * 0.5
        fr0, fr1 = self._full_range
        if x0 < fr0:
            x0 = fr0
            x1 = fr0 + span
        if x1 > fr1:
            x1 = fr1
            x0 = fr1 - span

        self.timeWindowRequested.emit(float(x0), float(x1))
