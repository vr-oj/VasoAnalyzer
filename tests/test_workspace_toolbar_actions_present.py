from __future__ import annotations

from PyQt5.QtWidgets import QToolButton

from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def _collect_primary_toolbar_texts(window: VasoAnalyzerApp) -> set[str]:
    toolbar = window.primary_toolbar
    texts: set[str] = set()
    for action in toolbar.actions():
        text = action.text()
        if text:
            texts.add(text)
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, QToolButton):
            widget_text = widget.text()
            if widget_text:
                texts.add(widget_text)
    return texts


def test_primary_toolbar_actions_present(qt_app) -> None:
    window = VasoAnalyzerApp(check_updates=False)
    try:
        texts = _collect_primary_toolbar_texts(window)
        ellipsis = "\u2026"
        expected = {
            f"Open Data{ellipsis}",
            "Save Project",
            "Review Events",
            f"Excel mapper{ellipsis}",
        }
        missing = expected - texts
        assert not missing, f"Missing toolbar actions: {sorted(missing)}"
    finally:
        window.close()
        qt_app.processEvents()
