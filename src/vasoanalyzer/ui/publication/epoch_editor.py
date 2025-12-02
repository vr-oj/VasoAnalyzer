"""Epoch editor dialog for managing protocol timeline overlays."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
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

from vasoanalyzer.ui.publication.epoch_model import Epoch

__all__ = ["EpochEditorDialog"]


class EpochEditorDialog(QDialog):
    """Dialog for editing epoch timeline overlays.

    Features:
    - List view of epochs
    - Properties editor for selected epoch
    - Add/remove/duplicate epochs
    - Live preview updates
    """

    epochs_changed = pyqtSignal(list)  # Emitted when epochs are modified

    def __init__(self, epochs: list[Epoch], parent: QWidget | None = None) -> None:
        """Initialize epoch editor.

        Args:
            epochs: Initial list of epochs to edit
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Epoch Editor")
        self.setModal(False)
        self.resize(700, 500)

        # State
        self._epochs = [self._copy_epoch(e) for e in epochs]
        self._current_epoch: Epoch | None = None

        # Build UI
        self._build_ui()
        self._populate_list()

    def get_epochs(self) -> list[Epoch]:
        """Get current epoch list."""
        return [self._copy_epoch(e) for e in self._epochs]

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget
        tabs = QTabWidget()
        tabs.addTab(self._create_list_tab(), "Epochs")
        tabs.addTab(self._create_properties_tab(), "Properties")
        tabs.addTab(self._create_appearance_tab(), "Appearance")
        layout.addWidget(tabs)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_list_tab(self) -> QWidget:
        """Create epoch list tab."""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # List widget
        self._epoch_list = QListWidget()
        self._epoch_list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._epoch_list)

        # Buttons
        button_layout = QVBoxLayout()

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._on_add)
        button_layout.addWidget(add_btn)

        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self._on_duplicate)
        button_layout.addWidget(duplicate_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        button_layout.addWidget(remove_btn)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        return widget

    def _create_properties_tab(self) -> QWidget:
        """Create properties editor tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        # Channel
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(["Pressure", "Drug", "Blocker", "Perfusate", "Custom"])
        self._channel_combo.currentTextChanged.connect(self._on_property_changed)
        layout.addRow("Channel:", self._channel_combo)

        # Label
        self._label_edit = QLineEdit()
        self._label_edit.textChanged.connect(self._on_property_changed)
        layout.addRow("Label:", self._label_edit)

        # Start time
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 100000.0)
        self._start_spin.setDecimals(1)
        self._start_spin.setSuffix(" s")
        self._start_spin.valueChanged.connect(self._on_property_changed)
        layout.addRow("Start Time:", self._start_spin)

        # End time
        self._end_spin = QDoubleSpinBox()
        self._end_spin.setRange(0.0, 100000.0)
        self._end_spin.setDecimals(1)
        self._end_spin.setSuffix(" s")
        self._end_spin.valueChanged.connect(self._on_property_changed)
        layout.addRow("End Time:", self._end_spin)

        # Style
        self._style_combo = QComboBox()
        self._style_combo.addItems(["bar", "box", "shade"])
        self._style_combo.currentTextChanged.connect(self._on_property_changed)
        layout.addRow("Style:", self._style_combo)

        # Emphasis
        self._emphasis_combo = QComboBox()
        self._emphasis_combo.addItems(["light", "normal", "strong"])
        self._emphasis_combo.currentTextChanged.connect(self._on_property_changed)
        layout.addRow("Emphasis:", self._emphasis_combo)

        # Color
        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("e.g., #1f77b4 or leave empty for default")
        self._color_edit.textChanged.connect(self._on_property_changed)
        layout.addRow("Color:", self._color_edit)

        layout.addRow(QLabel("<i>Color should be hex code (e.g., #1f77b4) or empty for default</i>"))

        return widget

    def _create_appearance_tab(self) -> QWidget:
        """Create appearance settings tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        layout.addRow(QLabel("<b>Global Appearance Settings</b>"))
        layout.addRow(QLabel("<i>Row order and styling can be configured here</i>"))
        layout.addRow(QLabel("<i>(To be implemented)</i>"))

        return widget

    # ------------------------------------------------------------------ Data Management

    def _populate_list(self) -> None:
        """Populate epoch list widget."""
        self._epoch_list.clear()

        for epoch in self._epochs:
            item = QListWidgetItem(f"{epoch.channel}: {epoch.label} ({epoch.t_start:.1f}s - {epoch.t_end:.1f}s)")
            item.setData(Qt.UserRole, epoch.id)
            self._epoch_list.addItem(item)

        if self._epochs:
            self._epoch_list.setCurrentRow(0)

    def _on_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        """Handle epoch selection change."""
        if current is None:
            self._current_epoch = None
            self._clear_properties()
            return

        epoch_id = current.data(Qt.UserRole)
        epoch = next((e for e in self._epochs if e.id == epoch_id), None)

        if epoch is None:
            return

        self._current_epoch = epoch
        self._update_properties(epoch)

    def _update_properties(self, epoch: Epoch) -> None:
        """Update properties editor with epoch data."""
        # Block signals to prevent triggering updates
        self._channel_combo.blockSignals(True)
        self._label_edit.blockSignals(True)
        self._start_spin.blockSignals(True)
        self._end_spin.blockSignals(True)
        self._style_combo.blockSignals(True)
        self._emphasis_combo.blockSignals(True)
        self._color_edit.blockSignals(True)

        self._channel_combo.setCurrentText(epoch.channel)
        self._label_edit.setText(epoch.label)
        self._start_spin.setValue(epoch.t_start)
        self._end_spin.setValue(epoch.t_end)
        self._style_combo.setCurrentText(epoch.style)
        self._emphasis_combo.setCurrentText(epoch.emphasis)
        self._color_edit.setText(epoch.color or "")

        # Unblock signals
        self._channel_combo.blockSignals(False)
        self._label_edit.blockSignals(False)
        self._start_spin.blockSignals(False)
        self._end_spin.blockSignals(False)
        self._style_combo.blockSignals(False)
        self._emphasis_combo.blockSignals(False)
        self._color_edit.blockSignals(False)

    def _clear_properties(self) -> None:
        """Clear properties editor."""
        self._channel_combo.setCurrentIndex(0)
        self._label_edit.clear()
        self._start_spin.setValue(0.0)
        self._end_spin.setValue(0.0)
        self._style_combo.setCurrentIndex(0)
        self._emphasis_combo.setCurrentIndex(1)  # "normal"
        self._color_edit.clear()

    def _on_property_changed(self) -> None:
        """Handle property change."""
        if self._current_epoch is None:
            return

        # Update current epoch with new values
        try:
            # Find epoch in list
            idx = next((i for i, e in enumerate(self._epochs) if e.id == self._current_epoch.id), None)
            if idx is None:
                return

            # Create updated epoch
            color_text = self._color_edit.text().strip()
            color = color_text if color_text else None

            updated = Epoch(
                id=self._current_epoch.id,
                channel=self._channel_combo.currentText(),
                label=self._label_edit.text(),
                t_start=self._start_spin.value(),
                t_end=self._end_spin.value(),
                style=self._style_combo.currentText(),  # type: ignore
                color=color,
                emphasis=self._emphasis_combo.currentText(),  # type: ignore
                row_index=self._current_epoch.row_index,
                meta=self._current_epoch.meta.copy(),
            )

            # Update in list
            self._epochs[idx] = updated
            self._current_epoch = updated

            # Update list item text
            current_item = self._epoch_list.currentItem()
            if current_item is not None:
                current_item.setText(
                    f"{updated.channel}: {updated.label} ({updated.t_start:.1f}s - {updated.t_end:.1f}s)"
                )

        except Exception:
            # Ignore validation errors during editing
            pass

    # ------------------------------------------------------------------ Actions

    def _on_add(self) -> None:
        """Add new epoch."""
        # Create default epoch
        epoch_id = f"epoch_{len(self._epochs)}"
        epoch = Epoch(
            id=epoch_id,
            channel="Drug",
            label="New Epoch",
            t_start=0.0,
            t_end=60.0,
            style="bar",
            color=None,
            emphasis="normal",
        )

        self._epochs.append(epoch)
        self._populate_list()
        self._epoch_list.setCurrentRow(len(self._epochs) - 1)

    def _on_duplicate(self) -> None:
        """Duplicate selected epoch."""
        if self._current_epoch is None:
            return

        # Create copy with new ID
        epoch_id = f"epoch_{len(self._epochs)}"
        duplicated = Epoch(
            id=epoch_id,
            channel=self._current_epoch.channel,
            label=self._current_epoch.label + " (copy)",
            t_start=self._current_epoch.t_start,
            t_end=self._current_epoch.t_end,
            style=self._current_epoch.style,
            color=self._current_epoch.color,
            emphasis=self._current_epoch.emphasis,
            row_index=self._current_epoch.row_index,
            meta=self._current_epoch.meta.copy(),
        )

        self._epochs.append(duplicated)
        self._populate_list()
        self._epoch_list.setCurrentRow(len(self._epochs) - 1)

    def _on_remove(self) -> None:
        """Remove selected epoch."""
        if self._current_epoch is None:
            return

        # Remove epoch
        self._epochs = [e for e in self._epochs if e.id != self._current_epoch.id]
        self._populate_list()

    def _on_apply(self) -> None:
        """Apply changes and emit signal."""
        self.epochs_changed.emit(self.get_epochs())

    @staticmethod
    def _copy_epoch(epoch: Epoch) -> Epoch:
        """Create a copy of an epoch."""
        return Epoch(
            id=epoch.id,
            channel=epoch.channel,
            label=epoch.label,
            t_start=epoch.t_start,
            t_end=epoch.t_end,
            style=epoch.style,
            color=epoch.color,
            emphasis=epoch.emphasis,
            row_index=epoch.row_index,
            meta=epoch.meta.copy(),
        )
