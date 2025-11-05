from PyQt5.QtWidgets import QTabWidget
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedPlotSettingsDialog


def test_settings_dialog_tabs(qapp):
    fig = Figure(figsize=(4, 3))
    canvas = FigureCanvasQTAgg(fig)
    ax = fig.add_subplot(111)

    dialog = UnifiedPlotSettingsDialog(parent=None, ax=ax, canvas=canvas)
    tabs = dialog.findChildren(QTabWidget)
    assert tabs, "Unified settings dialog should expose tab widget"
    tab = tabs[0]
    for index in range(tab.count()):
        tab.setCurrentIndex(index)
    dialog.close()
