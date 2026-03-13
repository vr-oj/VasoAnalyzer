from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt

from vasoanalyzer.ui.plots.smooth_pan_viewbox import SmoothPanViewBox


class _FakeWheelEvent:
    def __init__(self, *, delta_y: int, modifiers: Qt.KeyboardModifier, scene_pos: QPointF) -> None:
        self._delta_y = int(delta_y)
        self._modifiers = modifiers
        self._scene_pos = QPointF(scene_pos)
        self.accepted = False

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta_y)

    def pixelDelta(self) -> QPoint:
        return QPoint(0, 0)

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def scenePos(self) -> QPointF:
        return QPointF(self._scene_pos)

    def accept(self) -> None:
        self.accepted = True


def test_shift_wheel_pans_y_by_five_percent_of_span(qt_app) -> None:
    vb = SmoothPanViewBox(enableMenu=False)
    vb.setRange(xRange=(0.0, 10.0), yRange=(0.0, 100.0), padding=0.0, update=True)
    _, y_before = vb.viewRange()

    ev = _FakeWheelEvent(delta_y=120, modifiers=Qt.KeyboardModifier.ShiftModifier, scene_pos=QPointF(5.0, 50.0))
    vb.wheelEvent(ev)
    _, y_after = vb.viewRange()

    assert ev.accepted is True
    assert abs((float(y_after[0]) - float(y_before[0])) - (-5.0)) < 1e-6


def test_alt_wheel_zooms_y_about_cursor(qt_app) -> None:
    vb = SmoothPanViewBox(enableMenu=False)
    vb.setRange(xRange=(0.0, 10.0), yRange=(0.0, 100.0), padding=0.0, update=True)
    _, y_before = vb.viewRange()
    span_before = float(y_before[1] - y_before[0])

    ev = _FakeWheelEvent(delta_y=120, modifiers=Qt.KeyboardModifier.AltModifier, scene_pos=QPointF(5.0, 50.0))
    vb.wheelEvent(ev)
    _, y_after = vb.viewRange()
    span_after = float(y_after[1] - y_after[0])

    assert ev.accepted is True
    assert span_after < span_before
