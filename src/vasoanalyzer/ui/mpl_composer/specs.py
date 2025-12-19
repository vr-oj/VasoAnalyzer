"""Semantic specs for the Matplotlib composer (document-first layer).

This module holds GraphSpec-level toggles that compile into renderer-friendly
FigureSpec structures (see renderer.py). Keep this file free of Matplotlib
imports to preserve purity of the specs layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from .templates import DEFAULT_TEMPLATE_ID

__all__ = ["GraphSpec", "EventDisplaySpec", "DEFAULT_EVENT_DISPLAY"]


@dataclass
class EventDisplaySpec:
    """Event visibility and styling defaults (no Matplotlib types)."""

    show_event_markers: bool = True
    show_event_labels: bool = False  # Matches current UI default in composer_window
    event_marker_style: Optional[Dict[str, Any]] = None
    event_label_style: Optional[Dict[str, Any]] = None


@dataclass
class GraphSpec:
    """Semantic graph definition (single-axes) used by the composer."""

    template_id: str = DEFAULT_TEMPLATE_ID
    figure_width_in: float | None = None
    figure_height_in: float | None = None
    size_mode: str = "template"  # "template", "preset", "custom"
    size_preset: str | None = None  # "wide", "tall", "square"
    show_event_markers: bool = True
    show_event_labels: bool = False
    event_marker_style: Optional[Dict[str, Any]] = None
    event_label_style: Optional[Dict[str, Any]] = None

    def apply_event_display(self, axes_spec: Any) -> None:
        """Copy event visibility flags onto a renderer-friendly AxesSpec."""
        if not hasattr(axes_spec, "show_event_markers"):
            axes_spec.show_event_markers = self.show_event_markers
        if not hasattr(axes_spec, "show_event_labels"):
            axes_spec.show_event_labels = self.show_event_labels


DEFAULT_EVENT_DISPLAY = EventDisplaySpec()
