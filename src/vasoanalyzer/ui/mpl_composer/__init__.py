"""Pure Matplotlib Figure Composer for VasoAnalyzer.

A publication-quality figure composition tool using only Matplotlib widgets
for UI controls, embedded in a Qt window as a canvas host.
"""

from __future__ import annotations

from .composer_window import PureMplFigureComposer
from .renderer import (
    AnnotationSpec,
    AxesSpec,
    EventSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)

__all__ = [
    "PureMplFigureComposer",
    "FigureSpec",
    "PageSpec",
    "AxesSpec",
    "TraceSpec",
    "EventSpec",
    "AnnotationSpec",
    "RenderContext",
    "build_figure",
    "export_figure",
]
