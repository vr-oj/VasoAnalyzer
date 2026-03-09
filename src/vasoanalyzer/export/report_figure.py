"""Multi-panel experiment report figure for SciNote / lab notebook export.

Layout (landscape):
┌──────────────────────────────────────────────────────────┐
│  HEADER: Sample Name  |  Experiment  |  Date  |  Version │
├─────────────────────────────────┬────────────────────────┤
│  TRACES (stacked by visibility) │  TIFF SNAPSHOT FRAME   │
│  ── Inner Diameter              │  (representative       │
│  ── Outer Diameter              │   frame image)         │
│  ── Avg Pressure                │                        │
│  ── Set Pressure                │                        │
├─────────────────────────────────┴────────────────────────┤
│  EVENT TABLE (all rows, all columns)                     │
└──────────────────────────────────────────────────────────┘

If no snapshot is available, traces span the full width.
If no events are loaded, the table panel is omitted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

from utils.config import APP_VERSION
from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["render_report_figure"]

# Use non-interactive backend for export
matplotlib.use("Agg")

# ── Trace definitions ────────────────────────────────────────────────────────
# Each entry: (key, label, color, unit, window_attr)
_TRACE_DEFS: list[tuple[str, str, str, str, str]] = [
    ("inner", "Inner Diameter", "#1a1a1a", "µm", "inner_mean"),
    ("outer", "Outer Diameter", "#E07020", "µm", "outer_mean"),
    ("avg_pressure", "Avg Pressure", "#2563EB", "mmHg", "avg_pressure_mean"),
    ("set_pressure", "Set Pressure", "#7C3AED", "mmHg", "set_pressure_mean"),
]

# Map trace keys to the event table columns they correspond to
_TRACE_KEY_TO_TABLE_COLS: dict[str, list[str]] = {
    "inner": ["ID (µm)"],
    "outer": ["OD (µm)"],
    "avg_pressure": ["Avg P (mmHg)", "Avg P"],
    "set_pressure": ["Set P (mmHg)", "Set P"],
}

# Column mapping for event table display
_COL_MAP: dict[str, str] = {
    "Event": "Event",
    "event": "Event",
    "#": "#",
    "Time (s)": "Time (s)",
    "time": "Time (s)",
    "ID (µm)": "ID (µm)",
    "id": "ID (µm)",
    "Inner Diameter": "ID (µm)",
    "OD (µm)": "OD (µm)",
    "od": "OD (µm)",
    "Outer Diameter": "OD (µm)",
    "Avg P (mmHg)": "Avg P",
    "avg_pressure": "Avg P",
    "Set P (mmHg)": "Set P",
    "set_pressure": "Set P",
}


# ── Public API ───────────────────────────────────────────────────────────────

def render_report_figure(
    trace_model: TraceModel | None,
    xlim: tuple[float, float],
    visible_traces: list[str] | None = None,
    events_df: pd.DataFrame | None = None,
    event_times: list[float] | None = None,
    event_labels: list[str] | None = None,
    snapshot_image: np.ndarray | None = None,
    metadata: dict[str, str] | None = None,
    figsize: tuple[float, float] = (11.0, 8.5),
    dpi: int = 300,
    include_frame: bool = True,
    include_table: bool = True,
) -> Figure:
    """Create a composite landscape report figure.

    Args:
        trace_model: TraceModel with full trace data.
        xlim: Time range to render (x0, x1).
        visible_traces: Which traces to show (e.g. ["inner", "outer"]).
            Defaults to all available.
        events_df: DataFrame with event data for the table panel.
        event_times: Event times for vertical markers on traces.
        event_labels: Labels for event markers.
        snapshot_image: 2-D numpy array (grayscale) or 3-D (H, W, C) for the
            TIFF frame panel. Pass None to skip.
        metadata: Dict with keys like sample_name, experiment, date.
        figsize: Figure size in inches (width, height).
        dpi: Output resolution.
        include_frame: Whether to include the snapshot panel.
        include_table: Whether to include the event table panel.

    Returns:
        Matplotlib Figure ready for saving.
    """
    meta = metadata or {}

    # Force light-mode rendering regardless of system/app theme
    import matplotlib as _mpl
    _saved_rcParams = _mpl.rcParams.copy()
    _mpl.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#333333",
        "axes.labelcolor": "black",
        "text.color": "black",
        "xtick.color": "black",
        "ytick.color": "black",
        "grid.color": "#CCCCCC",
        "legend.facecolor": "white",
        "legend.edgecolor": "#CCCCCC",
    })

    try:
        return _render_figure_impl(
            trace_model, xlim, visible_traces, events_df,
            event_times, event_labels, snapshot_image,
            meta, figsize, dpi, include_frame, include_table,
        )
    finally:
        _mpl.rcParams.update(_saved_rcParams)


def _render_figure_impl(
    trace_model, xlim, visible_traces, events_df,
    event_times, event_labels, snapshot_image,
    meta, figsize, dpi, include_frame, include_table,
) -> Figure:
    """Internal: render with light-mode rcParams already set."""
    fig = Figure(figsize=figsize, dpi=dpi, facecolor="white", edgecolor="none")

    # Determine which optional panels are present
    has_frame = include_frame and snapshot_image is not None
    has_table = include_table and events_df is not None and len(events_df) > 0

    # Resolve visible traces
    if visible_traces is None:
        visible_traces = _auto_detect_traces(trace_model)

    # ── Build layout ─────────────────────────────────────────────────────
    # Row heights: header (small) | traces (large) | table (scaled to row count)
    row_ratios = [0.06]  # header
    if has_table:
        n_event_rows = len(events_df) + 1  # +1 for header
        # Give table more space for more rows, but cap it
        table_ratio = min(0.55, max(0.30, n_event_rows * 0.022))
        trace_ratio = 0.94 - table_ratio
        row_ratios.append(trace_ratio)
        row_ratios.append(table_ratio)
    else:
        row_ratios.append(0.94)
    n_rows = len(row_ratios)

    # Column widths: traces | frame (optional)
    col_ratios = [0.65, 0.35] if has_frame else [1.0]
    n_cols = len(col_ratios)

    gs = GridSpec(
        n_rows, n_cols,
        figure=fig,
        height_ratios=row_ratios,
        width_ratios=col_ratios,
        hspace=0.25,
        wspace=0.08,
        left=0.06, right=0.96, top=0.96, bottom=0.08,
    )

    # ── Header (spans full width) ────────────────────────────────────────
    ax_header = fig.add_subplot(gs[0, :])
    _render_header(ax_header, meta)

    # ── Trace panel ──────────────────────────────────────────────────────
    ax_trace = fig.add_subplot(gs[1, 0])
    _render_traces(ax_trace, trace_model, xlim, visible_traces,
                   event_times, event_labels)

    # ── Snapshot frame panel ─────────────────────────────────────────────
    if has_frame:
        ax_frame = fig.add_subplot(gs[1, 1])
        _render_snapshot(ax_frame, snapshot_image)

    # ── Event table (spans full width) ───────────────────────────────────
    if has_table:
        ax_table = fig.add_subplot(gs[2, :])
        _render_event_table(ax_table, events_df, visible_traces)

    return fig


# ── Helper: auto-detect available traces ─────────────────────────────────────

def _auto_detect_traces(model: TraceModel | None) -> list[str]:
    """Return list of trace keys that have data in the model."""
    if model is None:
        return []
    available = ["inner"]  # always present
    if model.outer_full is not None:
        available.append("outer")
    if model.avg_pressure_full is not None:
        available.append("avg_pressure")
    if model.set_pressure_full is not None:
        available.append("set_pressure")
    return available


# ── Render: header ───────────────────────────────────────────────────────────

def _render_header(ax, meta: dict[str, str]) -> None:
    """Render the header bar with metadata."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    sample_name = meta.get("sample_name", "Untitled Sample")
    experiment = meta.get("experiment", "")
    date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d"))

    ax.set_facecolor("white")
    ax.text(
        0.0, 0.70, sample_name,
        fontsize=14, fontweight="bold", va="center", color="black",
        transform=ax.transAxes,
    )

    subtitle_parts = []
    if experiment:
        subtitle_parts.append(experiment)
    subtitle_parts.append(date_str)
    subtitle_parts.append(f"VasoAnalyzer {APP_VERSION}")
    ax.text(
        0.0, 0.20, "  |  ".join(subtitle_parts),
        fontsize=9, color="#666666", va="center",
        transform=ax.transAxes,
    )

    ax.axhline(y=0.0, xmin=0, xmax=1, color="#CCCCCC", linewidth=1.0)


