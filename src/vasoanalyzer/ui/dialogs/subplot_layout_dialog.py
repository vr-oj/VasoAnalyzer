# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Custom dialog for adjusting subplot spacing and margins."""

from matplotlib import rcParams
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

from utils import resource_path
from vasoanalyzer.ui.theme import CURRENT_THEME


class SubplotLayoutDialog(QDialog):
    """Dialog to tweak subplot layout with live preview."""

    def __init__(self, parent=None, fig=None):
        super().__init__(parent)

        self.setWindowTitle("Subplot Layout")
        self.setWindowIcon(QIcon(resource_path("icons", "Subplots.svg")))
        self.setFont(QFont("Arial", 10))

        self.fig = fig
        self.params = self._get_initial_params()
        self.controls = {}

        main = QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        # --- Margins -------------------------------------------------------
        margins_grp = QGroupBox("Margins")
        mlay = QVBoxLayout(margins_grp)
        for name in ("left", "right", "top", "bottom"):
            self._make_slider_control(name, self.params[name], mlay)
        main.addWidget(margins_grp)

        # --- Spacing -------------------------------------------------------
        spacing_grp = QGroupBox("Spacing")
        slay = QVBoxLayout(spacing_grp)
        for name in ("wspace", "hspace"):
            self._make_slider_control(name, self.params[name], slay)
        main.addWidget(spacing_grp)

        # --- Live preview --------------------------------------------------
        dpi = QApplication.primaryScreen().logicalDotsPerInch()
        self.preview_fig = Figure(figsize=(2, 2), facecolor=CURRENT_THEME["window_bg"], dpi=dpi)
        self.preview_canvas = FigureCanvas(self.preview_fig)
        self.preview_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_ax = self.preview_fig.add_subplot(111)
        self.preview_ax.axis("off")
        main.addWidget(self.preview_canvas, 1)

        # --- Buttons -------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply
            | QDialogButtonBox.Reset
            | QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_to_fig)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._on_reset)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self.update_preview()

    # ------------------------------------------------------------------
    def _make_slider_control(self, name: str, value: float, parent_layout: QVBoxLayout):
        row = QHBoxLayout()
        label = QLabel(f"{name.capitalize()}:")
        label.setFixedWidth(60)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)

        spin = QDoubleSpinBox()
        spin.setObjectName(name)
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.01)
        spin.setDecimals(2)

        slider.setValue(int(value * 100))
        spin.setValue(value)

        # keep controls in sync
        slider.valueChanged.connect(lambda v, s=spin: s.setValue(v / 100))
        spin.valueChanged.connect(lambda v, s=slider: s.setValue(int(v * 100)))
        spin.valueChanged.connect(self.update_preview)

        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        parent_layout.addLayout(row)

        self.controls[name] = spin

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    def get_values(self):
        return {name: ctrl.value() for name, ctrl in self.controls.items()}

    # ------------------------------------------------------------------
    def update_preview(self, *_):
        params = self.get_values()

        epsilon = 1e-3
        for key in params:
            params[key] = max(0.0, min(1.0, params[key]))

        # ensure left < right and bottom < top
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

        # draw preview rectangle showing the axes region
        self.preview_ax.clear()
        self.preview_ax.axis("off")
        self.preview_ax.add_patch(
            Rectangle(
                (params["left"], params["bottom"]),
                params["right"] - params["left"],
                params["top"] - params["bottom"],
                fill=False,
                edgecolor="#4a90e2",
                lw=2,
            )
        )
        self.preview_ax.set_xlim(0, 1)
        self.preview_ax.set_ylim(0, 1)
        self.preview_ax.invert_yaxis()
        self.preview_canvas.draw_idle()

    # ------------------------------------------------------------------
    def apply_to_fig(self):
        if self.fig is not None:
            self.fig.subplots_adjust(**self.get_values())
            self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    def _on_reset(self):
        defaults = {
            "left": 0.125,
            "right": 0.9,
            "top": 0.88,
            "bottom": 0.11,
            "wspace": 0.2,
            "hspace": 0.2,
        }
        for name, val in defaults.items():
            self.controls[name].setValue(val)

        self.update_preview()

    # ------------------------------------------------------------------
    def _on_ok(self):
        self.apply_to_fig()
        self.accept()
