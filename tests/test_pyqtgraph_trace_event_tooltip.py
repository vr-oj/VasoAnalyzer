from __future__ import annotations

import numpy as np
import pandas as pd

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import PyQtGraphTraceView


def test_trace_hover_text_includes_hovered_event_name_and_time(qt_app) -> None:
    df = pd.DataFrame(
        {
            "Time (s)": np.linspace(0.0, 4.0, 401),
            "Inner Diameter": np.linspace(40.0, 45.0, 401),
        }
    )
    model = TraceModel.from_dataframe(df)
    view = PyQtGraphTraceView(mode="inner", enable_opengl=False)
    try:
        view.enable_hover_tooltip(True, precision=3)
        view.set_model(model)
        view.set_events(times=[1.25], labels=["Occlusion Start"])
        view.set_hovered_event_index(0)

        level_idx = model.best_level_for_window(0.0, 4.0, 600)
        window = model.window(level_idx, 0.0, 4.0)
        hover_text = view._build_hover_text(window, 100)

        assert "Event: Occlusion Start" in hover_text
        assert "Event time: 1.250 s" in hover_text
    finally:
        view.get_widget().close()
        qt_app.processEvents()
