"""Single-axes Matplotlib renderer for the Single Figure Studio.

This module owns the neutral FigureSpec model and the pure Matplotlib
rendering pipeline used by both preview and export. It is intentionally
independent of Qt so it can be reused for headless exports/tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np
from matplotlib import patches as mpatches
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from vasoanalyzer.core.trace_model import TraceModel

log = logging.getLogger(__name__)

__all__ = [
    "PageSpec",
    "AxesSpec",
    "TraceSpec",
    "EventSpec",
    "AnnotationSpec",
    "FigureSpec",
    "RenderContext",
    "build_figure",
    "export_figure",
]


@dataclass
class PageSpec:
    width_in: float
    height_in: float
    dpi: float
    axes_first: bool = False
    axes_width_in: Optional[float] = None
    axes_height_in: Optional[float] = None
    min_margin_in: float = 0.5
    # effective_* are computed by build_figure; callers should treat them as
    # readonly outputs (they are reset at the beginning of each build).
    effective_width_in: Optional[float] = None
    effective_height_in: Optional[float] = None


@dataclass
class AxesSpec:
    x_range: Optional[Tuple[float, float]] = None  # None = auto
    y_range: Optional[Tuple[float, float]] = None  # None = auto
    xlabel: str = ""
    ylabel: str = ""
    show_grid: bool = True
    grid_linestyle: str = "--"
    grid_color: str = "#c0c0c0"
    grid_alpha: float = 0.7
    show_event_labels: bool = False
    # New: optional font sizes
    xlabel_fontsize: Optional[float] = None
    ylabel_fontsize: Optional[float] = None
    tick_label_fontsize: Optional[float] = None


@dataclass
class TraceSpec:
    key: str  # e.g. "inner", "outer", "avg_pressure"
    visible: bool
    color: str
    linewidth: float
    linestyle: str
    marker: str
    use_right_axis: bool = False  # placeholder for future support


@dataclass
class EventSpec:
    visible: bool
    time_s: float
    color: str
    linewidth: float
    linestyle: str
    label: str
    label_above: bool


@dataclass
class AnnotationSpec:
    kind: str  # "text", "box", "arrow", "line"
    text: str
    x: float
    y: float
    x2: Optional[float] = None  # for line/arrow end
    y2: Optional[float] = None
    coord_space: str = "data"  # "data" or "axes"
    fontsize: float = 8.0
    color: str = "black"
    linewidth: float = 1.0


@dataclass
class FigureSpec:
    page: PageSpec
    axes: AxesSpec
    traces: List[TraceSpec]
    events: List[EventSpec] = field(default_factory=list)
    annotations: List[AnnotationSpec] = field(default_factory=list)
    legend_visible: bool = True
    legend_fontsize: Optional[float] = 9.0
    legend_loc: str = "upper right"  # "best", "upper right", ...
    # New: global scaling for line widths
    line_width_scale: float = 1.0


@dataclass
class RenderContext:
    is_preview: bool = False
    trace_model: Optional["TraceModel"] = None
    series_map: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None


def build_figure(spec: FigureSpec, ctx: RenderContext, fig: Figure | None = None) -> Figure:
    """Entry point: choose figure-first or axes-first sizing."""
    page = spec.page
    if page.axes_first and page.axes_width_in and page.axes_height_in:
        return _build_axes_first_figure(spec, ctx, fig=fig)
    return _build_figure_first(spec, ctx, fig=fig)


def _build_figure_first(spec: FigureSpec, ctx: RenderContext, fig: Figure | None = None) -> Figure:
    """Legacy figure-first path: use page width/height directly."""
    page = spec.page

    # Reset effective size; this build will repopulate them.
    page.effective_width_in = None
    page.effective_height_in = None

    if fig is None:
        fig = Figure(figsize=(page.width_in, page.height_in), dpi=page.dpi)
    else:
        fig.clear()
        fig.set_size_inches(page.width_in, page.height_in, forward=True)
        fig.set_dpi(page.dpi)
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.20, top=0.95)

    _render_traces(ax, spec, ctx)

    if spec.axes.x_range is not None:
        ax.set_xlim(*spec.axes.x_range)
    if spec.axes.y_range is not None:
        ax.set_ylim(*spec.axes.y_range)

    _apply_axes_styles(ax, spec.axes)
    _render_events(ax, spec)
    _render_annotations(fig, ax, spec.annotations)

    if spec.legend_visible:
        eff_legend_fs = spec.legend_fontsize or 9.0
        leg = ax.legend(
            fontsize=eff_legend_fs,
            loc=spec.legend_loc,
            framealpha=0.8,
        )
        if leg is not None:
            frame = leg.get_frame()
            if frame is not None:
                frame.set_linewidth(0.8)

    # After any subplots_adjust, the figure size is fixed; store it as effective size.
    page.effective_width_in = fig.get_figwidth()
    page.effective_height_in = fig.get_figheight()

    return fig


def _build_axes_first_figure(spec: FigureSpec, ctx: RenderContext, fig: Figure | None = None) -> Figure:
    """Axes-first sizing using tightbbox measurement pass."""
    page = spec.page
    dpi = page.dpi
    axes_w = float(page.axes_width_in)
    axes_h = float(page.axes_height_in)
    margin = float(page.min_margin_in)
    page.effective_width_in = None
    page.effective_height_in = None

    # Pass 1: temporary figure to measure content
    tmp_fig = Figure(figsize=(axes_w + 2 * margin, axes_h + 2 * margin), dpi=dpi)
    tmp_fig_w, tmp_fig_h = tmp_fig.get_figwidth(), tmp_fig.get_figheight()
    ax_left = margin / tmp_fig_w
    ax_bottom = margin / tmp_fig_h
    ax_width = axes_w / tmp_fig_w
    ax_height = axes_h / tmp_fig_h
    tmp_ax = tmp_fig.add_axes([ax_left, ax_bottom, ax_width, ax_height])

    _render_traces(tmp_ax, spec, ctx)
    _apply_axes_styles(tmp_ax, spec.axes)
    _render_events(tmp_ax, spec)
    _render_annotations(tmp_fig, tmp_ax, spec.annotations)
    if spec.legend_visible:
        eff_legend_fs = spec.legend_fontsize or 9.0
        leg = tmp_ax.legend(
            fontsize=eff_legend_fs,
            loc=spec.legend_loc,
            framealpha=0.8,
        )
        if leg is not None:
            frame = leg.get_frame()
            if frame is not None:
                frame.set_linewidth(0.8)

    tmp_canvas = FigureCanvasAgg(tmp_fig)
    tmp_canvas.draw()
    renderer = tmp_canvas.get_renderer()
    tight_bbox = tmp_ax.get_tightbbox(renderer)
    tight_bbox_in = tight_bbox.transformed(tmp_fig.dpi_scale_trans.inverted())
    content_w_in = tight_bbox_in.width
    content_h_in = tight_bbox_in.height

    left = margin
    right = margin
    bottom = margin
    top = margin

    fig_w = content_w_in + left + right
    fig_h = content_h_in + bottom + top

    # Pass 2: real figure
    if fig is None:
        fig = Figure(figsize=(fig_w, fig_h), dpi=dpi)
    else:
        fig.clear()
        fig.set_size_inches(fig_w, fig_h, forward=True)
        fig.set_dpi(dpi)

    # Store effective size for downstream consumers (preview/export UI).
    page.effective_width_in = fig_w
    page.effective_height_in = fig_h

    ax_left = left / fig_w
    ax_bottom = bottom / fig_h
    ax_width = content_w_in / fig_w
    ax_height = content_h_in / fig_h
    ax = fig.add_axes([ax_left, ax_bottom, ax_width, ax_height])

    _render_traces(ax, spec, ctx)
    _apply_axes_styles(ax, spec.axes)
    _render_events(ax, spec)
    _render_annotations(fig, ax, spec.annotations)
    if spec.legend_visible:
        eff_legend_fs = spec.legend_fontsize or 9.0
        leg = ax.legend(
            fontsize=eff_legend_fs,
            loc=spec.legend_loc,
            framealpha=0.8,
        )
        if leg is not None:
            frame = leg.get_frame()
            if frame is not None:
                frame.set_linewidth(0.8)
    return fig


def export_figure(
    spec: FigureSpec,
    out_path: str,
    transparent: bool = False,
    ctx: RenderContext | None = None,
) -> None:
    """Export a FigureSpec to disk using only page size + DPI."""
    render_ctx = ctx or RenderContext(is_preview=False, trace_model=None)
    fig = build_figure(spec, render_ctx)

    page = spec.page
    w_in = page.effective_width_in or page.width_in
    h_in = page.effective_height_in or page.height_in
    dpi = spec.page.dpi
    width_px = w_in * dpi
    height_px = h_in * dpi

    # Safety clamp
    max_dim = 8000
    if width_px > max_dim or height_px > max_dim:
        scale = max_dim / max(width_px, height_px)
        old_dpi = dpi
        dpi = dpi * scale
        log.warning(
            "Export size clamped from %.0f×%.0f px (%.0f dpi) to %.0f×%.0f px (%.0f dpi) "
            "to stay under max_dim=%d",
            width_px,
            height_px,
            old_dpi,
            w_in * dpi,
            h_in * dpi,
            dpi,
            max_dim,
        )

    fig.savefig(
        out_path,
        dpi=dpi,
        facecolor="white" if not transparent else "none",
        bbox_inches="tight",
        transparent=transparent,
    )


def _render_traces(ax: "Axes", spec: FigureSpec, ctx: RenderContext) -> None:
    """
    Render all visible traces onto the given axes.
    """
    default_lw = 1.8
    lw_scale = spec.line_width_scale or 1.0
    right_ax: "Axes | None" = None
    for trace in spec.traces:
        if not trace.visible:
            continue
        series = _trace_series_from_context(trace.key, ctx)
        if series is None:
            log.debug("Trace %s missing data; skipping", trace.key)
            continue
        x, y = series
        target_ax = ax
        if trace.use_right_axis:
            if right_ax is None:
                right_ax = ax.twinx()
            target_ax = right_ax

        base_lw = trace.linewidth or default_lw
        lw = base_lw * lw_scale
        linestyle = trace.linestyle or "-"

        target_ax.plot(
            x,
            y,
            color=trace.color,
            linewidth=lw,
            linestyle=linestyle,
            marker=trace.marker or None,
            solid_capstyle="round",
            label=trace.key,
        )


def _trace_series_from_context(
    trace_key: str, ctx: RenderContext
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Resolve (x, y) series for a trace key using context-provided data."""
    if ctx.series_map and trace_key in ctx.series_map:
        return ctx.series_map[trace_key]

    tm = ctx.trace_model
    if tm is None:
        return None

    time = tm.time_full
    mapping = {
        "inner": tm.inner_full,
        "outer": tm.outer_full,
        "avg_pressure": tm.avg_pressure_full,
        "set_pressure": tm.set_pressure_full,
    }
    data = mapping.get(trace_key)
    if data is None:
        return None
    return np.asarray(time), np.asarray(data)


