"""Pure Matplotlib renderer for FigureSpec.

This module contains the core rendering logic that converts a FigureSpec
into a Matplotlib Figure. It is used for both preview (at screen DPI) and
export (at target DPI), guaranteeing "what you see is what you export".

No Qt imports are allowed in this module - it must remain pure Matplotlib.
"""

from __future__ import annotations

import logging
import string
from typing import TYPE_CHECKING, Any, Callable, Dict, List

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.artist import Artist
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, MultipleLocator

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from vasoanalyzer.core.trace_model import TraceModel

    from .specs import (
        AnnotationSpec,
        FigureSpec,
        FontSpec,
        GraphInstance,
        GraphSpec,
        PanelLabelSpec,
        StyleSpec,
    )

__all__ = ["render_figure", "render_into_axes", "create_annotation_artists", "TraceModelProvider"]

log = logging.getLogger(__name__)

# Type alias for trace model provider
TraceModelProvider = Callable[[str], "TraceModel"]


def _rc_params(spec: "FigureSpec") -> dict[str, Any]:
    """Build rcParams overrides from the figure font/style spec."""
    f = spec.font
    s: StyleSpec | None = getattr(spec, "style", None)
    rc: dict[str, Any] = {
        "font.family": f.family,
        "font.size": getattr(f, "base_size", f.tick_label.size if hasattr(f, "tick_label") else 8.0),
        "axes.labelsize": getattr(getattr(f, "axis_title", None), "size", 9.0),
        "xtick.labelsize": getattr(getattr(f, "tick_label", None), "size", 8.0),
        "ytick.labelsize": getattr(getattr(f, "tick_label", None), "size", 8.0),
        "legend.fontsize": getattr(getattr(f, "legend", None), "size", 8.0),
        "text.color": "#000000",
        "axes.labelcolor": "#000000",
        "xtick.color": "#000000",
        "ytick.color": "#000000",
    }
    if s is not None:
        rc.update(
            {
                "lines.linewidth": s.default_linewidth,
                "axes.linewidth": s.axis_spine_width,
                "xtick.direction": s.tick_direction,
                "ytick.direction": s.tick_direction,
                "xtick.major.size": s.tick_major_length,
                "ytick.major.size": s.tick_major_length,
                "xtick.minor.size": s.tick_minor_length,
                "ytick.minor.size": s.tick_minor_length,
            }
        )
    return rc


def _ensure_overlay_axes(fig: Figure) -> "Axes":
    """Return a figure overlay axes (0-1 normalized) for figure-level annotations."""
    overlay = getattr(fig, "_va_overlay_axes", None)
    if overlay is None or overlay.figure is None:
        overlay = fig.add_axes([0, 0, 1, 1], facecolor="none")
        overlay.set_axis_off()
        overlay.set_in_layout(False)
        overlay.set_zorder(20)
        try:
            overlay.set_navigate(False)
        except Exception:
            pass
        fig._va_overlay_axes = overlay
    return overlay


