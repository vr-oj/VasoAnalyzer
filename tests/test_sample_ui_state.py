import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import SampleN


def test_sample_state_persistence_and_dual_view(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_events = pd.DataFrame({"label": ["A"], "time": [1]})

    s1 = SampleN(name="N1", trace_data=df_trace, events_data=df_events)
    s2 = SampleN(name="N2", trace_data=df_trace, events_data=df_events)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()

    gui.load_sample_into_view(s1)
    gui.ax.set_xlim(1, 2)
    gui.load_sample_into_view(s2)

    assert s1.ui_state["axis_xlim"] == [1.0, 2.0]

    gui.open_samples_in_dual_view([s1, s2])
    view1, view2 = gui.dual_window.views
    assert list(view1.ax.get_xlim()) == [1.0, 2.0]

    app.quit()
