from __future__ import annotations

from pathlib import Path

from vasoanalyzer.app.window_manager import WindowManager


def test_window_manager_retains_windows(qt_app, tmp_path, monkeypatch) -> None:
    manager = WindowManager(app=qt_app, check_updates_on_first_window=False)

    home = manager.open_home()
    assert manager.home_window is home

    project_path = tmp_path / "demo.vaso"
    project_path.write_text("ok")

    def fake_open(window, path: str) -> bool:
        window.project_path = str(Path(path))
        window.current_project = object()
        return True

    monkeypatch.setattr(manager, "_open_project_in_window", fake_open)

    window = manager.open_project(str(project_path))
    assert window is not None
    assert window in manager.main_windows

    window.current_project = None
    window.close()
    qt_app.processEvents()
    assert window not in manager.main_windows

    home.close()


def test_window_manager_dashboard_visibility_and_dedupe(qt_app, tmp_path, monkeypatch) -> None:
    manager = WindowManager(app=qt_app, check_updates_on_first_window=False)

    home = manager.show_dashboard()
    qt_app.processEvents()
    assert home.isVisible()

    manager.hide_dashboard()
    qt_app.processEvents()
    assert not home.isVisible()

    manager.show_dashboard()
    qt_app.processEvents()
    assert home.isVisible()

    project_path = tmp_path / "demo.vaso"
    project_path.write_text("ok")

    def fake_open(window, path: str) -> bool:
        window.project_path = str(Path(path))
        window.current_project = object()
        return True

    monkeypatch.setattr(manager, "_open_project_in_window", fake_open)

    window = manager.open_project(str(project_path))
    assert window is not None
    qt_app.processEvents()
    assert not home.isVisible()
    assert len(manager.main_windows) == 1

    window_second = manager.open_project(str(project_path))
    assert window_second is window
    assert len(manager.main_windows) == 1

    if window is not None:
        window.current_project = None
        window.close()
    home.close()
    qt_app.processEvents()
