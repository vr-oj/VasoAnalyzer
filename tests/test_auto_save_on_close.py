import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import Project, Experiment, save_project, load_project


def test_auto_save_on_close(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    path = tmp_path / "proj.vaso"
    proj = Project(name="P")
    exp = Experiment(name="E")
    proj.experiments.append(exp)
    save_project(proj, path)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    gui.current_project = load_project(path)

    # Modify UI state
    gui.ax.set_xlim(1, 2)
    gui.ax.set_ylim(3, 4)

    gui.close()

    reloaded = load_project(path)
    assert reloaded.ui_state["axis_xlim"] == [1.0, 2.0]
    assert reloaded.ui_state["axis_ylim"] == [3.0, 4.0]
    app.quit()
