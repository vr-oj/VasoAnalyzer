from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QDoubleSpinBox,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib import rcParams
from vasoanalyzer.theme_manager import CURRENT_THEME


class SubplotLayoutDialog(QDialog):
    def __init__(self, parent=None, fig=None):
        super().__init__(parent)
        self.setWindowTitle("Subplot Layout")
        self.fig = fig

        self.params = self._get_initial_params()

        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.controls = {}
        names = ["left", "right", "top", "bottom", "wspace", "hspace"]
        for row, name in enumerate(names):
            label = QLabel(name.capitalize())
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.01)
            spin.setDecimals(2)
            slider.setValue(int(self.params[name] * 100))
            spin.setValue(self.params[name])
            slider.valueChanged.connect(lambda v, s=spin: s.setValue(v / 100))
            spin.valueChanged.connect(lambda v, s=slider: s.setValue(int(v * 100)))
            slider.valueChanged.connect(self.update_preview)
            spin.valueChanged.connect(self.update_preview)
            form.addWidget(label, row, 0)
            form.addWidget(slider, row, 1)
            form.addWidget(spin, row, 2)
            self.controls[name] = spin
        layout.addLayout(form)

        self.preview_fig = Figure(figsize=(2, 2), facecolor=CURRENT_THEME['window_bg'])
        self.preview_canvas = FigureCanvas(self.preview_fig)
        self.preview_axes = self.preview_fig.subplots(2, 2)
        for ax in self.preview_axes.flat:
            ax.plot([0, 1], [0, 1])
            ax.set_xticks([])
            ax.set_yticks([])
        layout.addWidget(self.preview_canvas)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        self.update_preview()

    def _get_initial_params(self):
        if self.fig is not None:
            sp = self.fig.subplotpars
            return {
                "left": sp.left,
                "right": sp.right,
                "top": sp.top,
                "bottom": sp.bottom,
                "wspace": sp.wspace,
                "hspace": sp.hspace,
            }
        return {
            "left": rcParams.get("figure.subplot.left", 0.125),
            "right": rcParams.get("figure.subplot.right", 0.9),
            "top": rcParams.get("figure.subplot.top", 0.88),
            "bottom": rcParams.get("figure.subplot.bottom", 0.11),
            "wspace": rcParams.get("figure.subplot.wspace", 0.2),
            "hspace": rcParams.get("figure.subplot.hspace", 0.2),
        }

    def get_values(self):
        return {name: ctrl.value() for name, ctrl in self.controls.items()}

    def update_preview(self, *_):
        params = self.get_values()
        # Clamp parameters to [0, 1]
        epsilon = 1e-3
        for key in params:
            params[key] = max(0.0, min(1.0, params[key]))

        # Ensure left < right and bottom < top
        if params["right"] <= params["left"]:
            if params["left"] >= 1.0 - epsilon:
                params["left"] = 1.0 - epsilon
                params["right"] = 1.0
            else:
                params["right"] = min(1.0, params["left"] + epsilon)

        if params["top"] <= params["bottom"]:
            if params["bottom"] >= 1.0 - epsilon:
                params["bottom"] = 1.0 - epsilon
                params["top"] = 1.0
            else:
                params["top"] = min(1.0, params["bottom"] + epsilon)

        self.preview_fig.subplots_adjust(**params)
        self.preview_canvas.draw_idle()

