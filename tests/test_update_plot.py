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


def test_event_labels_from_complex_file(tmp_path):
    """Event column should use the actual event label, not the time."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    trace_path = tmp_path / "trace.csv"
    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_trace.to_csv(trace_path, index=False)

    event_path = tmp_path / "trace_table.csv"
    df_evt = pd.DataFrame({"Event": ["DrugA", "DrugB"], "Event Time": [0.5, 1.0]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))

    labels = [row[0] for row in gui.event_table_data]
    times = [row[1] for row in gui.event_table_data]

    assert labels == ["DrugA", "DrugB"]
    assert times == [0.5, 1.0]

    app.quit()


def test_event_table_od_values(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    trace_path = tmp_path / "trace.csv"
    df_trace = pd.DataFrame(
        {
            "Time (s)": [0, 1, 2],
            "Inner Diameter": [10, 11, 12],
            "Outer Diameter": [15, 16, 17],
        }
    )
    df_trace.to_csv(trace_path, index=False)

    event_path = tmp_path / "trace_table.csv"
    df_evt = pd.DataFrame({"label": ["A"], "time": [1]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))

    assert len(gui.event_table_data[0]) == 5
    assert gui.event_table_data[0][3] == 16.0
    app.quit()



