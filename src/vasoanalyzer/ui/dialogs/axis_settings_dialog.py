# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Improved Axis Settings dialog with tabbed layout and styled inputs."""

import contextlib

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path


class AxisSettingsDialog(QDialog):
    """Dialog to edit axis ranges and labels for a matplotlib plot."""

    def __init__(self, parent, ax, canvas, ax2=None):
        super().__init__(parent)

        self.ax = ax
        self.ax2 = ax2
        self.canvas = canvas

        self.setWindowTitle("Axis Settings")
        self.setWindowIcon(QIcon(resource_path("icons", "Customize_edit_axis_ranges.svg")))
        self.setFont(QFont("Arial", 10))

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)

        tabs = QTabWidget()
        main.addWidget(tabs)

        # ------------------------------------------------------------------
        # Scale tab
        # ------------------------------------------------------------------
        scale_tab = QWidget()
        scale_form = QFormLayout(scale_tab)
        scale_form.setLabelAlignment(Qt.AlignRight)
        scale_form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        scale_form.setHorizontalSpacing(12)
        scale_form.setVerticalSpacing(6)

        # --- X range -------------------------------------------------------
        self.x_min = QDoubleSpinBox()
        self.x_min.setRange(-1e6, 1e6)
        self.x_min.setDecimals(2)
        self.x_min.setSingleStep(1.0)
        self.x_min.setSuffix(" s")
        self.x_min.setValue(round(ax.get_xlim()[0], 2))

        self.x_max = QDoubleSpinBox()
        self.x_max.setRange(-1e6, 1e6)
        self.x_max.setDecimals(2)
        self.x_max.setSingleStep(1.0)
        self.x_max.setSuffix(" s")
        self.x_max.setValue(round(ax.get_xlim()[1], 2))

        scale_form.addRow("X Range:", self._hbox(self.x_min, self.x_max))

        # --- Inner Y range -------------------------------------------------
        self.yi_min = QDoubleSpinBox(suffix=" \u00b5m")
        self.yi_min.setRange(-1e6, 1e6)
        self.yi_min.setDecimals(2)
        self.yi_min.setSingleStep(1.0)
        self.yi_min.setValue(round(ax.get_ylim()[0], 2))

        self.yi_max = QDoubleSpinBox(suffix=" \u00b5m")
        self.yi_max.setRange(-1e6, 1e6)
        self.yi_max.setDecimals(2)
        self.yi_max.setSingleStep(1.0)
        self.yi_max.setValue(round(ax.get_ylim()[1], 2))

        scale_form.addRow("Inner Y Range:", self._hbox(self.yi_min, self.yi_max))

        # --- Outer Y range -------------------------------------------------
        if ax2 is not None:
            self.yo_min = QDoubleSpinBox(suffix=" \u00b5m")
            self.yo_min.setRange(-1e6, 1e6)
            self.yo_min.setDecimals(2)
            self.yo_min.setSingleStep(1.0)
            self.yo_min.setValue(round(ax2.get_ylim()[0], 2))

            self.yo_max = QDoubleSpinBox(suffix=" \u00b5m")
            self.yo_max.setRange(-1e6, 1e6)
            self.yo_max.setDecimals(2)
            self.yo_max.setSingleStep(1.0)
            self.yo_max.setValue(round(ax2.get_ylim()[1], 2))

            scale_form.addRow("Outer Y Range:", self._hbox(self.yo_min, self.yo_max))

        tabs.addTab(scale_tab, "Scale")

        # ------------------------------------------------------------------
        # Appearance tab
        # ------------------------------------------------------------------
        app_tab = QWidget()
        app_form = QFormLayout(app_tab)
        app_form.setLabelAlignment(Qt.AlignRight)
        app_form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        app_form.setHorizontalSpacing(12)
        app_form.setVerticalSpacing(6)

        x_axis = ax2 if ax2 is not None else ax
        self.x_title = QLineEdit(x_axis.get_xlabel())
        self.yi_title = QLineEdit(ax.get_ylabel())
        app_form.addRow("X Label:", self.x_title)
        app_form.addRow("Inner Y Label:", self.yi_title)

        if ax2 is not None:
            self.yo_title = QLineEdit(ax2.get_ylabel())
            app_form.addRow("Outer Y Label:", self.yo_title)

        self.show_grid = QCheckBox("Show grid")
        self.show_grid.setChecked(any(line.get_visible() for line in ax.get_xgridlines()))
        app_form.addRow("", self.show_grid)

        tabs.addTab(app_tab, "Appearance")

        # ------------------------------------------------------------------
        # Buttons
        # ------------------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

    # ------------------------------------------------------------------
    def _hbox(self, *widgets):
        """Return a QWidget with the given widgets in a horizontal layout."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for widget in widgets:
            h.addWidget(widget)
        return w

    # ------------------------------------------------------------------
    def _apply(self):
        """Apply current values to the axes."""
        with contextlib.suppress(Exception):
            self.ax.set_xlim(self.x_min.value(), self.x_max.value())

        with contextlib.suppress(Exception):
            self.ax.set_ylim(self.yi_min.value(), self.yi_max.value())

        if self.ax2 is not None:
            with contextlib.suppress(Exception):
                self.ax2.set_ylim(self.yo_min.value(), self.yo_max.value())
            self.ax2.set_ylabel(self.yo_title.text())

        x_label_text = self.x_title.text()
        parent = self.parent()
        shared_setter = getattr(parent, "_set_shared_xlabel", None)
        if callable(shared_setter):
            shared_setter(x_label_text)
        else:
            x_axis = self.ax2 if self.ax2 is not None else self.ax
            if x_axis is not None:
                x_axis.set_xlabel(x_label_text)
            if self.ax2 is not None and self.ax is not None and x_axis is self.ax2:
                self.ax.set_xlabel("")
        self.ax.set_ylabel(self.yi_title.text())
        self.ax.grid(self.show_grid.isChecked())
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    def _on_ok(self):
        self._apply()
        self.accept()
