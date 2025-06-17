import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_diameter_toggle_visibility(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    trace_path = tmp_path / 'trace.csv'
    df = pd.DataFrame({
        'Time (s)': [0, 1, 2],
        'Inner Diameter': [10, 11, 12],
        'Outer Diameter': [15, 16, 17],
    })
    df.to_csv(trace_path, index=False)
    event_path = tmp_path / 'trace_table.csv'
    pd.DataFrame({'label': ['A'], 'time': [1]}).to_csv(event_path, index=False)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.load_trace_and_events(str(trace_path))

    # Toolbar should include diameter toggle actions
    toolbar_actions = gui.toolbar.actions()
    assert any(
        act is gui.id_toggle_act
        or (
            hasattr(act, "defaultWidget")
            and act.defaultWidget().defaultAction() is gui.id_toggle_act
        )
        for act in toolbar_actions
    )
    assert any(
        act is gui.od_toggle_act
        or (
            hasattr(act, "defaultWidget")
            and act.defaultWidget().defaultAction() is gui.od_toggle_act
        )
        for act in toolbar_actions
    )

    assert gui.trace_line.get_visible() is True
    assert gui.od_line.get_visible() is True

    gui.toggle_inner_diameter(False)
    gui.toggle_outer_diameter(False)

    assert gui.trace_line.get_visible() is False
    assert gui.od_line.get_visible() is False
    assert gui.ax2.get_visible() is False

    gui.toggle_inner_diameter(True)
    gui.toggle_outer_diameter(True)

    assert gui.trace_line.get_visible() is True
    assert gui.od_line.get_visible() is True
    assert gui.ax2.get_visible() is True
    app.quit()
