"""Single-axes Matplotlib renderer for the Single Figure Studio.

This module owns the neutral FigureSpec model and the pure Matplotlib
rendering pipeline used by both preview and export. It is intentionally
independent of Qt so it can be reused for headless exports/tests.
"""

# NOTE:
# Renderer for the maintained PureMplFigureComposer. Legacy composer code lives in src/vasoanalyzer/ui/_archive.

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Literal

import numpy as np
from matplotlib import patches as mpatches
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from vasoanalyzer.core.trace_model import TraceModel

log = logging.getLogger(__name__)

_MIN_PAGE_WIDTH_IN = 2.0
_MIN_PAGE_HEIGHT_IN = 1.5
_MAX_PAGE_WIDTH_IN = 20.0
_MAX_PAGE_HEIGHT_IN = 20.0

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
    sizing_mode: Literal["axes_first", "figure_first"] = "axes_first"
    axes_first: bool = False
    axes_width_in: Optional[float] = None
    axes_height_in: Optional[float] = None
    min_margin_in: float = 0.15
    export_background: str = "white"  # "white" or "transparent"
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
    label_bold: bool = True


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
    _clamp_page_size(page)
    sizing_mode = getattr(page, "sizing_mode", "axes_first")
    # Backwards compatibility for legacy flag
    if sizing_mode not in ("axes_first", "figure_first"):
        sizing_mode = "axes_first" if getattr(page, "axes_first", False) else "figure_first"
    if sizing_mode == "axes_first":
        return _build_axes_first_figure(spec, ctx, fig=fig)
    return _build_figure_first(spec, ctx, fig=fig)


