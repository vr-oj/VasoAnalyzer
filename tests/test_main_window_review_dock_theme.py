from __future__ import annotations

from vasoanalyzer.ui import main_window as main_window_module


def test_apply_theme_with_review_dock_open_does_not_raise(qtbot, monkeypatch) -> None:
    monkeypatch.setenv("VASO_DISABLE_SNAPSHOT_PANEL", "1")
    monkeypatch.setattr(main_window_module, "onboarding_needed", lambda _settings: False)

    window = main_window_module.VasoAnalyzerApp(check_updates=False)
    qtbot.addWidget(window)

    assert getattr(window, "review_panel", None) is not None
    assert getattr(window, "review_dock", None) is not None

    window.show()
    window.review_dock.show()
    window.apply_theme("dark")
