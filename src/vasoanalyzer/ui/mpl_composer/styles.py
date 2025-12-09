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
    axis_label_size: float
    tick_label_size: float
    legend_size: float
    default_linewidth: float
    export_dpi: int


STYLE_PRESETS: Dict[str, StylePreset] = {
    "Lab default": StylePreset(
        name="Lab default",
        description="General lab figures (single-column style).",
        width_in=5.9,
        height_in=3.0,
        base_font_size=8.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        default_linewidth=1.5,
        export_dpi=600,
    ),
    "Journal single-column": StylePreset(
        name="Journal single-column",
        description="Single-column journal layout (~85–90 mm).",
        width_in=3.4,
        height_in=3.0,
        base_font_size=8.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        default_linewidth=1.2,
        export_dpi=600,
    ),
    "Journal double-column": StylePreset(
        name="Journal double-column",
        description="Double-column journal layout (~175–180 mm).",
        width_in=7.1,
        height_in=3.5,
        base_font_size=8.0,
        axis_label_size=9.0,
        tick_label_size=7.0,
        legend_size=7.0,
        default_linewidth=1.2,
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
        font.axis_label_size = preset.axis_label_size
        font.tick_label_size = preset.tick_label_size
        font.legend_size = preset.legend_size

    spec.export.dpi = preset.export_dpi

    for graph in spec.graphs.values():
        graph.default_linewidth = preset.default_linewidth

    spec.metadata["style_preset"] = preset.name
