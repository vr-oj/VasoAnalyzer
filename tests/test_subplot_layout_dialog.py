import os
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from matplotlib.figure import Figure
from vasoanalyzer.gui import SubplotLayoutDialog


def test_subplot_layout_dialog_extreme_values():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    fig = Figure()
    dialog = SubplotLayoutDialog(None, fig)
    dialog.controls['left'].setValue(1.0)
    dialog.controls['right'].setValue(0.0)
    dialog.controls['bottom'].setValue(1.0)
    dialog.controls['top'].setValue(0.0)
    dialog.controls['wspace'].setValue(1.5)
    dialog.controls['hspace'].setValue(1.5)
    dialog.update_preview()
    app.quit()
