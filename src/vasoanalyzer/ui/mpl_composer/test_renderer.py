"""Smoke tests for the single-axes Matplotlib renderer."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from vasoanalyzer.core.trace_model import TraceModel

from .renderer import (
    AxesSpec,
    EventSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def create_dummy_trace_model(sample_id: str = "test_sample") -> TraceModel:
    """Create a dummy TraceModel for testing."""
    time = np.linspace(0, 10, 200)
    inner = 50 + 5 * np.sin(2 * np.pi * 0.2 * time)
    outer = 60 + 5 * np.cos(2 * np.pi * 0.1 * time)
    avg_pressure = 80 + 10 * np.sin(2 * np.pi * 0.05 * time)
    set_pressure = 90 + 0 * time

    return TraceModel(
        time=time,
        inner=inner,
        outer=outer,
        avg_pressure=avg_pressure,
        set_pressure=set_pressure,
    )


def _build_default_spec() -> FigureSpec:
    page = PageSpec(
        width_in=6.0,
        height_in=3.0,
        dpi=150.0,
        sizing_mode="axes_first",
        min_margin_in=0.5,
    )
    axes = AxesSpec(
        x_range=None,
        y_range=None,
        xlabel="Time (s)",
        ylabel="Diameter (µm)",
        show_grid=True,
        grid_linestyle="--",
        grid_color="#c0c0c0",
        grid_alpha=0.7,
        show_event_labels=False,
    )
    traces = [
        TraceSpec(key="inner", visible=True, color="#1f77b4", linewidth=1.5, linestyle="-", marker=""),
        TraceSpec(key="outer", visible=True, color="#ff7f0e", linewidth=1.2, linestyle="-", marker=""),
    ]
    events = [
        EventSpec(visible=True, time_s=2.0, color="#444444", linewidth=1.0, linestyle="--", label="Start", label_above=True),
        EventSpec(visible=True, time_s=8.0, color="#444444", linewidth=1.0, linestyle="--", label="End", label_above=False),
    ]
    return FigureSpec(
        page=page,
        axes=axes,
        traces=traces,
        events=events,
        annotations=[],
        legend_visible=True,
        legend_fontsize=8.0,
        legend_loc="upper right",
    )


def test_build_and_save(tmp_path):
    trace_model = create_dummy_trace_model()
    spec = _build_default_spec()
    ctx = RenderContext(is_preview=True, trace_model=trace_model)

    fig = build_figure(spec, ctx)
    out = Path(tmp_path) / "preview.png"
    fig.savefig(out, dpi=spec.page.dpi)
    assert out.exists()
    log.info("Preview saved to %s", out)


def test_export_helper(tmp_path):
    trace_model = create_dummy_trace_model()
    spec = _build_default_spec()
    out = Path(tmp_path) / "export.png"
    ctx = RenderContext(is_preview=False, trace_model=trace_model)
    export_figure(spec, out, transparent=False, ctx=ctx)
    assert out.exists()
    log.info("Export saved to %s", out)