def create_annotation_artists(
    fig: Figure,
    axes_map: Dict[str, "Axes"],
    annot: "AnnotationSpec",
    *,
    figure_transform=None,
    figure_axes: "Axes | Figure | None" = None,
) -> List[Artist]:
    """Create Matplotlib artist(s) for a single AnnotationSpec and attach them.

    Allowed transforms: ax.transData, ax.get_xaxis_transform(), ax.transAxes.
    No use of annotate() to avoid mixed transform surprises across backends.
    """
    artists: List[Artist] = []
    figure_axes = figure_axes or _ensure_overlay_axes(fig)
    figure_transform = figure_transform or figure_axes.transAxes

    # Phase 1 audit (updated):
    # - transform chosen by coord_system: transData for data, transAxes for axes/figure.
    # - linewidth/linestyle in points; dash pattern relies on Matplotlib defaults.
    # - No annotate(); arrows use FancyArrowPatch with allowed transforms only.
    if annot.target_type == "graph" and annot.target_id:
        ax = axes_map.get(annot.target_id)
        if ax is None:
            log.warning("Target axes %s not found for annotation %s", annot.target_id, annot.annotation_id)
            return artists
    else:
        ax = None

    if ax is None:
        transform = figure_transform
        target = figure_axes
    elif annot.coord_system == "axes":
        transform = ax.transAxes
        target = ax
    elif annot.coord_system == "figure":
        transform = figure_transform
        target = figure_axes
    else:
        transform = ax.transData
        target = ax

    zorder = getattr(annot, "zorder", 10)

    if annot.kind == "text":
        # Phase 1 audit (text):
        # - transform: resolved above (figure/axes/data).
        # - fontsize in points; clip_on default True; no bbox unless added to spec.
        artist = target.text(
            annot.x0,
            annot.y0,
            annot.text_content,
            transform=transform,
            fontfamily=annot.font_family,
            fontsize=annot.font_size,
            fontweight=annot.font_weight,
            fontstyle=annot.font_style,
            color=annot.color,
            ha=annot.ha,
            va=annot.va,
            rotation=annot.rotation,
            alpha=annot.alpha,
            zorder=zorder,
        )
        artists.append(artist)
    elif annot.kind == "box":
        # Phase 1 audit (box):
        # - transform: resolved above; linewidth/dash in points; clip_on default True.
        width = abs(annot.x1 - annot.x0)
        height = abs(annot.y1 - annot.y0)
        x = min(annot.x0, annot.x1)
        y = min(annot.y0, annot.y1)

        rect = mpatches.Rectangle(
            (x, y),
            width,
            height,
            transform=transform,
            edgecolor=annot.edgecolor,
            facecolor=annot.facecolor,
            alpha=annot.alpha,
            linewidth=annot.linewidth,
            linestyle=annot.linestyle,
            zorder=zorder,
        )
        if hasattr(target, "add_patch"):
            target.add_patch(rect)
        else:
            fig.add_artist(rect)
        artists.append(rect)
    elif annot.kind == "arrow":
        # Phase 1 audit (arrow):
        # - Uses FancyArrowPatch with explicit transform; linewidth in points; no annotate().
        arrow = mpatches.FancyArrowPatch(
            (annot.x0, annot.y0),
            (annot.x1, annot.y1),
            transform=transform,
            color=annot.color,
            linewidth=annot.linewidth,
            arrowstyle=annot.arrowstyle or "->",
            alpha=annot.alpha,
            zorder=zorder,
            mutation_scale=max(annot.linewidth * 6.0, 6.0),
        )
        if hasattr(target, "add_patch"):
            target.add_patch(arrow)
        else:
            fig.add_artist(arrow)
        artists.append(arrow)
    elif annot.kind == "line":
        # Phase 1 audit (line):
        # - transform: resolved above; linewidth/dash in points; clip_on default True.
        if hasattr(target, "plot"):
            lines = target.plot(
                [annot.x0, annot.x1],
                [annot.y0, annot.y1],
                transform=transform,
                color=annot.color,
                linewidth=annot.linewidth,
                linestyle=annot.linestyle,
                alpha=annot.alpha,
                zorder=zorder,
            )
            artists.extend(lines)
        else:
            line = Line2D(
                [annot.x0, annot.x1],
                [annot.y0, annot.y1],
                transform=transform,
                color=annot.color,
                linewidth=annot.linewidth,
                linestyle=annot.linestyle,
                alpha=annot.alpha,
                zorder=zorder,
            )
            fig.add_artist(line)
            artists.append(line)

    return artists


