import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.ui.main_window import VasoAnalyzerApp

def test_update_plot_no_frame(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    trace_path = tmp_path / 'trace.csv'
    df_trace = pd.DataFrame({'Time (s)': [0, 1, 2, 3], 'Inner Diameter': [10, 11, 12, 13]})
    df_trace.to_csv(trace_path, index=False)
    event_path = tmp_path / 'trace_table.csv'
    df_evt = pd.DataFrame({'label': ['A', 'B'], 'time': [1, 2]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))
    gui.update_plot()
    app.quit()


def test_event_table_id_values(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    trace_path = tmp_path / 'trace.csv'
    df_trace = pd.DataFrame(
        {
            'Time (s)': [0, 1, 2, 3],
            'Inner Diameter': [10, 11, 12, 13],
        }
    )
    df_trace.to_csv(trace_path, index=False)

    event_path = tmp_path / 'trace_table.csv'
    df_evt = pd.DataFrame({'label': ['A', 'B'], 'time': [1, 2]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))

    # Expected diameters sampled 2s before next event or end
    assert gui.event_table_data[0][2] == 10.0
    assert gui.event_table_data[1][2] == 11.0
    app.quit()



