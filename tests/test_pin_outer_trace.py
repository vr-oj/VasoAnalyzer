import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from unittest.mock import patch
from matplotlib.backend_bases import MouseEvent
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_add_event_from_outer_pin(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    trace_path = tmp_path / "trace.csv"
    df = pd.DataFrame(
        {
            "Time (s)": [0, 1, 2],
            "Inner Diameter": [10, 11, 12],
            "Outer Diameter": [15, 16, 17],
        }
    )
    df.to_csv(trace_path, index=False)

    event_path = tmp_path / "trace_table.csv"
    pd.DataFrame({"label": ["A"], "time": [1]}).to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))

    xdata, ydata = 1.0, 16.0
    xp, yp = gui.ax2.transData.transform((xdata, ydata))
    me = MouseEvent("button_press_event", gui.canvas, xp, yp, button=1)
    me.inaxes = gui.ax2

    gui.handle_click_on_plot(me)

    assert len(gui.pinned_points) == 1
    marker, _ = gui.pinned_points[0]
    assert getattr(marker, "trace_type", "") == "outer"

    with patch("PyQt5.QtWidgets.QInputDialog.getItem", return_value=("↘️ Add to end", True)), 
         patch("PyQt5.QtWidgets.QInputDialog.getText", return_value=("New", True)):
        gui.prompt_add_event(xdata, ydata, "outer")

    assert len(gui.event_table_data) == 2
    last = gui.event_table_data[-1]
    assert last[2] == 11.0
    assert last[3] == 16.0

    app.quit()
