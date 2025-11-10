"""Simple epoch renderer for main trace view - publication-ready style.

This module provides a simplified epoch rendering system optimized for the main
trace view, using plain rectangular bars similar to those in scientific publications.

Key differences from the full EpochLayer system:
- Simple rectangular bars (no fancy styles)
- Publication-ready black/white design
- Semantic row organization (Pressure, Drug, Treatment)
- Minimal visual complexity
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from matplotlib.axes import Axes
from matplotlib.patches import Rectangle
from matplotlib.text import Text
from matplotlib.transforms import blended_transform_factory

log = logging.getLogger(__name__)

__all__ = ["SimpleEpoch", "SimpleEpochRenderer", "events_to_simple_epochs"]


class SimpleEpoch:
    """Simple epoch representation for main trace view."""

    def __init__(
        self,
        label: str,
        t_start: float,
        t_end: float,
        row: str = "Protocol",
        *,
        color: str = "#000000",
        fill: str = "#FFFFFF",
    ):
        """Initialize simple epoch.

        Args:
            label: Display text
            t_start: Start time (seconds)
            t_end: End time (seconds)
            row: Semantic row name ("Pressure", "Drug", "Treatment", "Protocol")
            color: Border color (default black)
            fill: Fill color (default white)
        """
        self.label = label
        self.t_start = t_start
        self.t_end = t_end
        self.row = row
        self.color = color
        self.fill = fill

    def overlaps(self, other: SimpleEpoch) -> bool:
        """Check if this epoch overlaps with another."""
        return not (self.t_end <= other.t_start or other.t_end <= self.t_start)

    def duration(self) -> float:
        """Return epoch duration in seconds."""
        return self.t_end - self.t_start


class SimpleEpochRenderer:
    """Simple epoch renderer for main trace view.

    Renders protocol timeline epochs as simple rectangular bars above traces,
    using a publication-ready black/white design.
    """

    # Semantic row order (top to bottom)
    DEFAULT_ROW_ORDER = ["Treatment", "Drug", "Pressure", "Protocol"]

    def __init__(
        self,
        *,
        row_height_px: float = 20.0,
        row_gap_px: float = 3.0,
        font_size: float = 8.0,
        border_width: float = 1.0,
    ):
        """Initialize simple epoch renderer.

        Args:
            row_height_px: Height of each epoch bar in pixels
            row_gap_px: Vertical gap between rows
            font_size: Label font size in points
            border_width: Border line width
        """
        self.row_height_px = row_height_px
        self.row_gap_px = row_gap_px
        self.font_size = font_size
        self.border_width = border_width

        self._epochs: list[SimpleEpoch] = []
        self._axes: Axes | None = None
        self._artists: list[Any] = []
        self._row_order = self.DEFAULT_ROW_ORDER

    def set_epochs(self, epochs: list[SimpleEpoch]) -> None:
        """Set the epochs to render."""
        self._epochs = epochs
        if self._axes is not None:
            self._redraw()

    def attach(self, axes: Axes | None) -> None:
        """Attach to matplotlib axes."""
        if self._axes is axes:
            return

        self._clear_artists()
        self._axes = axes

        if axes is not None:
            self._redraw()

    def clear(self) -> None:
        """Clear all epochs and artists."""
        self._epochs.clear()
        self._clear_artists()

    def _clear_artists(self) -> None:
        """Remove all matplotlib artists."""
        for artist in self._artists:
            with contextlib.suppress(Exception):
                artist.remove()
        self._artists.clear()

    def _redraw(self) -> None:
        """Redraw all epochs."""
        if self._axes is None or not self._epochs:
            return

        self._clear_artists()

        # Group epochs by row and handle overlaps
        row_assignments = self._assign_rows()

        # Render each epoch
        for epoch, absolute_row_idx in row_assignments:
            self._render_epoch(epoch, absolute_row_idx)

    def _assign_rows(self) -> list[tuple[SimpleEpoch, int]]:
        """Assign absolute row indices to epochs, handling overlaps.

        Returns:
            List of (epoch, row_index) tuples
        """
        # Group epochs by semantic row
        row_groups: dict[str, list[SimpleEpoch]] = {}
        for epoch in self._epochs:
            row_name = epoch.row
            if row_name not in row_groups:
                row_groups[row_name] = []
            row_groups[row_name].append(epoch)

        result: list[tuple[SimpleEpoch, int]] = []
        current_row = 0

        # Process rows in defined order
        for row_name in self._row_order:
            if row_name not in row_groups:
                continue

            epochs_in_row = row_groups[row_name]
            epochs_in_row.sort(key=lambda e: e.t_start)

            # Stack overlapping epochs in sub-rows
            sub_rows: list[list[SimpleEpoch]] = []
            for epoch in epochs_in_row:
                # Find first sub-row where epoch fits
                placed = False
                for sub_row in sub_rows:
                    if not any(epoch.overlaps(other) for other in sub_row):
                        sub_row.append(epoch)
                        placed = True
                        break

                if not placed:
                    # Create new sub-row
                    sub_rows.append([epoch])

            # Assign absolute row indices
            for sub_row_idx, sub_row in enumerate(sub_rows):
                for epoch in sub_row:
                    result.append((epoch, current_row + sub_row_idx))

            # Advance to next row group
            current_row += len(sub_rows)

        return result

    def _render_epoch(self, epoch: SimpleEpoch, row_idx: int) -> None:
        """Render a single epoch bar."""
        if self._axes is None:
            return

        # Use blended transform (data X, axes Y)
        transform = self._axes.get_xaxis_transform()

        # Calculate y position (above plot area)
        y_base = 1.02  # Start above top spine
        row_height_axes = self._px_to_axes_height(self.row_height_px)
        row_gap_axes = self._px_to_axes_height(self.row_gap_px)

        y = y_base + row_idx * (row_height_axes + row_gap_axes)

        # Create rectangle bar
        rect = Rectangle(
            xy=(epoch.t_start, y),
            width=epoch.t_end - epoch.t_start,
            height=row_height_axes,
            transform=transform,
            facecolor=epoch.fill,
            edgecolor=epoch.color,
            linewidth=self.border_width,
            clip_on=False,
            zorder=20,
        )
        self._axes.add_patch(rect)
        self._artists.append(rect)

        # Add label
        x_center = (epoch.t_start + epoch.t_end) / 2.0
        y_center = y + row_height_axes / 2.0

        text = self._axes.text(
            x_center,
            y_center,
            epoch.label,
            transform=transform,
            fontsize=self.font_size,
            color=epoch.color,
            ha="center",
            va="center",
            clip_on=False,
            zorder=30,
        )
        self._artists.append(text)

    def _px_to_axes_height(self, px: float) -> float:
        """Convert pixel height to axes coordinates."""
        if self._axes is None or self._axes.figure is None:
            return 0.01

        bbox = self._axes.get_window_extent()
        axes_height_px = bbox.height

        if axes_height_px > 0:
            return px / axes_height_px
        return 0.01


def events_to_simple_epochs(
    event_times: list[float],
    event_labels: list[str],
    event_label_meta: list[dict[str, Any]],
    *,
    default_duration: float = 60.0,
) -> list[SimpleEpoch]:
    """Convert VasoAnalyzer events to SimpleEpoch objects.

    Maps event categories to semantic rows:
    - "pressure" or "setpoint" → Pressure row
    - "drug" → Drug row
    - "blocker" → Drug row (treated same as drug)
    - "bath" or "perfusate" → Treatment row
    - Other → Protocol row

    Args:
        event_times: Event timestamps in seconds
        event_labels: Event text labels
        event_label_meta: Event metadata dictionaries
        default_duration: Default epoch duration when not specified (seconds)

    Returns:
        List of SimpleEpoch objects
    """
    if not event_times or not event_labels:
        return []

    epochs: list[SimpleEpoch] = []

    # Group events by category to infer durations
    category_events: dict[str, list[tuple[int, float, str]]] = {}
    for i, (t, label, meta) in enumerate(zip(event_times, event_labels, event_label_meta)):
        category = (meta.get("category", "") or "").lower()
        if category not in category_events:
            category_events[category] = []
        category_events[category].append((i, t, label))

    # Sort each category by time
    for events in category_events.values():
        events.sort(key=lambda x: x[1])

    # Process each event
    for i, (t, label, meta) in enumerate(zip(event_times, event_labels, event_label_meta)):
        category = (meta.get("category", "") or "").lower()

        # Determine semantic row
        if category in {"pressure", "setpoint"}:
            row = "Pressure"
        elif category in {"drug", "blocker"}:
            row = "Drug"
        elif category in {"bath", "perfusate"}:
            row = "Treatment"
        else:
            row = "Protocol"

        # Determine end time
        explicit_end = meta.get("t_end")
        duration = meta.get("duration")

        if explicit_end is not None and explicit_end > t:
            t_end = float(explicit_end)
        elif duration is not None and duration > 0:
            t_end = t + float(duration)
        else:
            # Try to infer from next event in same category
            cat_events = category_events.get(category, [])
            event_index = next((idx for idx, (ei, _, _) in enumerate(cat_events) if ei == i), -1)
            if event_index >= 0 and event_index + 1 < len(cat_events):
                next_time = cat_events[event_index + 1][1]
                t_end = next_time
            else:
                t_end = t + default_duration

        # Create epoch
        epoch = SimpleEpoch(
            label=label,
            t_start=t,
            t_end=t_end,
            row=row,
            color="#000000",
            fill="#FFFFFF",
        )
        epochs.append(epoch)

    return epochs