def _clamp_page_size(page: PageSpec) -> None:
    """Enforce a minimum physical size to keep labels visible."""
    page.width_in = min(max(float(page.width_in), _MIN_PAGE_WIDTH_IN), _MAX_PAGE_WIDTH_IN)
    page.height_in = min(max(float(page.height_in), _MIN_PAGE_HEIGHT_IN), _MAX_PAGE_HEIGHT_IN)


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
        # Use forward=False to prevent matplotlib from resizing the Qt canvas widget.
        # The composer window manually controls canvas sizing via setFixedSize().
        fig.set_size_inches(page.width_in, page.height_in, forward=False)
        fig.set_dpi(page.dpi)
    ax = fig.add_subplot(111)
    # Extra left margin keeps y-label visible on tall/narrow sizes; slightly tighter right/bottom.
    base_left = 0.18
    w_in = max(page.width_in, 1e-6)
    h_in = max(page.height_in, 1e-6)
    aspect = h_in / w_in
    extra_left = 0.0
    if aspect >= 1.6 or w_in <= 3.0:
        extra_left = 0.02  # 2% of width for extreme tall/narrow
    if w_in <= 2.0:  # Very small figures need even more left margin for ylabel
        extra_left = max(extra_left, 0.08)  # At least 8% extra for small figures
    if w_in <= 1.5:  # Tiny figures need aggressive margins
        extra_left = max(extra_left, 0.12)  # At least 12% extra for tiny figures
    left = min(0.40, base_left + extra_left)
    # Dynamic bottom margin: tall/square figures and very small figures need more space for xlabel
    base_bottom = 0.16
    extra_bottom = 0.0
    if aspect >= 1.0:  # Square or taller figures
        extra_bottom = 0.06  # Add 6% for xlabel visibility
    if h_in <= 2.0:  # Very small figures need even more bottom margin
        extra_bottom = max(extra_bottom, 0.10)  # At least 10% extra for small figures
    if h_in <= 1.5:  # Tiny figures need aggressive margins
        extra_bottom = max(extra_bottom, 0.14)  # At least 14% extra for tiny figures
    bottom = min(0.35, base_bottom + extra_bottom)
    fig.subplots_adjust(left=left, right=0.97, bottom=bottom, top=0.95)

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
    """Axes-first sizing that keeps the data rectangle at the requested size."""
    page = spec.page
    dpi = page.dpi
    axes_w = float(page.width_in)
    axes_h = float(page.height_in)
    # Use min_margin_in as a floor for padding; never go below 0.15 in.
    pad_in = max(0.15, float(getattr(page, "min_margin_in", 0.0) or 0.0))
    initial_margin = max(pad_in, 0.5)
    page.effective_width_in = None
    page.effective_height_in = None
    page.axes_width_in = axes_w
    page.axes_height_in = axes_h

    # Provisional figure that is slightly larger than the target axes box.
    provisional_w = axes_w + 2 * initial_margin
    provisional_h = axes_h + 2 * initial_margin
    original_canvas = fig.canvas if fig is not None else None
    if fig is None:
        fig = Figure(figsize=(provisional_w, provisional_h), dpi=dpi)
    else:
        fig.clear()
        fig.set_size_inches(provisional_w, provisional_h, forward=False)
        fig.set_dpi(dpi)

    ax_left = initial_margin / provisional_w
    ax_bottom = initial_margin / provisional_h
    ax_width = axes_w / provisional_w
    ax_height = axes_h / provisional_h
    ax = fig.add_axes([ax_left, ax_bottom, ax_width, ax_height])

    # Render all content onto the provisional axes.
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    ax.set_facecolor("white")
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

    agg_canvas = FigureCanvasAgg(fig)
    agg_canvas.draw()
    agg_renderer = agg_canvas.get_renderer()
    required_artists = _collect_required_artists(ax, spec)
    fig_trans = fig.dpi_scale_trans.inverted()
    axes_bbox = ax.get_window_extent(renderer=agg_renderer).transformed(fig_trans)

    min_x = axes_bbox.x0
    max_x = axes_bbox.x1
    min_y = axes_bbox.y0
    max_y = axes_bbox.y1
    for art in required_artists:
        try:
            bbox = art.get_window_extent(renderer=agg_renderer)
            if bbox is None:
                continue
            bbox_in = bbox.transformed(fig_trans)
            min_x = min(min_x, bbox_in.x0)
            max_x = max(max_x, bbox_in.x1)
            min_y = min(min_y, bbox_in.y0)
            max_y = max(max_y, bbox_in.y1)
        except Exception:
            log.debug("Failed to measure artist bbox", exc_info=True)

    left_margin = max(0.0, axes_bbox.x0 - min_x) + pad_in
    right_margin = max(0.0, max_x - axes_bbox.x1) + pad_in
    bottom_margin = max(0.0, axes_bbox.y0 - min_y) + pad_in
    top_margin = max(0.0, max_y - axes_bbox.y1) + pad_in

    fig_w = axes_w + left_margin + right_margin
    fig_h = axes_h + top_margin + bottom_margin

    fig.set_size_inches(fig_w, fig_h, forward=True)
    ax.set_position(
        [
            left_margin / fig_w,
            bottom_margin / fig_h,
            axes_w / fig_w,
            axes_h / fig_h,
        ]
    )

    # Store effective figure size for downstream consumers.
    page.effective_width_in = fig_w
    page.effective_height_in = fig_h

    try:
        agg_canvas.draw()
    except Exception:
        log.debug("Final draw after resizing failed", exc_info=True)
    if original_canvas is not None:
        fig.set_canvas(original_canvas)
    return fig


