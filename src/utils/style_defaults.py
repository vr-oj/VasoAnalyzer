"""Central definition for factory plot style defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STYLE_SCHEMA_VERSION = 4

STYLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "axis": {
        "plot_title": "",
        "x_title": "Time (s)",
        "y_left_title": "Inner Diameter (µm)",
        "y_right_title": "Outer Diameter (µm)",
        "font_family": "Arial",
        "font_size": 25,
        "bold": True,
        "italic": False,
        "x_color": "#000000",
        "y_left_color": "#000000",
        "y_right_color": "#000000",
    },
    "ticks": {
        "font_size": 18,
        "x_color": "#000000",
        "y_left_color": "#000000",
        "y_right_color": "#000000",
        "length": 4.0,
        "width": 1.0,
    },
    "events": {
        "font_family": "Arial",
        "font_size": 15,
        "bold": False,
        "italic": False,
        "color": "#000000",
        "mode": "vertical",  # vertical, horizontal, horizontal_outside
        "max_per_cluster": 1,
        "style_policy": "first",
        "lanes": 3,
        "belt_baseline": True,
        "span_siblings": True,
        "use_v3": True,
        "auto_mode": False,
        "density_compact": 0.8,
        "density_belt": 0.25,
        "outline_enabled": True,
        "outline_width": 2.0,
        "outline_color": (1.0, 1.0, 1.0, 0.9),
        "tooltips_enabled": True,
        "legend_enabled": True,
        "legend_loc": "upper right",
        "tooltip_proximity": 10,
    },
    "pinned": {
        "font_family": "Arial",
        "font_size": 10,
        "bold": False,
        "italic": False,
        "label_color": "#000000",
        "marker_size": 6,
    },
    "lines": {
        "inner_width": 2.0,
        "inner_style": "solid",
        "inner_color": "#000000",
        "outer_width": 2.0,
        "outer_style": "solid",
        "outer_color": "tab:orange",
    },
    "highlights": {
        "event_color": "#1D5CFF",
        "event_alpha": 0.95,
        "event_duration_ms": 2000,
    },
}


def load_factory_defaults() -> dict[str, dict[str, Any]]:
    """Return a deep copy of the nested factory defaults."""

    return deepcopy(STYLE_DEFAULTS)


def _get(style: dict[str, Any], key: str, fallback: Any) -> Any:
    return style.get(key, fallback)


def flatten_style_defaults(style: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Flatten the nested defaults for legacy consumers in the UI layer."""

    source = style or STYLE_DEFAULTS
    axis = source.get("axis", {})
    ticks = source.get("ticks", {})
    events = source.get("events", {})
    pinned = source.get("pinned", {})
    lines = source.get("lines", {})
    highlights = source.get("highlights", {})

    defaults = {
        "style_schema_version": STYLE_SCHEMA_VERSION,
        # Axis titles
        "axis_plot_title": _get(axis, "plot_title", STYLE_DEFAULTS["axis"]["plot_title"]),
        "axis_x_title": _get(axis, "x_title", STYLE_DEFAULTS["axis"]["x_title"]),
        "axis_y_title": _get(axis, "y_left_title", STYLE_DEFAULTS["axis"]["y_left_title"]),
        "axis_y_right_title": _get(axis, "y_right_title", STYLE_DEFAULTS["axis"]["y_right_title"]),
        # Axis fonts
        "axis_font_family": _get(axis, "font_family", STYLE_DEFAULTS["axis"]["font_family"]),
        "axis_font_size": _get(axis, "font_size", STYLE_DEFAULTS["axis"]["font_size"]),
        "axis_bold": _get(axis, "bold", STYLE_DEFAULTS["axis"]["bold"]),
        "axis_italic": _get(axis, "italic", STYLE_DEFAULTS["axis"]["italic"]),
        # Axis colours
        "axis_color": _get(axis, "x_color", STYLE_DEFAULTS["axis"]["x_color"]),
        "x_axis_color": _get(axis, "x_color", STYLE_DEFAULTS["axis"]["x_color"]),
        "y_axis_color": _get(axis, "y_left_color", STYLE_DEFAULTS["axis"]["y_left_color"]),
        "right_axis_color": _get(axis, "y_right_color", STYLE_DEFAULTS["axis"]["y_right_color"]),
        # Tick styling
        "tick_font_size": _get(ticks, "font_size", STYLE_DEFAULTS["ticks"]["font_size"]),
        "tick_color": _get(ticks, "x_color", STYLE_DEFAULTS["ticks"]["x_color"]),
        "x_tick_color": _get(ticks, "x_color", STYLE_DEFAULTS["ticks"]["x_color"]),
        "y_tick_color": _get(ticks, "y_left_color", STYLE_DEFAULTS["ticks"]["y_left_color"]),
        "right_tick_color": _get(ticks, "y_right_color", STYLE_DEFAULTS["ticks"]["y_right_color"]),
        "tick_length": float(_get(ticks, "length", STYLE_DEFAULTS["ticks"]["length"])),
        "tick_width": float(_get(ticks, "width", STYLE_DEFAULTS["ticks"]["width"])),
        # Event annotations
        "event_font_family": _get(events, "font_family", STYLE_DEFAULTS["events"]["font_family"]),
        "event_font_size": _get(events, "font_size", STYLE_DEFAULTS["events"]["font_size"]),
        "event_bold": _get(events, "bold", STYLE_DEFAULTS["events"]["bold"]),
        "event_italic": _get(events, "italic", STYLE_DEFAULTS["events"]["italic"]),
        "event_color": _get(events, "color", STYLE_DEFAULTS["events"]["color"]),
        "event_label_max_per_cluster": int(
            _get(events, "max_per_cluster", STYLE_DEFAULTS["events"]["max_per_cluster"])
        ),
        "event_label_style_policy": _get(
            events, "style_policy", STYLE_DEFAULTS["events"]["style_policy"]
        ),
        "event_label_lanes": int(_get(events, "lanes", STYLE_DEFAULTS["events"]["lanes"])),
        "event_label_belt_baseline": bool(
            _get(events, "belt_baseline", STYLE_DEFAULTS["events"]["belt_baseline"])
        ),
        "event_label_span_siblings": bool(
            _get(events, "span_siblings", STYLE_DEFAULTS["events"]["span_siblings"])
        ),
        "event_labels_v3_enabled": bool(
            _get(events, "use_v3", STYLE_DEFAULTS["events"]["use_v3"])
        ),
        "event_label_mode": _get(events, "mode", STYLE_DEFAULTS["events"]["mode"]),
        "event_label_auto_mode": bool(
            _get(events, "auto_mode", STYLE_DEFAULTS["events"]["auto_mode"])
        ),
        "event_label_density_compact": float(
            _get(events, "density_compact", STYLE_DEFAULTS["events"]["density_compact"])
        ),
        "event_label_density_belt": float(
            _get(events, "density_belt", STYLE_DEFAULTS["events"]["density_belt"])
        ),
        "event_label_outline_enabled": bool(
            _get(events, "outline_enabled", STYLE_DEFAULTS["events"]["outline_enabled"])
        ),
        "event_label_outline_width": float(
            _get(events, "outline_width", STYLE_DEFAULTS["events"]["outline_width"])
        ),
        "event_label_outline_color": tuple(
            _get(events, "outline_color", STYLE_DEFAULTS["events"]["outline_color"])
        ),
        "event_label_tooltips_enabled": bool(
            _get(events, "tooltips_enabled", STYLE_DEFAULTS["events"]["tooltips_enabled"])
        ),
        "event_label_legend_enabled": bool(
            _get(events, "legend_enabled", STYLE_DEFAULTS["events"]["legend_enabled"])
        ),
        "event_label_legend_loc": _get(
            events, "legend_loc", STYLE_DEFAULTS["events"]["legend_loc"]
        ),
        "event_label_tooltip_proximity": int(
            _get(events, "tooltip_proximity", STYLE_DEFAULTS["events"]["tooltip_proximity"])
        ),
        # Pinned annotations
        "pin_font_family": _get(pinned, "font_family", STYLE_DEFAULTS["pinned"]["font_family"]),
        "pin_font_size": _get(pinned, "font_size", STYLE_DEFAULTS["pinned"]["font_size"]),
        "pin_bold": _get(pinned, "bold", STYLE_DEFAULTS["pinned"]["bold"]),
        "pin_italic": _get(pinned, "italic", STYLE_DEFAULTS["pinned"]["italic"]),
        "pin_color": _get(pinned, "label_color", STYLE_DEFAULTS["pinned"]["label_color"]),
        "pin_size": _get(pinned, "marker_size", STYLE_DEFAULTS["pinned"]["marker_size"]),
        # Trace lines
        "line_width": float(_get(lines, "inner_width", STYLE_DEFAULTS["lines"]["inner_width"])),
        "line_style": _get(lines, "inner_style", STYLE_DEFAULTS["lines"]["inner_style"]),
        "line_color": _get(lines, "inner_color", STYLE_DEFAULTS["lines"]["inner_color"]),
        "outer_line_width": float(
            _get(lines, "outer_width", STYLE_DEFAULTS["lines"]["outer_width"])
        ),
        "outer_line_style": _get(lines, "outer_style", STYLE_DEFAULTS["lines"]["outer_style"]),
        "outer_line_color": _get(lines, "outer_color", STYLE_DEFAULTS["lines"]["outer_color"]),
        # Event highlight styling
        "event_highlight_color": _get(
            highlights,
            "event_color",
            STYLE_DEFAULTS["highlights"]["event_color"],
        ),
        "event_highlight_alpha": float(
            _get(
                highlights,
                "event_alpha",
                STYLE_DEFAULTS["highlights"]["event_alpha"],
            )
        ),
        "event_highlight_duration_ms": int(
            _get(
                highlights,
                "event_duration_ms",
                STYLE_DEFAULTS["highlights"]["event_duration_ms"],
            )
        ),
    }

    return defaults


def load_flat_factory_defaults() -> dict[str, Any]:
    """Return a flattened, deep-copied defaults dictionary."""

    return deepcopy(flatten_style_defaults())
