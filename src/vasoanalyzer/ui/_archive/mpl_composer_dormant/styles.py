"""Style presets for the figure composer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .specs import FigureSpec


@dataclass(frozen=True)
class StylePreset:
    name: str
    description: str
    width_in: float
    height_in: float
    base_font_size: float
    title_size: float
    axis_label_size: float
    tick_label_size: float
    legend_size: float
    annotation_size: float
    default_linewidth: float
    axis_spine_width: float
    tick_direction: str
    tick_major_length: float
    tick_minor_length: float
    export_dpi: int


STYLE_PRESETS: Dict[str, StylePreset] = {
    "Lab default": StylePreset(
        name="Lab default",
        description="General lab figures (single-column style).",
        width_in=5.9,
        height_in=3.0,
        base_font_size=8.0,
        title_size=10.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        annotation_size=8.0,
        default_linewidth=1.5,
        axis_spine_width=1.0,
        tick_direction="out",
        tick_major_length=3.5,
        tick_minor_length=2.0,
        export_dpi=600,
    ),
    "Journal single-column": StylePreset(
        name="Journal single-column",
        description="Single-column journal layout (~85–90 mm).",
        width_in=3.4,
        height_in=3.0,
        base_font_size=8.0,
        title_size=10.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        annotation_size=8.0,
        default_linewidth=1.2,
        axis_spine_width=0.9,
        tick_direction="out",
        tick_major_length=3.5,
        tick_minor_length=2.0,
        export_dpi=600,
    ),
    "Journal double-column": StylePreset(
        name="Journal double-column",
        description="Double-column journal layout (~175–180 mm).",
        width_in=7.1,
        height_in=3.5,
        base_font_size=8.0,
        title_size=10.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        annotation_size=8.0,
        default_linewidth=1.2,
        axis_spine_width=1.0,
        tick_direction="out",
        tick_major_length=3.5,
        tick_minor_length=2.0,
        export_dpi=600,
    ),
}


def apply_style_preset(spec: FigureSpec, preset: StylePreset) -> None:
    """Apply a style preset to the given FigureSpec."""
    spec.layout.width_in = preset.width_in
    spec.layout.height_in = preset.height_in

    font = getattr(spec, "font", None)
    if font is not None:
        font.base_size = preset.base_font_size
        if hasattr(font, "figure_title"):
            font.figure_title.size = preset.title_size
        if hasattr(font, "panel_label"):
            font.panel_label.size = preset.axis_label_size
        if hasattr(font, "axis_title"):
            font.axis_title.size = preset.axis_label_size
        if hasattr(font, "tick_label"):
            font.tick_label.size = preset.tick_label_size
        if hasattr(font, "legend"):
            font.legend.size = preset.legend_size
        if hasattr(font, "annotation"):
            font.annotation.size = preset.annotation_size

    style = getattr(spec, "style", None)
    if style is not None:
        style.default_linewidth = preset.default_linewidth
        style.axis_spine_width = preset.axis_spine_width
        style.tick_direction = preset.tick_direction
        style.tick_major_length = preset.tick_major_length
        style.tick_minor_length = preset.tick_minor_length

    spec.export.dpi = preset.export_dpi

    for graph in spec.graphs.values():
        graph.default_linewidth = preset.default_linewidth

    spec.metadata["style_preset"] = preset.name
