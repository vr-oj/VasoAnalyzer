"""Helpers for applying unified plot styles across the UI and exports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, cast

from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.text import Text

from .constants import DEFAULT_STYLE

EventText = Sequence[tuple[Text, float, object]]
PinnedPoint = Sequence[tuple[Line2D, Text]]
FontStyle = Literal["normal", "italic", "oblique"]


class PlotStyleManager:
    """Maintain and apply a normalized plot style dictionary."""

    def __init__(self, style: dict | None = None) -> None:
        self._style: dict = {}
        self.replace(style)

    # ------------------------------------------------------------------
    def style(self) -> dict:
        """Return a shallow copy of the current style dictionary."""

        return self._style.copy()

    def replace(self, style: dict | None) -> None:
        """Replace the managed style with a fresh merge against defaults."""

        merged = DEFAULT_STYLE.copy()
        if style:
            merged.update(style)
        self._style = merged

    def update(self, overrides: dict | None) -> dict:
        """Update the current style with overrides and return the result."""

        if overrides:
            updated = self._style.copy()
            updated.update(overrides)
            self.replace(updated)
        return self._style

    # ------------------------------------------------------------------ Preset Support

    def to_preset(self, name: str, description: str = "", tags: list[str] | None = None) -> dict:
        """
        Convert current style to a preset dictionary.

        Args:
            name: Preset name
            description: Optional description
            tags: Optional tags (e.g., ["journal", "nature"])

        Returns:
            Preset dictionary with metadata and style
        """
        return {
            "name": name,
            "description": description,
            "tags": tags or [],
            "style": self._style.copy(),
        }

    def from_preset(self, preset: dict) -> None:
        """
        Load style from preset dictionary.

        Args:
            preset: Preset dictionary (must contain "style" key)
        """
        if "style" in preset:
            self.replace(preset["style"])

    # ------------------------------------------------------------------
    def apply(
        self,
        *,
        ax: Axes | None,
        ax_secondary: Axes | None = None,
        x_axis: Axes | None = None,
        event_text_objects: Iterable[tuple[Text, float, object]] | None = None,
        pinned_points: Iterable[tuple[Line2D, Text]] | None = None,
        main_line: Line2D | None = None,
        od_line: Line2D | None = None,
    ) -> None:
        """Apply the managed style to the provided matplotlib artists."""

        if ax is None:
            return

        x_axis = x_axis or ax

        # Detect PyQtGraph backend - skip matplotlib-specific styling
        # PyQtGraph axes don't have 'xaxis' attribute (matplotlib-specific)
        is_pyqtgraph = not hasattr(x_axis, 'xaxis')
        if is_pyqtgraph:
            # PyQtGraph styling is handled by the PyQtGraph renderer itself
            # This style manager is designed for matplotlib only
            return

        style = self._style
        axis_font_size = style.get("axis_font_size", DEFAULT_STYLE["axis_font_size"])
        axis_font_family = style.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
        axis_weight = "bold" if style.get("axis_bold", DEFAULT_STYLE["axis_bold"]) else "normal"
        axis_style: FontStyle = (
            "italic" if style.get("axis_italic", DEFAULT_STYLE["axis_italic"]) else "normal"
        )

        x_axis_color = style.get(
            "x_axis_color", style.get("axis_color", DEFAULT_STYLE["axis_color"])
        )
        y_axis_color = style.get(
            "y_axis_color", style.get("axis_color", DEFAULT_STYLE["axis_color"])
        )
        right_axis_color = style.get(
            "right_axis_color", style.get("axis_color", DEFAULT_STYLE["axis_color"])
        )

        tick_font_size = style.get("tick_font_size", DEFAULT_STYLE["tick_font_size"])
        tick_length = float(style.get("tick_length", DEFAULT_STYLE["tick_length"]))
        tick_width = float(style.get("tick_width", DEFAULT_STYLE["tick_width"]))
        x_tick_color = style.get(
            "x_tick_color", style.get("tick_color", DEFAULT_STYLE["tick_color"])
        )
        y_tick_color = style.get(
            "y_tick_color", style.get("tick_color", DEFAULT_STYLE["tick_color"])
        )
        right_tick_color = style.get(
            "right_tick_color", style.get("tick_color", DEFAULT_STYLE["tick_color"])
        )

        if x_axis is not None:
            x_label = x_axis.xaxis.label
            x_label.set_fontsize(axis_font_size)
            x_label.set_fontname(axis_font_family)
            x_label.set_fontstyle(axis_style)
            x_label.set_fontweight(axis_weight)
            x_label.set_color(x_axis_color)

            for spine_name in ("bottom", "top"):
                if spine_name in x_axis.spines:
                    x_axis.spines[spine_name].set_color(x_axis_color)

            x_axis.tick_params(
                axis="x",
                labelsize=tick_font_size,
                colors=x_tick_color,
                length=tick_length,
                width=tick_width,
            )

        y_label = ax.yaxis.label
        y_label.set_fontsize(axis_font_size)
        y_label.set_fontname(axis_font_family)
        y_label.set_fontstyle(axis_style)
        y_label.set_fontweight(axis_weight)
        y_label.set_color(y_axis_color)

        for spine_name in ("left", "right"):
            if spine_name in ax.spines:
                ax.spines[spine_name].set_color(y_axis_color)

        ax.tick_params(
            axis="y",
            labelsize=tick_font_size,
            colors=y_tick_color,
            length=tick_length,
            width=tick_width,
        )

        if ax_secondary is not None:
            ax_secondary.yaxis.label.set_fontsize(axis_font_size)
            ax_secondary.yaxis.label.set_fontname(axis_font_family)
            ax_secondary.yaxis.label.set_fontstyle(axis_style)
            ax_secondary.yaxis.label.set_fontweight(axis_weight)
            ax_secondary.yaxis.label.set_color(right_axis_color)

            if "right" in ax_secondary.spines:
                ax_secondary.spines["right"].set_color(right_axis_color)
            for spine_name, color in (("top", x_axis_color), ("bottom", x_axis_color)):
                if spine_name in ax_secondary.spines:
                    ax_secondary.spines[spine_name].set_color(color)

            ax_secondary.tick_params(
                axis="y",
                labelsize=tick_font_size,
                colors=right_tick_color,
                length=tick_length,
                width=tick_width,
            )

        event_style = {
            "size": style.get("event_font_size", DEFAULT_STYLE["event_font_size"]),
            "family": style.get("event_font_family", DEFAULT_STYLE["event_font_family"]),
            "weight": "bold" if style.get("event_bold", DEFAULT_STYLE["event_bold"]) else "normal",
            "style": cast(
                FontStyle,
                "italic" if style.get("event_italic", DEFAULT_STYLE["event_italic"]) else "normal",
            ),
            "color": style.get("event_color", DEFAULT_STYLE["event_color"]),
        }

        for txt, *_ in event_text_objects or []:
            if isinstance(txt, Text):
                txt.set_fontsize(event_style["size"])
                txt.set_fontname(event_style["family"])
                txt.set_fontstyle(event_style["style"])
                txt.set_fontweight(event_style["weight"])
                txt.set_color(event_style["color"])

        pin_font = {
            "size": style.get("pin_font_size", DEFAULT_STYLE["pin_font_size"]),
            "family": style.get("pin_font_family", DEFAULT_STYLE["pin_font_family"]),
            "weight": "bold" if style.get("pin_bold", DEFAULT_STYLE["pin_bold"]) else "normal",
            "style": cast(
                FontStyle,
                "italic" if style.get("pin_italic", DEFAULT_STYLE["pin_italic"]) else "normal",
            ),
            "color": style.get("pin_color", DEFAULT_STYLE["pin_color"]),
        }
        pin_marker_size = style.get("pin_size", DEFAULT_STYLE["pin_size"])

        for marker, label in pinned_points or []:
            if isinstance(marker, Line2D):
                marker.set_markersize(pin_marker_size)
                marker.set_color(pin_font["color"])
            if isinstance(label, Text):
                label.set_fontsize(pin_font["size"])
                label.set_fontname(pin_font["family"])
                label.set_fontstyle(pin_font["style"])
                label.set_fontweight(pin_font["weight"])
                label.set_color(pin_font["color"])

        primary_line = main_line or (ax.lines[0] if ax.lines else None)
        if isinstance(primary_line, Line2D):
            primary_line.set_linewidth(style.get("line_width", DEFAULT_STYLE["line_width"]))
            primary_line.set_color(style.get("line_color", DEFAULT_STYLE["line_color"]))
            primary_line.set_linestyle(style.get("line_style", DEFAULT_STYLE["line_style"]))

        od_target = od_line
        if od_target is None and ax_secondary is not None and ax_secondary.lines:
            od_target = ax_secondary.lines[0]
        if isinstance(od_target, Line2D):
            od_target.set_linewidth(
                style.get("outer_line_width", DEFAULT_STYLE["outer_line_width"])
            )
            od_target.set_color(style.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]))
            od_target.set_linestyle(
                style.get("outer_line_style", DEFAULT_STYLE.get("outer_line_style", "solid"))
            )
