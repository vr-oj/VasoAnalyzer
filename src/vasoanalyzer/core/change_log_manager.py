"""Manager for collecting and persisting change log entries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from vasoanalyzer.core.audit import (
    CATEGORY_EVENT_ADD,
    CATEGORY_EVENT_DELETE,
    CATEGORY_EVENT_EDIT,
    CATEGORY_EVENT_LABEL,
    CATEGORY_POINT_EDIT,
    CATEGORY_REVIEW_STATUS,
    ChangeEntry,
    EditAction,
    deserialize_change_log,
    edit_action_to_change_entry,
    serialize_change_log,
)

__all__ = ["ChangeLogManager"]

log = logging.getLogger(__name__)


class ChangeLogManager:
    """Collect and manage change log entries for a single sample."""

    def __init__(self) -> None:
        self._entries: list[ChangeEntry] = []

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record(
        self,
        category: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> ChangeEntry:
        """Record a new change entry and return it."""
        entry = ChangeEntry(
            category=category,
            description=description,
            details=details or {},
        )
        self._entries.append(entry)
        log.debug("Change recorded: [%s] %s", category, description)
        return entry

    def record_point_edits(self, actions: Sequence[EditAction]) -> None:
        """Convert EditAction objects into change entries."""
        for action in actions:
            self._entries.append(edit_action_to_change_entry(action))

    def record_event_value_edit(
        self, row: int, old_val: float, new_val: float, event_label: str = ""
    ) -> None:
        label_part = f" ({event_label})" if event_label else ""
        self.record(
            CATEGORY_EVENT_EDIT,
            f"Event row {row + 1}{label_part}: value {old_val:.2f} \u2192 {new_val:.2f}",
            {"row": row, "old_value": old_val, "new_value": new_val, "label": event_label},
        )

    def record_event_label_edit(
        self, row: int, old_label: str, new_label: str
    ) -> None:
        self.record(
            CATEGORY_EVENT_LABEL,
            f"Event row {row + 1}: label \u201c{old_label}\u201d \u2192 \u201c{new_label}\u201d",
            {"row": row, "old_label": old_label, "new_label": new_label},
        )

    def record_event_add(self, row: int, event_label: str = "") -> None:
        label_part = f" \u201c{event_label}\u201d" if event_label else ""
        self.record(
            CATEGORY_EVENT_ADD,
            f"Event added at row {row + 1}{label_part}",
            {"row": row, "label": event_label},
        )

    def record_event_delete(self, row: int, event_label: str = "") -> None:
        label_part = f" \u201c{event_label}\u201d" if event_label else ""
        self.record(
            CATEGORY_EVENT_DELETE,
            f"Event deleted at row {row + 1}{label_part}",
            {"row": row, "label": event_label},
        )

    def record_review_status_change(
        self, row: int, old_state: str, new_state: str, event_label: str = ""
    ) -> None:
        label_part = f" ({event_label})" if event_label else ""
        self.record(
            CATEGORY_REVIEW_STATUS,
            f"Event row {row + 1}{label_part}: review {old_state} \u2192 {new_state}",
            {
                "row": row,
                "old_state": old_state,
                "new_state": new_state,
                "label": event_label,
            },
        )

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def entries(self) -> list[ChangeEntry]:
        """Return entries sorted newest-first."""
        return sorted(self._entries, key=lambda e: e.timestamp, reverse=True)

    @property
    def count(self) -> int:
        return len(self._entries)

    def entries_by_category(self, category: str) -> list[ChangeEntry]:
        return [e for e in self.entries if e.category == category]

    def clear(self) -> None:
        self._entries.clear()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize(self) -> list[dict[str, Any]]:
        return serialize_change_log(self._entries)

    def load(self, payload: list[dict[str, Any]] | None) -> None:
        """Load entries from serialized data, replacing current entries."""
        self._entries.clear()
        if payload:
            self._entries.extend(deserialize_change_log(payload))

    def merge_edit_history(self, edit_history: list[dict[str, Any]] | None) -> None:
        """Import existing EditAction-based edit_history entries that aren't already tracked."""
        if not edit_history:
            return
        existing_timestamps = {e.timestamp for e in self._entries if e.category == CATEGORY_POINT_EDIT}
        from vasoanalyzer.core.audit import deserialize_edit_log
        for action in deserialize_edit_log(edit_history):
            if action.timestamp not in existing_timestamps:
                self._entries.append(edit_action_to_change_entry(action))
