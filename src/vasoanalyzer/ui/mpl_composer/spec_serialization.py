"""FigureSpec serialization helpers for the active Matplotlib composer."""

from __future__ import annotations

from typing import Any

from .renderer import AnnotationSpec, AxesSpec, EventSpec, FigureSpec, PageSpec, TraceSpec

SPEC_VERSION = 1


def figure_spec_to_dict(spec: FigureSpec) -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "template_id": getattr(spec, "template_id", "single_column"),
        "page": {
            "width_in": spec.page.width_in,
            "height_in": spec.page.height_in,
            "dpi": spec.page.dpi,
            "sizing_mode": getattr(spec.page, "sizing_mode", "axes_first"),
            "axes_first": getattr(spec.page, "axes_first", False),
            "axes_width_in": getattr(spec.page, "axes_width_in", None),
            "axes_height_in": getattr(spec.page, "axes_height_in", None),
            "min_margin_in": getattr(spec.page, "min_margin_in", None),
            "left_margin_in": getattr(spec.page, "left_margin_in", None),
            "right_margin_in": getattr(spec.page, "right_margin_in", None),
            "top_margin_in": getattr(spec.page, "top_margin_in", None),
            "bottom_margin_in": getattr(spec.page, "bottom_margin_in", None),
            "export_background": getattr(spec.page, "export_background", "white"),
        },
        "axes": {
            "x_range": list(spec.axes.x_range) if spec.axes.x_range is not None else None,
            "y_range": list(spec.axes.y_range) if spec.axes.y_range is not None else None,
            "xlabel": spec.axes.xlabel,
            "ylabel": spec.axes.ylabel,
            "show_grid": spec.axes.show_grid,
            "grid_linestyle": spec.axes.grid_linestyle,
            "grid_color": spec.axes.grid_color,
            "grid_alpha": spec.axes.grid_alpha,
            "show_event_markers": getattr(spec.axes, "show_event_markers", True),
            "show_event_labels": getattr(spec.axes, "show_event_labels", False),
            "xlabel_fontsize": getattr(spec.axes, "xlabel_fontsize", None),
            "ylabel_fontsize": getattr(spec.axes, "ylabel_fontsize", None),
            "tick_label_fontsize": getattr(spec.axes, "tick_label_fontsize", None),
            "label_bold": getattr(spec.axes, "label_bold", True),
        },
        "traces": [
            {
                "key": t.key,
                "visible": t.visible,
                "color": t.color,
                "linewidth": t.linewidth,
                "linestyle": t.linestyle,
                "marker": t.marker,
                "use_right_axis": getattr(t, "use_right_axis", False),
            }
            for t in spec.traces
        ],
        "events": [
            {
                "visible": e.visible,
                "time_s": e.time_s,
                "color": e.color,
                "linewidth": e.linewidth,
                "linestyle": e.linestyle,
                "label": e.label,
                "label_above": e.label_above,
            }
            for e in spec.events
        ],
        "annotations": [
            {
                "kind": a.kind,
                "text": a.text,
                "x": a.x,
                "y": a.y,
                "x2": a.x2,
                "y2": a.y2,
                "coord_space": a.coord_space,
                "fontsize": a.fontsize,
                "color": a.color,
                "linewidth": a.linewidth,
            }
            for a in spec.annotations
        ],
        "legend_visible": spec.legend_visible,
        "legend_fontsize": spec.legend_fontsize,
        "legend_loc": spec.legend_loc,
        "line_width_scale": spec.line_width_scale,
    }


def figure_spec_from_dict(data: dict[str, Any]) -> FigureSpec:
    axes_d = data.get("axes", {}) or {}
    page_d = data.get("page", {}) or {}
    traces_d = data.get("traces", []) or []
    events_d = data.get("events", []) or []
    annos_d = data.get("annotations", []) or []
    default_show_event_markers = (
        any(bool(e.get("visible", True)) for e in events_d) if events_d else True
    )
    template_id = data.get("template_id", "single_column")

    page = PageSpec(
        width_in=float(page_d.get("width_in", 6.0)),
        height_in=float(page_d.get("height_in", 3.0)),
        dpi=float(page_d.get("dpi", 300.0)),
        sizing_mode=page_d.get("sizing_mode", "axes_first"),
        axes_first=bool(page_d.get("axes_first", False)),
        axes_width_in=page_d.get("axes_width_in"),
        axes_height_in=page_d.get("axes_height_in"),
        min_margin_in=page_d.get("min_margin_in", 0.15),
        left_margin_in=page_d.get("left_margin_in"),
        right_margin_in=page_d.get("right_margin_in"),
        top_margin_in=page_d.get("top_margin_in"),
        bottom_margin_in=page_d.get("bottom_margin_in"),
        export_background=page_d.get("export_background", "white"),
    )

    axes = AxesSpec(
        x_range=tuple(axes_d["x_range"]) if axes_d.get("x_range") else None,
        y_range=tuple(axes_d["y_range"]) if axes_d.get("y_range") else None,
        xlabel=axes_d.get("xlabel", ""),
        ylabel=axes_d.get("ylabel", ""),
        show_grid=bool(axes_d.get("show_grid", True)),
        grid_linestyle=axes_d.get("grid_linestyle", "--"),
        grid_color=axes_d.get("grid_color", "#c0c0c0"),
        grid_alpha=float(axes_d.get("grid_alpha", 0.7)),
        show_event_markers=bool(axes_d.get("show_event_markers", default_show_event_markers)),
        show_event_labels=bool(axes_d.get("show_event_labels", False)),
        xlabel_fontsize=axes_d.get("xlabel_fontsize"),
        ylabel_fontsize=axes_d.get("ylabel_fontsize"),
        tick_label_fontsize=axes_d.get("tick_label_fontsize"),
        label_bold=bool(axes_d.get("label_bold", True)),
    )

    traces = [
        TraceSpec(
            key=t.get("key", "inner"),
            visible=bool(t.get("visible", True)),
            color=t.get("color", "#000000"),
            linewidth=float(t.get("linewidth", 1.5)),
            linestyle=t.get("linestyle", "-"),
            marker=t.get("marker", ""),
            use_right_axis=bool(t.get("use_right_axis", False)),
        )
        for t in traces_d
    ]

    events = [
        EventSpec(
            visible=bool(e.get("visible", True)),
            time_s=float(e.get("time_s", 0.0)),
            color=e.get("color", "#444444"),
            linewidth=float(e.get("linewidth", 1.0)),
            linestyle=e.get("linestyle", "--"),
            label=e.get("label", ""),
            label_above=bool(e.get("label_above", True)),
        )
        for e in events_d
    ]

    annotations = [
        AnnotationSpec(
            kind=a.get("kind", "text"),
            text=a.get("text", ""),
            x=float(a.get("x", 0.0)),
            y=float(a.get("y", 0.0)),
            x2=a.get("x2"),
            y2=a.get("y2"),
            coord_space=a.get("coord_space", "data"),
            fontsize=float(a.get("fontsize", 8.0)),
            color=a.get("color", "black"),
            linewidth=float(a.get("linewidth", 1.0)),
        )
        for a in annos_d
    ]

    return FigureSpec(
        page=page,
        axes=axes,
        traces=traces,
        events=events,
        annotations=annotations,
        template_id=template_id,
        legend_visible=bool(data.get("legend_visible", True)),
        legend_fontsize=data.get("legend_fontsize", 9.0),
        legend_loc=data.get("legend_loc", "upper right"),
        line_width_scale=float(data.get("line_width_scale", 1.0)),
    )