def render_figure(
    spec: FigureSpec,
    trace_model_provider: TraceModelProvider,
    dpi: int = 100,
    *,
    event_times: list[float] | None = None,
    event_labels: list[str] | None = None,
    event_colors: list[str] | None = None,
) -> Figure:
    """Render a FigureSpec to a Matplotlib Figure.

    This function is the single rendering path for both preview and export.
    It creates a Figure with the exact physical size specified in the spec,
    at the requested DPI.

    Args:
        spec: Complete figure specification
        trace_model_provider: Callable that returns TraceModel for a sample_id
        dpi: Dots per inch for rendering
        event_times: Optional event times to mark on plots
        event_labels: Optional event labels
        event_colors: Optional event colors

    Returns:
        Matplotlib Figure object ready for display or export

    Note:
        This function has no Qt dependencies and can be used standalone. Export
        calls rebuild a fresh Figure per output, while preview uses
        render_into_axes on a persistent FigureCanvasQTAgg (TODO: Phase 2 – unify
        preview/export surface construction).
    """
    with mpl.rc_context(_rc_params(spec)):
        # Create figure with exact physical size from spec
        fig = Figure(
            figsize=(spec.layout.width_in, spec.layout.height_in),
            dpi=dpi,
            layout="constrained",  # Modern constrained layout
            facecolor="#ffffff",
        )

        # If no graph instances, return empty figure
        if not spec.layout.graph_instances:
            ax = fig.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                "No graphs to display",
                ha="center",
                va="center",
                fontsize=12,
                color="#666666",
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig

        # Create GridSpec for layout
        gs = GridSpec(
            spec.layout.nrows,
            spec.layout.ncols,
            figure=fig,
            hspace=spec.layout.hspace,
            wspace=spec.layout.wspace,
        )

        # Track axes for annotation rendering
        axes_map: dict[str, Axes] = {}

        # Render each graph instance
        for instance in spec.layout.graph_instances:
            try:
                ax = _render_graph_instance(
                    fig,
                    gs,
                    instance,
                    spec.graphs,
                    spec.font,
                    spec.style,
                    trace_model_provider,
                    event_times,
                    event_labels,
                    event_colors,
                )
                axes_map[instance.instance_id] = ax
            except Exception as e:
                log.error(f"Failed to render graph instance {instance.instance_id}: {e}", exc_info=True)
                # Create error placeholder
                ax = fig.add_subplot(
                    gs[
                        instance.row : instance.row + instance.rowspan,
                        instance.col : instance.col + instance.colspan,
                    ]
                )
                ax.text(
                    0.5,
                    0.5,
                    f"Error rendering graph:\n{str(e)[:100]}",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="#cc0000",
                )
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.axis("off")
                axes_map[instance.instance_id] = ax

        spec.layout._font_override = spec.font
        _render_panel_labels(spec.layout, axes_map)

        # Render annotations
        overlay_ax = _ensure_overlay_axes(fig)
        for annot in spec.annotations:
            try:
                create_annotation_artists(
                    fig,
                    axes_map,
                    annot,
                    figure_transform=overlay_ax.transAxes,
                    figure_axes=overlay_ax,
                )
            except Exception as e:
                log.warning(f"Failed to render annotation {annot.annotation_id}: {e}")

        return fig


def render_into_axes(
    ax: "Axes",
    spec: FigureSpec,
    trace_model_provider: TraceModelProvider,
    *,
    event_times: list[float] | None = None,
    event_labels: list[str] | None = None,
    event_colors: list[str] | None = None,
) -> dict[str, "Axes"]:
    """Render a FigureSpec into an existing axes (used for preview).

    The provided axes acts as the "page" container; graph panels are placed
    inside it using a nested GridSpec anchored to the axes' bounding box.

    Returns:
        Mapping of graph instance id -> axes created for that graph.
    """
    fig = ax.figure

    with mpl.rc_context(_rc_params(spec)):
        # Prepare the page container
        ax.set_facecolor("#ffffff")
        ax.set_box_aspect(max(spec.layout.height_in / max(spec.layout.width_in, 1e-6), 0.01))
        ax.set_xlim(0, spec.layout.width_in)
        ax.set_ylim(0, spec.layout.height_in)
        ax.axis("off")

        axes_map: dict[str, Axes] = {}

        if not spec.layout.graph_instances:
            ax.text(
                0.5,
                0.5,
                "No graphs to display",
                ha="center",
                va="center",
                fontsize=12,
                color="#666666",
            )
            return axes_map

        # Anchor a gridspec to the page axes bounding box (figure fractions)
        bbox = ax.get_position()
        gs = GridSpec(
            spec.layout.nrows,
            spec.layout.ncols,
            figure=fig,
            left=bbox.x0,
            right=bbox.x1,
            bottom=bbox.y0,
            top=bbox.y1,
            hspace=spec.layout.hspace,
            wspace=spec.layout.wspace,
        )

        for instance in spec.layout.graph_instances:
            try:
                graph_ax = _render_graph_instance(
                    fig,
                    gs,
                    instance,
                    spec.graphs,
                    spec.font,
                    spec.style,
                    trace_model_provider,
                    event_times,
                    event_labels,
                    event_colors,
                )
                axes_map[instance.instance_id] = graph_ax
            except Exception as exc:  # pragma: no cover - defensive for preview
                log.error("Preview render failed for %s: %s", instance.instance_id, exc, exc_info=True)

        spec.layout._font_override = spec.font
        _render_panel_labels(spec.layout, axes_map)

        return axes_map


