"""Serialization helpers for FigureSpec."""

from __future__ import annotations

import json
import copy
import logging
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .specs import (
    AnnotationSpec,
    ExportSpec,
    FigureSpec,
    FontSpec,
    GraphInstance,
    GraphSpec,
    LayoutSpec,
    PanelLabelSpec,
    StyleSpec,
    TextRoleFont,
)

FIGURE_SPEC_SCHEMA_VERSION = 1
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)
DATASET_FIGURE_KEY = "matplotlib_composer"

log = logging.getLogger(__name__)


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
    panel_labels_raw = layout_raw.get("panel_labels", {}) or {}
    layout_kwargs["panel_labels"] = PanelLabelSpec(**_filter_kwargs(PanelLabelSpec, panel_labels_raw))
    layout = LayoutSpec(**layout_kwargs)

    ann_list = raw.get("annotations", []) or []
    annotations = [
        AnnotationSpec(**_filter_kwargs(AnnotationSpec, a_raw)) for a_raw in ann_list
    ]

    export_raw = raw.get("export", {}) or {}
    export = ExportSpec(**_filter_kwargs(ExportSpec, export_raw))

    font_raw = raw.get("font", {}) or {}
    font = _coerce_font(font_raw)

    style_raw = raw.get("style", {}) or {}
    style = StyleSpec(**_filter_kwargs(StyleSpec, style_raw))

    metadata = raw.get("metadata", {}) or {}

    return FigureSpec(
        graphs=graphs,
        layout=layout,
        annotations=annotations,
        export=export,
        font=font,
        style=style,
        metadata=metadata,
    )


def _coerce_font(font_raw: Dict[str, Any]) -> FontSpec:
    """Handle legacy font structures when loading specs/templates."""
    if not font_raw:
        return FontSpec()

    # If new structure exists
    if "figure_title" in font_raw or "axis_title" in font_raw:
        def _make(role_key: str, fallback_size: float, fallback_weight: str = "normal"):
            raw_role = font_raw.get(role_key, {}) or {}
            if isinstance(raw_role, dict):
                size = raw_role.get("size", fallback_size)
                weight = raw_role.get("weight", fallback_weight)
                style = raw_role.get("style", "normal")
            else:
                size = fallback_size
                weight = fallback_weight
                style = "normal"
            return TextRoleFont(size=size, weight=weight, style=style)

        font = FontSpec(
            family=font_raw.get("family", "Arial"),
            figure_title=_make("figure_title", 10.0, "bold"),
            panel_label=_make("panel_label", 9.0, "bold"),
            axis_title=_make("axis_title", 9.0, "bold"),
            tick_label=_make("tick_label", 8.0, "normal"),
            legend=_make("legend", 8.0, "normal"),
            annotation=_make("annotation", 8.0, "normal"),
            base_size=float(font_raw.get("base_size", font_raw.get("base", 8.0))),
        )
        return font

    # Legacy structure: map scalar fields
    def _legacy_size(key: str, default: float) -> float:
        return float(font_raw.get(key, default))

    global_weight = font_raw.get("weight", "normal")
    global_style = font_raw.get("style", "normal")
    font = FontSpec(
        family=font_raw.get("family", "Arial"),
        figure_title=TextRoleFont(
            size=_legacy_size("title_size", 10.0),
            weight=global_weight,
            style=global_style,
        ),
        panel_label=TextRoleFont(
            size=_legacy_size("axis_label_size", 9.0),
            weight=global_weight,
            style=global_style,
        ),
        axis_title=TextRoleFont(
            size=_legacy_size("axis_label_size", 9.0),
            weight=global_weight,
            style=global_style,
        ),
        tick_label=TextRoleFont(
            size=_legacy_size("tick_label_size", 8.0),
            weight=global_weight,
            style=global_style,
        ),
        legend=TextRoleFont(
            size=_legacy_size("legend_size", 8.0),
            weight=global_weight,
            style=global_style,
        ),
        annotation=TextRoleFont(
            size=_legacy_size("annotation_size", 8.0),
            weight=global_weight,
            style=global_style,
        ),
        base_size=float(font_raw.get("base_size", font_raw.get("base", 8.0))),
    )
    return font


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
    dest.layout.graph_instances = copy.deepcopy(template.layout.graph_instances)
    dest.layout.panel_labels = copy.deepcopy(template.layout.panel_labels)

    dest.font.family = template.font.family
    dest.font.base_size = template.font.base_size
    dest.font.figure_title = copy.deepcopy(template.font.figure_title)
    dest.font.panel_label = copy.deepcopy(template.font.panel_label)
    dest.font.axis_title = copy.deepcopy(template.font.axis_title)
    dest.font.tick_label = copy.deepcopy(template.font.tick_label)
    dest.font.legend = copy.deepcopy(template.font.legend)
    dest.font.annotation = copy.deepcopy(template.font.annotation)

    dest.style.default_linewidth = template.style.default_linewidth
    dest.style.axis_spine_width = template.style.axis_spine_width
    dest.style.tick_direction = template.style.tick_direction
    dest.style.tick_major_length = template.style.tick_major_length
    dest.style.tick_minor_length = template.style.tick_minor_length

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


