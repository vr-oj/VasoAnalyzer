from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtWidgets import QFrame

from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import PyQtGraphTraceView
from vasoanalyzer.ui.plots.y_axis_controls import (
    BUTTON_PX,
    ICON_PX,
    YAxisControls,
    required_outer_gutter_px,
)


def test_pyqtgraph_trace_view_hides_builtin_hover_buttons(qt_app) -> None:
    view = PyQtGraphTraceView(enable_opengl=False)
    try:
        plot_item = view.get_widget().getPlotItem()
        assert bool(getattr(plot_item, "buttonsHidden", False)) is True
        assert bool(plot_item.menuEnabled()) is False
        assert bool(plot_item.getViewBox().menuEnabled()) is False
    finally:
        view.get_widget().close()
        qt_app.processEvents()


def test_y_axis_controls_presence_and_state_sync(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(
            track_id="inner",
            component="inner",
            label="Inner Diameter (um)",
        ),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 220)
        widget.show()
        qt_app.processEvents()

        plot_widget = track.view.get_widget()
        controls = track.widget.findChild(YAxisControls)
        assert controls is not None
        assert controls.parent() is track.gutter_widget
        assert controls.menu_btn.menu() is None
        assert controls._menu.parent() is controls.menu_btn
        assert controls.menu_button_widget.parent() is track.gutter_widget
        assert controls.scale_buttons_widget.parent() is track.gutter_widget

        assert widget.findChild(YAxisControls) is controls
        assert widget.findChild(type(controls.menu_btn), "ChannelTrackMenuButton") is None
        assert widget.layout().count() == 2
        separator = widget.findChild(QFrame, "TrackSeparatorBar")
        assert separator is not None

        track._set_continuous_autoscale(True)
        controls.refresh_state()
        qt_app.processEvents()
        assert controls._continuous_action.isChecked() is True
        assert controls.scale_menu_btn.property("continuousEnabled") is True

        controls.zoom_in_btn.click()
        controls.refresh_state()
        qt_app.processEvents()
        assert track.view.is_autoscale_enabled() is False
        assert controls._continuous_action.isChecked() is False
        assert controls.scale_menu_btn.property("continuousEnabled") is False

        menu_texts = [action.text() for action in controls._menu.actions() if action.text()]
        assert "Autoscale once" in menu_texts
        assert "Expand Y range" in menu_texts
        assert "Compress Y range" in menu_texts
        assert "Continuous autoscale" in menu_texts
        assert "Set Y scale..." in menu_texts
        assert "Reset Y scale" in menu_texts

        icon_min = ICON_PX
        icon_max = int(round(ICON_PX * 1.5))
        btn_min = BUTTON_PX
        btn_max = int(round(BUTTON_PX * 1.5))
        for button in (controls.scale_menu_btn, controls.zoom_in_btn, controls.zoom_out_btn):
            icon_size = button.iconSize()
            btn_size = button.size()
            assert icon_min <= icon_size.width() <= icon_max
            assert icon_min <= icon_size.height() <= icon_max
            assert btn_min <= btn_size.width() <= btn_max
            assert btn_min <= btn_size.height() <= btn_max
        assert controls.scale_menu_btn.text() == ""
        assert controls._menu_icon_path.endswith(".svg")

        assert controls.menu_button_widget.y() <= controls.scale_buttons_widget.y()
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_y_axis_controls_split_anchor_positions(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 220)
        widget.show()
        qt_app.processEvents()

        controls = track.widget.findChild(YAxisControls)
        assert controls is not None
        gutter = track.gutter_widget
        track.view.refresh_y_axis_controls()
        qt_app.processEvents()

        menu_geo = controls.menu_button_widget.geometry()
        scale_geo = controls.scale_buttons_widget.geometry()

        assert abs(menu_geo.center().x() - (gutter.width() // 2)) <= 4
        assert abs(scale_geo.center().x() - (gutter.width() // 2)) <= 4
        assert controls.menu_button_widget.isVisible() is True
        assert controls.scale_buttons_widget.isVisible() is True
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_y_axis_controls_hide_scale_block_on_tiny_tracks(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 56)
        widget.show()
        qt_app.processEvents()

        controls = track.widget.findChild(YAxisControls)
        assert controls is not None

        track.view.refresh_y_axis_controls()
        qt_app.processEvents()
        assert controls.menu_button_widget.isVisible() is False
        assert controls.scale_buttons_widget.isVisible() is False

        widget.resize(720, 40)
        qt_app.processEvents()
        track.view.refresh_y_axis_controls()
        qt_app.processEvents()
        assert controls.menu_button_widget.isVisible() is False
        assert controls.scale_buttons_widget.isVisible() is False

        widget.resize(720, 220)
        qt_app.processEvents()
        track.view.refresh_y_axis_controls()
        qt_app.processEvents()
        assert controls.menu_button_widget.isVisible() is True
        assert controls.scale_buttons_widget.isVisible() is True
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_y_axis_controls_are_left_of_left_axis(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 220)
        widget.show()
        qt_app.processEvents()

        controls = track.widget.findChild(YAxisControls)
        assert controls is not None

        menu_geo = controls.menu_button_widget.geometry()
        scale_geo = controls.scale_buttons_widget.geometry()
        gutter = track.gutter_widget
        assert gutter.width() >= required_outer_gutter_px()
        assert menu_geo.right() <= gutter.width()
        assert scale_geo.right() <= gutter.width()
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_right_click_axis_uses_same_controls_menu_instance(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        controls = track.widget.findChild(YAxisControls)
        assert controls is not None
        assert controls.menu_btn.menu() is None
        assert controls._menu.parent() is controls.menu_btn

        called = {"count": 0}

        def _popup(_global_pos=None):
            called["count"] += 1

        controls.popup_menu = _popup  # type: ignore[assignment]
        assert track.view._show_y_axis_menu(QPoint(5, 5)) is True
        assert called["count"] == 1
    finally:
        track.widget.close()
        qt_app.processEvents()


class _FakeMousePressEvent:
    def type(self):
        return QEvent.MouseButtonPress

    def pos(self):
        return QPoint(0, 0)

    def button(self):
        return Qt.LeftButton


class _FakeMouseMoveEvent:
    def __init__(self, pos: QPoint) -> None:
        self._pos = QPoint(pos)

    def type(self):
        return QEvent.MouseMove

    def pos(self):
        return QPoint(self._pos)


def test_y_axis_event_filter_ignores_unknown_objects(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        event = _FakeMousePressEvent()
        assert track.view._process_axis_mouse_event(object(), event) is False
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_axis_hover_sets_vertical_resize_cursor(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        widget = track.widget
        widget.resize(720, 220)
        widget.show()
        qt_app.processEvents()

        axis_rect = track.view._left_axis_rect_in_widget()
        assert axis_rect is not None

        axis_pos = axis_rect.center()
        non_axis_pos = QPoint(max(axis_rect.right() + 20, 50), axis_pos.y())

        moved_axis = track.view._process_axis_mouse_event(
            track.view.get_widget(),
            _FakeMouseMoveEvent(axis_pos),
        )
        assert moved_axis is False
        assert track.view.get_widget().cursor().shape() == Qt.SizeVerCursor

        moved_non_axis = track.view._process_axis_mouse_event(
            track.view.get_widget(),
            _FakeMouseMoveEvent(non_axis_pos),
        )
        assert moved_non_axis is False
        assert track.view.get_widget().cursor().shape() != Qt.SizeVerCursor
    finally:
        track.widget.close()
        qt_app.processEvents()
