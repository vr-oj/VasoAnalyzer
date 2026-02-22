from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QWidget

from vasoanalyzer.ui.plots.track_frame import TRACK_DIVIDER_THICKNESS_PX, TrackFrame


def test_track_frame_uses_structural_separator_widget(qt_app) -> None:
    child = QWidget()
    frame = TrackFrame(child)
    try:
        frame.resize(420, 180)
        frame.show()
        qt_app.processEvents()

        separator = frame.findChild(QFrame, "TrackSeparatorBar")
        assert separator is not None
        assert separator.height() == TRACK_DIVIDER_THICKNESS_PX
        assert separator.width() > 0

        frame.set_divider_visible(False)
        qt_app.processEvents()
        assert separator.height() == 0

        frame.set_divider_visible(True)
        frame.set_divider_thickness(3)
        qt_app.processEvents()
        assert separator.height() == 3
    finally:
        frame.close()
        qt_app.processEvents()
