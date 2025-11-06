"""Axis editor dialog for publication figures."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

__all__ = ["AxisEditorDialog"]


class AxisEditorDialog(QDialog):
    """Dialog for editing axis properties in publication figures.

    Features:
    - Set X/Y axis limits
    - Edit axis labels
    - Configure tick marks and labels
    - Set axis scales (linear/log)
    - Toggle grid visibility
    """

    axes_changed = pyqtSignal(dict)  # Emitted when axis settings change

    def __init__(self, axes_list: list[Any], parent: QWidget | None = None) -> None:
        """Initialize axis editor.

        Args:
            axes_list: List of matplotlib Axes objects to edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Axis Editor")
        self.setModal(False)
        self.resize(600, 500)

        self._axes_list = axes_list
        self._current_axes: Any = None

        # Build UI
        self._build_ui()

        # Select first axes
        if axes_list:
            self._axes_selector.setCurrentRow(0)

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dialog UI."""
        layout = QHBoxLayout(self)

        # Left: Axes selector
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("<b>Select Axes:</b>"))

        self._axes_selector = QListWidget()
        self._axes_selector.currentItemChanged.connect(self._on_axes_selection_changed)
        left_panel.addWidget(self._axes_selector)

        # Populate axes list
        for i, ax in enumerate(self._axes_list):
            ylabel = ax.get_ylabel() or f"Axes {i + 1}"
            item = QListWidgetItem(ylabel)
            item.setData(Qt.UserRole, ax)
            self._axes_selector.addItem(item)

        layout.addLayout(left_panel, stretch=1)

        # Right: Axis properties
        right_panel = QVBoxLayout()

        # Tab widget for properties
        tabs = QTabWidget()
        tabs.addTab(self._create_limits_tab(), "Limits")
        tabs.addTab(self._create_labels_tab(), "Labels")
        tabs.addTab(self._create_ticks_tab(), "Ticks")
        tabs.addTab(self._create_appearance_tab(), "Appearance")
        right_panel.addWidget(tabs)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)
        button_layout.addWidget(reset_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        right_panel.addLayout(button_layout)

        layout.addLayout(right_panel, stretch=2)

    def _create_limits_tab(self) -> QWidget:
        """Create axis limits tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # X-axis limits
        x_group = QGroupBox("X-Axis Limits")
        x_layout = QFormLayout(x_group)

        self._x_auto_checkbox = QCheckBox("Auto")
        self._x_auto_checkbox.stateChanged.connect(self._on_x_auto_changed)
        x_layout.addRow("", self._x_auto_checkbox)

        self._x_min_spin = QDoubleSpinBox()
        self._x_min_spin.setRange(-1e10, 1e10)
        self._x_min_spin.setDecimals(3)
        x_layout.addRow("Min:", self._x_min_spin)

        self._x_max_spin = QDoubleSpinBox()
        self._x_max_spin.setRange(-1e10, 1e10)
        self._x_max_spin.setDecimals(3)
        x_layout.addRow("Max:", self._x_max_spin)

        layout.addWidget(x_group)

        # Y-axis limits
        y_group = QGroupBox("Y-Axis Limits")
        y_layout = QFormLayout(y_group)

        self._y_auto_checkbox = QCheckBox("Auto")
        self._y_auto_checkbox.stateChanged.connect(self._on_y_auto_changed)
        y_layout.addRow("", self._y_auto_checkbox)

        self._y_min_spin = QDoubleSpinBox()
        self._y_min_spin.setRange(-1e10, 1e10)
        self._y_min_spin.setDecimals(3)
        y_layout.addRow("Min:", self._y_min_spin)

        self._y_max_spin = QDoubleSpinBox()
        self._y_max_spin.setRange(-1e10, 1e10)
        self._y_max_spin.setDecimals(3)
        y_layout.addRow("Max:", self._y_max_spin)

        layout.addWidget(y_group)

        layout.addStretch()

        return widget

    def _create_labels_tab(self) -> QWidget:
        """Create axis labels tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        # X-axis label
        self._x_label_edit = QLineEdit()
        self._x_label_edit.setPlaceholderText("e.g., Time (s)")
        layout.addRow("X-Axis Label:", self._x_label_edit)

        # Y-axis label
        self._y_label_edit = QLineEdit()
        self._y_label_edit.setPlaceholderText("e.g., Diameter (µm)")
        layout.addRow("Y-Axis Label:", self._y_label_edit)

        # Title
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Optional title")
        layout.addRow("Title:", self._title_edit)

        layout.addRow(QLabel("<i>Use Unicode for special characters (µ, ², ³, etc.)</i>"))

        return widget

    def _create_ticks_tab(self) -> QWidget:
        """Create ticks configuration tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        # X-axis ticks
        self._x_tick_count_spin = QSpinBox()
        self._x_tick_count_spin.setRange(2, 50)
        self._x_tick_count_spin.setValue(5)
        self._x_tick_count_spin.setSpecialValueText("Auto")
        layout.addRow("X-Axis Tick Count:", self._x_tick_count_spin)

        # Y-axis ticks
        self._y_tick_count_spin = QSpinBox()
        self._y_tick_count_spin.setRange(2, 50)
        self._y_tick_count_spin.setValue(5)
        self._y_tick_count_spin.setSpecialValueText("Auto")
        layout.addRow("Y-Axis Tick Count:", self._y_tick_count_spin)

        # Tick label visibility
        self._x_tick_labels_checkbox = QCheckBox("Show X-Axis Tick Labels")
        self._x_tick_labels_checkbox.setChecked(True)
        layout.addRow("", self._x_tick_labels_checkbox)

        self._y_tick_labels_checkbox = QCheckBox("Show Y-Axis Tick Labels")
        self._y_tick_labels_checkbox.setChecked(True)
        layout.addRow("", self._y_tick_labels_checkbox)

        layout.addRow(QLabel("<i>Tick configuration affects visual appearance only</i>"))

        return widget

    def _create_appearance_tab(self) -> QWidget:
        """Create appearance tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        # Scale type
        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["linear", "log"])
        layout.addRow("X-Axis Scale:", self._x_scale_combo)

        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["linear", "log"])
        layout.addRow("Y-Axis Scale:", self._y_scale_combo)

        # Grid
        self._grid_checkbox = QCheckBox("Show Grid")
        layout.addRow("", self._grid_checkbox)

        self._grid_which_combo = QComboBox()
        self._grid_which_combo.addItems(["both", "major", "minor"])
        layout.addRow("Grid Lines:", self._grid_which_combo)

        # Spines
        self._top_spine_checkbox = QCheckBox("Show Top Spine")
        layout.addRow("", self._top_spine_checkbox)

        self._right_spine_checkbox = QCheckBox("Show Right Spine")
        layout.addRow("", self._right_spine_checkbox)

        return widget

    # ------------------------------------------------------------------ Event Handlers

    def _on_axes_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        """Handle axes selection change."""
        if current is None:
            self._current_axes = None
            return

        axes = current.data(Qt.UserRole)
        self._current_axes = axes
        self._load_axes_properties(axes)

    def _load_axes_properties(self, axes: Any) -> None:
        """Load axes properties into UI."""
        if axes is None:
            return

        # Block signals while loading
        self._block_signals(True)

        try:
            # Limits
            xlim = axes.get_xlim()
            ylim = axes.get_ylim()

            self._x_min_spin.setValue(xlim[0])
            self._x_max_spin.setValue(xlim[1])
            self._y_min_spin.setValue(ylim[0])
            self._y_max_spin.setValue(ylim[1])

            self._x_auto_checkbox.setChecked(False)
            self._y_auto_checkbox.setChecked(False)

            # Labels
            self._x_label_edit.setText(axes.get_xlabel())
            self._y_label_edit.setText(axes.get_ylabel())
            self._title_edit.setText(axes.get_title())

            # Scale
            self._x_scale_combo.setCurrentText(axes.get_xscale())
            self._y_scale_combo.setCurrentText(axes.get_yscale())

            # Grid
            grid_visible = axes.xaxis._gridOnMajor or axes.yaxis._gridOnMajor
            self._grid_checkbox.setChecked(grid_visible)

            # Spines
            self._top_spine_checkbox.setChecked(axes.spines['top'].get_visible())
            self._right_spine_checkbox.setChecked(axes.spines['right'].get_visible())

            # Tick labels
            self._x_tick_labels_checkbox.setChecked(axes.xaxis.get_tick_params()['labelbottom'])
            self._y_tick_labels_checkbox.setChecked(axes.yaxis.get_tick_params()['labelleft'])

        finally:
            self._block_signals(False)

    def _block_signals(self, block: bool) -> None:
        """Block/unblock signals from all controls."""
        for widget in [
            self._x_min_spin,
            self._x_max_spin,
            self._y_min_spin,
            self._y_max_spin,
            self._x_auto_checkbox,
            self._y_auto_checkbox,
            self._x_label_edit,
            self._y_label_edit,
            self._title_edit,
            self._x_scale_combo,
            self._y_scale_combo,
            self._grid_checkbox,
            self._grid_which_combo,
            self._top_spine_checkbox,
            self._right_spine_checkbox,
            self._x_tick_labels_checkbox,
            self._y_tick_labels_checkbox,
        ]:
            widget.blockSignals(block)

    def _on_x_auto_changed(self, state: int) -> None:
        """Handle X-axis auto checkbox change."""
        auto = state == Qt.Checked
        self._x_min_spin.setEnabled(not auto)
        self._x_max_spin.setEnabled(not auto)

    def _on_y_auto_changed(self, state: int) -> None:
        """Handle Y-axis auto checkbox change."""
        auto = state == Qt.Checked
        self._y_min_spin.setEnabled(not auto)
        self._y_max_spin.setEnabled(not auto)

    def _on_apply(self) -> None:
        """Apply changes to current axes."""
        if self._current_axes is None:
            return

        axes = self._current_axes

        # Apply limits
        if not self._x_auto_checkbox.isChecked():
            axes.set_xlim(self._x_min_spin.value(), self._x_max_spin.value())

        if not self._y_auto_checkbox.isChecked():
            axes.set_ylim(self._y_min_spin.value(), self._y_max_spin.value())

        # Apply labels
        axes.set_xlabel(self._x_label_edit.text())
        axes.set_ylabel(self._y_label_edit.text())
        axes.set_title(self._title_edit.text())

        # Apply scale
        axes.set_xscale(self._x_scale_combo.currentText())
        axes.set_yscale(self._y_scale_combo.currentText())

        # Apply grid
        if self._grid_checkbox.isChecked():
            axes.grid(True, which=self._grid_which_combo.currentText())
        else:
            axes.grid(False)

        # Apply spines
        axes.spines['top'].set_visible(self._top_spine_checkbox.isChecked())
        axes.spines['right'].set_visible(self._right_spine_checkbox.isChecked())

        # Apply tick label visibility
        axes.tick_params(labelbottom=self._x_tick_labels_checkbox.isChecked())
        axes.tick_params(labelleft=self._y_tick_labels_checkbox.isChecked())

        # Emit signal
        self.axes_changed.emit({"axes": axes})

        # Redraw canvas
        if hasattr(axes.figure, "canvas"):
            axes.figure.canvas.draw_idle()

    def _on_reset(self) -> None:
        """Reset current axes to defaults."""
        if self._current_axes is None:
            return

        axes = self._current_axes

        # Reset to autoscale
        axes.autoscale()

        # Reload properties
        self._load_axes_properties(axes)

        # Redraw
        if hasattr(axes.figure, "canvas"):
            axes.figure.canvas.draw_idle()


if __name__ == "__main__":
    import sys

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = AxisEditorDialog([])
    dialog.show()
    sys.exit(app.exec_())