def _apply_axes_styles(ax: "Axes", axes_spec: AxesSpec) -> None:
    """
    Apply axis labels, ticks, grid, and spine styling.
    Font sizes come from AxesSpec if set; otherwise we fall back to sane defaults.
    """
    # Defaults
    default_label_fs = 11.0
    default_tick_fs = 9.0

    # Effective font sizes
    xlabel_fs = axes_spec.xlabel_fontsize or default_label_fs
    ylabel_fs = axes_spec.ylabel_fontsize or default_label_fs
    tick_fs = axes_spec.tick_label_fontsize or default_tick_fs

    # Axis labels
    ax.set_xlabel(
        axes_spec.xlabel,
        fontsize=xlabel_fs,
        fontweight="bold",
        labelpad=8,
    )
    ax.set_ylabel(
        axes_spec.ylabel,
        fontsize=ylabel_fs,
        fontweight="bold",
        labelpad=10,
    )

    # Tick labels and tick appearance
    ax.tick_params(
        axis="both",
        which="major",
        labelsize=tick_fs,
        direction="out",
        length=5,
        width=1.0,
    )
    ax.tick_params(
        axis="both",
        which="minor",
        length=3,
        width=0.8,
    )

    # Spines
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)

    # Grid
    if axes_spec.show_grid:
        ax.grid(
            True,
            which="major",
            linestyle=axes_spec.grid_linestyle or "--",
            color=axes_spec.grid_color or "#d0d0d0",
            linewidth=0.6,
            alpha=axes_spec.grid_alpha,
        )
    else:
        ax.grid(False)


