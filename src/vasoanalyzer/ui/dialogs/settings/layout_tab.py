from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QWidget

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog

__all__ = ["build_layout_tab"]


def build_layout_tab(dialog: "UnifiedSettingsDialog") -> QWidget:
    """Delegate to the legacy layout tab builder."""

    return dialog._make_layout_tab_legacy()
