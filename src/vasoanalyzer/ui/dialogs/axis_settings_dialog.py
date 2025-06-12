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
)


class AxisSettingsDialog(QDialog):
    def __init__(self, parent, ax, canvas):
        super().__init__(parent)
        self.ax = ax
        self.canvas = canvas
        self.setWindowTitle("Axis Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.xmin = QLineEdit(str(ax.get_xlim()[0]))
        self.xmax = QLineEdit(str(ax.get_xlim()[1]))
        self.ymin = QLineEdit(str(ax.get_ylim()[0]))
        self.ymax = QLineEdit(str(ax.get_ylim()[1]))
        self.xlabel = QLineEdit(ax.get_xlabel())
        self.ylabel = QLineEdit(ax.get_ylabel())
        self.grid_chk = QCheckBox("Show Grid")
        self.grid_chk.setChecked(any(line.get_visible() for line in ax.get_xgridlines()))

        form.addRow("X Min:", self.xmin)
        form.addRow("X Max:", self.xmax)
        form.addRow("Y Min:", self.ymin)
        form.addRow("Y Max:", self.ymax)
        form.addRow("X Title:", self.xlabel)
        form.addRow("Y Title:", self.ylabel)
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
            self.ax.set_xlim(float(self.xmin.text()), float(self.xmax.text()))
        except ValueError:
            pass
        try:
            self.ax.set_ylim(float(self.ymin.text()), float(self.ymax.text()))
        except ValueError:
            pass
        self.ax.set_xlabel(self.xlabel.text())
        self.ax.set_ylabel(self.ylabel.text())
        self.ax.grid(self.grid_chk.isChecked())
        self.canvas.draw_idle()

    def accept(self):
        self.apply()
        super().accept()
