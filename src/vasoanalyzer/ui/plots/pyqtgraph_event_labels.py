"""PyQtGraph-based event label renderer with clustering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PyQtGraphEventLabeler"]


@dataclass
class PyQtGraphLabelItem:
    """Wrapper for PyQtGraph text item with positioning info."""

    text_item: pg.TextItem
    event_entry: EventEntryV3
    x_pos: float
    y_pos: float
    lane: int = 0
    pixel_length: float = 0.0


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
            self._render_cluster(cluster)

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
    ) -> None:
        """Render a single cluster of events."""
        if not cluster:
            return

        cluster_x = sum(e.t for e in cluster) / len(cluster)
        representative = self._select_representative(cluster)
        label_text = self._compose_cluster_label(cluster, representative)

        mode = (self.options.mode or "vertical").lower()

        text_item = pg.TextItem(
            text=label_text,
            color=self._get_label_color(representative),
        )

        font = self._create_label_font(representative)
        text_item.setFont(font)
        text_extent_px = self._text_pixel_length(font, label_text)

        # When showing numbers only, display horizontally regardless of mode
        if self.options.show_numbers_only:
            # Horizontal display for numbers
            text_item.setAnchor((0.5, 0.0))
            x_pos = cluster_x
            rotation = 0.0
            text_item.setRotation(rotation)
        elif mode == "vertical":
            rotation = self.options.rotation_deg or -90.0
            text_item.setRotation(rotation)
            text_item.setAnchor((0.5, 0.0))
            x_pos = cluster_x
        elif mode == "h_belt":
            text_item.setAnchor((0.5, 0.0))
            x_pos = cluster_x
            rotation = self.options.rotation_deg or 0.0
            if rotation:
                text_item.setRotation(rotation)
        else:
            text_item.setAnchor((0.5, 1.0))
            x_pos = cluster_x
            rotation = self.options.rotation_deg or 0.0
            if rotation:
                text_item.setRotation(rotation)

        y_pos = self._mode_y_position(mode, text_extent_px)
        text_item.setPos(x_pos, y_pos)
        text_item.setZValue(self.options.z_label)

        self.plot_item.addItem(text_item)

        label_item = PyQtGraphLabelItem(
            text_item=text_item,
            event_entry=representative,
            x_pos=cluster_x,
            y_pos=y_pos,
            pixel_length=text_extent_px,
        )
        self._label_items.append(label_item)
        text_item.setVisible(self._visible)

    def _select_representative(self, cluster: list[EventEntryV3]) -> EventEntryV3:
        policy = (self.options.style_policy or "first").lower()
        if policy == "priority":
            return max(cluster, key=lambda entry: entry.priority)
        if policy == "first":
            return cluster[0]
        return cluster[0]

    def _compose_cluster_label(
        self,
        cluster: list[EventEntryV3],
        representative: EventEntryV3,
    ) -> str:
        # If showing numbers only, use event index
        if self.options.show_numbers_only and representative.index is not None:
            if len(cluster) > 1:
                # Show index range or list for clusters
                indices = sorted([e.index for e in cluster if e.index is not None])
                if len(indices) > 1:
                    if indices[-1] - indices[0] == len(indices) - 1:
                        # Consecutive indices - show range
                        return f"{indices[0]}-{indices[-1]}"
                    else:
                        # Non-consecutive - show count
                        return f"{representative.index} (+{len(cluster) - 1})"
                else:
                    return str(representative.index)
            return str(representative.index)

        # Default text-based labels
        if len(cluster) > self.options.max_labels_per_cluster:
            if self.options.compact_counts:
                return str(len(cluster))
            return f"{representative.text} (+{len(cluster) - 1})"
        if len(cluster) > 1:
            return f"{representative.text} ({len(cluster)})"
        return str(representative.text)

    def _text_pixel_length(self, font: QFont, text: str) -> float:
        metrics = QFontMetricsF(font)
        try:
            advance = float(metrics.horizontalAdvance(text))
        except AttributeError:
            advance = float(metrics.width(text))
        return max(advance, 0.0)

    def _mode_y_position(self, mode: str, text_size_px: float) -> float:
        view_range = self.plot_item.viewRange()
        if not view_range or len(view_range) < 2:
            return 0.0
        y_min_raw, y_max_raw = view_range[1]
        y_min = float(y_min_raw)
        y_max = float(y_max_raw)
        span = max(y_max - y_min, 1e-9)
        if mode == "vertical":
            return self._vertical_label_position(text_size_px, y_min, y_max)
        if mode == "h_inside":
            return y_max - (span * 0.05)
        if mode == "h_belt":
            return y_max + (span * 0.05)
        return self._vertical_label_position(text_size_px, y_min, y_max)

    def _vertical_label_position(
        self,
        text_size_px: float,
        y_min: float,
        y_max: float,
    ) -> float:
        vb = getattr(self.plot_item, "vb", None)
        if vb is None:
            return y_max
        try:
            pixel_height = float(vb.height())
        except Exception:
            return y_max
        if pixel_height <= 0.0:
            return y_max
        span = max(y_max - y_min, 1e-9)
        pad_px = (text_size_px / 2.0) + 4.0
        pad_data = (pad_px / pixel_height) * span
        pad_data = min(pad_data, span)
        return y_max - pad_data

    def _get_label_color(self, event: EventEntryV3) -> tuple[int, int, int]:
        """Resolve RGB color for event label."""
        color = self._coerce_color(event.meta.get("color"))
        if color is None:
            color = self._coerce_color(self.options.font_color)
        if color is None:
            color = self._coerce_color(event.meta.get("event_color"))
        if color is None or (
            color == QColor("#000000") and CURRENT_THEME.get("text", "#000000").lower() != "#000000"
        ):
            color = QColor(CURRENT_THEME.get("text", "#000000"))
        return (color.red(), color.green(), color.blue())

    def _coerce_color(self, value: Any) -> QColor | None:
        if value is None:
            return None
        if isinstance(value, QColor):
            candidate = QColor(value)
            return candidate if candidate.isValid() else None
        if isinstance(value, str):
            candidate = QColor(value)
            return candidate if candidate.isValid() else None
        if isinstance(value, Sequence):
            comps = list(value)[:3]
            if len(comps) < 3:
                return None
            scaled = []
            use_unit = all(
                isinstance(comp, int | float) and 0.0 <= float(comp) <= 1.0 for comp in comps
            )
            for comp in comps:
                number = float(comp)
                if use_unit:
                    number = max(0.0, min(number, 1.0)) * 255.0
                scaled.append(int(max(0.0, min(number, 255.0))))
            try:
                candidate = QColor(*scaled)
            except Exception:
                return None
            return candidate if candidate.isValid() else None
        return None

    def _create_label_font(self, event: EventEntryV3) -> QFont:
        """Create QFont for event label from metadata."""
        family = (
            event.meta.get("font")
            or event.meta.get("fontfamily")
            or self.options.font_family
            or "Arial"
        )
        font = QFont(family)

        size_value = (
            event.meta.get("fontsize") or event.meta.get("font_size") or self.options.font_size
        )
        try:
            font.setPointSizeF(float(size_value))
        except (TypeError, ValueError):
            font.setPointSizeF(float(self.options.font_size or 10.0))

        bold_override = event.meta.get("fontweight")
        if isinstance(bold_override, str):
            bold_flag = bold_override.lower() in {"bold", "semibold", "demi", "black"}
        elif "font_bold" in event.meta:
            bold_flag = bool(event.meta.get("font_bold"))
        else:
            bold_flag = bool(self.options.font_bold)
        font.setBold(bold_flag)

        italic_override = event.meta.get("fontstyle")
        if isinstance(italic_override, str):
            italic_flag = italic_override.lower() == "italic"
        elif "font_italic" in event.meta:
            italic_flag = bool(event.meta.get("font_italic"))
        else:
            italic_flag = bool(self.options.font_italic)
        font.setItalic(italic_flag)

        return font

    def update_positions(self, xlim: tuple[float, float]) -> None:
        """Update label positions when view changes.

        Args:
            xlim: New visible X range
        """
        mode = (self.options.mode or "vertical").lower()
        for item in self._label_items:
            y_pos = self._mode_y_position(mode, item.pixel_length)
            item.text_item.setPos(item.x_pos, y_pos)
            item.y_pos = y_pos
