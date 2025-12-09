"""Serialization helpers for FigureSpec."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict

from .specs import AnnotationSpec, ExportSpec, FigureSpec, FontSpec, GraphInstance, GraphSpec, LayoutSpec

FIGURE_SPEC_SCHEMA_VERSION = 1
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)


def _filter_kwargs(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Drop unknown keys so older templates load after we add fields."""
    if raw is None:
        return {}
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in valid}


def figure_spec_to_dict(spec: FigureSpec) -> Dict[str, Any]:
    data = asdict(spec)
    data["schema_version"] = FIGURE_SPEC_SCHEMA_VERSION
    return data


def figure_spec_from_dict(raw: Dict[str, Any]) -> FigureSpec:
    raw = dict(raw)
    raw.pop("schema_version", None)

    graphs_raw = raw.get("graphs", {}) or {}
    graphs: Dict[str, GraphSpec] = {}
    for graph_id, g_raw in graphs_raw.items():
        graphs[graph_id] = GraphSpec(**_filter_kwargs(GraphSpec, g_raw))

    layout_raw = raw.get("layout", {}) or {}
    gi_raw_list = layout_raw.get("graph_instances", [])
    graph_instances = [
        GraphInstance(**_filter_kwargs(GraphInstance, gi_raw)) for gi_raw in gi_raw_list
    ]
    layout_kwargs = _filter_kwargs(LayoutSpec, layout_raw)
    layout_kwargs["graph_instances"] = graph_instances
    layout = LayoutSpec(**layout_kwargs)

    ann_list = raw.get("annotations", []) or []
    annotations = [
        AnnotationSpec(**_filter_kwargs(AnnotationSpec, a_raw)) for a_raw in ann_list
    ]

    export_raw = raw.get("export", {}) or {}
    export = ExportSpec(**_filter_kwargs(ExportSpec, export_raw))

    font_raw = raw.get("font", {}) or {}
    font = FontSpec(**_filter_kwargs(FontSpec, font_raw))

    metadata = raw.get("metadata", {}) or {}

    return FigureSpec(
        graphs=graphs,
        layout=layout,
        annotations=annotations,
        export=export,
        font=font,
        metadata=metadata,
    )


def save_figure_spec(path: str | Path, spec: FigureSpec) -> None:
    path = Path(path)
    data = figure_spec_to_dict(spec)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_figure_spec(path: str | Path) -> FigureSpec:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return figure_spec_from_dict(raw)


def list_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.json"))


def save_template(name: str, spec: FigureSpec) -> Path:
    path = TEMPLATE_DIR / f"{name}.json"
    save_figure_spec(path, spec)
    return path


def load_template(name: str) -> FigureSpec:
    path = TEMPLATE_DIR / f"{name}.json"
    return load_figure_spec(path)


def apply_template_structure(dest: FigureSpec, template: FigureSpec) -> None:
    """Copy layout/font/export and graph presentation from template onto dest."""
    dest.layout.width_in = template.layout.width_in
    dest.layout.height_in = template.layout.height_in
    dest.layout.nrows = template.layout.nrows
    dest.layout.ncols = template.layout.ncols
    dest.layout.hspace = template.layout.hspace
    dest.layout.wspace = template.layout.wspace
    dest.layout.graph_instances = template.layout.graph_instances

    dest.font.base_size = template.font.base_size
    dest.font.axis_label_size = template.font.axis_label_size
    dest.font.tick_label_size = template.font.tick_label_size
    dest.font.legend_size = template.font.legend_size
    dest.font.family = template.font.family
    dest.font.weight = template.font.weight
    dest.font.style = template.font.style

    dest.export.dpi = template.export.dpi
    dest.export.format = template.export.format
    dest.export.transparent = template.export.transparent

    for graph_id, t_graph in template.graphs.items():
        if graph_id in dest.graphs:
            d_graph = dest.graphs[graph_id]
            d_graph.x_label = t_graph.x_label
            d_graph.y_label = t_graph.y_label
            d_graph.x_scale = t_graph.x_scale
            d_graph.y_scale = t_graph.y_scale
            d_graph.x_lim = t_graph.x_lim
            d_graph.y_lim = t_graph.y_lim
            d_graph.grid = t_graph.grid
            d_graph.show_spines = t_graph.show_spines
            d_graph.show_legend = t_graph.show_legend
            d_graph.legend_loc = t_graph.legend_loc
            d_graph.x_tick_interval = t_graph.x_tick_interval
            d_graph.x_max_ticks = t_graph.x_max_ticks
            d_graph.y_max_ticks = t_graph.y_max_ticks
            d_graph.twin_y = t_graph.twin_y
            d_graph.y2_label = t_graph.y2_label
            d_graph.y2_scale = t_graph.y2_scale
            d_graph.y2_lim = t_graph.y2_lim
            d_graph.default_linewidth = t_graph.default_linewidth
            d_graph.trace_styles = t_graph.trace_styles
            d_graph.show_event_markers = t_graph.show_event_markers
            d_graph.show_event_labels = t_graph.show_event_labels
            d_graph.event_line_color = t_graph.event_line_color
            d_graph.event_line_width = t_graph.event_line_width
            d_graph.event_line_style = t_graph.event_line_style
            d_graph.event_label_rotation = t_graph.event_label_rotation
