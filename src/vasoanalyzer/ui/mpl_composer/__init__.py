"""Pure Matplotlib Figure Composer for VasoAnalyzer.

A publication-quality figure composition tool using only Matplotlib widgets
for UI controls, embedded in a Qt window as a canvas host.

Architecture:
    - Spec layer: Declarative models (FigureSpec, GraphSpec, etc.)
    - Renderer: Pure Matplotlib rendering (render_figure)
    - Composer UI: Matplotlib widgets + event handling

Key features:
    - Publication-ready exports (PDF, SVG, PNG, TIFF)
    - Explicit physical sizing (mm/inches) and DPI control
    - Multi-panel layouts with graph-level configuration
    - Rich annotations (text, boxes, arrows, lines)
    - "What you see is what you export" guarantee
"""

from __future__ import annotations

from .composer_window import PureMplFigureComposer
from .specs import (
    AnnotationSpec,
    ExportSpec,
    FigureSpec,
    GraphInstance,
    GraphSpec,
    LayoutSpec,
    FontSpec,
    TextRoleFont,
    StyleSpec,
    PanelLabelSpec,
    TraceBinding,
)

__all__ = [
    "PureMplFigureComposer",
    "FigureSpec",
    "GraphSpec",
    "GraphInstance",
    "LayoutSpec",
    "FontSpec",
    "TextRoleFont",
    "StyleSpec",
    "PanelLabelSpec",
    "AnnotationSpec",
    "ExportSpec",
    "TraceBinding",
]
