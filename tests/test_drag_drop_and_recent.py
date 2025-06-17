import os
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication, QDropEvent
from PyQt5.QtCore import Qt, QMimeData, QUrl, QPoint

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.project import Project, Experiment, save_project


def create_project(path):
    proj = Project(name="P", experiments=[Experiment(name="E")])
    save_project(proj, path)
    return path


def build_drop_event(path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return QDropEvent(QPoint(0, 0), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)


def test_drop_vaso_loads_project(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    proj_path = create_project(tmp_path / "test.vaso")

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()

    event = build_drop_event(proj_path)
    gui.dropEvent(event)

    assert gui.current_project is not None
    assert os.path.samefile(gui.current_project.path, str(proj_path))
    app.quit()


def test_clear_recent_lists(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    proj_path = create_project(tmp_path / "recent.vaso")

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()

    gui.update_recent_projects(str(proj_path))
    gui.recent_files = ["f1.csv", "f2.csv"]
    gui.save_recent_files()

    gui.clear_recent_files()
    gui.clear_recent_projects()

    settings = gui.settings
    assert settings.value("recentFiles") == []
    assert settings.value("recentProjects") == []
    app.quit()