def _render_graph_instance(
    fig: Figure,
    gs: GridSpec,
    instance: GraphInstance,
    graphs: dict[str, GraphSpec],
    font: "FontSpec",
    style: "StyleSpec",
    trace_model_provider: TraceModelProvider,
    event_times: list[float] | None,
    event_labels: list[str] | None,
    event_colors: list[str] | None,
) -> Axes:
    """Render a single graph instance into the GridSpec."""
    # Get the graph spec
    graph_spec = graphs.get(instance.graph_id)
    if graph_spec is None:
        raise ValueError(f"Graph {instance.graph_id} not found in spec")

    # Create axes for this graph
    ax = fig.add_subplot(
        gs[
            instance.row : instance.row + instance.rowspan,
            instance.col : instance.col + instance.colspan,
        ]
    )

    _populate_graph_axes(
        ax,
        graph_spec,
        font,
        style,
        trace_model_provider,
        event_times,
        event_labels,
        event_colors,
    )

    return ax


def _populate_graph_axes(
    ax: Axes,
    graph_spec: GraphSpec,
    font: "FontSpec",
    style: "StyleSpec",
    trace_model_provider: TraceModelProvider,
    event_times: list[float] | None,
    event_labels: list[str] | None,
    event_colors: list[str] | None,
) -> None:
    """Populate an existing axes with traces and styling."""
    # Get trace model
    try:
        trace_model = trace_model_provider(graph_spec.sample_id)
    except Exception as e:
        raise ValueError(f"Failed to get trace model for sample {graph_spec.sample_id}: {e}")

    default_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    if graph_spec.twin_y and len(graph_spec.trace_bindings) >= 2:
        primary_binding = graph_spec.trace_bindings[0]
        secondary_binding = graph_spec.trace_bindings[1]

        try:
            _plot_trace(ax, trace_model, primary_binding, graph_spec, style, 0, default_colors)
        except Exception as e:
            log.warning(f"Failed to plot trace {primary_binding.name}: {e}")

        _configure_axes(ax, graph_spec, font)

        ax2 = ax.twinx()
        try:
            _plot_trace(ax2, trace_model, secondary_binding, graph_spec, style, 1, default_colors)
        except Exception as e:
            log.warning(f"Failed to plot secondary trace {secondary_binding.name}: {e}")
        _configure_secondary_y(ax2, graph_spec, font)

        if event_times:
            _add_event_markers(
                ax,
                graph_spec,
                event_times,
                event_labels,
                event_colors,
                font,
            )

        if graph_spec.show_legend:
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            handles = h1 + h2
            labels = l1 + l2
            if handles:
                leg = ax.legend(handles, labels, loc=graph_spec.legend_loc, frameon=True, framealpha=0.9)
                if leg:
                    for text in leg.get_texts():
                        text.set_fontsize(font.legend.size)
                        text.set_fontweight(font.legend.weight)
                        text.set_fontstyle(font.legend.style)
    else:
        for idx, binding in enumerate(graph_spec.trace_bindings):
            try:
                _plot_trace(ax, trace_model, binding, graph_spec, style, idx, default_colors)
            except Exception as e:
                log.warning(f"Failed to plot trace {binding.name}: {e}")

        _configure_axes(ax, graph_spec, font)

        if event_times:
            _add_event_markers(
                ax,
                graph_spec,
                event_times,
                event_labels,
                event_colors,
                font,
            )

        if graph_spec.show_legend and graph_spec.trace_bindings:
            leg = ax.legend(loc=graph_spec.legend_loc, frameon=True, framealpha=0.9)
            if leg:
                for text in leg.get_texts():
                    text.set_fontsize(font.legend.size)
                    text.set_fontweight(font.legend.weight)
                    text.set_fontstyle(font.legend.style)


