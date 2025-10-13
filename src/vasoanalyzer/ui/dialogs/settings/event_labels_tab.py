from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QWidget

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog

__all__ = ["build_event_labels_tab"]


def build_event_labels_tab(dialog: "UnifiedSettingsDialog") -> QWidget:
    """Delegate to the legacy event labels tab builder."""

    return dialog._make_event_labels_tab_legacy()
