from __future__ import annotations

from vasoanalyzer.ui.dialogs.excel_map_wizard import ExcelMapWizard


def test_excel_map_wizard_apply_theme_does_not_raise(qtbot) -> None:
    wizard = ExcelMapWizard()
    qtbot.addWidget(wizard)
    wizard.apply_theme()