def _plot_trace(
    ax: Axes,
    trace_model: TraceModel,
    binding: Any,  # TraceBinding
    graph_spec: GraphSpec,
    style_spec: "StyleSpec",
    idx: int,
    default_colors: list[str],
) -> None:
    """Plot a single trace on the axes."""
    # Get data arrays based on trace kind
    time = trace_model.time_full
    if binding.kind == "inner":
        data = trace_model.inner_full
        default_label = "Inner Diameter"
    elif binding.kind == "outer":
        data = trace_model.outer_full
        if data is None:
            log.warning(f"Outer diameter not available for trace {binding.name}")
            return
        default_label = "Outer Diameter"
    elif binding.kind == "avg_pressure":
        data = trace_model.avg_pressure_full
        if data is None:
            log.warning(f"Average pressure not available for trace {binding.name}")
            return
        default_label = "Avg Pressure"
    elif binding.kind == "set_pressure":
        data = trace_model.set_pressure_full
        if data is None:
            log.warning(f"Set pressure not available for trace {binding.name}")
            return
        default_label = "Set Pressure"
    else:
        raise ValueError(f"Unknown trace kind: {binding.kind}")

    # Get style for this trace
    trace_style = graph_spec.trace_styles.get(binding.name, {})
    color = trace_style.get("color", default_colors[idx % len(default_colors)])
    linewidth = trace_style.get("linewidth", graph_spec.default_linewidth or style_spec.default_linewidth)
    linestyle = trace_style.get("linestyle", "-")
    marker = trace_style.get("marker", "")
    markersize = trace_style.get("markersize", 4)
    alpha = trace_style.get("alpha", 1.0)
    label = trace_style.get("label", default_label)

    # Plot the trace
    ax.plot(
        time,
        data,
        color=color,
        linewidth=linewidth,
        linestyle=linestyle,
        marker=marker,
        markersize=markersize,
        alpha=alpha,
        label=label,
    )


def _configure_axes(ax: Axes, graph_spec: GraphSpec, font: "FontSpec") -> None:
    """Configure axes appearance based on graph spec."""
    # Set labels
    ax.set_xlabel(graph_spec.x_label, fontsize=font.axis_title.size, fontweight=font.axis_title.weight, fontstyle=font.axis_title.style)
    ax.set_ylabel(graph_spec.y_label, fontsize=font.axis_title.size, fontweight=font.axis_title.weight, fontstyle=font.axis_title.style)

    # Set scales
    ax.set_xscale(graph_spec.x_scale)
    ax.set_yscale(graph_spec.y_scale)

    # Remove default padding so autoscale matches data extents
    ax.set_xmargin(0.0)
    ax.set_ymargin(0.02)

    # Set limits if specified
    if graph_spec.x_lim is not None:
        ax.set_xlim(graph_spec.x_lim)
    if graph_spec.y_lim is not None:
        ax.set_ylim(graph_spec.y_lim)

    # Grid
    if graph_spec.grid:
        ax.grid(True, alpha=0.3, linestyle="--", linewidth=0.5)

    # Spines
    for spine_name, visible in graph_spec.show_spines.items():
        if spine_name in ax.spines:
            ax.spines[spine_name].set_visible(visible)

    # Ticks
    if graph_spec.x_tick_interval is not None and graph_spec.x_scale == "linear":
        ax.xaxis.set_major_locator(MultipleLocator(graph_spec.x_tick_interval))
    elif graph_spec.x_max_ticks is not None:
        ax.xaxis.set_major_locator(MaxNLocator(graph_spec.x_max_ticks))

    if graph_spec.y_max_ticks is not None:
        ax.yaxis.set_major_locator(MaxNLocator(graph_spec.y_max_ticks))

    ax.tick_params(axis="x", labelsize=font.tick_label.size)
    ax.tick_params(axis="y", labelsize=font.tick_label.size)
    # Apply tick label weight/style
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontweight(font.tick_label.weight)
        lbl.set_fontstyle(font.tick_label.style)


