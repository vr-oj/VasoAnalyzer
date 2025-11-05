"""Dialog for configuring figure export parameters."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class FigureExportDialog(QDialog):
    """Collect export settings such as output format, DPI, and geometry."""

    PRESETS = [
        ("Single column (85 mm)", 85.0),
        ("One-and-a-half column (120 mm)", 120.0),
        ("Double column (180 mm)", 180.0),
        ("Presentation slide (260 mm)", 260.0),
        ("Custom", None),
    ]

    def __init__(
        self,
        parent=None,
        *,
        default_format: str = "tiff",
        default_dpi: int = 600,
        aspect_ratio: float = 0.6,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Figure")
        self.setModal(True)
        self._result: dict[str, Any] | None = None
        self._aspect_ratio = aspect_ratio if aspect_ratio > 0 else 0.6

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)

        # Format selector
        self.format_combo = QComboBox()
        self.format_combo.addItem("TIFF (publication raster)", "tiff")
        self.format_combo.addItem("SVG (vector)", "svg")
        idx = max(self.format_combo.findData(default_format), 0)
        self.format_combo.setCurrentIndex(idx)
        self.format_combo.currentIndexChanged.connect(self._update_svg_controls)
        form.addRow("Format:", self.format_combo)

        # DPI selector
        self.dpi_spin = QDoubleSpinBox()
        self.dpi_spin.setDecimals(0)
        self.dpi_spin.setMinimum(72)
        self.dpi_spin.setMaximum(2400)
        self.dpi_spin.setSingleStep(10)
        self.dpi_spin.setValue(default_dpi)
        form.addRow("DPI:", self.dpi_spin)

        # Width presets
        width_row = QHBoxLayout()
        width_row.setSpacing(6)
        self.preset_combo = QComboBox()
        for label, value in self.PRESETS:
            self.preset_combo.addItem(label, value)
        self.preset_combo.currentIndexChanged.connect(self._handle_preset_change)
        width_row.addWidget(self.preset_combo, 2)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(40.0, 400.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(1.0)
        self.width_spin.setValue(120.0)
        self.width_spin.valueChanged.connect(self._update_height_label)
        width_row.addWidget(self.width_spin, 1)

        width_widget = QWidget()
        width_widget.setLayout(width_row)
        form.addRow("Width (mm):", width_widget)

        self.height_label = QLabel("")
        form.addRow("Height:", self.height_label)

        # Padding control
        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setDecimals(3)
        self.pad_spin.setRange(0.0, 1.0)
        self.pad_spin.setSingleStep(0.005)
        self.pad_spin.setValue(0.03)
        form.addRow("Pad inches:", self.pad_spin)

        # SVG flatten fonts checkbox
        self.flatten_checkbox = QCheckBox("Flatten fonts (outline text)")
        form.addRow("SVG fonts:", self.flatten_checkbox)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.accepted.connect(self._commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._handle_preset_change()
        self._update_svg_controls()
        self._update_height_label()

    # ------------------------------------------------------------------
    def _handle_preset_change(self) -> None:
        value = self.preset_combo.currentData()
        is_custom = value is None
        if not is_custom:
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(float(value))
            self.width_spin.blockSignals(False)
        self.width_spin.setEnabled(is_custom)
        self._update_height_label()

    def _update_svg_controls(self) -> None:
        fmt = self.format_combo.currentData()
        self.flatten_checkbox.setEnabled(fmt == "svg")
        if fmt != "svg":
            self.flatten_checkbox.setChecked(False)

    def _update_height_label(self) -> None:
        width_mm = self.width_spin.value()
        height_mm = width_mm * self._aspect_ratio
        self.height_label.setText(f"{height_mm:.1f} mm (locked to current aspect)")

    # ------------------------------------------------------------------
    def _commit(self) -> None:
        width_mm = self.width_spin.value()
        height_mm = width_mm * self._aspect_ratio
        self._result = {
            "format": self.format_combo.currentData(),
            "dpi": int(self.dpi_spin.value()),
            "width_mm": float(width_mm),
            "height_mm": float(height_mm),
            "pad_inches": float(self.pad_spin.value()),
            "svg_flatten_fonts": bool(self.flatten_checkbox.isChecked()),
        }
        self.accept()

    def get_settings(self) -> dict | None:
        return self._result
