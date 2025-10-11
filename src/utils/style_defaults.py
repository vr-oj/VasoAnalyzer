"""Central definition for factory plot style defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

STYLE_SCHEMA_VERSION = 3

STYLE_DEFAULTS: Dict[str, Dict[str, Any]] = {
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


def load_factory_defaults() -> Dict[str, Dict[str, Any]]:
    """Return a deep copy of the nested factory defaults."""

    return deepcopy(STYLE_DEFAULTS)


def _get(style: Dict[str, Any], key: str, fallback: Any) -> Any:
    return style.get(key, fallback)


def flatten_style_defaults(style: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
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
        "outer_line_width": float(_get(lines, "outer_width", STYLE_DEFAULTS["lines"]["outer_width"])),
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


def load_flat_factory_defaults() -> Dict[str, Any]:
    """Return a flattened, deep-copied defaults dictionary."""

    return deepcopy(flatten_style_defaults())
