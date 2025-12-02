from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_CONFIRMED = "CONFIRMED"
REVIEW_EDITED = "EDITED"
REVIEW_NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class EventReviewWizard(QDialog):
    """Guided review dialog for stepping through events and confirming values."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        events: Sequence[Sequence[Any]],
        review_states: Sequence[str] | None = None,
        focus_event_callback: Callable[[int, tuple | None], None] | None = None,
        sample_values_callback: Callable[[float], Sequence[Any]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Events")
        self._row_lengths = [len(evt) for evt in events]
        self._original_events = [self._normalize_event(evt) for evt in events]
        self._events = [list(self._normalize_event(evt)) for evt in events]
        self._review_states = self._normalise_states(review_states, len(self._events))
        self._focus_event_callback = focus_event_callback
        self._sample_values_callback = sample_values_callback
        self._current_index = 0

        self._build_ui()
        self._load_current_event()

    # UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.progress_label = QLabel("", self)
        layout.addWidget(self.progress_label)

        form = QFormLayout()
        self.label_value = QLabel("")
        self.time_value = QLabel("")
        self.id_input = QLineEdit()
        self.od_input = QLineEdit()
        self.avg_p_input = QLineEdit()
        self.set_p_input = QLineEdit()
        self.state_combo = QComboBox()
        self.state_combo.addItems(
            [
                "Unreviewed",
                "Confirmed",
                "Edited",
                "Needs follow-up",
            ]
        )

        form.addRow("Event", self.label_value)
        form.addRow("Time (s)", self.time_value)
        form.addRow("ID (µm)", self.id_input)
        form.addRow("OD (µm)", self.od_input)
        form.addRow("Avg P (mmHg)", self.avg_p_input)
        form.addRow("Set P (mmHg)", self.set_p_input)
        form.addRow("Review state", self.state_combo)
        layout.addLayout(form)

        nav_row = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.confirm_button = QPushButton("Confirm & Next")
        self.prev_button.clicked.connect(self._go_previous)
        self.next_button.clicked.connect(self._go_next)
        self.confirm_button.clicked.connect(self._confirm_and_next)
        nav_row.addWidget(self.prev_button)
        nav_row.addWidget(self.next_button)
        nav_row.addWidget(self.confirm_button)
        layout.addLayout(nav_row)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # Helpers -------------------------------------------------------------
    def _normalise_states(self, states: Sequence[str] | None, length: int) -> list[str]:
        incoming = list(states or [])
        if len(incoming) < length:
            incoming.extend([REVIEW_UNREVIEWED] * (length - len(incoming)))
        elif len(incoming) > length:
            incoming = incoming[:length]
        normalised: list[str] = []
        for state in incoming:
            if isinstance(state, str) and state.strip():
                normalised.append(state.strip().upper())
            else:
                normalised.append(REVIEW_UNREVIEWED)
        return normalised

    def _normalize_event(self, evt: Sequence[Any]) -> tuple:
        values = list(evt)
        if len(values) >= 7:
            return tuple(values[:7])
        if len(values) == 5:
            label, time_val, id_val, od_val, frame = values
            return (label, time_val, id_val, od_val, None, None, frame)
        if len(values) == 6:
            label, time_val, id_val, od_val, avg_val, frame = values
            return (label, time_val, id_val, od_val, avg_val, None, frame)
        if len(values) == 4:
            label, time_val, id_val, frame = values
            return (label, time_val, id_val, None, None, None, frame)
        if len(values) < 4:
            values.extend([None] * (4 - len(values)))
            label, time_val, id_val, frame = values[:4]
            return (label, time_val, id_val, None, None, None, frame)
        # len(values) == 6 or other edge cases
        values.extend([None] * (7 - len(values)))
        return tuple(values[:7])

    def _state_to_label(self, state: str) -> str:
        mapping = {
            REVIEW_UNREVIEWED: "Unreviewed",
            REVIEW_CONFIRMED: "Confirmed",
            REVIEW_EDITED: "Edited",
            REVIEW_NEEDS_FOLLOWUP: "Needs follow-up",
        }
        return mapping.get(state, "Unreviewed")

    def _label_to_state(self, label: str) -> str:
        norm = label.strip().lower()
        mapping = {
            "unreviewed": REVIEW_UNREVIEWED,
            "confirmed": REVIEW_CONFIRMED,
            "edited": REVIEW_EDITED,
            "needs follow-up": REVIEW_NEEDS_FOLLOWUP,
            "needs follow up": REVIEW_NEEDS_FOLLOWUP,
        }
        return mapping.get(norm, REVIEW_UNREVIEWED)

    def _load_current_event(self) -> None:
        if not self._events:
            return
        idx = self._current_index
        total = len(self._events)
        evt = self._events[idx]
        row_len = self._row_lengths[idx] if idx < len(self._row_lengths) else len(evt)
        self.progress_label.setText(f"Event {idx + 1} of {total}")

        self.label_value.setText(str(evt[0]) if len(evt) > 0 else "")
        time_val = evt[1] if len(evt) > 1 else None
        self.time_value.setText("—" if time_val is None else f"{float(time_val):.2f}")
        self.id_input.setText(self._format_value(evt, 2))
        has_od = row_len >= 5
        has_avg = row_len > 5
        has_set = row_len > 6
        self.od_input.setEnabled(has_od)
        self.avg_p_input.setEnabled(has_avg)
        self.set_p_input.setEnabled(has_set)
        self.od_input.setText(self._format_value(evt, 3) if has_od else "")
        self.avg_p_input.setText(self._format_value(evt, 4) if has_avg else "")
        self.set_p_input.setText(self._format_value(evt, 5) if has_set else "")
        state_label = self._state_to_label(self._review_states[idx])
        self.state_combo.setCurrentText(state_label)

        self.prev_button.setEnabled(idx > 0)
        self.next_button.setEnabled(idx < total - 1)

        if callable(self._focus_event_callback):
            with_context = tuple(evt) if not isinstance(evt, tuple) else evt
            self._focus_event_callback(idx, with_context)

    def _format_value(self, evt: Sequence[Any], index: int) -> str:
        if len(evt) <= index:
            return ""
        val = evt[index]
        if val is None:
            return ""
        try:
            return f"{float(val):.2f}"
        except (TypeError, ValueError):
            return str(val)

    def _parse_float(self, text: str) -> float | None:
        stripped = text.strip()
        if stripped == "":
            return None
        try:
            return float(stripped)
        except ValueError:
            return None

    def _apply_current_edits(self) -> None:
        if not self._events:
            return
        idx = self._current_index
        current = self._events[idx]
        if len(current) < 7:
            # Ensure tuple has correct length for updates
            missing = 7 - len(current)
            current = list(current) + [None] * missing
        updated = list(current[:7])
        selected_state = self._label_to_state(self.state_combo.currentText())

        id_val = self._parse_float(self.id_input.text())
        od_val = self._parse_float(self.od_input.text())
        avg_val = self._parse_float(self.avg_p_input.text())
        set_val = self._parse_float(self.set_p_input.text())

        if id_val is not None:
            updated[2] = round(id_val, 2)
        if od_val is not None or (od_val is None and len(updated) > 3):
            updated[3] = None if od_val is None else round(od_val, 2)
        if avg_val is not None or (avg_val is None and len(updated) > 4):
            updated[4] = None if avg_val is None else round(avg_val, 2)
        if set_val is not None or (set_val is None and len(updated) > 5):
            updated[5] = None if set_val is None else round(set_val, 2)

        self._review_states[idx] = selected_state
        if (
            tuple(updated) != self._original_events[idx]
            and self._review_states[idx] == REVIEW_UNREVIEWED
        ):
            self._review_states[idx] = REVIEW_EDITED

        self._events[idx] = updated

    def handle_trace_click(self, time_sec: float) -> None:
        """Update the current event using sampled values at ``time_sec``."""
        if self._sample_values_callback is None or not self._events:
            return
        idx = self._current_index
        if not (0 <= idx < len(self._events)):
            return
        try:
            sampled = self._sample_values_callback(time_sec)
        except Exception:
            return
        if not sampled or len(sampled) < 4:
            return
        try:
            id_val, od_val, avg_val, set_val = sampled[:4]
        except Exception:
            return
        if all(val is None for val in (id_val, od_val, avg_val, set_val)):
            return

        row_len = self._row_lengths[idx] if idx < len(self._row_lengths) else len(self._events[idx])
        has_od = row_len >= 5
        has_avg = row_len > 5
        has_set = row_len > 6

        def _set_text(widget: QLineEdit, value: Any) -> None:
            try:
                widget.setText(f"{float(value):.2f}")
            except Exception:
                return

        if id_val is not None:
            _set_text(self.id_input, id_val)
        if has_od and od_val is not None:
            _set_text(self.od_input, od_val)
        if has_avg and avg_val is not None:
            _set_text(self.avg_p_input, avg_val)
        if has_set and set_val is not None:
            _set_text(self.set_p_input, set_val)

        self.state_combo.setCurrentText("Edited")
        self._apply_current_edits()

    def _go_next(self) -> None:
        self._apply_current_edits()
        if self._current_index < len(self._events) - 1:
            self._current_index += 1
            self._load_current_event()

    def _go_previous(self) -> None:
        self._apply_current_edits()
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current_event()

    def _confirm_and_next(self) -> None:
        self.state_combo.setCurrentText("Confirmed")
        self._go_next()

    def _accept(self) -> None:
        self._apply_current_edits()
        self.accept()

    # Public API ---------------------------------------------------------
    def updated_events(self) -> list[tuple]:
        denormed: list[tuple] = []
        for evt, length in zip(self._events, self._row_lengths, strict=False):
            denormed.append(self._denormalize_event(evt, length))
        return denormed

    def updated_review_states(self) -> list[str]:
        return list(self._review_states)

    def _denormalize_event(self, evt: Sequence[Any], length: int) -> tuple:
        if length >= 7:
            return tuple(evt[:length])
        if length == 5:
            return (evt[0], evt[1], evt[2], evt[3], evt[6])
        if length == 6:
            return (evt[0], evt[1], evt[2], evt[3], evt[4], evt[6])
        if length == 4:
            return (evt[0], evt[1], evt[2], evt[6])
        return tuple(evt[:length])
