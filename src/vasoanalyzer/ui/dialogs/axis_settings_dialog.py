# [L] ========================= AxisSettingsDialog =========================
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QLabel,
    QDoubleSpinBox,
)


class AxisSettingsDialog(QDialog):
    def __init__(self, parent, ax, canvas, ax2=None):
        super().__init__(parent)
        self.ax = ax
        self.ax2 = ax2
        self.canvas = canvas
        self.setWindowTitle("Axis Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # -- X axis --
        self.xmin = QDoubleSpinBox()
        self.xmin.setDecimals(2)
        self.xmin.setRange(-1e9, 1e9)
        self.xmin.setValue(round(ax.get_xlim()[0], 2))

        self.xmax = QDoubleSpinBox()
        self.xmax.setDecimals(2)
        self.xmax.setRange(-1e9, 1e9)
        self.xmax.setValue(round(ax.get_xlim()[1], 2))

        # -- Inner / primary Y axis --
        self.ymin = QDoubleSpinBox()
        self.ymin.setDecimals(2)
        self.ymin.setRange(-1e9, 1e9)
        self.ymin.setValue(round(ax.get_ylim()[0], 2))

        self.ymax = QDoubleSpinBox()
        self.ymax.setDecimals(2)
        self.ymax.setRange(-1e9, 1e9)
        self.ymax.setValue(round(ax.get_ylim()[1], 2))

        self.xlabel = QLineEdit(ax.get_xlabel())
        self.ylabel = QLineEdit(ax.get_ylabel())

        # -- Outer / secondary Y axis --
        if ax2 is not None:
            self.y2min = QDoubleSpinBox()
            self.y2min.setDecimals(2)
            self.y2min.setRange(-1e9, 1e9)
            self.y2min.setValue(round(ax2.get_ylim()[0], 2))

            self.y2max = QDoubleSpinBox()
            self.y2max.setDecimals(2)
            self.y2max.setRange(-1e9, 1e9)
            self.y2max.setValue(round(ax2.get_ylim()[1], 2))

            self.ylabel2 = QLineEdit(ax2.get_ylabel())

        self.grid_chk = QCheckBox("Show Grid")
        self.grid_chk.setChecked(any(line.get_visible() for line in ax.get_xgridlines()))

        form.addRow("X Min:", self.xmin)
        form.addRow("X Max:", self.xmax)
        form.addRow("Inner Y Min:", self.ymin)
        form.addRow("Inner Y Max:", self.ymax)
        if ax2 is not None:
            form.addRow("Outer Y Min:", self.y2min)
            form.addRow("Outer Y Max:", self.y2max)
        form.addRow("X Title:", self.xlabel)
        form.addRow("Inner Y Title:", self.ylabel)
        if ax2 is not None:
            form.addRow("Outer Y Title:", self.ylabel2)
        form.addRow(self.grid_chk)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        apply_btn = QPushButton("Apply")
        cancel_btn = QPushButton("Cancel")
        ok_btn = QPushButton("OK")
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        apply_btn.clicked.connect(self.apply)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)

    def apply(self):
        try:
            self.ax.set_xlim(self.xmin.value(), self.xmax.value())
        except Exception:
            pass
        try:
            self.ax.set_ylim(self.ymin.value(), self.ymax.value())
        except Exception:
            pass
        if self.ax2 is not None:
            try:
                self.ax2.set_ylim(self.y2min.value(), self.y2max.value())
            except Exception:
                pass
            self.ax2.set_ylabel(self.ylabel2.text())
        self.ax.set_xlabel(self.xlabel.text())
        self.ax.set_ylabel(self.ylabel.text())
        self.ax.grid(self.grid_chk.isChecked())
        self.canvas.draw_idle()

    def accept(self):
        self.apply()
        super().accept()
