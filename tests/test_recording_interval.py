import os
import json
import numpy as np
import tifffile
import matplotlib
matplotlib.use('Agg')
from PyQt5.QtWidgets import QApplication
from unittest.mock import patch
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def _create_tiff(path, metadata=None):
    data = np.zeros((2, 5, 5), dtype=np.uint8)
    if metadata is not None:
        tifffile.imwrite(path, data[0], description=json.dumps(metadata))
        tifffile.imwrite(path, data[1], append=True)
    else:
        tifffile.imwrite(path, data)


def test_recording_interval_from_metadata(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tiff_path = tmp_path / "stack.tiff"
    _create_tiff(tiff_path, {"Rec_intvl": 200})

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    with patch("PyQt5.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(tiff_path), "")):
        gui.load_snapshot()
    assert abs(gui.recording_interval - 0.2) < 1e-6
    app.quit()


def test_recording_interval_default(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tiff_path = tmp_path / "stack.tiff"
    _create_tiff(tiff_path)

    app = QApplication.instance() or QApplication([])
    gui = VasoAnalyzerApp()
    with patch("PyQt5.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(tiff_path), "")):
        gui.load_snapshot()
    assert abs(gui.recording_interval - 0.14) < 1e-6
    app.quit()
