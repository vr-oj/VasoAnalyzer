import math

from vasoanalyzer.ui.plots.pyqtgraph_nav_math import (
    font_size_for_trace_count,
    pan_step,
    zoomed_range,
)


def test_pan_step_fraction() -> None:
    span = 100.0
    assert pan_step(span, 0.10) == 10.0
    assert pan_step(span, 0.50) == 50.0


def test_zoomed_range_anchor_preserved() -> None:
    x_min, x_max = 0.0, 10.0
    anchor = 2.5  # 25% into the window
    new_min, new_max = zoomed_range(x_min, x_max, anchor, 0.5)
    assert math.isclose(new_min, 1.25, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(new_max, 6.25, rel_tol=0.0, abs_tol=1e-9)


def test_font_size_policy() -> None:
    base = 14.0
    assert font_size_for_trace_count(base, 1) == 14.0
    assert font_size_for_trace_count(base, 2) == 14.0
    assert font_size_for_trace_count(base, 3) == 14.0
    assert font_size_for_trace_count(base, 4) == 14.0
    assert font_size_for_trace_count(base, 5) == 14.0
    assert font_size_for_trace_count(base, 8) == 14.0
