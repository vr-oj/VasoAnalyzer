from vasoanalyzer.ui.plots.pyqtgraph_nav_math import tick_style_for_trace_count


def test_tick_density_policy_levels() -> None:
    assert tick_style_for_trace_count(1).density == 1.0
    assert tick_style_for_trace_count(2).density == 1.0
    assert tick_style_for_trace_count(3).density == 0.7
    assert tick_style_for_trace_count(4).density == 0.7
    assert tick_style_for_trace_count(5).density == 0.55
    assert tick_style_for_trace_count(8).density == 0.55


def test_tick_text_metrics_stable() -> None:
    base = tick_style_for_trace_count(1)
    for count in (3, 5, 7):
        style = tick_style_for_trace_count(count)
        assert style.text_offset == base.text_offset
        assert style.text_width == base.text_width
        assert style.text_height == base.text_height
