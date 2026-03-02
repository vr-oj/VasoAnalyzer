from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel

from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.y_axis_controls import YAxisControls, required_outer_gutter_px


def test_gutter_width_and_controls_parenting(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner", label="Inner"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 220)
        widget.show()
        qt_app.processEvents()

        controls = widget.findChild(YAxisControls)
        assert controls is not None
        assert track.gutter_width_px() == required_outer_gutter_px()
        assert controls.parent() is track.gutter_widget
        assert controls.menu_button_widget.parent() is track.gutter_widget
        assert controls.scale_buttons_widget.parent() is track.gutter_widget
        assert track.view.get_widget().findChild(YAxisControls) is None
        gutter_layout = track.gutter_widget.layout()
        assert gutter_layout is not None
        margins = gutter_layout.contentsMargins()
        assert margins.left() == 0
        assert margins.top() == 0
        assert margins.right() == 0
        assert margins.bottom() == 0
        assert gutter_layout.spacing() == 0
        assert track.gutter_widget.testAttribute(Qt.WA_PaintUnclipped) is False
        menu_geo = controls.menu_button_widget.geometry()
        scale_geo = controls.scale_buttons_widget.geometry()
        assert menu_geo.left() >= 0
        assert menu_geo.right() <= track.gutter_widget.width()
        assert scale_geo.left() >= 0
        assert scale_geo.right() <= track.gutter_widget.width()
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_gutter_label_hides_for_short_tracks(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner", label="Inner Diameter"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 56)
        widget.show()
        qt_app.processEvents()

        label = track.gutter_widget.findChild(QLabel, "ChannelTrackGutterLabel")
        assert label is not None
        track.gutter_widget.set_channel_label("")
        track.gutter_widget.layout_channel_label()
        qt_app.processEvents()
        assert label.isVisible() is False

        track.gutter_widget.set_channel_label("Inner Diameter")
        widget.resize(720, 220)
        qt_app.processEvents()
        track.refresh_header()
        qt_app.processEvents()
        assert label.isVisible() is False
    finally:
        track.widget.close()
        qt_app.processEvents()
