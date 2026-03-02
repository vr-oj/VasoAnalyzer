import numpy as np
import pandas as pd
import pytest

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost


def test_plot_host_set_time_window_exact(qt_app):
    df = pd.DataFrame(
        {
            "Time (s)": np.linspace(0.0, 100.0, 101),
            "Inner Diameter": np.linspace(50.0, 60.0, 101),
        }
    )
    trace_model = TraceModel.from_dataframe(df)

    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels([ChannelTrackSpec(track_id="inner", component="inner")])
    host.set_trace_model(trace_model)

    host.set_time_window(10.0, 20.0)
    window = host.current_window()
    assert window is not None
    assert window[0] == pytest.approx(10.0, abs=1e-6)
    assert window[1] == pytest.approx(20.0, abs=1e-6)

    host.set_time_window(30.0, 40.0)
    window = host.current_window()
    assert window is not None
    assert window[0] == pytest.approx(30.0, abs=1e-6)
    assert window[1] == pytest.approx(40.0, abs=1e-6)
    assert (window[1] - window[0]) == pytest.approx(10.0, abs=1e-6)
