"""Test harness for the Pure Matplotlib Figure Composer renderer.

This script creates a simple FigureSpec with dummy data and validates
that the rendering pipeline works correctly.

Usage:
    python -m vasoanalyzer.ui.mpl_composer.test_renderer
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from vasoanalyzer.core.trace_model import TraceModel

from .renderer import render_figure
from .specs import (
    AnnotationSpec,
    ExportSpec,
    FigureSpec,
    GraphInstance,
    GraphSpec,
    LayoutSpec,
    TraceBinding,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def create_dummy_trace_model(sample_id: str = "test_sample") -> TraceModel:
    """Create a dummy TraceModel for testing."""
    # Generate synthetic vessel data
    time = np.linspace(0, 60, 600)  # 60 seconds, 10 Hz
    inner = 100 + 10 * np.sin(2 * np.pi * 0.1 * time) + np.random.normal(0, 1, len(time))
    outer = 120 + 10 * np.sin(2 * np.pi * 0.1 * time) + np.random.normal(0, 1, len(time))
    avg_pressure = 80 + 20 * np.sin(2 * np.pi * 0.05 * time) + np.random.normal(0, 2, len(time))
    set_pressure = 100 + 0 * time  # Constant set pressure

    return TraceModel(
        time=time,
        inner=inner,
        outer=outer,
        avg_pressure=avg_pressure,
        set_pressure=set_pressure,
    )


def test_single_panel_render():
    """Test rendering a single-panel figure."""
    log.info("Testing single-panel figure rendering...")

    # Create a simple trace model provider
    trace_model = create_dummy_trace_model("test_sample")

    def provider(sample_id: str) -> TraceModel:
        return trace_model

    # Create specs
    graph_spec = GraphSpec(
        graph_id="graph1",
        name="Test Graph",
        sample_id="test_sample",
        trace_bindings=[
            TraceBinding(name="inner", kind="inner"),
            TraceBinding(name="outer", kind="outer"),
        ],
        x_label="Time (s)",
        y_label="Diameter (µm)",
        grid=True,
    )

    graph_instance = GraphInstance(
        instance_id="inst1",
        graph_id="graph1",
        row=0,
        col=0,
    )

    layout_spec = LayoutSpec(
        width_in=5.9,  # ~150 mm
        height_in=3.0,
        graph_instances=[graph_instance],
        nrows=1,
        ncols=1,
    )

    export_spec = ExportSpec(
        format="pdf",
        dpi=600,
    )

    figure_spec = FigureSpec(
        graphs={"graph1": graph_spec},
        layout=layout_spec,
        export=export_spec,
    )

    # Render at preview DPI
    fig = render_figure(
        figure_spec,
        provider,
        dpi=100,
        event_times=[10.0, 30.0, 50.0],
        event_labels=["Start", "Peak", "End"],
        event_colors=["#00aa00", "#ff0000", "#0000ff"],
    )

    # Save preview
    output_path = Path("test_output_preview.png")
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    log.info(f"Preview saved to {output_path}")

    # Render at export DPI
    fig_export = render_figure(
        figure_spec,
        provider,
        dpi=600,
    )

    # Save export
    output_path_pdf = Path("test_output_export.pdf")
    fig_export.savefig(output_path_pdf, format="pdf", bbox_inches="tight")
    log.info(f"Export saved to {output_path_pdf}")

    plt.close(fig)
    plt.close(fig_export)

    log.info("✓ Single-panel rendering test passed")


def test_multi_panel_render():
    """Test rendering a multi-panel figure."""
    log.info("Testing multi-panel figure rendering...")

    # Create a trace model provider
    trace_model = create_dummy_trace_model("test_sample")

    def provider(sample_id: str) -> TraceModel:
        return trace_model

    # Create two different graph specs
    graph_spec1 = GraphSpec(
        graph_id="graph1",
        name="Diameter",
        sample_id="test_sample",
        trace_bindings=[
            TraceBinding(name="inner", kind="inner"),
            TraceBinding(name="outer", kind="outer"),
        ],
        x_label="Time (s)",
        y_label="Diameter (µm)",
    )

    graph_spec2 = GraphSpec(
        graph_id="graph2",
        name="Pressure",
        sample_id="test_sample",
        trace_bindings=[
            TraceBinding(name="avg_pressure", kind="avg_pressure"),
            TraceBinding(name="set_pressure", kind="set_pressure"),
        ],
        x_label="Time (s)",
        y_label="Pressure (mmHg)",
    )

    # Create layout with 2 rows
    graph_instances = [
        GraphInstance(instance_id="inst1", graph_id="graph1", row=0, col=0),
        GraphInstance(instance_id="inst2", graph_id="graph2", row=1, col=0),
    ]

    layout_spec = LayoutSpec(
        width_in=5.9,
        height_in=6.0,  # Taller for 2 panels
        graph_instances=graph_instances,
        nrows=2,
        ncols=1,
        hspace=0.4,
    )

    figure_spec = FigureSpec(
        graphs={"graph1": graph_spec1, "graph2": graph_spec2},
        layout=layout_spec,
    )

    # Render and save
    fig = render_figure(figure_spec, provider, dpi=100)
    output_path = Path("test_output_multipanel.png")
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    log.info(f"Multi-panel figure saved to {output_path}")

    plt.close(fig)
    log.info("✓ Multi-panel rendering test passed")


def test_annotations():
    """Test rendering with annotations."""
    log.info("Testing annotations...")

    trace_model = create_dummy_trace_model("test_sample")

    def provider(sample_id: str) -> TraceModel:
        return trace_model

    graph_spec = GraphSpec(
        graph_id="graph1",
        name="Test Graph",
        sample_id="test_sample",
        trace_bindings=[TraceBinding(name="inner", kind="inner")],
    )

    graph_instance = GraphInstance(instance_id="inst1", graph_id="graph1", row=0, col=0)

    # Create annotations
    annotations = [
        # Text annotation in axes coordinates
        AnnotationSpec(
            annotation_id="text1",
            kind="text",
            target_type="graph",
            target_id="inst1",
            coord_system="axes",
            x0=0.5,
            y0=0.9,
            text_content="Test Annotation",
            font_size=12,
            ha="center",
            va="top",
        ),
        # Box annotation in data coordinates
        AnnotationSpec(
            annotation_id="box1",
            kind="box",
            target_type="graph",
            target_id="inst1",
            coord_system="data",
            x0=10.0,
            y0=95.0,
            x1=20.0,
            y1=105.0,
            edgecolor="#ff0000",
            facecolor="none",
            linewidth=2.0,
        ),
        # Arrow annotation
        AnnotationSpec(
            annotation_id="arrow1",
            kind="arrow",
            target_type="graph",
            target_id="inst1",
            coord_system="data",
            x0=30.0,
            y0=110.0,
            x1=35.0,
            y1=105.0,
            color="#0000ff",
            linewidth=2.0,
            arrowstyle="->",
        ),
    ]

    layout_spec = LayoutSpec(
        width_in=5.9,
        height_in=3.0,
        graph_instances=[graph_instance],
        nrows=1,
        ncols=1,
    )

    figure_spec = FigureSpec(
        graphs={"graph1": graph_spec},
        layout=layout_spec,
        annotations=annotations,
    )

    # Render and save
    fig = render_figure(figure_spec, provider, dpi=100)
    output_path = Path("test_output_annotations.png")
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    log.info(f"Annotated figure saved to {output_path}")

    plt.close(fig)
    log.info("✓ Annotation rendering test passed")


def main():
    """Run all tests."""
    log.info("=" * 60)
    log.info("Pure Matplotlib Figure Composer - Renderer Tests")
    log.info("=" * 60)

    test_single_panel_render()
    test_multi_panel_render()
    test_annotations()

    log.info("=" * 60)
    log.info("All tests passed! ✓")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
