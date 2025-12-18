import pytest

from vasoanalyzer.ui.mpl_composer.renderer import (
    AxesSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    validate_required_visibility,
)
from vasoanalyzer.ui.mpl_composer.spec_serialization import (
    figure_spec_from_dict,
    figure_spec_to_dict,
)
from vasoanalyzer.ui.mpl_composer.templates import (
    apply_template_preset,
    get_template_preset,
    preset_dimensions_from_base,
)


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
    # Preset sizes recompute from the active template defaults; verify deterministic mapping.
    spec = _base_spec("single_column")
    apply_template_preset(spec, "single_column", respect_overrides=False)
    spec.size_mode = "preset"
    spec.size_preset = "wide"
    sc_w, sc_h = _apply_size_like_composer(spec)

    spec.template_id = "double_column"
    apply_template_preset(spec, "double_column", respect_overrides=True)
    base_dc = get_template_preset("double_column").layout_defaults
    dc_w, dc_h = preset_dimensions_from_base(base_dc["width_in"], base_dc["height_in"], "wide")
    _apply_size_like_composer(spec)

    assert spec.page.width_in == pytest.approx(dc_w)
    assert spec.page.height_in == pytest.approx(dc_h)


def test_renderer_respects_figure_size_override_and_serialization():
    spec = _base_spec()
    spec.figure_width_in = 6.0
    spec.figure_height_in = 2.5
    spec.page.width_in = 3.0
    spec.page.height_in = 1.5
    spec.size_mode = "custom"
    spec.page.sizing_mode = "axes_first"

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


def test_preset_aspect_preserves_area_and_direction():
    preset = get_template_preset("single_column").layout_defaults
    base_w = preset["width_in"]
    base_h = preset["height_in"]

    wide_w, wide_h = preset_dimensions_from_base(base_w, base_h, "wide")
    tall_w, tall_h = preset_dimensions_from_base(base_w, base_h, "tall")
    square_w, square_h = preset_dimensions_from_base(base_w, base_h, "square")

    assert wide_w > base_w
    assert wide_h < base_h
    assert tall_w < base_w
    assert tall_h > base_h
    assert square_w == pytest.approx(square_h)
    base_area = base_w * base_h
    assert pytest.approx(base_area) == pytest.approx(wide_w * wide_h)
    assert pytest.approx(base_area) == pytest.approx(tall_w * tall_h)
    assert pytest.approx(base_area) == pytest.approx(square_w * square_h)


def _apply_size_like_composer(spec: FigureSpec) -> tuple[float, float]:
    base = get_template_preset(spec.template_id).layout_defaults
    base_w, base_h = float(base["width_in"]), float(base["height_in"])
    mode = getattr(spec, "size_mode", "template")
    preset = getattr(spec, "size_preset", None) or "wide"
    if mode == "template":
        w, h = base_w, base_h
    elif mode == "preset":
        w, h = preset_dimensions_from_base(base_w, base_h, preset)
    else:
        w = getattr(spec, "figure_width_in", None) or base_w
        h = getattr(spec, "figure_height_in", None) or base_h
    if hasattr(spec.page, "sizing_mode"):
        spec.page.sizing_mode = "figure_first"
    if hasattr(spec.page, "axes_first"):
        spec.page.axes_first = False
    for attr in ("axes_width_in", "axes_height_in", "effective_width_in", "effective_height_in"):
        if hasattr(spec.page, attr):
            setattr(spec.page, attr, None)
    spec.figure_width_in = w
    spec.figure_height_in = h
    spec.page.width_in = w
    spec.page.height_in = h
    return w, h


def test_preset_cycle_deterministic():
    spec = _base_spec("single_column")
    apply_template_preset(spec, "single_column", respect_overrides=False)
    spec.size_mode = "preset"
    spec.size_preset = "wide"
    w1, h1 = _apply_size_like_composer(spec)
    assert getattr(spec.page, "sizing_mode", None) == "figure_first"

    spec.size_preset = "square"
    _apply_size_like_composer(spec)
    spec.size_preset = "wide"
    w2, h2 = _apply_size_like_composer(spec)

    assert w2 == pytest.approx(w1)
    assert h2 == pytest.approx(h1)


def test_preset_template_cycle_deterministic():
    spec = _base_spec("single_column")
    apply_template_preset(spec, "single_column", respect_overrides=False)
    spec.size_mode = "preset"
    spec.size_preset = "wide"
    w1, h1 = _apply_size_like_composer(spec)
    assert getattr(spec.page, "sizing_mode", None) == "figure_first"


def test_validate_skips_off_axis_tick_labels():
    spec = _base_spec()
    spec.axes.x_range = (0.0, 1.0)
    ctx = RenderContext(is_preview=True, trace_model=None)
    fig = build_figure(spec, ctx)
    ax = fig.axes[0]
    ax.set_xlim(0.0, 1.0)
    ax.set_xticks([0.0, 0.5, 1.0, 2.0])  # tick outside range
    issues = validate_required_visibility(fig, spec, check_only=True)
    assert not any("2" in msg for msg in issues)
