from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QInputDialog, QWidget

from vasoanalyzer.ui.panels.event_review_panel import EventReviewPanel


class _FakeController:
    def __init__(self) -> None:
        self._times = [1.0, 2.0]
        self.calls: list[tuple[int, float]] = []

    def update_time(self, idx: int, t: float) -> None:
        self.calls.append((idx, t))


def test_edit_current_time_uses_list_times_and_updates_controller(qtbot, monkeypatch) -> None:
    controller = _FakeController()
    panel = EventReviewPanel(controller)
    qtbot.addWidget(panel)
    panel._current_index = 0

    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args, **kwargs: (5.0, True))

    panel._edit_current_time()

    assert controller.calls == [(0, 5.0)]


def test_shortcuts_install_without_crashing(qtbot) -> None:
    panel = EventReviewPanel()
    qtbot.addWidget(panel)

    # Event filter is installed on all child widgets for panel-wide key handling
    children = panel.findChildren(QWidget)
    assert len(children) > 0, "Panel should have child widgets"
