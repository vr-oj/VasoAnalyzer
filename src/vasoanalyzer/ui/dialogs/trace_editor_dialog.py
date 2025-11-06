"""Trace editor dialog for publication figures."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["TraceEditorDialog"]


class TraceEditorDialog(QDialog):
    """Dialog for editing trace/line properties in publication figures.

    Features:
    - Edit line colors, widths, styles
    - Toggle trace visibility
    - Set markers and marker sizes
    - Configure line alpha/transparency
    """

    traces_changed = pyqtSignal(dict)  # Emitted when trace settings change

    def __init__(self, axes_list: list[Any], parent: QWidget | None = None) -> None:
        """Initialize trace editor.

        Args:
            axes_list: List of matplotlib Axes objects containing traces
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Trace Editor")
        self.setModal(False)
        self.resize(600, 500)

        self._axes_list = axes_list
        self._traces: list[Any] = []
        self._current_trace: Any = None

        # Collect all line artists from axes
        self._collect_traces()

        # Build UI
        self._build_ui()

        # Select first trace
        if self._traces:
            self._trace_selector.setCurrentRow(0)

    # ------------------------------------------------------------------ Data Collection

    def _collect_traces(self) -> None:
        """Collect all line artists from axes."""
        self._traces = []
        for axes in self._axes_list:
            for line in axes.get_lines():
                self._traces.append(line)

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dialog UI."""
        layout = QHBoxLayout(self)

        # Left: Trace selector
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("<b>Select Trace:</b>"))

        self._trace_selector = QListWidget()
        self._trace_selector.currentItemChanged.connect(self._on_trace_selection_changed)
        left_panel.addWidget(self._trace_selector)

        # Populate trace list
        for i, line in enumerate(self._traces):
            label = line.get_label() or f"Trace {i + 1}"
            if label.startswith("_"):  # Skip internal matplotlib labels
                label = f"Trace {i + 1}"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, line)

            # Show line color as item foreground
            color = line.get_color()
            if color:
                try:
                    qcolor = QColor(color)
                    item.setForeground(qcolor)
                except Exception:
                    pass

            self._trace_selector.addItem(item)

        layout.addLayout(left_panel, stretch=1)

        # Right: Trace properties
        right_panel = QVBoxLayout()

        # Properties group
        props_group = QGroupBox("Trace Properties")
        props_layout = QFormLayout(props_group)

        # Visibility
        self._visible_checkbox = QCheckBox("Visible")
        self._visible_checkbox.stateChanged.connect(self._on_property_changed)
        props_layout.addRow("", self._visible_checkbox)

        # Color
        color_layout = QHBoxLayout()
        self._color_display = QLabel()
        self._color_display.setFixedSize(30, 20)
        self._color_display.setStyleSheet("border: 1px solid black;")
        color_layout.addWidget(self._color_display)

        self._color_button = QPushButton("Change Color...")
        self._color_button.clicked.connect(self._on_choose_color)
        color_layout.addWidget(self._color_button)
        color_layout.addStretch()

        props_layout.addRow("Color:", color_layout)

        # Line width
        self._linewidth_spin = QDoubleSpinBox()
        self._linewidth_spin.setRange(0.1, 10.0)
        self._linewidth_spin.setDecimals(1)
        self._linewidth_spin.setSingleStep(0.5)
        self._linewidth_spin.valueChanged.connect(self._on_property_changed)
        props_layout.addRow("Line Width:", self._linewidth_spin)

        # Line style
        self._linestyle_combo = QComboBox()
        self._linestyle_combo.addItems(["-", "--", "-.", ":", "None"])
        self._linestyle_combo.currentTextChanged.connect(self._on_property_changed)
        props_layout.addRow("Line Style:", self._linestyle_combo)

        # Alpha
        self._alpha_spin = QDoubleSpinBox()
        self._alpha_spin.setRange(0.0, 1.0)
        self._alpha_spin.setDecimals(2)
        self._alpha_spin.setSingleStep(0.1)
        self._alpha_spin.valueChanged.connect(self._on_property_changed)
        props_layout.addRow("Alpha:", self._alpha_spin)

        # Marker
        self._marker_combo = QComboBox()
        self._marker_combo.addItems(["None", "o", "s", "^", "v", "D", "*", "+", "x"])
        self._marker_combo.currentTextChanged.connect(self._on_property_changed)
        props_layout.addRow("Marker:", self._marker_combo)

        # Marker size
        self._markersize_spin = QDoubleSpinBox()
        self._markersize_spin.setRange(0.0, 20.0)
        self._markersize_spin.setDecimals(1)
        self._markersize_spin.setSingleStep(1.0)
        self._markersize_spin.valueChanged.connect(self._on_property_changed)
        props_layout.addRow("Marker Size:", self._markersize_spin)

        right_panel.addWidget(props_group)

        # Z-order group
        zorder_group = QGroupBox("Layer Order")
        zorder_layout = QFormLayout(zorder_group)

        self._zorder_spin = QDoubleSpinBox()
        self._zorder_spin.setRange(-100, 100)
        self._zorder_spin.setDecimals(0)
        self._zorder_spin.valueChanged.connect(self._on_property_changed)
        zorder_layout.addRow("Z-Order:", self._zorder_spin)

        zorder_layout.addRow(QLabel("<i>Higher values appear on top</i>"))

        right_panel.addWidget(zorder_group)

        right_panel.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        right_panel.addLayout(button_layout)

        layout.addLayout(right_panel, stretch=2)

    # ------------------------------------------------------------------ Event Handlers

    def _on_trace_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        """Handle trace selection change."""
        if current is None:
            self._current_trace = None
            return

        line = current.data(Qt.UserRole)
        self._current_trace = line
        self._load_trace_properties(line)

    def _load_trace_properties(self, line: Any) -> None:
        """Load trace properties into UI."""
        if line is None:
            return

        # Block signals while loading
        self._block_signals(True)

        try:
            # Visibility
            self._visible_checkbox.setChecked(line.get_visible())

            # Color
            color = line.get_color()
            if color:
                try:
                    qcolor = QColor(color)
                    self._color_display.setStyleSheet(f"background-color: {qcolor.name()}; border: 1px solid black;")
                except Exception:
                    pass

            # Line width
            self._linewidth_spin.setValue(line.get_linewidth())

            # Line style
            linestyle = line.get_linestyle()
            if linestyle == "solid":
                linestyle = "-"
            elif linestyle == "dashed":
                linestyle = "--"
            elif linestyle == "dashdot":
                linestyle = "-."
            elif linestyle == "dotted":
                linestyle = ":"

            self._linestyle_combo.setCurrentText(linestyle)

            # Alpha
            alpha = line.get_alpha()
            if alpha is None:
                alpha = 1.0
            self._alpha_spin.setValue(alpha)

            # Marker
            marker = line.get_marker()
            if marker == "none" or marker == "None":
                marker = "None"
            self._marker_combo.setCurrentText(marker)

            # Marker size
            self._markersize_spin.setValue(line.get_markersize())

            # Z-order
            self._zorder_spin.setValue(line.get_zorder())

        finally:
            self._block_signals(False)

    def _block_signals(self, block: bool) -> None:
        """Block/unblock signals from all controls."""
        for widget in [
            self._visible_checkbox,
            self._linewidth_spin,
            self._linestyle_combo,
            self._alpha_spin,
            self._marker_combo,
            self._markersize_spin,
            self._zorder_spin,
        ]:
            widget.blockSignals(block)

    def _on_property_changed(self) -> None:
        """Handle property change (for live preview)."""
        # Could implement live preview here
        pass

    def _on_choose_color(self) -> None:
        """Open color picker dialog."""
        if self._current_trace is None:
            return

        current_color = self._current_trace.get_color()
        qcolor = QColor(current_color) if current_color else QColor(Qt.blue)

        color = QColorDialog.getColor(qcolor, self, "Choose Trace Color")

        if color.isValid():
            self._color_display.setStyleSheet(f"background-color: {color.name()}; border: 1px solid black;")

    def _on_apply(self) -> None:
        """Apply changes to current trace."""
        if self._current_trace is None:
            return

        line = self._current_trace

        # Apply visibility
        line.set_visible(self._visible_checkbox.isChecked())

        # Apply color
        color_style = self._color_display.styleSheet()
        if "background-color:" in color_style:
            import re

            match = re.search(r"background-color:\s*([^;]+)", color_style)
            if match:
                color = match.group(1).strip()
                line.set_color(color)

        # Apply line width
        line.set_linewidth(self._linewidth_spin.value())

        # Apply line style
        line.set_linestyle(self._linestyle_combo.currentText())

        # Apply alpha
        line.set_alpha(self._alpha_spin.value())

        # Apply marker
        marker = self._marker_combo.currentText()
        if marker == "None":
            marker = ""
        line.set_marker(marker)

        # Apply marker size
        line.set_markersize(self._markersize_spin.value())

        # Apply z-order
        line.set_zorder(self._zorder_spin.value())

        # Emit signal
        self.traces_changed.emit({"line": line})

        # Redraw canvas
        if hasattr(line.axes, "figure") and hasattr(line.axes.figure, "canvas"):
            line.axes.figure.canvas.draw_idle()


if __name__ == "__main__":
    import sys

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = TraceEditorDialog([])
    dialog.show()
    sys.exit(app.exec_())
