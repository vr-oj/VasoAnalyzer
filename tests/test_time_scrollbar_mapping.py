from vasoanalyzer.ui.time_scrollbar import (
    TIME_SCROLLBAR_SCALE,
    compute_scrollbar_state,
    compute_window_start,
    window_from_scroll_value,
)


def test_scrollbar_state_basic():
    value, page_step = compute_scrollbar_state(
        0.0,
        100.0,
        20.0,
        40.0,
        scale=1000,
    )
    assert value == 200
    assert page_step == 200


def test_window_start_clamped_end():
    start = compute_window_start(0.0, 100.0, 20.0, 1000, scale=1000)
    assert start == 80.0


def test_scrollbar_state_zero_total():
    value, page_step = compute_scrollbar_state(5.0, 5.0, 5.0, 5.0)
    assert value == 0
    assert page_step == TIME_SCROLLBAR_SCALE
    start = compute_window_start(5.0, 5.0, 0.0, 500)
    assert start == 5.0


def test_window_from_scroll_value_preserves_width():
    t0, t1 = 0.0, 200.0
    width = 60.0
    max_value = 1000
    for value in (0, max_value // 2, max_value):
        start, end = window_from_scroll_value(
            value,
            t0=t0,
            t1=t1,
            current_width=width,
            max_value=max_value,
        )
        assert end - start == width
    start, end = window_from_scroll_value(
        max_value,
        t0=t0,
        t1=t1,
        current_width=width,
        max_value=max_value,
    )
    assert start == t1 - width
    assert end - start == width