# ── Render: stacked traces ──────────────────────────────────────────────────

def _render_traces(
    ax,
    model: TraceModel | None,
    xlim: tuple[float, float],
    visible_traces: list[str],
    event_times: list[float] | None,
    event_labels: list[str] | None,
) -> None:
    """Render stacked trace lines on a single axes with secondary Y-axes."""
    ax.set_facecolor("white")
    if model is None:
        ax.text(0.5, 0.5, "No trace data", ha="center", va="center",
                fontsize=12, color="black")
        ax.set_frame_on(False)
        return

    x0, x1 = xlim
    pixel_width = 2000
    level_idx = model.best_level_for_window(x0, x1, pixel_width)
    window = model.window(level_idx, x0, x1)

    time_arr = window.time
    if time_arr.size == 0:
        ax.text(0.5, 0.5, "No data in view range", ha="center", va="center")
        return

    # Separate diameter traces (left Y) from pressure traces (right Y)
    diam_traces = [t for t in visible_traces if t in ("inner", "outer")]
    pres_traces = [t for t in visible_traces if t in ("avg_pressure", "set_pressure")]

    all_lines = []
    all_labels = []

    # Plot diameter traces on primary axis
    for key in diam_traces:
        defn = _trace_def(key)
        if defn is None:
            continue
        data = getattr(window, defn[4], None)
        if data is None:
            continue
        lw = 1.2 if key == "inner" else 1.0
        line, = ax.plot(time_arr, data, color=defn[2], linewidth=lw, label=defn[1])
        all_lines.append(line)
        all_labels.append(defn[1])

    if diam_traces:
        units = "µm"
        if len(diam_traces) == 1:
            defn = _trace_def(diam_traces[0])
            ax.set_ylabel(f"{defn[1]} ({units})" if defn else f"Diameter ({units})",
                          fontsize=9)
        else:
            ax.set_ylabel(f"Diameter ({units})", fontsize=9)

    # Plot pressure traces on secondary axis
    ax2 = None
    if pres_traces:
        ax2 = ax.twinx()
        for key in pres_traces:
            defn = _trace_def(key)
            if defn is None:
                continue
            data = getattr(window, defn[4], None)
            if data is None:
                continue
            line, = ax2.plot(time_arr, data, color=defn[2], linewidth=1.0, label=defn[1])
            all_lines.append(line)
            all_labels.append(defn[1])

        if len(pres_traces) == 1:
            defn = _trace_def(pres_traces[0])
            ax2.set_ylabel(f"{defn[1]} (mmHg)" if defn else "Pressure (mmHg)",
                           fontsize=9, color=defn[2] if defn else "#333")
            ax2.tick_params(axis="y", labelcolor=defn[2] if defn else "#333", labelsize=8)
        else:
            ax2.set_ylabel("Pressure (mmHg)", fontsize=9)
            ax2.tick_params(axis="y", labelsize=8)

    # Event markers
    if event_times:
        for i, evt_time in enumerate(event_times):
            if x0 <= evt_time <= x1:
                ax.axvline(evt_time, color="#888888", linestyle="--",
                           linewidth=0.8, alpha=0.6)
                if event_labels and i < len(event_labels):
                    ylim = ax.get_ylim()
                    ax.text(
                        evt_time, ylim[1], f" {event_labels[i]}",
                        rotation=90, va="top", fontsize=6.5,
                        color="#888888", alpha=0.85,
                    )

    ax.set_xlabel("Time (s)", fontsize=9, color="black")
    ax.set_xlim(x0, x1)
    ax.tick_params(labelsize=8, colors="black")
    ax.set_facecolor("white")
    for spine in ax.spines.values():
        spine.set_color("#333333")
    ax.grid(True, alpha=0.2, color="#CCCCCC")

    if ax2 is not None:
        for spine in ax2.spines.values():
            spine.set_color("#333333")

    if all_lines:
        legend = ax.legend(all_lines, all_labels, loc="upper right", fontsize=7,
                           framealpha=0.9, facecolor="white", edgecolor="#CCCCCC")
        for text in legend.get_texts():
            text.set_color("black")


