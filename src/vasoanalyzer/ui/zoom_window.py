"""Focused zoom dock that mirrors the active plot window."""

from __future__ import annotations

from dataclasses import dataclass

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QDockWidget, QSizePolicy, QVBoxLayout, QWidget

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.trace_view import TraceView


@dataclass
class ZoomSpan:
    start: float
    end: float

    def normalized(self) -> tuple[float, float]:
        if self.start <= self.end:
            return self.start, self.end
        return self.end, self.start


class ZoomWindowDock(QDockWidget):
    """Dockable Matplotlib view that mirrors the current cursor span."""

    def __init__(self, parent=None) -> None:
        super().__init__("Zoom", parent)
        self.setObjectName("ZoomWindowDock")
        self._model: TraceModel | None = None
        self._span: ZoomSpan | None = None

        self.figure = Figure(
            figsize=(4, 2.5),
            dpi=120,
            facecolor=CURRENT_THEME.get("window_bg", "#FFFFFF"),
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
        self.ax.grid(True, color=CURRENT_THEME.get("grid_color", "#CCCCCC"))
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Diameter (µm)")

        self.view = TraceView(self.ax, self.canvas, mode="dual")

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setWidget(container)

    def apply_theme(self) -> None:
        """Reapply theme colors to the zoom plot."""

        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        grid = CURRENT_THEME.get("grid_color", "#CCCCCC")
        text = CURRENT_THEME.get("text", "#000000")

        self.figure.set_facecolor(bg)
        self.ax.set_facecolor(bg)
        self.ax.tick_params(colors=text)
        self.ax.xaxis.label.set_color(text)
        self.ax.yaxis.label.set_color(text)
        self.ax.title.set_color(text)
        self.ax.grid(True, color=grid)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ public API
    def set_trace_model(self, model: TraceModel | None) -> None:
        self._model = model
        if model is None:
            self.clear_span()
            return
        self.view.set_model(model)
        if self._span is not None:
            self._render_span(self._span)

    def show_span(self, start: float, end: float) -> None:
        if self._model is None:
            return
        span = ZoomSpan(start, end)
        self._span = span
        self._render_span(span)

    def clear_span(self) -> None:
        self._span = None
        if self.view.inner_line is not None:
            self.view.inner_line.set_data([], [])
        if self.view.inner_band is not None:
            self.view.inner_band.set_verts([])
        if self.view.outer_line is not None:
            self.view.outer_line.set_data([], [])
        if self.view.outer_band is not None:
            self.view.outer_band.set_verts([])
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ helpers
    def _render_span(self, span: ZoomSpan) -> None:
        start, end = span.normalized()
        if self._model is None or end - start <= 0:
            self.clear_span()
            return
        pixel_width = max(int(self.canvas.width()), 640)
        self.view.update_window(start, end, pixel_width=pixel_width)
        limits = self.view.data_limits()
        if limits is not None:
            ymin, ymax = limits
            if ymin == ymax:
                pad = abs(ymin) * 0.05 if abs(ymin) > 1e-6 else 1.0
                ymin -= pad
                ymax += pad
            self.ax.set_ylim(ymin, ymax)
        self.ax.set_xlim(start, end)
        self.canvas.draw_idle()
