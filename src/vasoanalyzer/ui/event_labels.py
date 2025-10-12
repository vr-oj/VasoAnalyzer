"""Decluttered event labels for Matplotlib time-series plots with per-label styling.

The helper supports three modes:

* ``vertical`` – rotated labels placed just inside the top-most shared-x axes.
* ``horizontal`` – horizontal lanes inside the host axes.
* ``horizontal_outside`` – labels in a slim belt above the top-most axes.

Dashed event lines can span every shared-x sibling axes, while the labels themselves
anchor to a single “host” axes (top by default).  Pixel-aware clustering keeps crowded
regions tidy by summarising nearby events with a ``(+N more)`` suffix.  Individual labels
can override typography, offsets, visibility, and box styling through metadata payloads.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from matplotlib.axes import Axes
from matplotlib.font_manager import FontProperties
from matplotlib.transforms import ScaledTranslation, blended_transform_factory

try:  # axes_grid1 is optional; fall back gracefully if absent
    from mpl_toolkits.axes_grid1 import make_axes_locatable  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    make_axes_locatable = None


@dataclass
class LayoutOptions:
    """User-tunable layout parameters."""

    # Clustering / summarisation
    min_px: int = 24
    max_labels_per_cluster: int = 1
    truncate: int = 28

    # Inside placement controls
    top_pad_axes: float = 0.03
    lane_gap_axes: float = 0.06
    max_lanes: int = 3
    horizontal_x_pad_px: float = 6.0

    # Rendering behaviour
    live: bool = False
    line_width: float = 1.0
    line_style: str = "--"
    fontsize: int = 9
    show_lines: bool = True

    # Shared-x routing
    span_siblings: bool = True
    label_host: str = "auto_top"  # {"self", "auto_top", "auto_bottom"}

    # Vertical niceties
    vertical_side: str = "right"  # {"right", "left"}
    vertical_x_pad_px: float = 6.0

    # Outside belt specifics
    outside_height_pct: float = 12.0
    outside_pad_in: float = 0.18
    outside_show_baseline: bool = False


@dataclass
class EventEntry:
    """Normalised event metadata with optional styling overrides."""

    time: float
    label: str
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_label(self) -> str:
        override = self.meta.get("text")
        if isinstance(override, str) and override.strip():
            return override
        return self.label

    @property
    def visible(self) -> bool:
        value = self.meta.get("visible", True)
        if value is None:
            return True
        return bool(value)


@dataclass
class ClusteredLabel:
    """Clustered label payload passed to rendering helpers."""

    x: float
    text: str
    meta: Dict[str, Any]
    entries: List[EventEntry]


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return f"{text[: limit - 1]}…"


def _measure_text(renderer, text: str, fontsize: float) -> Tuple[float, float]:
    if renderer is None:
        return 0.0, 0.0
    props = FontProperties(size=fontsize)
    width, height, _ = renderer.get_text_width_height_descent(text, props, ismath=False)
    return float(width), float(height)


def _shared_x_axes(ax: Axes) -> List[Axes]:
    try:
        siblings = list(ax.get_shared_x_axes().get_siblings(ax))
    except Exception:
        siblings = [ax]
    return [candidate for candidate in siblings if candidate is not None]


def _select_host(ax: Axes, policy: str) -> Axes:
    siblings = _shared_x_axes(ax)
    if policy == "self" or len(siblings) <= 1:
        return ax
    siblings.sort(key=lambda candidate: candidate.get_position().y1)
    if policy == "auto_bottom":
        return siblings[0]
    return siblings[-1]


def _cluster_by_pixels(ax: Axes, xs_data: Sequence[float], min_px: int) -> List[List[int]]:
    transform = ax.transData
    xs_px = [transform.transform((x, 0))[0] for x in xs_data]
    order = sorted(range(len(xs_px)), key=xs_px.__getitem__)
    clusters: List[List[int]] = []
    current: List[int] = []
    last_px: Optional[float] = None
    for idx in order:
        px = xs_px[idx]
        if last_px is None or abs(px - last_px) >= min_px:
            if current:
                clusters.append(current)
            current = [idx]
        else:
            current.append(idx)
        last_px = px
    if current:
        clusters.append(current)
    return clusters


def _auto_fontsize(base: float, count: int) -> float:
    if count <= 10:
        return base
    if count <= 20:
        return max(7, base - 1)
    if count <= 35:
        return max(6, base - 2)
    return max(6, base - 3)


class EventLabeler:
    """Cluster and render event labels with shared-x awareness and per-label overrides."""

    _VALID_MODES = {"vertical", "horizontal", "horizontal_outside"}

    def __init__(
        self,
        ax: Axes,
        events: Iterable[Any],
        mode: str = "vertical",
        options: Optional[LayoutOptions] = None,
    ) -> None:
        self.ax = ax
        self.options = options or LayoutOptions()

        self.mode = mode.lower()
        if self.mode not in self._VALID_MODES:
            raise ValueError(f"Unsupported mode '{mode}'. Expected one of {sorted(self._VALID_MODES)}.")

        self.events: List[EventEntry] = self._normalise_events(events)
        host_policy = (self.options.label_host or "auto_top").lower()
        if host_policy not in {"self", "auto_top", "auto_bottom"}:
            host_policy = "auto_top"
        self._host_ax: Axes = _select_host(ax, host_policy)

        self._artists: List = []
        self._belt_artists: List = []
        self._belt_ax: Optional[Axes] = None
        self._cid: Optional[int] = None

    # ------------------------------------------------------------------ lifecycle
    def draw(self) -> "EventLabeler":
        self.clear()
        if not self.events:
            return self
        self._render()
        if self.options.live and self._cid is None:
            canvas = getattr(self.ax.figure, "canvas", None)
            if canvas is not None:
                self._cid = canvas.mpl_connect("draw_event", self._on_draw)
        return self

    def clear(self) -> None:
        for artist in self._artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._artists.clear()

        for artist in self._belt_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._belt_artists.clear()

    def disconnect(self) -> None:
        if self._cid is None:
            return
        try:
            self.ax.figure.canvas.mpl_disconnect(self._cid)
        except Exception:
            pass
        self._cid = None

    def destroy(self, *, remove_belt: bool = False) -> None:
        """Disconnect callbacks, clear artists, and optionally remove the belt axes."""
        self.disconnect()
        self.clear()
        if remove_belt and self._belt_ax is not None:
            belt = self._belt_ax
            self._belt_ax = None
            try:
                belt.remove()
            except Exception:
                try:
                    belt.figure.delaxes(belt)
                except Exception:
                    pass
        else:
            self._belt_ax = None

    @property
    def host_axes(self) -> Axes:
        """Expose the host axes for external coordination."""
        return self._host_ax

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalise_events(events: Iterable[Any]) -> List[EventEntry]:
        entries: List[EventEntry] = []
        for item in events:
            meta: Dict[str, Any] = {}
            if isinstance(item, EventEntry):
                entries.append(EventEntry(time=float(item.time), label=str(item.label), meta=dict(item.meta or {})))
                continue

            if isinstance(item, Mapping):
                raw_time = item.get("t", item.get("time", item.get("x")))
                raw_label = item.get("label", item.get("name", ""))
                meta_payload = item.get("meta") or {}
                if isinstance(meta_payload, Mapping):
                    meta = dict(meta_payload)
                text_override = item.get("text")
                if text_override is not None:
                    meta.setdefault("text", text_override)
            else:
                try:
                    raw_time, raw_label = item  # type: ignore[misc]
                except Exception as exc:  # pragma: no cover - defensive
                    raise TypeError("Events must be (time, label) tuples, mappings, or EventEntry instances.") from exc

            try:
                time_value = float(raw_time)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid event time: {raw_time!r}") from exc

            label_value = "" if raw_label is None else str(raw_label)
            entries.append(EventEntry(time=time_value, label=label_value, meta=meta))

        entries.sort(key=lambda entry: (entry.time, entry.display_label))
        return entries

    @staticmethod
    def _meta_float(meta: Mapping[str, Any], key: str, default: Optional[float] = None) -> Optional[float]:
        value = meta.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _meta_int(meta: Mapping[str, Any], key: str, default: Optional[int] = None) -> Optional[int]:
        value = meta.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _render(self) -> None:
        if self.mode == "vertical":
            self._draw_vertical_inside()
        elif self.mode == "horizontal":
            self._draw_horizontal_inside()
        else:
            self._draw_horizontal_outside()

    def _visible_indices(self, ax: Axes) -> List[int]:
        xmin, xmax = ax.get_xlim()
        pad = 0.02 * (xmax - xmin)
        return [idx for idx, entry in enumerate(self.events) if (xmin - pad) <= entry.time <= (xmax + pad)]

    def _cluster(self, ax: Axes, indices: List[int]) -> List[ClusteredLabel]:
        if not indices:
            return []

        xs_data = [self.events[i].time for i in indices]
        clusters = _cluster_by_pixels(ax, xs_data, max(1, int(self.options.min_px)))
        results: List[ClusteredLabel] = []

        for cluster in clusters:
            actual_indices = [indices[j] for j in cluster]
            entries = [self.events[idx] for idx in actual_indices if self.events[idx].visible]
            if not entries:
                continue

            x_vals = [entry.time for entry in entries]
            centre = sum(x_vals) / len(x_vals) if x_vals else entries[0].time

            texts: List[str] = []
            seen = set()
            for entry in entries:
                text_piece = _truncate(entry.display_label, self.options.truncate)
                if not text_piece:
                    continue
                if text_piece not in seen:
                    texts.append(text_piece)
                    seen.add(text_piece)

            if not texts:
                continue

            max_labels = max(1, int(self.options.max_labels_per_cluster))
            shown = texts[:max_labels]
            remaining = max(0, len(texts) - len(shown))
            label_text = " · ".join(shown)
            if remaining:
                label_text = f"{label_text} (+{remaining} more)"

            primary_meta = dict(entries[0].meta or {})
            results.append(ClusteredLabel(x=centre, text=label_text, meta=primary_meta, entries=entries))

        results.sort(key=lambda cluster: cluster.x)
        return results

    def _draw_event_lines(self, xs: Sequence[float]) -> None:
        if not self.options.show_lines or self.options.line_width <= 0:
            return
        targets = _shared_x_axes(self.ax) if self.options.span_siblings else [self.ax]
        for axis in targets:
            for x in xs:
                line = axis.axvline(
                    x,
                    linestyle=self.options.line_style,
                    linewidth=self.options.line_width,
                    zorder=2.5,
                )
                self._artists.append(line)

    def _resolve_halign(self, default: str, meta: Mapping[str, Any]) -> str:
        override = meta.get("align")
        if isinstance(override, str):
            override = override.lower()
            if override in {"left", "right", "center"}:
                return override
        return default

    def _resolve_valign(self, default: str, meta: Mapping[str, Any]) -> str:
        override = meta.get("valign")
        if isinstance(override, str):
            override = override.lower()
            if override in {"top", "center", "bottom", "baseline"}:
                return override
        return default

    # ------------------------------------------------------------------ modes
    def _draw_vertical_inside(self) -> None:
        host = self._host_ax
        indices = self._visible_indices(host)
        if not indices:
            return

        self._draw_event_lines([self.events[i].time for i in indices])

        clusters = self._cluster(host, indices)
        if not clusters:
            return

        base_fontsize = _auto_fontsize(self.options.fontsize, len(clusters))
        base_transform = blended_transform_factory(host.transData, host.transAxes)
        side = self.options.vertical_side.lower()
        default_pad = abs(float(self.options.vertical_x_pad_px))
        direction = -1.0 if side == "right" else 1.0
        base_y = 1.0 - float(self.options.top_pad_axes)

        dpi = host.figure.dpi
        for cluster in clusters:
            meta = cluster.meta or {}
            if not bool(meta.get("visible", True)):
                continue

            fontsize = self._meta_float(meta, "fontsize", base_fontsize) or base_fontsize
            pad_px = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            total_pad = (direction * default_pad) + pad_px
            offset = ScaledTranslation(total_pad / dpi, 0.0, host.figure.dpi_scale_trans)
            transform = base_transform + offset
            y_axes = base_y + (self._meta_float(meta, "y_offset_axes", 0.0) or 0.0)
            ha = self._resolve_halign("right" if side == "right" else "left", meta)
            va = self._resolve_valign("top", meta)

            kwargs: Dict[str, Any] = {}
            font_family = meta.get("font") or meta.get("fontfamily")
            if isinstance(font_family, str) and font_family.strip():
                kwargs["fontfamily"] = font_family
            font_style = meta.get("fontstyle")
            if isinstance(font_style, str) and font_style.strip():
                kwargs["fontstyle"] = font_style
            font_weight = meta.get("fontweight")
            if isinstance(font_weight, str) and font_weight.strip():
                kwargs["fontweight"] = font_weight
            color = meta.get("color")
            if isinstance(color, str) and color.strip():
                kwargs["color"] = color
            alpha = self._meta_float(meta, "alpha", None)
            if alpha is not None:
                kwargs["alpha"] = max(0.0, min(alpha, 1.0))
            clip_on = bool(meta.get("clip_on", True))
            rotation = meta.get("rotation", 90)

            text_value = meta.get("text_override", cluster.text)
            if isinstance(text_value, str):
                label_text = text_value
            else:
                label_text = cluster.text

            txt = host.text(
                cluster.x,
                y_axes,
                label_text,
                rotation=rotation,
                rotation_mode="anchor",
                transform=transform,
                ha=ha,
                va=va,
                fontsize=fontsize,
                clip_on=clip_on,
                zorder=4.0,
                **kwargs,
            )
            self._artists.append(txt)

    def _draw_horizontal_inside(self) -> None:
        host = self._host_ax
        indices = self._visible_indices(host)
        if not indices:
            return

        self._draw_event_lines([self.events[i].time for i in indices])

        clusters = self._cluster(host, indices)
        if not clusters:
            return

        base_fontsize = _auto_fontsize(self.options.fontsize, len(clusters))
        lanes = max(1, int(self.options.max_lanes))
        lane_right_px = [-float("inf")] * lanes
        buffer_px = 6.0
        lane_ys = [
            max(0.0, (1.0 - float(self.options.top_pad_axes)) - lane * float(self.options.lane_gap_axes))
            for lane in range(lanes)
        ]

        canvas = getattr(host.figure, "canvas", None)
        renderer = None
        if canvas is not None:
            try:
                canvas.draw()
            except Exception:
                pass
            try:
                renderer = canvas.get_renderer()
            except Exception:
                renderer = None

        base_transform = blended_transform_factory(host.transData, host.transAxes)
        dpi = host.figure.dpi
        default_pad = abs(float(self.options.horizontal_x_pad_px))
        axes_bbox = None
        if renderer is not None:
            try:
                axes_bbox = host.get_window_extent(renderer)
            except Exception:
                axes_bbox = None

        for cluster in clusters:
            meta = cluster.meta or {}
            if not bool(meta.get("visible", True)):
                continue

            fontsize = self._meta_float(meta, "fontsize", base_fontsize) or base_fontsize
            pad_px = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            x_px = host.transData.transform((cluster.x, 0.0))[0]
            width_px = _measure_text(renderer, cluster.text, fontsize)[0]
            if width_px <= 0.0:
                width_px = 0.0

            align_pref = self._resolve_halign("left", meta)
            align_right = align_pref == "right"

            total_pad = default_pad + pad_px
            if align_pref == "center":
                text_left = x_px - width_px / 2.0
                text_right = x_px + width_px / 2.0
            elif align_right:
                text_right = x_px - total_pad
                text_left = text_right - width_px
            else:
                text_left = x_px + total_pad
                text_right = text_left + width_px

            if axes_bbox is not None:
                if not align_right and text_right > axes_bbox.x1 - buffer_px:
                    align_right = True
                    text_right = x_px - total_pad
                    text_left = text_right - width_px
                elif align_right and text_left < axes_bbox.x0 + buffer_px:
                    align_right = False
                    text_left = x_px + total_pad
                    text_right = text_left + width_px

            preferred_lane = self._meta_int(meta, "lane", None)
            lane_idx: Optional[int] = None
            if preferred_lane is not None and preferred_lane >= 0:
                lane_idx = min(preferred_lane, lanes - 1)
            else:
                for idx_lane, right_edge in enumerate(lane_right_px):
                    if text_left >= right_edge:
                        lane_idx = idx_lane
                        break
            if lane_idx is None:
                lane_idx = min(range(lanes), key=lambda idx: lane_right_px[idx])

            lane_right_px[lane_idx] = max(lane_right_px[lane_idx], text_right + buffer_px)
            offset = total_pad if not align_right else -total_pad
            if align_pref == "center":
                offset = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            transform = base_transform + ScaledTranslation(offset / dpi, 0.0, host.figure.dpi_scale_trans)
            ha = "right" if align_right else ("center" if align_pref == "center" else "left")
            va = self._resolve_valign("top", meta)
            y_axes = lane_ys[lane_idx] + (self._meta_float(meta, "y_offset_axes", 0.0) or 0.0)

            kwargs: Dict[str, Any] = {}
            font_family = meta.get("font") or meta.get("fontfamily")
            if isinstance(font_family, str) and font_family.strip():
                kwargs["fontfamily"] = font_family
            font_style = meta.get("fontstyle")
            if isinstance(font_style, str) and font_style.strip():
                kwargs["fontstyle"] = font_style
            font_weight = meta.get("fontweight")
            if isinstance(font_weight, str) and font_weight.strip():
                kwargs["fontweight"] = font_weight
            color = meta.get("color")
            if isinstance(color, str) and color.strip():
                kwargs["color"] = color
            alpha = self._meta_float(meta, "alpha", None)
            if alpha is not None:
                kwargs["alpha"] = max(0.0, min(alpha, 1.0))
            clip_on = bool(meta.get("clip_on", True))
            rotation = meta.get("rotation", 0)

            txt = host.text(
                cluster.x,
                y_axes,
                cluster.text,
                transform=transform,
                ha=ha,
                va=va,
                fontsize=fontsize,
                clip_on=clip_on,
                rotation=rotation,
                rotation_mode="anchor",
                zorder=4.0,
                **kwargs,
            )
            self._artists.append(txt)

    def _ensure_belt(self, host: Axes) -> Optional[Axes]:
        if make_axes_locatable is None:
            return None
        belt = self._belt_ax
        if belt is not None and belt in host.figure.axes:
            return belt

        divider = make_axes_locatable(host)
        belt = divider.append_axes(
            "top",
            size=f"{float(self.options.outside_height_pct):.1f}%",
            pad=float(self.options.outside_pad_in),
            sharex=host,
        )
        self._belt_ax = belt

        belt.set_ylim(0.0, 1.0)
        belt.set_yticks([])
        belt.set_xticks([])
        belt.tick_params(axis="x", which="both", length=0, labelbottom=False, labeltop=False)
        belt.set_facecolor("none")
        for spine in belt.spines.values():
            spine.set_visible(False)
        return belt

    def _draw_horizontal_outside(self) -> None:
        host = self._host_ax
        indices = self._visible_indices(host)
        if not indices:
            return

        self._draw_event_lines([self.events[i].time for i in indices])

        clusters = self._cluster(host, indices)
        if not clusters:
            return
        fontsize_base = _auto_fontsize(self.options.fontsize, len(clusters))

        belt = self._ensure_belt(host)
        if belt is None:
            self._draw_horizontal_outside_fallback(host, clusters, fontsize_base)
            return

        canvas = getattr(belt.figure, "canvas", None)
        renderer = None
        if canvas is not None:
            try:
                canvas.draw()
            except Exception:
                pass
            try:
                renderer = canvas.get_renderer()
            except Exception:
                renderer = None

        lanes = max(1, int(self.options.max_lanes))
        lane_right_px = [-float("inf")] * lanes
        buffer_px = 6.0
        if lanes == 1:
            lane_ys = [0.85]
        else:
            top = 0.9
            gap = 0.7 / (lanes - 1)
            lane_ys = [max(0.12, top - lane * gap) for lane in range(lanes)]

        if self.options.outside_show_baseline:
            baseline = belt.axhline(0.0, linewidth=0.6, color="0.8", zorder=1.0)
            self._belt_artists.append(baseline)

        base_transform = blended_transform_factory(belt.transData, belt.transAxes)
        dpi = belt.figure.dpi
        default_pad = abs(float(self.options.horizontal_x_pad_px))
        axes_bbox = None
        if renderer is not None:
            try:
                axes_bbox = belt.get_window_extent(renderer)
            except Exception:
                axes_bbox = None

        for cluster in clusters:
            meta = cluster.meta or {}
            if not bool(meta.get("visible", True)):
                continue

            fontsize = self._meta_float(meta, "fontsize", fontsize_base) or fontsize_base
            pad_px = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            x_px = belt.transData.transform((cluster.x, 0.0))[0]
            width_px = _measure_text(renderer, cluster.text, fontsize)[0]
            if width_px <= 0.0:
                width_px = 0.0

            align_pref = self._resolve_halign("left", meta)
            align_right = align_pref == "right"

            total_pad = default_pad + pad_px
            if align_pref == "center":
                text_left = x_px - width_px / 2.0
                text_right = x_px + width_px / 2.0
            elif align_right:
                text_right = x_px - total_pad
                text_left = text_right - width_px
            else:
                text_left = x_px + total_pad
                text_right = text_left + width_px

            if axes_bbox is not None:
                if not align_right and text_right > axes_bbox.x1 - buffer_px:
                    align_right = True
                    text_right = x_px - total_pad
                    text_left = text_right - width_px
                elif align_right and text_left < axes_bbox.x0 + buffer_px:
                    align_right = False
                    text_left = x_px + total_pad
                    text_right = text_left + width_px

            preferred_lane = self._meta_int(meta, "lane", None)
            lane_idx: Optional[int] = None
            if preferred_lane is not None and preferred_lane >= 0:
                lane_idx = min(preferred_lane, lanes - 1)
            else:
                for idx_lane, right_edge in enumerate(lane_right_px):
                    if text_left >= right_edge:
                        lane_idx = idx_lane
                        break
            if lane_idx is None:
                lane_idx = min(range(lanes), key=lambda idx: lane_right_px[idx])

            lane_right_px[lane_idx] = max(lane_right_px[lane_idx], text_right + buffer_px)
            offset = total_pad if not align_right else -total_pad
            if align_pref == "center":
                offset = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            transform = base_transform + ScaledTranslation(offset / dpi, 0.0, belt.figure.dpi_scale_trans)
            ha = "right" if align_right else ("center" if align_pref == "center" else "left")
            va = self._resolve_valign("top", meta)
            y_axes = lane_ys[lane_idx] + (self._meta_float(meta, "y_offset_axes", 0.0) or 0.0)

            kwargs: Dict[str, Any] = {}
            font_family = meta.get("font") or meta.get("fontfamily")
            if isinstance(font_family, str) and font_family.strip():
                kwargs["fontfamily"] = font_family
            font_style = meta.get("fontstyle")
            if isinstance(font_style, str) and font_style.strip():
                kwargs["fontstyle"] = font_style
            font_weight = meta.get("fontweight")
            if isinstance(font_weight, str) and font_weight.strip():
                kwargs["fontweight"] = font_weight
            color = meta.get("color")
            if isinstance(color, str) and color.strip():
                kwargs["color"] = color
            alpha = self._meta_float(meta, "alpha", None)
            if alpha is not None:
                kwargs["alpha"] = max(0.0, min(alpha, 1.0))
            rotation = meta.get("rotation", 0)
            bbox = meta.get("bbox")
            if bbox is False:
                bbox_kwargs = None
            elif isinstance(bbox, Mapping):
                bbox_kwargs = dict(bbox)
            else:
                bbox_kwargs = {
                    "facecolor": "white",
                    "edgecolor": "0.7",
                    "linewidth": 0.8,
                    "boxstyle": "round,pad=0.3",
                    "alpha": 0.9,
                }

            txt = belt.text(
                cluster.x,
                y_axes,
                cluster.text,
                transform=transform,
                ha=ha,
                va=va,
                fontsize=fontsize,
                clip_on=False,
                rotation=rotation,
                rotation_mode="anchor",
                zorder=4.0,
                bbox=bbox_kwargs,
                **kwargs,
            )
            self._belt_artists.append(txt)

    def _draw_horizontal_outside_fallback(
        self,
        host: Axes,
        clusters: Sequence[ClusteredLabel],
        fontsize_base: float,
    ) -> None:
        lanes = max(1, int(self.options.max_lanes))
        lane_right_px = [-float("inf")] * lanes
        buffer_px = 6.0
        lane_ys = [1.02 + lane * 0.08 for lane in range(lanes)]

        canvas = getattr(host.figure, "canvas", None)
        renderer = None
        if canvas is not None:
            try:
                canvas.draw()
            except Exception:
                pass
            try:
                renderer = canvas.get_renderer()
            except Exception:
                renderer = None

        base_transform = blended_transform_factory(host.transData, host.transAxes)
        dpi = host.figure.dpi
        default_pad = abs(float(self.options.horizontal_x_pad_px))
        axes_bbox = None
        if renderer is not None:
            try:
                axes_bbox = host.get_window_extent(renderer)
            except Exception:
                axes_bbox = None

        for cluster in clusters:
            meta = cluster.meta or {}
            if not bool(meta.get("visible", True)):
                continue

            fontsize = self._meta_float(meta, "fontsize", fontsize_base) or fontsize_base
            pad_px = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            x_px = host.transData.transform((cluster.x, 0.0))[0]
            width_px = _measure_text(renderer, cluster.text, fontsize)[0]
            if width_px <= 0.0:
                width_px = 0.0

            align_pref = self._resolve_halign("left", meta)
            align_right = align_pref == "right"
            total_pad = default_pad + pad_px

            if align_pref == "center":
                text_left = x_px - width_px / 2.0
                text_right = x_px + width_px / 2.0
            elif align_right:
                text_right = x_px - total_pad
                text_left = text_right - width_px
            else:
                text_left = x_px + total_pad
                text_right = text_left + width_px

            if axes_bbox is not None:
                if not align_right and text_right > axes_bbox.x1 - buffer_px:
                    align_right = True
                    text_right = x_px - total_pad
                    text_left = text_right - width_px
                elif align_right and text_left < axes_bbox.x0 + buffer_px:
                    align_right = False
                    text_left = x_px + total_pad
                    text_right = text_left + width_px

            preferred_lane = self._meta_int(meta, "lane", None)
            lane_idx: Optional[int] = None
            if preferred_lane is not None and preferred_lane >= 0:
                lane_idx = min(preferred_lane, lanes - 1)
            else:
                for idx_lane, right_edge in enumerate(lane_right_px):
                    if text_left >= right_edge:
                        lane_idx = idx_lane
                        break
            if lane_idx is None:
                lane_idx = min(range(lanes), key=lambda idx: lane_right_px[idx])

            lane_right_px[lane_idx] = max(lane_right_px[lane_idx], text_right + buffer_px)
            offset = total_pad if not align_right else -total_pad
            if align_pref == "center":
                offset = self._meta_float(meta, "x_offset_px", 0.0) or 0.0
            transform = base_transform + ScaledTranslation(offset / dpi, 0.0, host.figure.dpi_scale_trans)
            ha = "right" if align_right else ("center" if align_pref == "center" else "left")
            va = self._resolve_valign("bottom", meta)
            y_axes = lane_ys[lane_idx] + (self._meta_float(meta, "y_offset_axes", 0.0) or 0.0)

            kwargs: Dict[str, Any] = {}
            font_family = meta.get("font") or meta.get("fontfamily")
            if isinstance(font_family, str) and font_family.strip():
                kwargs["fontfamily"] = font_family
            font_style = meta.get("fontstyle")
            if isinstance(font_style, str) and font_style.strip():
                kwargs["fontstyle"] = font_style
            font_weight = meta.get("fontweight")
            if isinstance(font_weight, str) and font_weight.strip():
                kwargs["fontweight"] = font_weight
            color = meta.get("color")
            if isinstance(color, str) and color.strip():
                kwargs["color"] = color
            alpha = self._meta_float(meta, "alpha", None)
            if alpha is not None:
                kwargs["alpha"] = max(0.0, min(alpha, 1.0))
            rotation = meta.get("rotation", 0)
            bbox = meta.get("bbox")
            if bbox is False:
                bbox_kwargs = None
            elif isinstance(bbox, Mapping):
                bbox_kwargs = dict(bbox)
            else:
                bbox_kwargs = {
                    "facecolor": "white",
                    "edgecolor": "0.7",
                    "linewidth": 0.8,
                    "boxstyle": "round,pad=0.3",
                    "alpha": 0.9,
                }

            txt = host.text(
                cluster.x,
                y_axes,
                cluster.text,
                transform=transform,
                ha=ha,
                va=va,
                fontsize=fontsize,
                clip_on=False,
                rotation=rotation,
                rotation_mode="anchor",
                zorder=4.0,
                bbox=bbox_kwargs,
                **kwargs,
            )
            self._artists.append(txt)

    # ------------------------------------------------------------------ callbacks
    def _on_draw(self, event) -> None:
        if event is None or event.canvas is None or event.canvas.figure is not self.ax.figure:
            return
        self.clear()
        self._render()