def export_figure(
    spec: FigureSpec,
    out_path: str,
    transparent: bool = False,
    ctx: RenderContext | None = None,
    export_background: str | None = None,
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

    # Fallback tight layout for extreme tall/narrow exports to keep labels visible.
    try:
        aspect = h_in / max(w_in, 1e-6)
        if aspect >= 1.6 or w_in <= 3.0:
            fig.tight_layout(pad=0.02)
    except Exception:
        log.debug("tight_layout skipped", exc_info=True)

    # Ensure required elements remain visible; one corrective pass only.
    try:
        _ensure_required_visibility(fig, spec)
    except Exception as exc:
        log.warning("Visibility validation failed: %s", exc)
        raise

    # Determine export background behavior
    bg_mode = export_background or getattr(spec.page, "export_background", "white")
    if transparent:
        bg_mode = "transparent"
    savefig_kwargs = _apply_export_background(fig, bg_mode)

    fig.savefig(
        out_path,
        dpi=dpi,
        bbox_inches="tight",
        **savefig_kwargs,
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
    label_weight = "bold" if getattr(axes_spec, "label_bold", True) else "normal"

    # Axis labels (always black regardless of theme)
    ax.set_xlabel(
        axes_spec.xlabel,
        fontsize=xlabel_fs,
        fontweight=label_weight,
        labelpad=8,
        color="black",
    )
    ax.set_ylabel(
        axes_spec.ylabel,
        fontsize=ylabel_fs,
        fontweight=label_weight,
        labelpad=10,
        color="black",
    )
    try:
        ax.xaxis.label.set_clip_on(False)
        ax.yaxis.label.set_clip_on(False)
        ax.title.set_clip_on(False)
    except Exception:
        log.debug("Failed to disable label clipping", exc_info=True)

    # Tick labels and tick appearance (always black regardless of theme)
    ax.tick_params(
        axis="both",
        which="major",
        labelsize=tick_fs,
        direction="out",
        length=5,
        width=1.0,
        colors="black",
        labelcolor="black",
    )
    ax.tick_params(
        axis="both",
        which="minor",
        length=3,
        width=0.8,
        colors="black",
    )

    # Spines (always black regardless of theme)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_edgecolor("black")

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


def _apply_export_background(fig: Figure, mode: str) -> Dict[str, object]:
    """Set figure/axes background and return savefig kwargs for the mode."""
    normalized = "transparent" if str(mode).lower() == "transparent" else "white"
    facecolor = "none" if normalized == "transparent" else "white"
    edgecolor = facecolor
    try:
        fig.patch.set_facecolor(facecolor)
        fig.patch.set_alpha(0.0 if normalized == "transparent" else 1.0)
        for axis in fig.axes:
            axis.set_facecolor(facecolor)
    except Exception:
        log.debug("Failed to set export background", exc_info=True)

    if normalized == "transparent":
        return {"transparent": True}
    return {"transparent": False, "facecolor": facecolor, "edgecolor": edgecolor}


def _get_renderer_for_figure(fig: Figure):
    """
    Return a renderer suitable for measuring artist extents using an Agg canvas.
    Always uses FigureCanvasAgg to avoid backend-specific renderer differences.
    """
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    return canvas.get_renderer(), canvas


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


def _collect_required_artists(ax: "Axes", spec: FigureSpec) -> List[object]:
    """Gather artists that must remain visible."""
    artists: List[object] = []
    try:
        if ax.get_xlabel():
            artists.append(ax.xaxis.label)
        if ax.get_ylabel():
            artists.append(ax.yaxis.label)
        title_text = ax.get_title()
        if title_text:
            artists.append(ax.title)
    except Exception:
        log.debug("Failed to collect axis labels", exc_info=True)

    # Legend
    if spec.legend_visible:
        try:
            leg = ax.get_legend()
            if leg is not None:
                artists.append(leg)
        except Exception:
            log.debug("Legend collection failed", exc_info=True)

    # Tick labels
    try:
        artists.extend([lbl for lbl in ax.get_xticklabels() if lbl.get_text()])
        artists.extend([lbl for lbl in ax.get_yticklabels() if lbl.get_text()])
    except Exception:
        log.debug("Failed to collect tick labels", exc_info=True)

    return artists


def _validate_artists(fig: Figure, artists: List[object], *, tolerance: float = 1.5) -> List[str]:
    """Return list of failure messages for artists outside the figure bbox."""
    failures: List[str] = []
    if not artists:
        return failures

    # Ensure we have a renderer
    renderer, _canvas = _get_renderer_for_figure(fig)
    fig_bbox = fig.bbox

    for art in artists:
        try:
            if hasattr(art, "get_visible") and not art.get_visible():
                continue
            bbox = art.get_window_extent(renderer=renderer)
            if bbox is None:
                continue
            if (
                bbox.x0 < fig_bbox.x0 - tolerance
                or bbox.y0 < fig_bbox.y0 - tolerance
                or bbox.x1 > fig_bbox.x1 + tolerance
                or bbox.y1 > fig_bbox.y1 + tolerance
            ):
                label = getattr(art, "get_text", lambda: "")()
                kind = art.__class__.__name__
                failures.append(f"{kind} '{label}' not fully visible")
        except Exception:
            log.debug("Artist validation failed", exc_info=True)
            continue
    return failures


def _ensure_required_visibility(fig: Figure, spec: FigureSpec) -> None:
    """Validate required artists; try one corrective layout pass before erroring."""
    if not fig.axes:
        return
    ax = fig.axes[0]
    artists = _collect_required_artists(ax, spec)
    failures = _validate_artists(fig, artists)
    if not failures:
        return

    # One corrective pass
    try:
        fig.tight_layout(pad=0.8)
    except Exception:
        log.debug("tight_layout corrective pass skipped", exc_info=True)
    failures = _validate_artists(fig, artists)
    if failures:
        msg = "; ".join(failures)
        raise ValueError(
            "Figure too small to render required elements. "
            "Increase figure size or reduce text. Details: " + msg
        )
