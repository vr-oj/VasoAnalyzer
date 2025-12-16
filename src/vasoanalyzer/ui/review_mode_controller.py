"""Review Mode Controller for managing event review workflow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp
    from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost
    from vasoanalyzer.ui.panels.event_review_panel import EventReviewPanel

log = logging.getLogger(__name__)

# Review state constants
REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_CONFIRMED = "CONFIRMED"
REVIEW_EDITED = "EDITED"
REVIEW_NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class ReviewModeController(QObject):
    """Controller for event review mode.

    Manages the review session state and coordinates between:
    - EventReviewPanel (UI)
    - Event table (data)
    - Trace plots (visualization)

    Responsibilities:
    - Navigation between events
    - Sampling mode coordination
    - Value persistence
    - Review state management
    """

    # Signals
    sampling_mode_changed = pyqtSignal(bool)  # enabled

    def __init__(
        self,
        main_window: VasoAnalyzerApp,
        panel: EventReviewPanel,
        plot_host: PyQtGraphPlotHost | None = None,
    ) -> None:
        """Initialize the review mode controller.

        Args:
            main_window: Main window instance
            panel: Review panel widget
            plot_host: PyQtGraph plot host (optional)
        """
        super().__init__(parent=main_window)

        self._main_window = main_window
        self._panel = panel
        self._plot_host = plot_host

        # State
        self._active: bool = False
        self._current_index: int = 0
        self._sampling_mode: bool = False
        self._events: list[tuple] = []
        self._review_states: list[str] = []

        # Connect panel signals
        self._panel.event_selected.connect(self.navigate_to_event)
        self._panel.values_changed.connect(self._on_values_changed)
        self._panel.sample_requested.connect(self.toggle_sampling_mode)
        self._panel.confirm_all_requested.connect(self.confirm_all_unreviewed)
        self._panel.review_completed.connect(self.end_review)

        # Connect to plot host if available
        if self._plot_host is not None:
            self.sampling_mode_changed.connect(self._plot_host.set_sampling_mode)

    # ---- Public API --------------------------------------------------------

    def is_active(self) -> bool:
        """Check if review mode is currently active.

        Returns:
            True if review session is active
        """
        return self._active

    @property
    def sampling_mode(self) -> bool:
        """Get sampling mode state.

        Returns:
            True if sampling mode is active
        """
        return self._sampling_mode

    def start_review(self) -> None:
        """Start a new review session."""
        if self._active:
            log.debug("Review mode already active")
            return

        # Load events from main window
        if not self._main_window.event_table_data:
            log.warning("No events to review")
            return

        self._events = [tuple(row) for row in self._main_window.event_table_data]
        self._review_states = self._load_review_states()

        log.info(f"Starting review session with {len(self._events)} events")

        # Find first unreviewed event or start at 0
        first_index = 0
        for i, state in enumerate(self._review_states):
            if state == REVIEW_UNREVIEWED:
                first_index = i
                break

        self._active = True
        self._current_index = first_index

        # Enable animated highlighting for review mode
        if self._plot_host is not None:
            self._plot_host.set_review_mode_highlighting(True)

        # Navigate to first event
        self.navigate_to_event(first_index)

    def end_review(self) -> None:
        """End the review session and save changes."""
        if not self._active:
            return

        log.info(f"Ending review session at event {self._current_index + 1}/{len(self._events)}")

        # Exit sampling mode if active
        if self._sampling_mode:
            self.toggle_sampling_mode()

        # Disable animated highlighting
        if self._plot_host is not None:
            self._plot_host.set_review_mode_highlighting(False)

        self._active = False
        self._current_index = 0
        self._events.clear()
        self._review_states.clear()

        # Note: Changes are saved immediately via _on_values_changed,
        # so no batch save needed here

    def navigate_to_event(self, index: int) -> None:
        """Navigate to a specific event.

        Args:
            index: Event index (0-based)
        """
        if not self._active or not self._events:
            return

        if not (0 <= index < len(self._events)):
            log.warning(f"Event index {index} out of range (0-{len(self._events) - 1})")
            return

        log.debug(f"Navigating to event {index + 1}/{len(self._events)}")

        # Hide any visible crosshair from previous sampling
        if self._plot_host is not None:
            self._plot_host.hide_sampling_crosshair()

        self._current_index = index

        # Get event data and review state
        event_data = self._events[index]
        state = self._review_states[index] if index < len(self._review_states) else REVIEW_UNREVIEWED

        # Update panel
        self._panel.set_event(index, event_data, state, len(self._events))

        # Focus event in main window (synchronizes table, trace, snapshot)
        try:
            self._main_window._focus_event_row(index, source="review_controller")
        except Exception as e:
            log.error(f"Failed to focus event row {index}: {e}", exc_info=True)

    def navigate_next(self) -> None:
        """Navigate to the next event."""
        if self._current_index < len(self._events) - 1:
            self.navigate_to_event(self._current_index + 1)

    def navigate_previous(self) -> None:
        """Navigate to the previous event."""
        if self._current_index > 0:
            self.navigate_to_event(self._current_index - 1)

    def toggle_sampling_mode(self) -> None:
        """Toggle sampling mode on/off."""
        self._sampling_mode = not self._sampling_mode

        log.debug(f"Sampling mode: {'ON' if self._sampling_mode else 'OFF'}")

        # Update panel visual state
        self._panel.set_sampling_mode(self._sampling_mode)

        # Emit signal for plot host to update visual feedback
        self.sampling_mode_changed.emit(self._sampling_mode)

    def handle_trace_click(self, time_sec: float) -> None:
        """Handle trace click during sampling mode.

        Args:
            time_sec: Time value where user clicked
        """
        if not self._sampling_mode or not self._active:
            return

        log.debug(f"Sampling values at time {time_sec:.2f}s")

        try:
            # Sample values from main window
            sampled = self._main_window._sample_values_at_time(time_sec)

            if not sampled or len(sampled) < 2:
                log.warning("Sampling returned no valid values")
                return

            id_val, od_val = sampled[0], sampled[1]

            # Show crosshair at sampled location
            if self._plot_host is not None:
                self._plot_host.show_sampling_crosshair(time_sec, id_val, od_val)

            # Update panel with sampled values
            self._panel.set_sampled_values(id_val, od_val)

            # Auto-advance to next event for efficient workflow
            # (sampling mode stays active so user can keep clicking through events)
            if self._current_index < len(self._events) - 1:
                self.navigate_next()
            else:
                log.debug("Reached last event - staying in place")

        except Exception as e:
            log.error(f"Error sampling values at time {time_sec}: {e}", exc_info=True)

    def confirm_all_unreviewed(self) -> None:
        """Mark all reviewed events as confirmed.

        Called when user clicks "Confirm Review" to finalize the review session.
        Marks both UNREVIEWED and EDITED events as CONFIRMED.
        Only leaves NEEDS_FOLLOWUP events unchanged.
        """
        if not self._active:
            return

        log.info("Confirming all reviewed events")

        confirmed_count = 0
        for i in range(len(self._events)):
            if i < len(self._review_states):
                # Mark UNREVIEWED and EDITED events as CONFIRMED
                # Only leave NEEDS_FOLLOWUP unchanged
                if self._review_states[i] in (REVIEW_UNREVIEWED, REVIEW_EDITED):
                    self._review_states[i] = REVIEW_CONFIRMED
                    self._main_window._set_review_state_for_row(i, REVIEW_CONFIRMED)
                    confirmed_count += 1

        if confirmed_count > 0:
            log.info(f"Marked {confirmed_count} event(s) as CONFIRMED")
            # Mark sample state dirty to trigger save
            self._main_window._sample_state_dirty = True
            # Refresh table display
            self._main_window.populate_table()

    def sync_to_event(self, row: int) -> None:
        """Sync review panel when event is focused externally.

        Called when user clicks event in table outside of review navigation.

        Args:
            row: Event row index
        """
        if not self._active:
            return

        # Update panel without triggering another focus (avoid loop)
        if 0 <= row < len(self._events):
            self._current_index = row
            event_data = self._events[row]
            state = self._review_states[row] if row < len(self._review_states) else REVIEW_UNREVIEWED
            self._panel.set_event(row, event_data, state, len(self._events))

    # ---- Private helpers ---------------------------------------------------

    def _load_review_states(self) -> list[str]:
        """Load review states from main window event metadata.

        Returns:
            List of review state strings
        """
        states: list[str] = []

        # Ensure metadata is normalized
        self._main_window._normalize_event_label_meta(len(self._events))

        for i in range(len(self._events)):
            if i < len(self._main_window.event_label_meta):
                meta = self._main_window.event_label_meta[i]
                state = meta.get("review_state", REVIEW_UNREVIEWED)
                states.append(state)
            else:
                states.append(REVIEW_UNREVIEWED)

        return states

    def _on_values_changed(
        self,
        index: int,
        id_val: float | None,
        od_val: float | None,
        state: str,
    ) -> None:
        """Handle value changes from panel.

        Immediately persists changes to main window data structures.

        Args:
            index: Event index
            id_val: New ID value (or None)
            od_val: New OD value (or None)
            state: New review state
        """
        if not self._active or index != self._current_index:
            return

        log.debug(f"Saving changes for event {index + 1}: ID={id_val}, OD={od_val}, state={state}")

        try:
            # Update event data
            if 0 <= index < len(self._main_window.event_table_data):
                current_row = list(self._main_window.event_table_data[index])

                # Update ID (index 2)
                if len(current_row) > 2:
                    current_row[2] = round(id_val, 2) if id_val is not None else None

                # Update OD (index 3)
                if len(current_row) > 3:
                    current_row[3] = round(od_val, 2) if od_val is not None else None

                self._main_window.event_table_data[index] = tuple(current_row)

                # Update local cache
                self._events[index] = tuple(current_row)

            # Update review state
            self._main_window._set_review_state_for_row(index, state)
            self._review_states[index] = state

            # Mark sample state dirty (triggers save)
            self._main_window._sample_state_dirty = True

            # Refresh table display
            self._main_window.populate_table()

        except Exception as e:
            log.error(f"Error saving event changes for index {index}: {e}", exc_info=True)