def _configure_secondary_y(ax2: Axes, graph_spec: GraphSpec, font: "FontSpec") -> None:
    """Configure the secondary y axis for twin-Y plots."""
    if graph_spec.y2_label:
        ax2.set_ylabel(
            graph_spec.y2_label,
            fontsize=font.axis_title.size,
            fontweight=font.axis_title.weight,
            fontstyle=font.axis_title.style,
        )
    ax2.set_yscale(graph_spec.y2_scale)
    if graph_spec.y2_lim is not None:
        ax2.set_ylim(graph_spec.y2_lim)

    ax2.grid(False)
    if "right" in ax2.spines:
        ax2.spines["right"].set_visible(True)
    if "left" in ax2.spines:
        ax2.spines["left"].set_visible(False)

    ax2.tick_params(axis="y", labelsize=font.tick_label.size)
    for lbl in ax2.get_yticklabels():
        lbl.set_fontweight(font.tick_label.weight)
        lbl.set_fontstyle(font.tick_label.style)


def _add_event_markers(
    ax: Axes,
    graph_spec: GraphSpec,
    event_times: list[float],
    event_labels: list[str] | None,
    event_colors: list[str] | None,
    font: "FontSpec",
) -> None:
    """Add vertical lines for event markers."""
    if not graph_spec.show_event_markers:
        return

    # Phase 1 audit:
    # - Vertical events drawn with ax.axvline -> x/y in data coords, linewidth in points, dash style via linestyle (backend defaults).
    # - Labels use transform=ax.get_xaxis_transform() (x=data, y=axes fraction); WARNING: blended transform that could diverge across backends/DPI.
    # - clip_on not specified (uses Matplotlib default True).
    for i, event_time in enumerate(event_times):
        color = (
            event_colors[i]
            if event_colors and i < len(event_colors)
            else graph_spec.event_line_color
        )
        label = (
            event_labels[i]
            if graph_spec.show_event_labels and event_labels and i < len(event_labels)
            else None
        )

        ax.axvline(
            event_time,
            color=color,
            linestyle=graph_spec.event_line_style,
            linewidth=graph_spec.event_line_width,
            alpha=0.6,
            zorder=1,
        )

        # Add label at top if provided
        if label:
            ax.text(
                event_time,
                0.98,
                label,
                transform=ax.get_xaxis_transform(),
                rotation=graph_spec.event_label_rotation,
                va="top",
                ha="right",
                fontsize=getattr(getattr(font, "annotation", None), "size", getattr(font, "annotation_size", 8)),
                fontweight=getattr(getattr(font, "annotation", None), "weight", getattr(font, "weight", "normal")),
                fontstyle=getattr(getattr(font, "annotation", None), "style", getattr(font, "style", "normal")),
                color=color,
                alpha=0.8,
            )


def _panel_label_from_index(idx: int) -> str:
    """Return alphabetical panel label (A, B, ..., Z, AA, AB...)."""
    letters = string.ascii_uppercase
    label = ""
    n = idx
    while True:
        label = letters[n % 26] + label
        n = n // 26 - 1
        if n < 0:
            break
    return label


def _render_panel_labels(layout, axes_map: dict[str, Axes]) -> None:
    """Render panel labels if enabled."""
    label_spec: PanelLabelSpec | None = getattr(layout, "panel_labels", None)
    if label_spec is None or not label_spec.show:
        return
    font = getattr(getattr(layout, "_font_override", None), "panel_label", None)

    # Phase 1 audit:
    # - Panel labels use ax.transAxes (axes fraction) with fontsize/weight in points.
    # - No bbox; inherits default dash/clip settings.
    for idx, inst in enumerate(getattr(layout, "graph_instances", [])):
        ax = axes_map.get(inst.instance_id)
        if ax is None:
            continue
        label = _panel_label_from_index(idx)
        ax.text(
            label_spec.x_offset,
            label_spec.y_offset,
            label,
            transform=ax.transAxes,
            fontsize=font.size if font else label_spec.font_size,
            fontweight=font.weight if font else label_spec.weight,
            fontstyle=getattr(font, "style", "normal") if font else "normal",
            ha="left",
            va="baseline",
        )
