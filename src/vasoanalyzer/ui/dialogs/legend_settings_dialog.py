# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Dialog for editing legend placement, appearance, and labels."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)


class LegendSettingsDialog(QDialog):
    """Collect legend layout/label preferences from the user."""

    _LOCATIONS = [
        ("Best", "best"),
        ("Upper Left", "upper left"),
        ("Upper Center", "upper center"),
        ("Upper Right", "upper right"),
        ("Center Left", "center left"),
        ("Center", "center"),
        ("Center Right", "center right"),
        ("Lower Left", "lower left"),
        ("Lower Center", "lower center"),
        ("Lower Right", "lower right"),
        ("Outside Right", "right"),
    ]

    _DEFAULT_FONTS = ["Default", "Arial", "Helvetica", "Times New Roman", "Courier New"]

    def __init__(
        self,
        parent,
        *,
        settings: dict,
        labels: dict,
        defaults: dict,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Legend Settings")
        self.setModal(True)

        self._defaults = defaults or {}

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        self.visible_check = QCheckBox("Show legend")
        self.visible_check.setChecked(settings.get("visible", True))
        main.addWidget(self.visible_check)

        # Appearance block -------------------------------------------------
        appearance_box = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance_box)
        appearance_form.setLabelAlignment(Qt.AlignRight)

        self.title_edit = QLineEdit(settings.get("title", ""))
        appearance_form.addRow("Title:", self.title_edit)

        self.location_combo = QComboBox()
        for label, value in self._LOCATIONS:
            self.location_combo.addItem(label, value)
        loc_value = settings.get("location", "upper right")
        idx = self.location_combo.findData(loc_value)
        if idx < 0:
            idx = self.location_combo.findData("upper right")
        self.location_combo.setCurrentIndex(max(idx, 0))
        appearance_form.addRow("Location:", self.location_combo)

        self.ncol_spin = QSpinBox()
        self.ncol_spin.setRange(1, 4)
        self.ncol_spin.setValue(max(1, int(settings.get("ncol", 1))))
        appearance_form.addRow("Columns:", self.ncol_spin)

        self.frame_check = QCheckBox("Draw border")
        self.frame_check.setChecked(settings.get("frame_on", False))
        appearance_form.addRow("", self.frame_check)

        main.addWidget(appearance_box)

        # Font block -------------------------------------------------------
        font_box = QGroupBox("Font")
        font_form = QFormLayout(font_box)
        font_form.setLabelAlignment(Qt.AlignRight)

        self.font_combo = QComboBox()
        self.font_combo.addItems(self._DEFAULT_FONTS)
        family = settings.get("font_family", "").strip()
        if family and family not in self._DEFAULT_FONTS:
            self.font_combo.addItem(family)
            self.font_combo.setCurrentText(family)
        elif family:
            self.font_combo.setCurrentText(family)
        else:
            self.font_combo.setCurrentIndex(0)
        font_form.addRow("Family:", self.font_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 48)
        self.font_size_spin.setValue(int(settings.get("font_size", 9)))
        font_form.addRow("Size:", self.font_size_spin)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(12)
        self.font_bold_check = QCheckBox("Bold")
        self.font_bold_check.setChecked(settings.get("font_bold", False))
        self.font_italic_check = QCheckBox("Italic")
        self.font_italic_check.setChecked(settings.get("font_italic", False))
        toggle_row.addWidget(self.font_bold_check)
        toggle_row.addWidget(self.font_italic_check)
        font_form.addRow("", toggle_row)

        main.addWidget(font_box)

        # Labels block -----------------------------------------------------
        labels_box = QGroupBox("Legend Labels")
        labels_form = QFormLayout(labels_box)
        labels_form.setLabelAlignment(Qt.AlignRight)

        self.inner_edit = None
        self.outer_edit = None

        if "inner" in defaults:
            self.inner_edit = QLineEdit(labels.get("inner", defaults.get("inner", "")))
            labels_form.addRow("Inner trace:", self.inner_edit)

        if "outer" in defaults:
            self.outer_edit = QLineEdit(labels.get("outer", defaults.get("outer", "")))
            labels_form.addRow("Outer trace:", self.outer_edit)

        if labels_form.rowCount() > 0:
            main.addWidget(labels_box)

        # Buttons ----------------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

    # ------------------------------------------------------------------
    def get_settings(self) -> dict:
        """Return the legend preferences selected by the user."""

        labels = {}
        if self.inner_edit is not None:
            text = self.inner_edit.text().strip()
            default = self._defaults.get("inner", "")
            labels["inner"] = text or default
        if self.outer_edit is not None:
            text = self.outer_edit.text().strip()
            default = self._defaults.get("outer", "")
            labels["outer"] = text or default

        font_family = self.font_combo.currentText().strip()
        if font_family == "Default":
            font_family = ""

        return {
            "visible": self.visible_check.isChecked(),
            "title": self.title_edit.text().strip(),
            "location": self.location_combo.currentData(),
            "ncol": self.ncol_spin.value(),
            "frame_on": self.frame_check.isChecked(),
            "font_family": font_family,
            "font_size": self.font_size_spin.value(),
            "font_bold": self.font_bold_check.isChecked(),
            "font_italic": self.font_italic_check.isChecked(),
            "labels": labels,
        }
