"""Dev-only smoke test for template sizing/export."""

from __future__ import annotations

import numpy as np
from pathlib import Path

from .renderer import (
    AxesSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)
from .templates import apply_template_preset


def _base_spec(template_id: str) -> FigureSpec:
    page = PageSpec(width_in=6.0, height_in=3.0, dpi=150.0, sizing_mode="axes_first")
    axes = AxesSpec(
        xlabel="Time (s)",
        ylabel="Signal",
        show_grid=True,
        show_event_markers=True,
        show_event_labels=True,
    )
    traces = [TraceSpec(key="inner", visible=True, color="#1f77b4", linewidth=1.5, linestyle="-", marker="")]
    events = []
    spec = FigureSpec(
        page=page,
        axes=axes,
        traces=traces,
        events=events,
        annotations=[],
        template_id=template_id,
        legend_visible=False,
    )
    apply_template_preset(spec, template_id, respect_overrides=False)
    return spec


def _series() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    x = np.linspace(0, 10, 200)
    y = np.sin(x)
    return {"inner": (x, y)}


if __name__ == "__main__":
    out_dir = Path("template_smoke_exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    series = _series()
    ctx = RenderContext(is_preview=False, series_map=series)
    for template_id in ("single_column", "double_column", "slide"):
        spec = _base_spec(template_id)
        # Build once to inspect margins/axes positioning.
        fig = build_figure(spec, ctx)
        ax = fig.axes[0]
        fig_w_in = fig.get_figwidth()
        fig_h_in = fig.get_figheight()
        pos = ax.get_position()
        margin_left_in = pos.x0 * fig_w_in
        margin_right_in = (1.0 - pos.x1) * fig_w_in
        margin_bottom_in = pos.y0 * fig_h_in
        margin_top_in = (1.0 - pos.y1) * fig_h_in
        print(
            f"{template_id}: size=({fig_w_in:.2f}in x {fig_h_in:.2f}in) "
            f"margins(in) L={margin_left_in:.3f} R={margin_right_in:.3f} "
            f"B={margin_bottom_in:.3f} T={margin_top_in:.3f} "
            f"fractions L={pos.x0:.3f} R={1-pos.x1:.3f} B={pos.y0:.3f} T={1-pos.y1:.3f}"
        )
        out_path = out_dir / f"{template_id}.png"
        export_figure(spec, str(out_path), transparent=False, ctx=ctx)
