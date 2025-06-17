import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import SampleN


def test_open_dual_view(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_events = pd.DataFrame({"label": ["A"], "time": [1]})

    s1 = SampleN(name="N1", trace_data=df_trace, events_data=df_events)
    s2 = SampleN(name="N2", trace_data=df_trace, events_data=df_events)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.open_samples_in_dual_view([s1, s2])

    assert hasattr(gui, "dual_window")
    assert gui.dual_window.centralWidget().orientation() == Qt.Vertical
    assert len(gui.dual_window.views) == 2
    for view in gui.dual_window.views:
        assert view.trace_data is not None
        assert len(view.event_table_data) == 1

    app.quit()

