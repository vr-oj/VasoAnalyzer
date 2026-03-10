"""Centralized PyQtGraph styling tokens."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtCore import Qt as QtCore
from PyQt5.QtGui import QBrush, QColor, QPen

from vasoanalyzer.ui.theme import CURRENT_THEME, FONTS


@dataclass(frozen=True)
class EventMarkerStyle:
    color: str
    width: float
    style: Qt.PenStyle
    alpha: float


@dataclass(frozen=True)
class SelectionBoxStyle:
    pen_color: str
    pen_width: float
    pen_style: Qt.PenStyle
    brush_color: str
    brush_alpha: float


# macOS: small sizes look great on Retina with Avenir Next.
# Windows: Segoe UI needs slightly larger sizes to render clearly.
PLOT_AXIS_FONT_SIZE = 8.5 if sys.platform == "darwin" else 10.0
PLOT_TICK_FONT_SIZE = 7.0 if sys.platform == "darwin" else 9.0
PLOT_AXIS_LABELS = {
    "inner": "ID (µm)",
    "outer": "OD (µm)",
    "avg_pressure": "Avg P (mmHg)",
    "set_pressure": "Set P (mmHg)",
    "dual": "ID (µm)",
}
PLOT_AXIS_TOOLTIPS = {
    "inner": "Inner Diameter",
    "outer": "Outer Diameter",
    "avg_pressure": "Average Pressure",
    "set_pressure": "Set Pressure",
    "dual": "Inner Diameter",
}


@dataclass(frozen=True)
class PyQtGraphStyleTokens:
    background_color: str
    axis_pen_color: str
    tick_label_color: str
    grid_alpha: float
    font_family: str
    font_size: float
    tick_font_size: float
    event_marker: EventMarkerStyle
    selection_box: SelectionBoxStyle


def _color_with_alpha(color: str, alpha: float) -> QColor:
    qcolor = QColor(color)
    if not qcolor.isValid():
        qcolor = QColor("#000000")
    qcolor.setAlphaF(max(0.0, min(float(alpha), 1.0)))
    return qcolor


def get_pyqtgraph_style() -> PyQtGraphStyleTokens:
    """Return the current style tokens derived from the active theme."""
    background = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
    axis_color = CURRENT_THEME.get("text", "#000000")
    tick_color = CURRENT_THEME.get("text", "#000000")
    grid_alpha = float(CURRENT_THEME.get("grid_alpha", 0.10))

    event_color = CURRENT_THEME.get("event_line", "#8A8A8A")
    event_marker = EventMarkerStyle(
        color=event_color,
        width=2.0,
        style=Qt.PenStyle.DashLine,
        alpha=0.85,
    )

    selection_color = CURRENT_THEME.get("selection_bg", "#3B82F6")
    selection_box = SelectionBoxStyle(
        pen_color=selection_color,
        pen_width=1.0,
        pen_style=Qt.PenStyle.DashLine,
        brush_color=selection_color,
        brush_alpha=0.15,
    )

    return PyQtGraphStyleTokens(
        background_color=background,
        axis_pen_color=axis_color,
        tick_label_color=tick_color,
        grid_alpha=grid_alpha,
        font_family=str(FONTS.get("family", "Arial")),
        font_size=PLOT_AXIS_FONT_SIZE,
        tick_font_size=PLOT_TICK_FONT_SIZE,
        event_marker=event_marker,
        selection_box=selection_box,
    )


def make_event_pen(style: EventMarkerStyle) -> QPen:
    qcolor = _color_with_alpha(style.color, style.alpha)
    return pg.mkPen(color=qcolor, width=float(style.width), style=style.style)


def make_selection_pen(style: SelectionBoxStyle) -> QPen:
    return pg.mkPen(
        color=style.pen_color, width=float(style.pen_width), style=style.pen_style
    )


def make_selection_brush(style: SelectionBoxStyle) -> QBrush:
    return pg.mkBrush(_color_with_alpha(style.brush_color, style.brush_alpha))


def apply_selection_box_style(view_box, style: SelectionBoxStyle) -> None:
    """Apply selection (box-zoom) styling to a ViewBox."""
    scale_box = getattr(view_box, "rbScaleBox", None)
    if scale_box is None:
        return
    scale_box.setPen(make_selection_pen(style))
    scale_box.setBrush(make_selection_brush(style))
