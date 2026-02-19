import numpy as np
import pandas as pd
import pytest

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.ui.time_scrollbar import TIME_SCROLLBAR_SCALE


def test_scrollbar_drag_freezes_width(qt_app) -> None:
    window = VasoAnalyzerApp(check_updates=False)
    try:
        if window._plot_host_is_pyqtgraph() and getattr(window, "trace_nav_bar", None) is not None:
            pytest.skip(
                "Legacy scrollbar hidden under pyqtgraph; trace nav bar replaces it"
            )

        df = pd.DataFrame(
            {
                "Time (s)": np.linspace(0.0, 1000.0, 1001),
                "Inner Diameter": np.linspace(50.0, 60.0, 1001),
            }
        )
        window.trace_data = df
        window.trace_model = TraceModel.from_dataframe(df)
        window.plot_host.set_trace_model(window.trace_model)
        window.plot_host.set_time_window(0.0, 1000.0)

        window._apply_time_span_preset(60.0)
        window.update_scroll_slider()

        expected_step = int(round(TIME_SCROLLBAR_SCALE * (60.0 / 1000.0)))
        assert window.scroll_slider.pageStep() == expected_step

        window._on_scrollbar_pressed()
        mid_value = window.scroll_slider.maximum() // 2
        window.scroll_plot_user(mid_value, source="sliderMoved")
        window._on_scrollbar_released()

        window_range = window.plot_host.current_window()
        assert window_range is not None
        assert (window_range[1] - window_range[0]) == pytest.approx(60.0, abs=1e-6)
    finally:
        window.close()
        qt_app.processEvents()
