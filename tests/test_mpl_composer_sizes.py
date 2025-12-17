import pytest

from vasoanalyzer.ui.mpl_composer.renderer import (
    AxesSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
)
from vasoanalyzer.ui.mpl_composer.spec_serialization import (
    figure_spec_from_dict,
    figure_spec_to_dict,
)
from vasoanalyzer.ui.mpl_composer.templates import apply_template_preset, get_template_preset


def _base_spec(template_id: str = "single_column") -> FigureSpec:
    page = PageSpec(width_in=3.0, height_in=2.0, dpi=300.0)
    axes = AxesSpec()
    trace = TraceSpec(key="t", visible=True, color="#000000", linewidth=1.0, linestyle="-", marker="")
    return FigureSpec(page=page, axes=axes, traces=[trace], template_id=template_id)


def test_template_mode_tracks_template_size():
    spec = _base_spec("single_column")
    apply_template_preset(spec, "single_column", respect_overrides=False)
    spec.size_mode = "template"
    spec.figure_width_in = 1.0
    spec.figure_height_in = 1.0

    apply_template_preset(spec, "double_column", respect_overrides=True)
    preset = get_template_preset("double_column").layout_defaults

    assert spec.page.width_in == pytest.approx(preset["width_in"])
    assert spec.page.height_in == pytest.approx(preset["height_in"])
    assert spec.figure_width_in == pytest.approx(preset["width_in"])
    assert spec.figure_height_in == pytest.approx(preset["height_in"])


def test_preset_size_survives_template_switch():
    spec = _base_spec("single_column")
    apply_template_preset(spec, "single_column", respect_overrides=False)
    base = get_template_preset("single_column").layout_defaults
    spec.size_mode = "preset"
    spec.size_preset = "wide"
    spec.figure_width_in = base["width_in"] * 1.25
    spec.figure_height_in = base["height_in"]
    spec.page.width_in = spec.figure_width_in
    spec.page.height_in = spec.figure_height_in

    apply_template_preset(spec, "double_column", respect_overrides=True)

    assert spec.page.width_in == pytest.approx(base["width_in"] * 1.25)
    assert spec.page.height_in == pytest.approx(base["height_in"])


def test_renderer_respects_figure_size_override_and_serialization():
    spec = _base_spec()
    spec.figure_width_in = 6.0
    spec.figure_height_in = 2.5
    spec.page.width_in = 3.0
    spec.page.height_in = 1.5
    spec.size_mode = "custom"

    ctx = RenderContext(is_preview=True, trace_model=None)
    fig = build_figure(spec, ctx)
    assert spec.page.axes_width_in == pytest.approx(6.0)
    assert spec.page.axes_height_in == pytest.approx(2.5)
    assert fig.get_figwidth() >= spec.figure_width_in
    assert fig.get_figheight() >= spec.figure_height_in

    dumped = figure_spec_to_dict(spec)
    restored = figure_spec_from_dict(dumped)
    assert restored.figure_width_in == pytest.approx(6.0)
    assert restored.figure_height_in == pytest.approx(2.5)
    assert restored.size_mode == "custom"
