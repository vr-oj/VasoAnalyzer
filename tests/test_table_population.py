import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.gui import VasoAnalyzerApp


def test_table_population_no_exception(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    trace_path = tmp_path / 'trace.csv'
    df_trace = pd.DataFrame({'Time (s)': [0, 1, 2], 'Inner Diameter': [10, 11, 12]})
    df_trace.to_csv(trace_path, index=False)
    event_path = tmp_path / 'trace_table.csv'
    df_evt = pd.DataFrame({'label': ['A'], 'time': [1]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))
    gui.populate_table()
    app.quit()