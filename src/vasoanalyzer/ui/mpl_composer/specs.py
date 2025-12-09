"""Specification models for the Pure Matplotlib Figure Composer.

These dataclasses define the declarative structure of a figure:
- What data to plot (GraphSpec, TraceBinding)
- How to arrange panels (LayoutSpec, GraphInstance)
- What annotations to add (AnnotationSpec)
- How to export (ExportSpec)

The complete FigureSpec serves as the single source of truth for both
preview rendering and final export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "TraceBinding",
    "GraphSpec",
    "GraphInstance",
    "AnnotationSpec",
    "LayoutSpec",
    "ExportSpec",
    "FontSpec",
    "TextRoleFont",
    "StyleSpec",
    "PanelLabelSpec",
    "FigureSpec",
]


@dataclass
class TraceBinding:
    """Description of a data trace to plot in a graph.

    Attributes:
        name: Unique identifier for this trace within the graph
        kind: Type of trace data (diameter or pressure channel)
    """

    name: str
    kind: Literal["inner", "outer", "avg_pressure", "set_pressure"]


@dataclass
class GraphSpec:
    """Specification for a single graph (equivalent to Prism "graph page").

    Defines what data to plot and how to style it.

    Attributes:
        graph_id: Unique identifier for this graph
        name: Human-readable name
        sample_id: Reference to sample in VasoAnalyzer project
        trace_bindings: List of traces to plot
        x_label: X-axis label text
        y_label: Y-axis label text
        x_unit: X-axis unit (for display)
        y_unit: Y-axis unit (for display)
        x_scale: X-axis scale type
        y_scale: Y-axis scale type
        x_lim: X-axis limits (None = auto)
        y_lim: Y-axis limits (None = auto)
        grid: Whether to show grid
        show_spines: Which spines to show
        show_legend: Whether to show legend
        legend_loc: Legend location (matplotlib notation)
        trace_styles: Per-trace style overrides {trace_name: {prop: value}}
    """

    graph_id: str
    name: str
    sample_id: str
    trace_bindings: list[TraceBinding] = field(default_factory=list)

    # Axis configuration
    x_label: str = "Time (s)"
    y_label: str = "Diameter (µm)"
    x_unit: str = "s"
    y_unit: str = "µm"
    x_scale: Literal["linear", "log", "symlog"] = "linear"
    y_scale: Literal["linear", "log", "symlog"] = "linear"
    x_lim: tuple[float, float] | None = None
    y_lim: tuple[float, float] | None = None

    # Visual configuration
    grid: bool = True
    show_spines: dict[str, bool] = field(
        default_factory=lambda: {"top": False, "right": False, "bottom": True, "left": True}
    )
    show_event_markers: bool = True
    show_event_labels: bool = True
    event_line_color: str = "#888888"
    event_line_width: float = 1.0
    event_line_style: str = "--"
    event_label_rotation: float = 90.0

    # Legend
    show_legend: bool = True
    legend_loc: str = "upper right"

    # Tick configuration
    x_tick_interval: float | None = None
    x_max_ticks: int | None = None
    y_max_ticks: int | None = None

    # Dual Y axis
    twin_y: bool = False
    y2_label: str = ""
    y2_scale: Literal["linear", "log", "symlog"] = "linear"
    y2_lim: tuple[float, float] | None = None

    # Defaults
    default_linewidth: float = 1.5

    # Per-trace style overrides
    # Format: {trace_name: {"color": "#ff0000", "linewidth": 2.0, ...}}
    trace_styles: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class GraphInstance:
    """Placement of a GraphSpec in the layout grid.

    Attributes:
        instance_id: Unique identifier for this instance
        graph_id: Reference to GraphSpec to display
        row: Grid row index (0-based)
        col: Grid column index (0-based)
        rowspan: Number of rows to span
        colspan: Number of columns to span
    """

    instance_id: str
    graph_id: str
    row: int = 0
    col: int = 0
    rowspan: int = 1
    colspan: int = 1


@dataclass
class AnnotationSpec:
    """Specification for a figure annotation.

    Attributes:
        annotation_id: Unique identifier
        target_type: Whether annotation is on a graph or the whole figure
        target_id: ID of target graph instance (None for figure-level)
        kind: Type of annotation
        x0, y0: Start/anchor point coordinates
        x1, y1: End point coordinates (for box/arrow/line)
        coord_system: Coordinate system for positioning
        text_content: Text content (for text annotations)
        font_family: Font family name
        font_size: Font size in points
        font_weight: Font weight
        font_style: Font style (normal, italic, oblique)
        color: Text or line color
        ha: Horizontal alignment (for text)
        va: Vertical alignment (for text)
        rotation: Rotation angle in degrees (for text)
        edgecolor: Edge color (for box)
        facecolor: Face color (for box)
        alpha: Transparency (0-1)
        linewidth: Line width
        linestyle: Line style
        arrowstyle: Arrow style (for arrow)
    """

    annotation_id: str
    target_type: Literal["graph", "figure"] = "figure"
    target_id: str | None = None
    kind: Literal["text", "box", "arrow", "line"] = "text"

    # Geometry
    x0: float = 0.5
    y0: float = 0.5
    x1: float = 0.5
    y1: float = 0.5
    coord_system: Literal["data", "axes", "figure"] = "axes"

    # Text properties
    text_content: str = "Text"
    font_family: str = "sans-serif"
    font_size: float = 10.0
    font_weight: Literal["normal", "bold", "light"] = "normal"
    font_style: Literal["normal", "italic", "oblique"] = "normal"
    color: str = "#000000"
    ha: Literal["left", "center", "right"] = "left"
    va: Literal["bottom", "center", "top"] = "bottom"
    rotation: float = 0.0

    # Box/shape properties
    edgecolor: str = "#000000"
    facecolor: str = "none"
    alpha: float = 1.0
    linewidth: float = 1.0
    linestyle: Literal["solid", "dashed", "dotted", "dashdot"] = "solid"

    # Arrow properties
    arrowstyle: str = "->"


@dataclass
class PanelLabelSpec:
    """Configuration for panel labels (A, B, C...) in multi-panel layouts."""

    show: bool = False
    font_size: float = 9.0
    weight: Literal["normal", "bold"] = "bold"
    x_offset: float = -0.05
    y_offset: float = 1.02


@dataclass
class LayoutSpec:
    """Specification for figure layout and panel arrangement.

    Attributes:
        width_in: Figure width in inches
        height_in: Figure height in inches
        graph_instances: List of graph instances to place
        nrows: Number of grid rows
        ncols: Number of grid columns
        hspace: Vertical spacing between subplots (fraction)
        wspace: Horizontal spacing between subplots (fraction)
    """

    width_in: float = 5.9  # ~150 mm (single column + margin)
    height_in: float = 3.0  # aspect ratio ~0.5
    graph_instances: list[GraphInstance] = field(default_factory=list)
    nrows: int = 1
    ncols: int = 1
    hspace: float = 0.3
    wspace: float = 0.3
    panel_labels: PanelLabelSpec = field(default_factory=PanelLabelSpec)


@dataclass
class ExportSpec:
    """Specification for figure export settings.

    Attributes:
        format: Export file format
        dpi: Resolution for raster formats
        preset_name: Name of preset used (if any)
        transparent: Whether to use transparent background
    """

    format: Literal["pdf", "svg", "png", "tiff"] = "pdf"
    dpi: int = 600
    preset_name: str | None = None
    transparent: bool = False


@dataclass
class TextRoleFont:
    """Font settings for a specific text role."""

    size: float
    weight: Literal["normal", "bold"] = "normal"
    style: Literal["normal", "italic", "oblique"] = "normal"


@dataclass
class FontSpec:
    """Global font settings for the figure."""

    family: str = "Arial"

    figure_title: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=10.0, weight="bold")
    )
    panel_label: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=9.0, weight="bold")
    )
    axis_title: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=9.0, weight="bold")
    )
    tick_label: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=8.0, weight="normal")
    )
    legend: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=8.0, weight="normal")
    )
    annotation: TextRoleFont = field(
        default_factory=lambda: TextRoleFont(size=8.0, weight="normal")
    )

    base_size: float = 8.0


@dataclass
class StyleSpec:
    """Global style settings beyond fonts."""

    default_linewidth: float = 1.5
    axis_spine_width: float = 1.0
    tick_direction: Literal["in", "out", "inout"] = "out"
    tick_major_length: float = 3.5
    tick_minor_length: float = 2.0


@dataclass
class FigureSpec:
    """Complete specification of a figure.

    The single source of truth for both preview and export rendering.

    Attributes:
        graphs: Dictionary of graph specifications {graph_id: GraphSpec}
        layout: Layout specification
        annotations: List of annotations
        export: Export settings
        metadata: Additional metadata (creation time, author, etc.)
    """

    graphs: dict[str, GraphSpec] = field(default_factory=dict)
    layout: LayoutSpec = field(default_factory=LayoutSpec)
    annotations: list[AnnotationSpec] = field(default_factory=list)
    export: ExportSpec = field(default_factory=ExportSpec)
    font: FontSpec = field(default_factory=FontSpec)
    style: StyleSpec = field(default_factory=StyleSpec)
    metadata: dict[str, Any] = field(default_factory=dict)
