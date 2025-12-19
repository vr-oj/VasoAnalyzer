"""Developer smoke test for template+preset sizing determinism and exports.

Run to quickly validate sizing and produce preview images:
    python -m vasoanalyzer.ui.mpl_composer.dev_smoke_test_templates_presets
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

import numpy as np

from vasoanalyzer.ui.mpl_composer.renderer import (
    AxesSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)
from vasoanalyzer.ui.mpl_composer.templates import (
    get_template_preset,
    preset_dimensions_from_base,
)

log = logging.getLogger("dev_smoke_test")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _make_spec(template_id: str, preset: str) -> FigureSpec:
    preset_def = get_template_preset(template_id)
    page = PageSpec(
        width_in=float(preset_def.layout_defaults["width_in"]),
        height_in=float(preset_def.layout_defaults["height_in"]),
        dpi=300.0,
    )
    axes = AxesSpec()
    trace = TraceSpec(key="t", visible=True, color="#000000", linewidth=1.0, linestyle="-", marker="")
    spec = FigureSpec(page=page, axes=axes, traces=[trace], template_id=template_id)
    spec.size_mode = "preset"
    spec.size_preset = preset
    # Apply the same sizing math as the composer
    base_w, base_h = float(page.width_in), float(page.height_in)
    w, h = preset_dimensions_from_base(base_w, base_h, preset)
    spec.figure_width_in = w
    spec.figure_height_in = h
    page.width_in = w
    page.height_in = h
    return spec


def _render_and_export(spec: FigureSpec, out_path: Path) -> tuple[float, float]:
    ctx = RenderContext(is_preview=False, trace_model=None)
    fig = build_figure(spec, ctx)
    export_figure(spec, str(out_path), transparent=False, ctx=ctx, export_background="white")
    return fig.get_figwidth(), fig.get_figheight()


def _assert_deterministic(template_id: str, preset: str, tol: float = 1e-6) -> None:
    spec = _make_spec(template_id, preset)
    base_w = spec.figure_width_in
    base_h = spec.figure_height_in

    spec.size_preset = "square"
    base_w_sq, base_h_sq = preset_dimensions_from_base(
        get_template_preset(template_id).layout_defaults["width_in"],
        get_template_preset(template_id).layout_defaults["height_in"],
        "square",
    )
    spec.figure_width_in = base_w_sq
    spec.figure_height_in = base_h_sq
    spec.page.width_in = base_w_sq
    spec.page.height_in = base_h_sq

    spec.size_preset = preset
    base_w2, base_h2 = preset_dimensions_from_base(
        get_template_preset(template_id).layout_defaults["width_in"],
        get_template_preset(template_id).layout_defaults["height_in"],
        preset,
    )
    assert math.isclose(base_w, base_w2, rel_tol=0, abs_tol=tol)
    assert math.isclose(base_h, base_h2, rel_tol=0, abs_tol=tol)


def main() -> int:
    out_dir = Path("template_smoke_matrix")
    out_dir.mkdir(exist_ok=True)

    template_ids = ["single_column", "double_column", "slide"]
    presets = ["wide", "tall", "square"]

    for template_id in template_ids:
        for preset in presets:
            spec = _make_spec(template_id, preset)
            w, h = spec.figure_width_in, spec.figure_height_in
            margins = getattr(spec.page, "min_margin_in", None)
            log.info("template=%s preset=%s size=%.4fx%.4f in margin=%s", template_id, preset, w, h, margins)
            out_path = out_dir / f"{template_id}_{preset}.png"
            _render_and_export(spec, out_path)
            try:
                _assert_deterministic(template_id, preset)
            except AssertionError as exc:
                log.error("Determinism check failed for template=%s preset=%s: %s", template_id, preset, exc)
                return 1

    log.info("Smoke test finished; outputs in %s", out_dir.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