def _normalize_dataset_id(value: Any) -> str | None:
    return None if value is None else str(value)


def _resolve_sample_for_dataset(project: Any, dataset_id: Any) -> Any:
    """Return sample matching dataset_id inside a project-like object."""
    if project is None or dataset_id is None:
        return None
    normalized = _normalize_dataset_id(dataset_id)

    # Accept being handed a sample directly
    if hasattr(project, "figure_configs") and not hasattr(project, "experiments"):
        sample_ds_id = _normalize_dataset_id(getattr(project, "dataset_id", None))
        if normalized == sample_ds_id:
            return project

    for exp in getattr(project, "experiments", []) or []:
        for sample in getattr(exp, "samples", []) or []:
            sample_ds_id = _normalize_dataset_id(getattr(sample, "dataset_id", None))
            if normalized == sample_ds_id:
                return sample
    return None


def save_dataset_figure_spec(project: Any, dataset_id: Any, spec: FigureSpec) -> None:
    """Persist a FigureSpec for a dataset within a project structure."""
    sample = _resolve_sample_for_dataset(project, dataset_id)
    if sample is None:
        log.warning("No sample found for dataset_id=%s; figure spec not saved", dataset_id)
        return

    spec_dict = figure_spec_to_dict(spec)
    if not isinstance(getattr(sample, "figure_configs", None), dict):
        sample.figure_configs = {}

    existing = sample.figure_configs.get(DATASET_FIGURE_KEY)
    metadata = {"modified": datetime.now().isoformat()}
    if isinstance(existing, dict):
        created = (existing.get("metadata") or {}).get("created")
        if created:
            metadata["created"] = created
    else:
        metadata["created"] = datetime.now().isoformat()

    figure_name = None
    if isinstance(existing, dict):
        figure_name = existing.get("figure_name") or figure_name
    if not figure_name:
        figure_name = "Matplotlib Composer"

    sample.figure_configs[DATASET_FIGURE_KEY] = {
        "figure_name": figure_name,
        "figure_kind": "pure_mpl",
        "metadata": metadata,
        "figure_spec": spec_dict,
    }


def load_dataset_figure_spec(project: Any, dataset_id: Any) -> Optional[FigureSpec]:
    """Load a dataset's saved FigureSpec if present."""
    sample = _resolve_sample_for_dataset(project, dataset_id)
    if sample is None:
        return None

    configs = getattr(sample, "figure_configs", None)
    if not isinstance(configs, dict):
        return None

    payload = configs.get(DATASET_FIGURE_KEY)
    raw_spec = None
    if isinstance(payload, dict):
        raw_spec = payload.get("figure_spec") or payload.get("spec")
        if raw_spec is None and {"graphs", "layout"} <= set(payload.keys()):
            raw_spec = payload
    elif isinstance(payload, (list, tuple)):
        return None

    if raw_spec is None:
        return None

    try:
        return figure_spec_from_dict(copy.deepcopy(raw_spec))
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Failed to load figure spec for dataset_id=%s: %s", dataset_id, exc)
        return None
