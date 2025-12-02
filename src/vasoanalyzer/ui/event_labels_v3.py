"""Next-generation event label helper with deterministic clustering and cached extents.

The v3 helper is designed to render dense event timelines without layout jank by:

- performing clustering in pixel space with a stable left-to-right sweep,
- caching text measurements to avoid synchronous `canvas.draw()` calls,
- supporting multiple layout modes (vertical, horizontal inside, horizontal belt),
- exposing cluster style policies and per-cluster summarisation controls, and
- keeping label guides above dashed event lines via explicit z-ordering.

IMPROVEMENTS IN THIS VERSION:
- Enhanced lane selection using best-fit algorithm for better label distribution
- Increased horizontal spacing (12px vs 6px) for clearer separation from dashed lines
- Labels now spread more evenly across lanes instead of clustering in the first available lane
"""

from __future__ import annotations

import contextlib
import hashlib
import math
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from matplotlib import patheffects as patheffects
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.text import Text

__all__ = [
    "EventEntryV3",
    "ClusteredLabelV3",
    "LayoutOptionsV3",
    "EventLabelerV3",
]


# --------------------------------------------------------------------------- data models
@dataclass(frozen=True)
class EventEntryV3:
    """Raw event payload consumed by the v3 labeler."""

    t: float
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    category: str | None = None
    pinned: bool = False
    index: int | None = None  # Optional event index for numbered display


@dataclass
class ClusteredLabelV3:
    """Collapsed label representing one or more events within a pixel cluster."""

    x: float
    px: float
    items: list[EventEntryV3]
    text: str
    style: dict[str, Any]
    width_px: float = 0.0
    pinned: bool = False
    max_priority: int = 0
    category: str | None = None


@dataclass
class LayoutOptionsV3:
    """Layout tuning options for the EventLabelerV3 helper."""

    mode: str = "vertical"  # {"vertical", "h_inside", "h_belt"}
    min_px: int = 24
    max_labels_per_cluster: int = 1
    style_policy: str = "first"  # {"first", "most_common", "priority", "blend_color"}
    span_siblings: bool = True
    lanes: int = 3
    belt_baseline: bool = True
    rotation_deg: float = 90.0
    z_label: float = 30.0
    z_guides: float = 20.0
    z_markers: float = 10.0
    outline_enabled: bool = False
    outline_width: float = 0.0
    outline_color: tuple[float, float, float, float] | None = None
    compact_counts: bool = False
    show_numbers_only: bool = True  # Show event index numbers instead of text labels
    font_family: str = "Arial"
    font_size: float = 10.0
    font_bold: bool = False
    font_italic: bool = False
    font_color: str | None = None


