"""Dialog for configuring experiment report export parameters."""

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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


# Template definitions: (label, width_in, height_in, description)
REPORT_TEMPLATES: list[tuple[str, float, float, str]] = [
    ("Standard Landscape", 11.0, 8.5, "Balanced view — trace + frame + table"),
    ("Wide Trace", 14.0, 8.5, "Long recordings — more horizontal room"),
    ("Trace Focus", 11.0, 8.5, "No TIFF frame — trace takes full width"),
    ("Poster Panel", 16.0, 10.0, "Presentations — everything bigger"),
    ("Custom", 11.0, 8.5, "Set your own dimensions"),
]


class ReportExportDialog(QDialog):
    """Collect export settings for experiment report figures."""

    def __init__(
        self,
        parent=None,
        *,
        has_snapshot: bool = False,
        has_events: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Experiment Report")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._result: dict[str, Any] | None = None
        self._has_snapshot = has_snapshot
        self._has_events = has_events

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- Template selector ----
        template_group = QGroupBox("Template")
        tpl_layout = QVBoxLayout(template_group)

        self.template_combo = QComboBox()
        for label, _w, _h, desc in REPORT_TEMPLATES:
            self.template_combo.addItem(f"{label} — {desc}", label)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        tpl_layout.addWidget(self.template_combo)

        layout.addWidget(template_group)

        # ---- Page dimensions ----
        dims_group = QGroupBox("Page Dimensions")
        dims_form = QFormLayout(dims_group)
        dims_form.setLabelAlignment(Qt.AlignRight)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(6.0, 24.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setSuffix(" in")
        dims_form.addRow("Width:", self.width_spin)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(5.0, 18.0)
        self.height_spin.setDecimals(1)
        self.height_spin.setSingleStep(0.5)
        self.height_spin.setSuffix(" in")
        dims_form.addRow("Height:", self.height_spin)

        layout.addWidget(dims_group)

        # ---- Panels ----
        panels_group = QGroupBox("Include Panels")
        panels_layout = QVBoxLayout(panels_group)

        self.include_frame_cb = QCheckBox("TIFF snapshot frame")
        self.include_frame_cb.setChecked(has_snapshot)
        self.include_frame_cb.setEnabled(has_snapshot)
        if not has_snapshot:
            self.include_frame_cb.setToolTip("No snapshot loaded for this sample")
        panels_layout.addWidget(self.include_frame_cb)

        self.include_table_cb = QCheckBox("Event table")
        self.include_table_cb.setChecked(has_events)
        self.include_table_cb.setEnabled(has_events)
        if not has_events:
            self.include_table_cb.setToolTip("No events loaded for this sample")
        panels_layout.addWidget(self.include_table_cb)

        layout.addWidget(panels_group)

        # ---- Output settings ----
        output_group = QGroupBox("Output")
        output_form = QFormLayout(output_group)
        output_form.setLabelAlignment(Qt.AlignRight)

        self.format_combo = QComboBox()
        self.format_combo.addItem("PNG Image", "png")
        self.format_combo.addItem("TIFF Image", "tiff")
        self.format_combo.addItem("PDF Document", "pdf")
        output_form.addRow("Format:", self.format_combo)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        output_form.addRow("DPI:", self.dpi_spin)

        layout.addWidget(output_group)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.accepted.connect(self._commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Apply initial template
        self._on_template_changed()

    # ------------------------------------------------------------------

    def _on_template_changed(self) -> None:
        idx = self.template_combo.currentIndex()
        if idx < 0 or idx >= len(REPORT_TEMPLATES):
            return

        label, width, height, _desc = REPORT_TEMPLATES[idx]
        is_custom = label == "Custom"
        is_trace_focus = label == "Trace Focus"

        self.width_spin.setEnabled(is_custom)
        self.height_spin.setEnabled(is_custom)

        if not is_custom:
            self.width_spin.blockSignals(True)
            self.height_spin.blockSignals(True)
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
            self.width_spin.blockSignals(False)
            self.height_spin.blockSignals(False)

        # Trace Focus forces frame off
        if is_trace_focus:
            self.include_frame_cb.setChecked(False)
            self.include_frame_cb.setEnabled(False)
        else:
            self.include_frame_cb.setEnabled(self._has_snapshot)
            if self._has_snapshot and not is_trace_focus:
                self.include_frame_cb.setChecked(True)

    def _commit(self) -> None:
        template_label = REPORT_TEMPLATES[self.template_combo.currentIndex()][0]
        self._result = {
            "template": template_label,
            "width": float(self.width_spin.value()),
            "height": float(self.height_spin.value()),
            "include_frame": bool(self.include_frame_cb.isChecked()),
            "include_table": bool(self.include_table_cb.isChecked()),
            "format": self.format_combo.currentData(),
            "dpi": int(self.dpi_spin.value()),
        }
        self.accept()

    def get_settings(self) -> dict[str, Any] | None:
        """Return export settings or None if cancelled."""
        return self._result
