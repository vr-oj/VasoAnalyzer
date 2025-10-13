from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QWidget

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog

__all__ = ["build_frame_tab"]


def build_frame_tab(dialog: "UnifiedSettingsDialog") -> QWidget:
    """Delegate to the legacy frame tab builder."""

    return dialog._make_frame_tab_legacy()