# --------------------------------------------------------------------------- cache helpers
class TextExtentsCache:
    """Lightweight cache keyed by text + font descriptor + DPI."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, float], tuple[float, float]] = {}

    @staticmethod
    def _key(text: str, fontdict: dict[str, Any], dpi: float) -> tuple[str, str, float]:
        font_key = "-".join(str(fontdict.get(key)) for key in ("family", "style", "weight", "size"))
        signature = hashlib.md5(text.encode("utf8")).hexdigest()
        return (signature, font_key, float(dpi))

    def get(
        self,
        text: str,
        fontdict: dict[str, Any],
        dpi: float,
        renderer,
    ) -> tuple[float, float]:
        if renderer is None:
            return 0.0, 0.0
        cache_key = self._key(text, fontdict, dpi)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        # Matplotlib keeps kwargs on Text.__init__ in sync with fontdict keys.
        kwargs = {k: v for k, v in fontdict.items() if v is not None}
        probe = Text(0, 0, text, **kwargs)
        try:
            bbox = probe.get_window_extent(renderer=renderer)
        except Exception:
            return 0.0, 0.0
        width = float(getattr(bbox, "width", 0.0))
        height = float(getattr(bbox, "height", 0.0))
        self._cache[cache_key] = (width, height)
        return width, height

    def clear(self) -> None:
        self._cache.clear()


# --------------------------------------------------------------------------- core helper
class EventLabelerV3:
    """Render clustered event labels with deterministic layout and cached extents."""

    def __init__(self, ax_host: Axes, sibling_axes: Iterable[Axes], options: LayoutOptionsV3):
        self.ax_host = ax_host
        self.sibling_axes = list(sibling_axes) if options.span_siblings else [ax_host]
        self.options = options
        self._cache = TextExtentsCache()
        self._artists: list[Any] = []
        self._belt_ax: Axes | None = None
        self._last_dpi: float | None = None
        self._artist_to_cluster: dict[Text, ClusteredLabelV3] = {}
        self._legend_artists: list[Any] = []

    # ------------------------------------------------------------------ lifecycle
    def clear(self) -> None:
        """Remove all artists associated with the current draw."""

        for artist in list(self._artists):
            with contextlib.suppress(Exception):
                artist.remove()
        self._artists.clear()
        self._artist_to_cluster.clear()
        if self._belt_ax is not None:
            with contextlib.suppress(Exception):
                self._belt_ax.remove()
            self._belt_ax = None
        for artist in list(self._legend_artists):
            with contextlib.suppress(Exception):
                artist.remove()
        self._legend_artists.clear()

    def draw(self, events: Sequence[EventEntryV3]) -> None:
        """Cluster and render the provided events."""

        self.clear()
        if not events:
            return
        host = self._resolve_host_axes()
        if host is None:
            return

        canvas = getattr(host.figure, "canvas", None)
        renderer = None
        if canvas is not None:
            renderer = getattr(canvas, "get_renderer", lambda: None)()
            if renderer is None:
                renderer = getattr(canvas, "_renderer", None)
        dpi = float(getattr(host.figure, "dpi", 96.0))
        if self._last_dpi is None or not math.isclose(self._last_dpi, dpi, rel_tol=1e-6):
            self._cache.clear()
            self._last_dpi = dpi

        clusters = self._cluster(events, host, dpi, renderer)
        if not clusters:
            return
        mode = (self.options.mode or "vertical").lower()
        if mode == "vertical":
            self._draw_vertical(host, clusters)
        elif mode == "h_inside":
            self._draw_horizontal_inside(host, clusters, dpi, renderer)
        else:
            self._draw_horizontal_belt(host, clusters, dpi, renderer)

    # ------------------------------------------------------------------ internals
    def _resolve_host_axes(self) -> Axes | None:
        ax = self.ax_host
        if getattr(ax, "figure", None) is None:
            return None
        return ax

    def _cluster(
        self,
        events: Sequence[EventEntryV3],
        ax: Axes,
        dpi: float,
        renderer,
    ) -> list[ClusteredLabelV3]:
        if not events:
            return []
        xs = np.array([event.t for event in events], dtype=float)
        transform = ax.transData
        # Transform in one vectorised call for stability/perf.
        zeros = np.zeros_like(xs)
        px_coords = transform.transform(np.column_stack([xs, zeros]))[:, 0]

        order = np.argsort(px_coords, kind="mergesort")
        min_gap = max(int(self.options.min_px), 1)
        clusters: list[list[int]] = []
        current: list[int] = []

        for idx in order:
            if not current:
                current.append(idx)
                continue
            last_px = px_coords[current[-1]]
            if abs(px_coords[idx] - last_px) <= min_gap:
                current.append(idx)
            else:
                clusters.append(current)
                current = [idx]
        if current:
            clusters.append(current)

        result: list[ClusteredLabelV3] = []
        for group in clusters:
            members = [events[i] for i in group]
            if not members:
                continue
            mean_x = float(np.mean([item.t for item in members]))
            mean_px = float(np.mean([px_coords[i] for i in group]))
            pinned = any(entry.pinned or bool(entry.meta.get("pinned")) for entry in members)
            max_priority = max((entry.priority for entry in members), default=0)

            # Determine category: use category from highest priority event
            category = None
            if members:
                sorted_by_priority = sorted(members, key=lambda e: e.priority, reverse=True)
                category = sorted_by_priority[0].category

            label_text, style = self._compose_cluster_label(members, dpi, renderer)
            if not label_text:
                continue
            result.append(
                ClusteredLabelV3(
                    x=mean_x,
                    px=mean_px,
                    items=members,
                    text=label_text,
                    style=style,
                    pinned=pinned,
                    max_priority=max_priority,
                    category=category,
                )
            )
        return result

    def _compose_cluster_label(
        self,
        members: list[EventEntryV3],
        dpi: float,
        renderer,
    ) -> tuple[str, dict[str, Any]]:
        style = self._select_style(members)
        ordered_labels: list[tuple[int, bool, str]] = []
        for order, entry in enumerate(members):
            if not bool(entry.meta.get("visible", True)):
                continue
            text_value = entry.meta.get("text_override") or entry.meta.get("text") or entry.text
            if not text_value:
                continue
            pinned = entry.pinned or bool(entry.meta.get("pinned"))
            ordered_labels.append((order, pinned, text_value))

        if not ordered_labels:
            return "", style

        # Sort: pinned first, higher priority next, preserve input order
        ordered_labels.sort(key=lambda item: (-int(item[1]), -members[item[0]].priority, item[0]))

        max_labels = max(0, int(self.options.max_labels_per_cluster))
        if self.options.compact_counts or max_labels == 0:
            pinned_labels = [text for _, pinned, text in ordered_labels if pinned]
            non_pinned_count = len(ordered_labels) - len(pinned_labels)
            if pinned_labels and non_pinned_count > 0:
                body = ", ".join(pinned_labels) + f" (+{non_pinned_count})"
            elif pinned_labels:
                body = ", ".join(pinned_labels)
            else:
                body = str(len(ordered_labels))
            return body, style

        shown_texts = [text for _, _, text in ordered_labels[:max_labels]]
        remainder = max(0, len(ordered_labels) - len(shown_texts))
        body = ", ".join(shown_texts)
        if remainder > 0:
            body = f"{body} (+{remainder})" if body else f"(+{remainder})"
        return body, style

    def _select_style(self, members: list[EventEntryV3]) -> dict[str, Any]:
        policy = (self.options.style_policy or "first").lower()
        if policy == "most_common":
            return self._style_most_common(members)
        if policy == "priority":
            sorted_members = sorted(members, key=lambda item: item.priority, reverse=True)
            return dict(sorted_members[0].meta or {})
        if policy == "blend_color":
            return self._style_blend_color(members)
        return dict(members[0].meta or {})

    def _style_most_common(self, members: list[EventEntryV3]) -> dict[str, Any]:
        from collections import Counter

        keys = [
            "fontfamily",
            "fontstyle",
            "fontweight",
            "fontsize",
            "color",
            "alpha",
            "rotation",
            "align",
            "valign",
            "clip_on",
            "bbox",
        ]
        output: dict[str, Any] = {}
        for key in keys:
            values = [entry.meta.get(key) for entry in members if entry.meta.get(key) is not None]
            if not values:
                continue
            try:
                output[key] = Counter(values).most_common(1)[0][0]
            except TypeError:
                output[key] = values[0]
        return output

    def _style_blend_color(self, members: list[EventEntryV3]) -> dict[str, Any]:
        base = dict(members[0].meta or {})
        colors = [
            value
            for value in (entry.meta.get("color") for entry in members)
            if isinstance(value, Sequence)
        ]
        if not colors:
            return base
        rgba = []
        for color in colors:
            try:
                rgba.append(tuple(float(component) for component in color))
            except (TypeError, ValueError):
                continue
        if not rgba:
            return base
        length = len(rgba[0])
        accum = [0.0] * length
        for color in rgba:
            for idx, component in enumerate(color):
                accum[idx] += component
        averaged = tuple(component / len(rgba) for component in accum)
        base["color"] = averaged
        return base

    # ------------------------------------------------------------------ drawing modes
    def _draw_vertical(self, ax: Axes, clusters: list[ClusteredLabelV3]) -> None:
        # Guides across sibling axes first.
        for peer in self.sibling_axes:
            transform = peer.get_xaxis_transform()
            for cluster in clusters:
                # Use enhanced style color (includes category color)
                enhanced_style = self._enhance_style_by_priority(
                    cluster.style, cluster.max_priority, cluster.category
                )
                style_color = enhanced_style.get("color")

                # Default to darker gray with higher opacity for better visibility
                if style_color is not None:
                    # If we have a color, use it with 50% opacity
                    if isinstance(style_color, list | tuple) and len(style_color) >= 3:
                        color = (*style_color[:3], 0.5)
                    else:
                        color = style_color
                else:
                    color = (0, 0, 0, 0.5)

                guide = Line2D(
                    [cluster.x, cluster.x],
                    [0, 1],
                    linestyle=(0, (4, 4)),
                    color=color,
                    linewidth=1.5,
                    transform=transform,
                    zorder=self.options.z_guides,
                    clip_on=False,
                )
                peer.add_line(guide)
                self._artists.append(guide)

        # Position labels INSIDE plot area, offset from dashed line
        y_axes = 0.98  # Inside plot, near top (was 1.0 = at top edge)
        for cluster in clusters:
            enhanced_style = self._enhance_style_by_priority(
                cluster.style, cluster.max_priority, cluster.category
            )
            text_kwargs = self._text_kwargs(enhanced_style)
            # Remove ha/va from kwargs since we're setting them explicitly
            text_kwargs.pop("ha", None)
            text_kwargs.pop("va", None)
            text = ax.text(
                cluster.x,
                y_axes,
                cluster.text,
                rotation=self.options.rotation_deg,
                rotation_mode="anchor",
                transform=ax.get_xaxis_transform(),
                ha="right",  # Right-align: label ENDS at this position, extends left
                va="bottom",  # Bottom-align at y position
                zorder=self.options.z_label,
                clip_on=True,  # Enable clipping to keep labels inside plot
                **text_kwargs,
            )
            self._apply_outline(text)
            self._artists.append(text)
            self._artist_to_cluster[text] = cluster

    def _draw_horizontal_inside(
        self,
        ax: Axes,
        clusters: list[ClusteredLabelV3],
        dpi: float,
        renderer,
    ) -> None:
        lanes = max(1, min(int(self.options.lanes), 12))
        selected_clusters = self._select_clusters_for_horizontal(clusters, dpi, renderer)
        if not selected_clusters:
            return

        lane_end_px = [float("-inf")] * lanes
        lane_step = 0.8 / max(1, lanes - 1) if lanes > 1 else 0.0

        if renderer is None:
            return

        bbox = ax.get_window_extent(renderer=renderer)
        x_min_px = float(bbox.x0)
        x_max_px = float(bbox.x1)
        margin_px = 4.0
        preferred_gap_px = 12.0  # Increased from 6.0 for better separation from dashed line
        min_gap_px = 2.0
        buffer_px = 12.0

        for cluster in selected_clusters:
            fontdict = self._font_dict(cluster.style)
            if cluster.width_px <= 0.0:
                width, _ = self._cache.get(cluster.text, fontdict, dpi, renderer)
                cluster.width_px = max(width, 0.0)
            width = max(cluster.width_px, 0.0)

            offset_px = preferred_gap_px
            left_px = cluster.px + offset_px
            right_px = left_px + width

            max_right = x_max_px - margin_px
            if right_px > max_right:
                offset_px -= right_px - max_right
                left_px = cluster.px + offset_px
                right_px = left_px + width

            if offset_px < min_gap_px:
                offset_px = min_gap_px
                left_px = cluster.px + offset_px
                right_px = left_px + width
                if right_px > max_right:
                    shift = right_px - max_right
                    left_px -= shift
                    offset_px = left_px - cluster.px
                    right_px = left_px + width

            min_left = x_min_px + margin_px
            if left_px < min_left:
                shift = min_left - left_px
                left_px = min_left
                offset_px = left_px - cluster.px
                right_px = left_px + width

            lane_index = self._select_lane(left_px, width, lane_end_px)
            lane_y = 0.94 - (lane_index * lane_step)
            lane_end_px[lane_index] = left_px + width + buffer_px

            y_display = ax.transAxes.transform((0.0, lane_y))[1]
            x_label = ax.transData.inverted().transform((left_px, y_display))[0]

            enhanced_style = self._enhance_style_by_priority(
                cluster.style, cluster.max_priority, cluster.category
            )
            text_kwargs = self._text_kwargs(enhanced_style)

            current_ha = text_kwargs.pop("ha", None)
            ha = current_ha if current_ha in {"left", "right"} else "left"
            artist = ax.text(
                x_label,
                lane_y,
                cluster.text,
                transform=ax.get_xaxis_transform(),
                ha=ha,
                va=text_kwargs.pop("va", "top"),
                clip_on=True,
                zorder=self.options.z_label,
                **text_kwargs,
            )
            self._apply_outline(artist)
            self._artists.append(artist)
            self._artist_to_cluster[artist] = cluster

    def _draw_horizontal_belt(
        self,
        ax: Axes,
        clusters: list[ClusteredLabelV3],
        dpi: float,
        renderer,
    ) -> None:
        belt_ax = self._ensure_belt_axes(ax)
        if belt_ax is None:
            return

        lanes = max(1, min(int(self.options.lanes), 12))
        selected_clusters = self._select_clusters_for_horizontal(clusters, dpi, renderer)
        if not selected_clusters:
            return

        lane_end_px = [float("-inf")] * lanes

        if renderer is None:
            return

        bbox = ax.get_window_extent(renderer=renderer)
        x_min_px = float(bbox.x0)
        x_max_px = float(bbox.x1)
        margin_px = 4.0
        preferred_gap_px = 12.0  # Increased from 6.0 for better separation from dashed line
        min_gap_px = 2.0
        buffer_px = 12.0

        for cluster in selected_clusters:
            fontdict = self._font_dict(cluster.style)
            if cluster.width_px <= 0.0:
                width, _ = self._cache.get(cluster.text, fontdict, dpi, renderer)
                cluster.width_px = max(width, 0.0)
            width = max(cluster.width_px, 0.0)

            offset_px = preferred_gap_px
            left_px = cluster.px + offset_px
            right_px = left_px + width

            max_right = x_max_px - margin_px
            if right_px > max_right:
                offset_px -= right_px - max_right
                left_px = cluster.px + offset_px
                right_px = left_px + width

            if offset_px < min_gap_px:
                offset_px = min_gap_px
                left_px = cluster.px + offset_px
                right_px = left_px + width
                if right_px > max_right:
                    shift = right_px - max_right
                    left_px -= shift
                    offset_px = left_px - cluster.px
                    right_px = left_px + width

            min_left = x_min_px + margin_px
            if left_px < min_left:
                shift = min_left - left_px
                left_px = min_left
                offset_px = left_px - cluster.px
                right_px = left_px + width

            lane_index = self._select_lane(left_px, width, lane_end_px)
            lane_end_px[lane_index] = left_px + width + buffer_px

            y_axes = 0.5 if lanes == 1 else 0.15 + lane_index * 0.75 / max(1, lanes - 1)

            enhanced_style = self._enhance_style_by_priority(
                cluster.style, cluster.max_priority, cluster.category
            )
            text_kwargs = self._text_kwargs(enhanced_style)
            bbox = text_kwargs.pop("bbox", None)
            y_display = belt_ax.transAxes.transform((0.0, y_axes))[1]
            x_label = belt_ax.transData.inverted().transform((left_px, y_display))[0]

            current_ha = text_kwargs.pop("ha", None)
            ha = current_ha if current_ha in {"left", "right"} else "left"
            artist = belt_ax.text(
                x_label,
                y_axes,
                cluster.text,
                transform=belt_ax.get_xaxis_transform(),
                ha=ha,
                va=text_kwargs.pop("va", "center"),
                clip_on=True,
                zorder=self.options.z_label,
                bbox=bbox,
                **text_kwargs,
            )
            self._apply_outline(artist)
            self._artists.append(artist)
            self._artist_to_cluster[artist] = cluster

    # ------------------------------------------------------------------ shared helpers
    def _ensure_belt_axes(self, ax: Axes) -> Axes | None:
        if self._belt_ax is not None and getattr(self._belt_ax, "figure", None) is not None:
            return self._belt_ax
        figure = ax.figure
        if figure is None:
            return None
        belt_ax: Axes | None = None
        try:
            from mpl_toolkits.axes_grid1 import make_axes_locatable

            divider = make_axes_locatable(ax)
            try:
                belt_ax = divider.append_axes("top", size="8mm", pad=0.15, sharex=ax)
            except Exception:
                # Fallback for backends that cannot parse "8mm" shorthand.
                size_inch = 8.0 / 25.4  # 8 mm expressed in inches
                belt_ax = divider.append_axes("top", size=size_inch, pad=0.15, sharex=ax)
        except Exception:
            belt_ax = None
        if belt_ax is None:
            try:
                from mpl_toolkits.axes.inset_locator import inset_axes

                bbox = ax.get_position()
                belt_ax = inset_axes(
                    ax,
                    width="100%",
                    height="8mm",
                    bbox_to_anchor=(bbox.x0, bbox.y1, bbox.width, 0.03),
                    bbox_transform=figure.transFigure,
                    loc="upper left",
                    borderpad=0,
                )
                belt_ax.get_xaxis().set_visible(False)
            except Exception:
                return None

        belt_ax.set_yticks([])
        belt_ax.set_ylim(0.0, 1.0)
        belt_ax.set_frame_on(False)
        if self.options.belt_baseline:
            baseline = Line2D(
                [0, 1],
                [0.1, 0.1],
                transform=belt_ax.transAxes,
                color=(0, 0, 0, 0.25),
                zorder=self.options.z_guides,
            )
            belt_ax.add_line(baseline)
            self._artists.append(baseline)
        self._belt_ax = belt_ax
        return belt_ax

    def annotation_text_objects(
        self,
    ) -> tuple[list[Text], dict[Text, ClusteredLabelV3]]:
        texts = [artist for artist in self._artists if isinstance(artist, Text)]
        return texts, dict(self._artist_to_cluster)

    def draw_compact_legend(
        self,
        ax: Axes,
        categories_counts: dict[str, tuple[int, tuple[float, float, float, float]]],
        *,
        title: str = "Events",
        loc: str = "upper right",
    ) -> None:
        for artist in list(self._legend_artists):
            with contextlib.suppress(Exception):
                artist.remove()
        self._legend_artists.clear()

        if not categories_counts:
            return

        try:
            from matplotlib.offsetbox import DrawingArea, HPacker, TextArea, VPacker
            from matplotlib.patches import Rectangle
            from mpl_toolkits.axes_grid1.anchored_artists import AnchoredOffsetbox
        except Exception:
            return

        rows: list[Any] = []
        header = TextArea(f"{title}", textprops={"weight": "bold"})
        rows.append(header)
        for category, (count, color) in categories_counts.items():
            drawing = DrawingArea(12, 12, 0, 0)
            rgba = tuple(max(0.0, min(1.0, float(component))) for component in color)
            patch = Rectangle((0, 0), 12, 12, facecolor=rgba, edgecolor="none")
            drawing.add_artist(patch)
            label = TextArea(f" {category}: {count}")
            row = HPacker(children=[drawing, label], align="center", pad=0, sep=4)
            rows.append(row)

        box = VPacker(children=rows, align="left", pad=4, sep=2)
        anchored = AnchoredOffsetbox(loc=loc, child=box, pad=0.3, frameon=True, borderpad=0.4)
        ax.add_artist(anchored)
        self._legend_artists.append(anchored)

    def _select_clusters_for_horizontal(
        self,
        clusters: list[ClusteredLabelV3],
        dpi: float,
        renderer,
    ) -> list[ClusteredLabelV3]:
        if not clusters:
            return []
        gap = 8.0
        pinned_intervals: list[tuple[float, float, int]] = []
        optional_intervals: list[tuple[float, float, float, int]] = []

        for idx, cluster in enumerate(clusters):
            fontdict = self._font_dict(cluster.style)
            if cluster.width_px <= 0.0:
                width, _ = self._cache.get(cluster.text, fontdict, dpi, renderer)
                cluster.width_px = max(width, 0.0)
            width = max(cluster.width_px, 0.0)
            half = (width / 2.0) + gap
            start = cluster.px - half
            end = cluster.px + half
            if cluster.pinned:
                pinned_intervals.append((start, end, idx))
                continue
            weight = float(max(cluster.max_priority, 0) + max(len(cluster.items), 1))
            optional_intervals.append((start, end, weight, idx))

        selected_indices: set[int] = {idx for _, _, idx in pinned_intervals}

        def overlaps_pinned(start: float, end: float) -> bool:
            for p_start, p_end, _ in pinned_intervals:
                if self._intervals_overlap(start, end, p_start, p_end):
                    return True
            return False

        filtered_optionals = [
            (s, e, w, idx) for (s, e, w, idx) in optional_intervals if not overlaps_pinned(s, e)
        ]

        selected_indices.update(self._weighted_interval_subset(filtered_optionals))

        return [cluster for idx, cluster in enumerate(clusters) if idx in selected_indices]

    @staticmethod
    def _intervals_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
        return not (a_end <= b_start or b_end <= a_start)

    def _weighted_interval_subset(
        self,
        intervals: list[tuple[float, float, float, int]],
    ) -> set[int]:
        if not intervals:
            return set()
        sorted_intervals = sorted(intervals, key=lambda item: item[1])
        n = len(sorted_intervals)
        ends = [item[1] for item in sorted_intervals]
        compat: list[int] = []
        for i in range(n):
            start = sorted_intervals[i][0]
            j = bisect_right(ends, start) - 1
            compat.append(j)

        dp = [0.0] * (n + 1)
        choose = [False] * n
        for i in range(1, n + 1):
            start, end, weight, _ = sorted_intervals[i - 1]
            include = weight + dp[compat[i - 1] + 1]
            exclude = dp[i - 1]
            if include > exclude:
                dp[i] = include
                choose[i - 1] = True
            else:
                dp[i] = exclude

        selected: set[int] = set()
        i = n
        while i > 0:
            if choose[i - 1]:
                _, _, _, idx = sorted_intervals[i - 1]
                selected.add(idx)
                i = compat[i - 1] + 1
            else:
                i -= 1
        return selected

    def _select_lane(
        self,
        px: float,
        width: float,
        lane_end_px: list[float],
    ) -> int:
        """Select the best lane for a label given its leftmost pixel coordinate.

        Uses a best-fit algorithm that prefers lanes with the earliest end position
        among those that can fit the label. This spreads labels more evenly across
        lanes rather than clustering in the first available lane.

        Returns the best lane index.
        """
        width = max(width, 0.0)

        # Find all lanes where this label can fit without overlap
        candidates = []
        for lane_index, lane_tail in enumerate(lane_end_px):
            if px >= lane_tail:  # Label fits without overlap
                candidates.append((lane_index, lane_tail))

        if candidates:
            # Choose the lane with the earliest end position (most room remaining)
            # This keeps labels as low as possible and spreads them across lanes
            best_lane = min(candidates, key=lambda x: x[1])[0]
            return best_lane

        # If no lane fits perfectly, use the one that ends earliest
        # This minimizes overlap
        return min(range(len(lane_end_px)), key=lambda i: lane_end_px[i])

    def _get_category_color(self, category: str | None) -> tuple[float, float, float, float] | None:
        """Get a consistent color for an event category."""
        if not category:
            return None

        # Professional color palette for event categories
        category_colors = {
            "stimulus": (0.12, 0.47, 0.71, 1.0),  # Blue
            "response": (0.84, 0.15, 0.16, 1.0),  # Red
            "drug": (0.17, 0.63, 0.17, 1.0),  # Green
            "baseline": (0.50, 0.50, 0.50, 1.0),  # Gray
            "intervention": (1.00, 0.50, 0.00, 1.0),  # Orange
            "measurement": (0.58, 0.40, 0.74, 1.0),  # Purple
            "event": (0.09, 0.75, 0.81, 1.0),  # Cyan
            "marker": (0.89, 0.47, 0.76, 1.0),  # Pink
            "warning": (0.74, 0.50, 0.00, 1.0),  # Dark orange
            "error": (0.65, 0.00, 0.00, 1.0),  # Dark red
        }

        # Case-insensitive lookup
        key = str(category).lower().strip()
        return category_colors.get(key)

    def _enhance_style_by_priority(
        self,
        style: dict[str, Any],
        priority: int,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Enhance text style based on event priority and category."""
        enhanced = dict(style)

        # Apply category color if available and no custom color is set
        if category and "color" not in enhanced:
            cat_color = self._get_category_color(category)
            if cat_color is not None:
                enhanced["color"] = cat_color

        # Priority 0 = normal, 1-2 = medium priority, 3+ = high priority
        if priority >= 3:
            # High priority: bold and larger
            enhanced["fontweight"] = "bold"
            base_size = float(enhanced.get("fontsize", 9.0))
            enhanced["fontsize"] = base_size * 1.3
        elif priority >= 1:
            # Medium priority: semi-bold and slightly larger
            enhanced["fontweight"] = "semibold"
            base_size = float(enhanced.get("fontsize", 9.0))
            enhanced["fontsize"] = base_size * 1.15

        return enhanced

    def _font_dict(self, style: dict[str, Any]) -> dict[str, Any]:
        return {
            "family": style.get("fontfamily"),
            "style": style.get("fontstyle"),
            "weight": style.get("fontweight"),
            "size": style.get("fontsize", 9.0),
            "color": style.get("color"),
        }

    def _text_kwargs(self, style: dict[str, Any]) -> dict[str, Any]:
        """Extract only matplotlib-compatible text properties from style dict."""
        # Only include matplotlib text properties, exclude layout/positioning metadata
        valid_keys = {
            "fontfamily",
            "fontstyle",
            "fontweight",
            "fontsize",
            "color",
            "alpha",
            "rotation",
            "align",
            "valign",
            "clip_on",
            "bbox",
        }
        kwargs = {key: value for key, value in style.items() if key in valid_keys}
        kwargs.setdefault("ha", kwargs.pop("align", "center"))
        kwargs.setdefault("va", kwargs.pop("valign", "center"))
        return kwargs

    def _apply_outline(self, artist: Text) -> None:
        if not self.options.outline_enabled:
            return
        width = max(float(self.options.outline_width or 0.0), 0.0)
        if width <= 0.0:
            width = 1.5
        color = self.options.outline_color or (1.0, 1.0, 1.0, 0.9)
        artist.set_path_effects([patheffects.withStroke(linewidth=width, foreground=color)])
