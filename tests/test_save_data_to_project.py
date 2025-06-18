import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import Project, Experiment


def test_save_data_to_project(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    trace_path = tmp_path / "trace.csv"
    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_trace.to_csv(trace_path, index=False)
    event_path = tmp_path / "trace_table.csv"
    df_evt = pd.DataFrame({"label": ["A"], "time": [1.0]})
    df_evt.to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.current_project = Project(name="P")
    exp = Experiment(name="E")
    gui.current_project.experiments.append(exp)
    gui.current_experiment = exp

    gui.load_trace_and_events(str(trace_path))

    with patch("PyQt5.QtWidgets.QInputDialog.getText", return_value=("N1", True)):
        gui.save_data_as_n()

    assert len(exp.samples) == 1
    sample = exp.samples[0]
    pd.testing.assert_frame_equal(sample.trace_data, gui.trace_data)
    pd.testing.assert_frame_equal(
        sample.events_data,
        pd.DataFrame(gui.event_table_data, columns=["Event", "Time (s)", "ID (µm)", "Frame"]),
    )
    app.quit()
