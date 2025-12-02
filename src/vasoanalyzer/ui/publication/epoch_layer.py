"""Epoch layer renderer for publication mode protocol timeline visualization.

Renders epoch bars, boxes, and shaded regions above trace plots with automatic
row stacking and collision avoidance.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.text import Text

from vasoanalyzer.ui.publication.epoch_model import Epoch, EpochManifest

__all__ = [
    "EpochTheme",
    "EpochLayer",
]

log = logging.getLogger(__name__)


class EpochTheme:
    """Visual styling constants for epoch rendering."""

    def __init__(
        self,
        *,
        row_height_px: float = 16.0,
        row_gap_px: float = 6.0,
        axes_padding_px: float = 12.0,
        label_padding_px: float = 4.0,
        bar_thickness: dict[str, float] | None = None,
        font_size_pt: float = 8.5,
        font_family: str = "sans-serif",
        colors: dict[str, str] | None = None,
        shade_alpha: float = 0.18,
        greyscale: bool = False,
    ) -> None:
        """Initialize epoch visual theme.

        Args:
            row_height_px: Height of each epoch row in pixels
            row_gap_px: Vertical gap between rows in pixels
            axes_padding_px: Padding above the axes baseline before first epoch row (px)
            label_padding_px: Extra clearance above tallest epoch row for labels (px)
            bar_thickness: Thickness by emphasis {"light": 2, "normal": 3, "strong": 4}
            font_size_pt: Label font size in points
            font_family: Label font family
            colors: Channel color map {"Pressure": "#111", "Drug": "#1f77b4", ...}
            shade_alpha: Alpha transparency for shaded regions
            greyscale: Export in greyscale mode with patterns
        """
        self.row_height_px = row_height_px
        self.row_gap_px = row_gap_px
        self.axes_padding_px = axes_padding_px
        self.label_padding_px = label_padding_px
        self.bar_thickness = bar_thickness or {"light": 2.0, "normal": 3.0, "strong": 4.0}
        self.font_size_pt = font_size_pt
        self.font_family = font_family
        self.colors = colors or {
            "Pressure": "#111111",
            "Drug": "#1f77b4",
            "Blocker": "#d62728",
            "Perfusate": "#2ca02c",
            "Custom": "#7f7f7f",
        }
        self.shade_alpha = shade_alpha
        self.greyscale = greyscale

    def get_color(self, channel: str, default: str | None = None) -> str:
        """Get color for channel."""
        return self.colors.get(channel, default or "#000000")

    def get_bar_thickness(self, emphasis: str) -> float:
        """Get bar thickness for emphasis level."""
        return self.bar_thickness.get(emphasis, 3.0)


class EpochLayer:
    """Epoch overlay renderer for matplotlib axes.

    Renders protocol timeline epochs as stacked bars, boxes, and shaded regions
    above the main trace plot area.
    """

    def __init__(
        self,
        epochs: list[Epoch] | None = None,
        row_order: list[str] | None = None,
        theme: EpochTheme | None = None,
    ) -> None:
        """Initialize epoch layer.

        Args:
            epochs: List of epochs to render
            row_order: Channel stacking order (top to bottom)
            theme: Visual theme for rendering
        """
        self.epochs = epochs or []
        self.row_order = row_order or ["Pressure", "Drug", "Blocker", "Perfusate", "Custom"]
        self.theme = theme or EpochTheme()

        # Internal state
        self._artists: list[Any] = []
        self._time_range: tuple[float, float] | None = None
        self._axes: Axes | None = None
        self._layout_change_callback: Callable[[int, float], None] | None = None
        self._row_count: int = 0
        self._required_margin_px: float = 0.0

    # ------------------------------------------------------------------ Public API

    def set_epochs(self, epochs: list[Epoch]) -> None:
        """Update epoch list and trigger redraw if attached to axes."""
        self.epochs = epochs
        if self._axes is not None:
            self._redraw()

    def set_time_range(self, t0: float, t1: float) -> None:
        """Set visible time range (for dynamic zoom/pan)."""
        self._time_range = (t0, t1)
        if self._axes is not None:
            self._redraw()

    def set_theme(self, theme: EpochTheme) -> None:
        """Update visual theme."""
        self.theme = theme
        if self._axes is not None:
            self._redraw()

    def attach(self, axes: Axes | None) -> None:
        """Attach to matplotlib axes (or detach if None)."""
        if self._axes is axes:
            return

        self._clear_artists()
        self._axes = axes

        if axes is not None:
            self._redraw()
        else:
            self._update_layout_metrics(0)

    def set_layout_change_callback(
        self,
        callback: Callable[[int, float], None] | None,
    ) -> None:
        """Register callback for layout (row count / margin) changes."""
        self._layout_change_callback = callback
        if callback is not None:
            callback(self._row_count, self._required_margin_px)

    def get_required_margin_px(self) -> float:
        """Return the current figure margin required for rendered epochs."""
        return self._required_margin_px

    def paint(
        self,
        painter: Any,
        rect: Any,
        x_to_px: Callable[[float], float] | None = None,
    ) -> None:
        """Paint epochs using provided painter and coordinate transform.

        This is an alternative API for QPainter-based rendering (future).

        Args:
            painter: QPainter or similar
            rect: Bounding rectangle
            x_to_px: Transform function from data coords to pixels
        """
        # Placeholder for QPainter rendering
        # Current implementation uses matplotlib artists
        pass

    def to_manifest(self) -> dict[str, Any]:
        """Export epoch configuration as manifest dictionary."""
        manifest = EpochManifest(
            epochs=self.epochs,
            epoch_theme="default_v1",
            row_order=self.row_order,
        )
        manifest_dict: dict[str, Any] = manifest.to_dict()
        return manifest_dict

    def clear(self) -> None:
        """Clear all epochs and artists."""
        self.epochs.clear()
        self._clear_artists()

    # ------------------------------------------------------------------ Rendering

    def _clear_artists(self) -> None:
        """Remove all matplotlib artists."""
        for artist in self._artists:
            with contextlib.suppress(Exception):
                artist.remove()
        self._artists.clear()

    def _redraw(self) -> None:
        """Redraw all epochs on attached axes."""
        if self._axes is None:
            return

        self._clear_artists()

        if not self.epochs:
            self._update_layout_metrics(0)
            return

        # Filter epochs by time range if set
        visible_epochs = self._filter_visible_epochs()

        if not visible_epochs:
            self._update_layout_metrics(0)
            return

        # Auto-assign row indices for overlapping epochs
        epochs_with_rows, row_count = self._assign_row_indices(visible_epochs)
        self._update_layout_metrics(row_count)

        # Render each epoch
        for epoch, row_idx in epochs_with_rows:
            self._render_epoch(epoch, row_idx)

    def _filter_visible_epochs(self) -> list[Epoch]:
        """Filter epochs to visible time range."""
        if self._time_range is None:
            return self.epochs

        t0, t1 = self._time_range
        visible = [epoch for epoch in self.epochs if not (epoch.t_end < t0 or epoch.t_start > t1)]
        return visible

    def _assign_row_indices(self, epochs: list[Epoch]) -> tuple[list[tuple[Epoch, int]], int]:
        """Assign row indices to epochs, handling overlaps.

        Epochs with the same channel that overlap are stacked in separate sub-rows.
        Returns (epoch,row_index) tuples and total row count.
        """
        # Group epochs by channel
        channels_to_epochs: dict[str, list[Epoch]] = {}
        for epoch in epochs:
            channel = epoch.channel
            if channel not in channels_to_epochs:
                channels_to_epochs[channel] = []
            channels_to_epochs[channel].append(epoch)

        # Assign absolute row indices based on channel order
        result: list[tuple[Epoch, int]] = []
        current_row = 0

        for channel in self.row_order:
            if channel not in channels_to_epochs:
                continue

            channel_epochs = channels_to_epochs[channel]

            # Sort by start time
            channel_epochs.sort(key=lambda e: e.t_start)

            # Stack overlapping epochs in sub-rows
            rows: list[list[Epoch]] = []
            for epoch in channel_epochs:
                # Find first row where this epoch fits (no overlap)
                placed = False
                for row in rows:
                    # Check if epoch overlaps with any epoch in this row
                    overlaps = any(epoch.overlaps(other) for other in row)
                    if not overlaps:
                        row.append(epoch)
                        placed = True
                        break

                if not placed:
                    # Create new sub-row
                    rows.append([epoch])

            # Assign absolute row indices
            for sub_row_idx, row in enumerate(rows):
                for epoch in row:
                    result.append((epoch, current_row + sub_row_idx))

            # Advance to next channel's rows
            current_row += len(rows)

        return result, current_row

    def _update_layout_metrics(self, row_count: int) -> None:
        """Update cached layout metrics and notify callbacks if needed."""
        if row_count <= 0:
            required_margin = 0.0
        else:
            required_margin = (
                self.theme.axes_padding_px
                + (row_count * self.theme.row_height_px)
                + (max(row_count - 1, 0) * self.theme.row_gap_px)
                + self.theme.label_padding_px
            )

        changed = (row_count != self._row_count) or (
            abs(required_margin - self._required_margin_px) > 0.5
        )
        self._row_count = row_count
        self._required_margin_px = required_margin

        if changed and self._layout_change_callback is not None:
            self._layout_change_callback(row_count, required_margin)

    def _render_epoch(self, epoch: Epoch, row_idx: int) -> None:
        """Render a single epoch at the specified row."""
        if self._axes is None:
            return

        # Get axis transform (data x, axes y)
        transform = self._axes.get_xaxis_transform()

        # Calculate y position (axes coordinates, 0=bottom, 1=top)
        # Place epochs above the plot area (y > 1.0)
        padding_axes = self._px_to_axes_height(self.theme.axes_padding_px)
        y_base = 1.0 + padding_axes
        row_height_axes = self._px_to_axes_height(self.theme.row_height_px)
        row_gap_axes = self._px_to_axes_height(self.theme.row_gap_px)

        y = y_base + row_idx * (row_height_axes + row_gap_axes)

        # Render based on style
        if epoch.style == "bar":
            self._render_bar(epoch, y, row_height_axes, transform)
        elif epoch.style == "box":
            self._render_box(epoch, y, row_height_axes, transform)
        elif epoch.style == "shade":
            self._render_shade(epoch, y, row_height_axes)

    def _render_bar(self, epoch: Epoch, y: float, height: float, transform: Any) -> None:
        """Render a horizontal bar (for drugs, blockers)."""
        if self._axes is None:
            return

        # Get color and thickness
        color = epoch.color or self.theme.get_color(epoch.channel)
        thickness = self.theme.get_bar_thickness(epoch.emphasis)

        # Convert thickness from points to axes height
        thickness_axes = self._px_to_axes_height(thickness)

        # Create rectangle
        rect = Rectangle(
            xy=(epoch.t_start, y),
            width=epoch.t_end - epoch.t_start,
            height=thickness_axes,
            transform=transform,
            facecolor=color,
            edgecolor="none",
            clip_on=False,
            zorder=20,
        )
        self._axes.add_patch(rect)
        self._artists.append(rect)

        # Add label
        self._render_label(epoch, y + thickness_axes / 2, transform)

    def _render_box(self, epoch: Epoch, y: float, height: float, transform: Any) -> None:
        """Render a box (for pressure setpoints)."""
        if self._axes is None:
            return

        # Get color
        color = epoch.color or self.theme.get_color(epoch.channel)

        # Box height
        box_height = self._px_to_axes_height(12.0)

        # Create fancy box with rounded corners
        box = FancyBboxPatch(
            xy=(epoch.t_start, y),
            width=epoch.t_end - epoch.t_start,
            height=box_height,
            boxstyle="round,pad=0.02",
            transform=transform,
            facecolor="white",
            edgecolor=color,
            linewidth=1.5,
            clip_on=False,
            zorder=20,
        )
        self._axes.add_patch(box)
        self._artists.append(box)

        # Add label
        self._render_label(epoch, y + box_height / 2, transform)

    def _render_shade(self, epoch: Epoch, y: float, height: float) -> None:
        """Render a shaded region (for perfusate changes)."""
        if self._axes is None:
            return

        # Get color
        color = epoch.color or self.theme.get_color(epoch.channel)

        # Shaded region spans the full height of the plot
        # Use data coordinates for both x and y
        ylim = self._axes.get_ylim()

        # Create shaded rectangle
        rect = Rectangle(
            xy=(epoch.t_start, ylim[0]),
            width=epoch.t_end - epoch.t_start,
            height=ylim[1] - ylim[0],
            facecolor=color,
            edgecolor="none",
            alpha=self.theme.shade_alpha,
            clip_on=True,
            zorder=5,  # Behind trace but above grid
        )
        self._axes.add_patch(rect)
        self._artists.append(rect)

        # Add label at top of shaded region
        transform = self._axes.get_xaxis_transform()
        self._render_label(epoch, y, transform)

    def _render_label(self, epoch: Epoch, y: float, transform: Any) -> None:
        """Render epoch label text."""
        if self._axes is None:
            return

        try:
            # Calculate label position (center of epoch)
            x_center = (epoch.t_start + epoch.t_end) / 2.0

            # Get color for text
            color = epoch.color or self.theme.get_color(epoch.channel)
            if epoch.style == "shade":
                # For shaded regions, use black text with white halo
                color = "#111111"

            # Create text with path effects for readability
            self._axes.text(
                x_center,
                y,
                epoch.label,
                transform=transform,
                fontsize=self.theme.font_size_pt,
                fontfamily=self.theme.font_family,
                color=color,
                ha="center",
                va="center",
                clip_on=False,
                zorder=30,
                path_effects=[mpatches.withStroke(linewidth=2.0, foreground="white", alpha=0.7)],
            )

        except Exception as e:
            log.warning("Could not render epoch label: %s", e, exc_info=True)

    def _px_to_axes_height(self, px: float) -> float:
        """Convert pixel height to axes coordinates (fraction of axes height)."""
        if self._axes is None or self._axes.figure is None:
            return 0.01  # Fallback

        # Get figure DPI and axes height in inches
        dpi = self._axes.figure.dpi
        bbox = self._axes.get_window_extent()
        axes_height_px = float(bbox.height)

        # Convert px to fraction of axes height
        if axes_height_px > 0:
            return px / axes_height_px
        return 0.01

    def _px_to_axes_width(self, px: float) -> float:
        """Convert pixel width to axes coordinates (fraction of axes width)."""
        if self._axes is None or self._axes.figure is None:
            return 0.01  # Fallback

        bbox = self._axes.get_window_extent()
        axes_width_px = float(bbox.width)

        if axes_width_px > 0:
            return px / axes_width_px
        return 0.01
