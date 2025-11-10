"""PyQtGraph-based event label renderer with clustering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3

__all__ = ["PyQtGraphEventLabeler"]


@dataclass
class PyQtGraphLabelItem:
    """Wrapper for PyQtGraph text item with positioning info."""

    text_item: pg.TextItem
    event_entry: EventEntryV3
    x_pos: float
    y_pos: float
    lane: int = 0


class PyQtGraphEventLabeler:
    """GPU-accelerated event label rendering using PyQtGraph TextItem.

    Provides similar functionality to EventLabelerV3 but optimized for
    PyQtGraph's rendering pipeline.
    """

    def __init__(
        self,
        plot_item: pg.PlotItem,
        options: LayoutOptionsV3 | None = None,
    ) -> None:
        """Initialize event labeler.

        Args:
            plot_item: PyQtGraph PlotItem to attach labels to
            options: Layout options (mode, clustering, etc.)
        """
        self.plot_item = plot_item
        self.options = options or LayoutOptionsV3()
        self._label_items: list[PyQtGraphLabelItem] = []
        self._visible: bool = True

    def clear(self) -> None:
        """Remove all label items from the plot."""
        for item in self._label_items:
            self.plot_item.removeItem(item.text_item)
        self._label_items.clear()

    def set_visible(self, visible: bool) -> None:
        """Show/hide all labels."""
        self._visible = visible
        for item in self._label_items:
            item.text_item.setVisible(visible)

    def render(
        self,
        events: Sequence[EventEntryV3],
        xlim: tuple[float, float],
        pixel_width: int,
    ) -> None:
        """Render event labels with clustering and layout.

        Args:
            events: Event entries to render
            xlim: Visible X-axis range (x0, x1)
            pixel_width: Viewport width in pixels for clustering
        """
        # Clear existing labels
        self.clear()

        if not events or pixel_width <= 0:
            return

        # Filter events in visible range
        x0, x1 = xlim
        visible_events = [e for e in events if x0 <= e.t <= x1]

        if not visible_events:
            return

        # Cluster events based on pixel spacing
        clusters = self._cluster_events(visible_events, xlim, pixel_width)

        # Render labels for each cluster
        for cluster in clusters:
            self._render_cluster(cluster, xlim)

    def _cluster_events(
        self,
        events: Sequence[EventEntryV3],
        xlim: tuple[float, float],
        pixel_width: int,
    ) -> list[list[EventEntryV3]]:
        """Cluster events that are too close in pixel space.

        Args:
            events: Events to cluster
            xlim: Visible X range
            pixel_width: Viewport width in pixels

        Returns:
            List of event clusters
        """
        if not events:
            return []

        x0, x1 = xlim
        data_width = x1 - x0
        if data_width <= 0:
            return [[e] for e in events]

        # Calculate pixels per data unit
        px_per_unit = pixel_width / data_width

        # Minimum pixel spacing from options
        min_px = self.options.min_px

        # Sort events by time
        sorted_events = sorted(events, key=lambda e: e.t)

        # Cluster events within min_px distance
        clusters: list[list[EventEntryV3]] = []
        current_cluster: list[EventEntryV3] = [sorted_events[0]]

        for event in sorted_events[1:]:
            # Calculate pixel distance from last event in current cluster
            last_event = current_cluster[-1]
            px_distance = abs(event.t - last_event.t) * px_per_unit

            if px_distance < min_px:
                # Add to current cluster
                current_cluster.append(event)
            else:
                # Start new cluster
                clusters.append(current_cluster)
                current_cluster = [event]

        # Don't forget the last cluster
        if current_cluster:
            clusters.append(current_cluster)

        return clusters

    def _render_cluster(
        self,
        cluster: list[EventEntryV3],
        xlim: tuple[float, float],
    ) -> None:
        """Render a single cluster of events.

        Args:
            cluster: Events in this cluster
            xlim: Visible X range for positioning
        """
        if not cluster:
            return

        # Determine cluster position (average of all events in cluster)
        cluster_x = sum(e.t for e in cluster) / len(cluster)

        # Select representative event(s) based on style policy
        if self.options.style_policy == "priority":
            # Show highest priority event
            representative = max(cluster, key=lambda e: e.priority)
        elif self.options.style_policy == "first":
            # Show first event
            representative = cluster[0]
        else:
            # Default to first
            representative = cluster[0]

        # Determine label text
        if len(cluster) > self.options.max_labels_per_cluster:
            # Show count if cluster is large
            if self.options.compact_counts:
                label_text = f"{len(cluster)}"
            else:
                label_text = f"{representative.text} (+{len(cluster)-1})"
        elif len(cluster) > 1:
            # Show representative with count
            label_text = f"{representative.text} ({len(cluster)})"
        else:
            # Single event
            label_text = representative.text

        # Create text item
        text_item = pg.TextItem(
            text=label_text,
            anchor=(0.5, 1.0),  # Center bottom anchor for vertical mode
            color=self._get_label_color(representative),
        )

        # Set font
        font = self._create_label_font(representative)
        text_item.setFont(font)

        # Position based on layout mode
        if self.options.mode == "vertical":
            # Vertical labels above the plot
            view_range = self.plot_item.viewRange()
            y_max = view_range[1][1]
            y_pos = y_max  # Top of visible area

            # Rotate text 90 degrees for vertical mode
            text_item.setRotation(self.options.rotation_deg)
            text_item.setAnchor((0.5, 0.0))  # Center top anchor when rotated

        elif self.options.mode == "h_inside":
            # Horizontal labels inside the plot
            view_range = self.plot_item.viewRange()
            y_max = view_range[1][1]
            y_pos = y_max * 0.95  # 95% of the way up

        elif self.options.mode == "h_belt":
            # Horizontal labels in belt above plot
            view_range = self.plot_item.viewRange()
            y_max = view_range[1][1]
            y_pos = y_max * 1.05  # 5% above plot

        else:
            # Default vertical
            view_range = self.plot_item.viewRange()
            y_max = view_range[1][1]
            y_pos = y_max

        # Set position
        text_item.setPos(cluster_x, y_pos)

        # Set Z value for layering
        text_item.setZValue(self.options.z_label)

        # Add to plot
        self.plot_item.addItem(text_item)

        # Store reference
        label_item = PyQtGraphLabelItem(
            text_item=text_item,
            event_entry=representative,
            x_pos=cluster_x,
            y_pos=y_pos,
        )
        self._label_items.append(label_item)

        # Set visibility
        text_item.setVisible(self._visible)

    def _get_label_color(self, event: EventEntryV3) -> tuple[int, int, int]:
        """Get RGB color for event label from metadata.

        Args:
            event: Event entry

        Returns:
            RGB tuple (0-255)
        """
        # Check metadata for color
        if "color" in event.meta:
            color_str = event.meta["color"]
            qcolor = QColor(color_str)
            return (qcolor.red(), qcolor.green(), qcolor.blue())

        # Default black
        return (0, 0, 0)

    def _create_label_font(self, event: EventEntryV3) -> QFont:
        """Create QFont for event label from metadata.

        Args:
            event: Event entry

        Returns:
            QFont instance
        """
        font = QFont()

        # Check metadata for font settings
        if "font_family" in event.meta:
            font.setFamily(event.meta["font_family"])
        else:
            font.setFamily("Arial")

        if "font_size" in event.meta:
            font.setPointSize(int(event.meta["font_size"]))
        else:
            font.setPointSize(10)

        if "font_bold" in event.meta:
            font.setBold(bool(event.meta["font_bold"]))

        if "font_italic" in event.meta:
            font.setItalic(bool(event.meta["font_italic"]))

        return font

    def update_positions(self, xlim: tuple[float, float]) -> None:
        """Update label positions when view changes.

        Args:
            xlim: New visible X range
        """
        # Update Y positions based on new view range
        view_range = self.plot_item.viewRange()
        y_max = view_range[1][1]

        for item in self._label_items:
            if self.options.mode == "vertical":
                y_pos = y_max
            elif self.options.mode == "h_inside":
                y_pos = y_max * 0.95
            elif self.options.mode == "h_belt":
                y_pos = y_max * 1.05
            else:
                y_pos = y_max

            item.text_item.setPos(item.x_pos, y_pos)
            item.y_pos = y_pos