def _render_events(ax: "Axes", spec: FigureSpec) -> None:
    show_labels = getattr(spec.axes, "show_event_labels", False)
    for ev in spec.events:
        if not ev.visible:
            continue
        ax.vlines(
            x=ev.time_s,
            ymin=0.0,
            ymax=1.0,
            transform=ax.get_xaxis_transform(),
            color=ev.color,
            linewidth=ev.linewidth,
            linestyle=ev.linestyle,
        )
        if show_labels and ev.label:
            y = 1.02 if ev.label_above else -0.02
            ax.text(
                ev.time_s,
                y,
                ev.label,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom" if ev.label_above else "top",
                fontsize=8.0,
            )


def _render_annotations(fig: Figure, ax: "Axes", annos: List[AnnotationSpec]) -> None:
    for a in annos:
        if a.coord_space == "data":
            trans = ax.transData
        else:
            trans = ax.transAxes

        if a.kind == "text":
            ax.text(
                a.x,
                a.y,
                a.text,
                transform=trans,
                fontsize=a.fontsize,
                color=a.color,
            )
        elif a.kind == "box":
            if a.x2 is None or a.y2 is None:
                continue
            rect = mpatches.Rectangle(
                (a.x, a.y),
                a.x2 - a.x,
                a.y2 - a.y,
                transform=trans,
                linewidth=a.linewidth,
                edgecolor=a.color,
                facecolor="none",
            )
            ax.add_patch(rect)
        elif a.kind == "line":
            if a.x2 is None or a.y2 is None:
                continue
            ax.plot(
                [a.x, a.x2],
                [a.y, a.y2],
                transform=trans,
                color=a.color,
                linewidth=a.linewidth,
            )
        elif a.kind == "arrow":
            if a.x2 is None or a.y2 is None:
                continue
            arrow = mpatches.FancyArrowPatch(
                (a.x, a.y),
                (a.x2, a.y2),
                transform=trans,
                linewidth=a.linewidth,
                color=a.color,
                mutation_scale=max(a.linewidth * 6.0, 6.0),
                arrowstyle="->",
            )
            ax.add_patch(arrow)