# ── Render: snapshot frame ───────────────────────────────────────────────────

def _render_snapshot(ax, image: np.ndarray) -> None:
    """Render a representative TIFF frame."""
    ax.axis("off")
    ax.set_facecolor("white")

    cmap = "gray" if image.ndim == 2 else None
    ax.imshow(image, cmap=cmap, aspect="equal", interpolation="bilinear")
    ax.set_title("Snapshot", fontsize=9, pad=4, color="black")


# ── Render: event table ─────────────────────────────────────────────────────

def _render_event_table(
    ax,
    events_df: pd.DataFrame,
    visible_traces: list[str] | None = None,
) -> None:
    """Render the full event summary table, filtering columns to match visible traces."""
    ax.axis("off")
    ax.set_facecolor("white")

    # Determine which table columns to hide based on invisible traces
    hidden_cols: set[str] = set()
    if visible_traces is not None:
        for trace_key, table_cols in _TRACE_KEY_TO_TABLE_COLS.items():
            if trace_key not in visible_traces:
                hidden_cols.update(table_cols)

    # Build display data with clean column names
    display_data: dict[str, list[str]] = {}
    for col in events_df.columns:
        mapped = _COL_MAP.get(col)
        if mapped and mapped not in display_data and mapped not in hidden_cols:
            formatted = []
            for v in events_df[col].tolist():
                if isinstance(v, float) and not np.isnan(v):
                    formatted.append(f"{v:.2f}")
                elif isinstance(v, (int, np.integer)):
                    formatted.append(str(v))
                else:
                    formatted.append(str(v) if v is not None else "")
            display_data[mapped] = formatted

    if not display_data:
        ax.text(0.5, 0.5, "No event data", ha="center", va="center", fontsize=10)
        return

    n_rows = len(next(iter(display_data.values())))
    col_labels = list(display_data.keys())
    cell_text = [[display_data[col][r] for col in col_labels] for r in range(n_rows)]

    # Scale font and row height based on row count to fit the allocated space
    total_rows = n_rows + 1  # +1 for header row
    if total_rows <= 15:
        font_size = 8.0
    elif total_rows <= 30:
        font_size = 7.0
    else:
        font_size = 6.0

    # Calculate row scale to fit within the axes height
    # Default cell height in axes coords is ~1/total_rows; scale to fill ~90% of axes
    row_scale = max(0.9, min(1.3, 12.0 / total_rows))

    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        loc="upper center",
        cellLoc="center",
    )
    table.set_clip_on(True)

    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    table.scale(1.0, row_scale)

    # Header style
    for j in range(len(col_labels)):
        cell = table[0, j]
        cell.set_facecolor("#2563EB")
        cell.set_text_props(color="white", fontweight="bold", fontsize=font_size + 0.5)
        cell.set_edgecolor("#1E40AF")

    # Alternate row colors — explicit black text for readability
    for i in range(1, len(cell_text) + 1):
        for j in range(len(col_labels)):
            cell = table[i, j]
            cell.set_facecolor("#F0F4FF" if i % 2 == 0 else "white")
            cell.set_edgecolor("#E5E7EB")
            cell.set_text_props(color="black")

    table.auto_set_column_width(list(range(len(col_labels))))


# ── Utilities ────────────────────────────────────────────────────────────────

def _trace_def(key: str) -> tuple[str, str, str, str, str] | None:
    """Look up trace definition by key."""
    for defn in _TRACE_DEFS:
        if defn[0] == key:
            return defn
    return None
