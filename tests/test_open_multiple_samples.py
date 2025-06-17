import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import SampleN


def test_open_multiple_samples(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_events = pd.DataFrame({"label": ["A"], "time": [1]})

    s1 = SampleN(name="N1", trace_data=df_trace, events_data=df_events)
    s2 = SampleN(name="N2", trace_data=df_trace, events_data=df_events)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.open_samples_in_new_windows([s1, s2])

    assert len(gui.compare_windows) == 2
    for win in gui.compare_windows:
        assert win.trace_data is not None
        assert len(win.event_table_data) == 1

    app.quit()

