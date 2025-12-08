"""Event Review Panel for efficient event data review workflow."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QKeyEvent
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QFrame,
    QSizePolicy,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

# Review state constants (matching event_review_wizard.py)
REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_CONFIRMED = "CONFIRMED"
REVIEW_EDITED = "EDITED"
REVIEW_NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class EventReviewPanel(QWidget):
    """Docked panel for reviewing event data alongside trace visualization.

    Provides an efficient workflow for reviewing and editing event diameters (ID/OD)
    with keyboard shortcuts, visual feedback, and sampling from traces.

    Signals:
        event_selected: Emitted when user navigates to a different event (index)
        values_changed: Emitted when ID/OD values change (index, id_val, od_val, state)
        sample_requested: Emitted when user requests sampling from trace
        confirm_all_requested: Emitted when user requests to confirm all unreviewed events
        review_completed: Emitted when user closes review mode
    """

    # Signals for coordination with controller
    event_selected = pyqtSignal(int)  # Event index
    values_changed = pyqtSignal(int, object, object, str)  # index, ID, OD, review_state
    sample_requested = pyqtSignal()
    confirm_all_requested = pyqtSignal()  # Request to confirm all unreviewed events
    review_completed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the event review panel.

        Args:
            parent: Parent widget (typically MainWindow)
        """
        super().__init__(parent)
        self.setObjectName("EventReviewPanel")

        # State
        self._current_index: int = 0
        self._total_events: int = 0
        self._current_event_data: tuple | None = None
        self._sampling_mode: bool = False

        # Build UI
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        """Build the panel UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # Header section
        layout.addWidget(self._build_header())

        # Event info section (read-only)
        layout.addWidget(self._build_event_info_section())

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1)

        # Editable values section
        layout.addWidget(self._build_values_section())

        # Sampling button
        layout.addWidget(self._build_sampling_section())

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        # Review state section
        layout.addWidget(self._build_review_state_section())

        # Separator
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep3)

        # Navigation section
        layout.addWidget(self._build_navigation_section())

        # Close button
        layout.addWidget(self._build_close_section())

        # Stretch to push everything to top
        layout.addStretch()

    def _build_header(self) -> QWidget:
        """Build header with title and progress."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Title
        title = QLabel("EVENT REVIEW")
        title.setObjectName("ReviewPanelTitle")
        font = title.font()
        font.setPointSize(11)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        # Progress label
        self.progress_label = QLabel("Event 0/0")
        self.progress_label.setObjectName("ReviewPanelProgress")
        layout.addWidget(self.progress_label)

        return widget

    def _build_event_info_section(self) -> QWidget:
        """Build event info section (label, time)."""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Event label (read-only)
        self.label_value = QLabel("—")
        self.label_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addRow("Event:", self.label_value)

        # Time (read-only)
        self.time_value = QLabel("—")
        self.time_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addRow("Time (s):", self.time_value)

        return widget

    def _build_values_section(self) -> QWidget:
        """Build editable ID/OD values section."""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # ID field (editable)
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("Enter ID")
        validator = QDoubleValidator()
        validator.setDecimals(2)
        validator.setBottom(0.0)
        self.id_input.setValidator(validator)
        self.id_input.editingFinished.connect(self._on_value_changed)
        layout.addRow("ID (µm):", self.id_input)

        # OD field (editable)
        self.od_input = QLineEdit()
        self.od_input.setPlaceholderText("Enter OD")
        validator_od = QDoubleValidator()
        validator_od.setDecimals(2)
        validator_od.setBottom(0.0)
        self.od_input.setValidator(validator_od)
        self.od_input.editingFinished.connect(self._on_value_changed)
        layout.addRow("OD (µm):", self.od_input)

        return widget

    def _build_sampling_section(self) -> QWidget:
        """Build sampling button section."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sample_button = QPushButton("Sample from Trace")
        self.sample_button.setObjectName("SampleButton")
        self.sample_button.setToolTip("Click to enter sampling mode, then click the trace to sample ID/OD values (S)")
        self.sample_button.clicked.connect(self._on_sample_requested)
        self.sample_button.setCheckable(True)
        layout.addWidget(self.sample_button)

        return widget

    def _build_review_state_section(self) -> QWidget:
        """Build review state radio buttons section."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Review State:")
        label.setObjectName("ReviewStateLabel")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)

        # Radio button group
        self.state_button_group = QButtonGroup(self)

        self.state_unreviewed = QRadioButton("Unreviewed")
        self.state_confirmed = QRadioButton("Confirmed")
        self.state_edited = QRadioButton("Edited")
        self.state_followup = QRadioButton("Needs Follow-up")

        self.state_button_group.addButton(self.state_unreviewed, 0)
        self.state_button_group.addButton(self.state_confirmed, 1)
        self.state_button_group.addButton(self.state_edited, 2)
        self.state_button_group.addButton(self.state_followup, 3)

        layout.addWidget(self.state_unreviewed)
        layout.addWidget(self.state_confirmed)
        layout.addWidget(self.state_edited)
        layout.addWidget(self.state_followup)

        # Connect state change
        self.state_button_group.buttonClicked.connect(self._on_state_changed)

        return widget

    def _build_navigation_section(self) -> QWidget:
        """Build navigation buttons section."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Previous/Next row
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)

        self.prev_button = QPushButton("← Previous")
        self.prev_button.setToolTip("Previous event (←)")
        self.prev_button.clicked.connect(self._on_previous)
        nav_row.addWidget(self.prev_button)

        self.next_button = QPushButton("Next →")
        self.next_button.setToolTip("Next event (→ or N)")
        self.next_button.clicked.connect(self._on_next)
        nav_row.addWidget(self.next_button)

        layout.addLayout(nav_row)

        # Confirm Review button
        self.confirm_button = QPushButton("Confirm Review")
        self.confirm_button.setObjectName("ConfirmButton")
        self.confirm_button.setToolTip("Confirm all reviews and close panel (C)")
        self.confirm_button.clicked.connect(self._on_confirm_review)
        layout.addWidget(self.confirm_button)

        return widget

    def _build_close_section(self) -> QWidget:
        """Build close review button."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.close_button = QPushButton("Close Review")
        self.close_button.setToolTip("Exit review mode (Ctrl+Shift+R)")
        self.close_button.clicked.connect(self._on_close_review)
        layout.addWidget(self.close_button)

        return widget

    def _apply_theme(self) -> None:
        """Apply theme styling to panel."""
        accent = CURRENT_THEME.get("accent", "#1D5CFF")

        # Style confirm button with accent color
        self.confirm_button.setStyleSheet(f"""
            QPushButton#ConfirmButton {{
                background-color: {accent};
                color: white;
                font-weight: bold;
                padding: 8px;
                border-radius: 4px;
            }}
            QPushButton#ConfirmButton:hover {{
                background-color: {accent};
                opacity: 0.9;
            }}
            QPushButton#ConfirmButton:disabled {{
                background-color: #CCCCCC;
                color: #666666;
            }}
        """)

    # ---- Public API --------------------------------------------------------

    def set_event(self, index: int, event_data: tuple, state: str, total: int) -> None:
        """Load an event into the panel for review.

        Args:
            index: Event index (0-based)
            event_data: Event tuple (label, time_sec, id_val, od_val, ...)
            state: Review state (UNREVIEWED, CONFIRMED, EDITED, NEEDS_FOLLOWUP)
            total: Total number of events
        """
        self._current_index = index
        self._total_events = total
        self._current_event_data = event_data

        # Update progress
        self.progress_label.setText(f"Event {index + 1}/{total}")

        # Update event info (read-only)
        label = event_data[0] if len(event_data) > 0 else "—"
        time_val = event_data[1] if len(event_data) > 1 else None

        self.label_value.setText(str(label))
        self.time_value.setText("—" if time_val is None else f"{float(time_val):.2f}")

        # Update editable values
        id_val = event_data[2] if len(event_data) > 2 else None
        od_val = event_data[3] if len(event_data) > 3 else None

        self.id_input.setText("" if id_val is None else f"{float(id_val):.2f}")
        self.od_input.setText("" if od_val is None else f"{float(od_val):.2f}")

        # Update review state
        self._set_review_state(state)

        # Update navigation button states
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < total - 1)
        self.confirm_button.setEnabled(total > 0)

    def set_sampled_values(self, id_val: float | None, od_val: float | None) -> None:
        """Update ID/OD fields with sampled values.

        Args:
            id_val: Sampled inner diameter value
            od_val: Sampled outer diameter value
        """
        if id_val is not None:
            self.id_input.setText(f"{float(id_val):.2f}")
        if od_val is not None:
            self.od_input.setText(f"{float(od_val):.2f}")

        # Auto-change state to EDITED when sampling
        self._set_review_state(REVIEW_EDITED)

        # Emit change
        self._on_value_changed()

    def get_edited_values(self) -> tuple[float | None, float | None]:
        """Get current ID/OD values from input fields.

        Returns:
            Tuple of (id_val, od_val) or None if empty/invalid
        """
        id_text = self.id_input.text().strip()
        od_text = self.od_input.text().strip()

        id_val = None
        od_val = None

        if id_text:
            try:
                id_val = float(id_text)
            except ValueError:
                pass

        if od_text:
            try:
                od_val = float(od_text)
            except ValueError:
                pass

        return (id_val, od_val)

    def get_review_state(self) -> str:
        """Get current review state selection.

        Returns:
            Review state string (UNREVIEWED, CONFIRMED, etc.)
        """
        if self.state_confirmed.isChecked():
            return REVIEW_CONFIRMED
        elif self.state_edited.isChecked():
            return REVIEW_EDITED
        elif self.state_followup.isChecked():
            return REVIEW_NEEDS_FOLLOWUP
        else:
            return REVIEW_UNREVIEWED

    def set_sampling_mode(self, enabled: bool) -> None:
        """Update visual state for sampling mode.

        Args:
            enabled: Whether sampling mode is active
        """
        self._sampling_mode = enabled
        self.sample_button.setChecked(enabled)

        if enabled:
            self.sample_button.setText("Sampling... (click trace)")
            self.sample_button.setStyleSheet("""
                QPushButton {
                    background-color: #1D5CFF;
                    color: white;
                    font-weight: bold;
                }
            """)
        else:
            self.sample_button.setText("Sample from Trace")
            self.sample_button.setStyleSheet("")

    # ---- Private helpers ---------------------------------------------------

    def _set_review_state(self, state: str) -> None:
        """Set review state radio button.

        Args:
            state: Review state constant
        """
        state_upper = state.upper() if state else REVIEW_UNREVIEWED

        if state_upper == REVIEW_CONFIRMED:
            self.state_confirmed.setChecked(True)
        elif state_upper == REVIEW_EDITED:
            self.state_edited.setChecked(True)
        elif state_upper == REVIEW_NEEDS_FOLLOWUP:
            self.state_followup.setChecked(True)
        else:
            self.state_unreviewed.setChecked(True)

    # ---- Event handlers ----------------------------------------------------

    def _on_value_changed(self) -> None:
        """Handle ID/OD value change."""
        id_val, od_val = self.get_edited_values()
        state = self.get_review_state()

        # Auto-change to EDITED if values changed and state is UNREVIEWED
        if state == REVIEW_UNREVIEWED and (id_val is not None or od_val is not None):
            if self._current_event_data:
                old_id = self._current_event_data[2] if len(self._current_event_data) > 2 else None
                old_od = self._current_event_data[3] if len(self._current_event_data) > 3 else None

                if id_val != old_id or od_val != old_od:
                    self._set_review_state(REVIEW_EDITED)
                    state = REVIEW_EDITED

        self.values_changed.emit(self._current_index, id_val, od_val, state)

    def _on_state_changed(self) -> None:
        """Handle review state radio button change."""
        # Emit with current values
        self._on_value_changed()

    def _on_sample_requested(self) -> None:
        """Handle sample button click."""
        self.sample_requested.emit()

    def _on_previous(self) -> None:
        """Handle previous button click."""
        if self._current_index > 0:
            self.event_selected.emit(self._current_index - 1)

    def _on_next(self) -> None:
        """Handle next button click."""
        if self._current_index < self._total_events - 1:
            self.event_selected.emit(self._current_index + 1)

    def _on_confirm_review(self) -> None:
        """Handle confirm review button click.

        Confirms all unreviewed events and closes the review panel.
        """
        # Emit signal to controller to confirm all unreviewed events
        self.confirm_all_requested.emit()

        # Then close the review panel
        self._on_close_review()

    def _on_close_review(self) -> None:
        """Handle close review button click."""
        # Find parent dock widget and hide it
        from PyQt5.QtWidgets import QDockWidget

        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QDockWidget):
                parent.hide()
                return
            parent = parent.parent()

        # Fallback: emit signal if dock not found
        self.review_completed.emit()

    # ---- Keyboard shortcuts ------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts.

        Args:
            event: Key press event
        """
        key = event.key()

        # Navigation
        if key == Qt.Key_Right or key == Qt.Key_N:
            self._on_next()
        elif key == Qt.Key_Left or key == Qt.Key_P:
            self._on_previous()
        # Confirm review (confirm all and close panel)
        elif key == Qt.Key_C:
            self._on_confirm_review()
        # Sample mode toggle
        elif key == Qt.Key_S:
            self._on_sample_requested()
        # Exit sampling mode or close panel
        elif key == Qt.Key_Escape:
            if self._sampling_mode:
                self._on_sample_requested()  # Toggle off
            else:
                self._on_close_review()
        # Number keys for review state
        elif key == Qt.Key_1:
            self._set_review_state(REVIEW_UNREVIEWED)
            self._on_state_changed()
        elif key == Qt.Key_2:
            self._set_review_state(REVIEW_CONFIRMED)
            self._on_state_changed()
        elif key == Qt.Key_3:
            self._set_review_state(REVIEW_EDITED)
            self._on_state_changed()
        elif key == Qt.Key_4:
            self._set_review_state(REVIEW_NEEDS_FOLLOWUP)
            self._on_state_changed()
        else:
            # Default handling
            super().keyPressEvent(event)
