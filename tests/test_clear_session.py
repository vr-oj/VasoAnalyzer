import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_clear_session_removes_outer_axis(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    trace1 = tmp_path / "t1.csv"
    df1 = pd.DataFrame(
        {
            "Time (s)": [0, 1],
            "Inner Diameter": [10, 11],
            "Outer Diameter": [20, 21],
        }
    )
    df1.to_csv(trace1, index=False)
    pd.DataFrame({"label": ["A"], "time": [1]}).to_csv(
        tmp_path / "t1_table.csv", index=False
    )

    trace2 = tmp_path / "t2.csv"
    df2 = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [30, 31]})
    df2.to_csv(trace2, index=False)
    pd.DataFrame({"label": ["B"], "time": [1]}).to_csv(
        tmp_path / "t2_table.csv", index=False
    )

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()

    gui.load_trace_and_events(str(trace1))
    assert len(gui.fig.axes) == 2

    gui.clear_current_session()
    assert len(gui.fig.axes) == 1

    gui.load_trace_and_events(str(trace2))
    assert len(gui.fig.axes) == 1

    app.quit()
