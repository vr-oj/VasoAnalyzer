from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt

from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import (
    PyQtGraphTraceView,
    axis_controls_top_left_for_viewbox,
)
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


def test_axis_controls_anchor_stays_left_of_viewbox() -> None:
    viewbox_rect = QRect(84, 8, 620, 188)
    x, y = axis_controls_top_left_for_viewbox(
        viewbox_rect=viewbox_rect,
        controls_width=24,
        controls_height=16,
        widget_width=720,
        widget_height=220,
        margin=2,
    )
    assert x + 24 <= viewbox_rect.left()
    assert y >= viewbox_rect.top()


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
        controls = plot_widget.findChild(YAxisControls)
        assert controls is not None
        assert controls.parent() is plot_widget
        assert controls.menu_btn.menu() is controls._menu
        assert controls.menu_button_widget.parent() is plot_widget
        assert controls.scale_buttons_widget.parent() is plot_widget

        assert widget.findChild(YAxisControls) is controls
        assert widget.findChild(type(controls.menu_btn), "ChannelTrackMenuButton") is None
        assert widget.layout().count() == 1

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

        assert controls.scale_menu_btn.iconSize() == QSize(ICON_PX, ICON_PX)
        assert controls.zoom_in_btn.iconSize() == QSize(ICON_PX, ICON_PX)
        assert controls.zoom_out_btn.iconSize() == QSize(ICON_PX, ICON_PX)
        assert controls.scale_menu_btn.size() == QSize(BUTTON_PX, BUTTON_PX)
        assert controls.zoom_in_btn.size() == QSize(BUTTON_PX, BUTTON_PX)
        assert controls.zoom_out_btn.size() == QSize(BUTTON_PX, BUTTON_PX)
        assert controls.scale_menu_btn.text() == ""
        assert controls.zoom_in_btn.icon().isNull() is False or controls.zoom_in_btn.text() == "+"
        assert controls.zoom_out_btn.icon().isNull() is False or controls.zoom_out_btn.text() == "-"
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

        controls = track.view.get_widget().findChild(YAxisControls)
        assert controls is not None

        viewbox_rect = track.view._viewbox_rect_in_widget()
        assert viewbox_rect is not None

        menu_geo = controls.menu_button_widget.geometry()
        scale_geo = controls.scale_buttons_widget.geometry()

        assert menu_geo.x() + menu_geo.width() <= viewbox_rect.left() + 2
        assert menu_geo.y() <= viewbox_rect.top() + 6

        assert scale_geo.x() + scale_geo.width() <= viewbox_rect.left() + 2
        assert scale_geo.y() + scale_geo.height() >= viewbox_rect.bottom() - 6
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

        controls = track.view.get_widget().findChild(YAxisControls)
        assert controls is not None

        track.view.refresh_y_axis_controls()
        qt_app.processEvents()
        assert controls.menu_button_widget.isVisible() is True
        assert controls.scale_buttons_widget.isVisible() is False

        widget.resize(720, 220)
        qt_app.processEvents()
        track.view.refresh_y_axis_controls()
        qt_app.processEvents()
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

        controls = track.view.get_widget().findChild(YAxisControls)
        assert controls is not None

        track.view.refresh_y_axis_controls()
        qt_app.processEvents()

        plot_widget = track.view.get_widget()
        axis = plot_widget.getPlotItem().getAxis("left")
        assert axis is not None
        axis_scene = axis.sceneBoundingRect()
        assert axis_scene is not None
        assert axis_scene.isValid() and not axis_scene.isEmpty()

        axis_left_px = int(plot_widget.mapFromScene(axis_scene.topLeft()).x())
        assert axis_left_px >= required_outer_gutter_px() - 1

        menu_geo = controls.menu_button_widget.geometry()
        scale_geo = controls.scale_buttons_widget.geometry()

        assert menu_geo.right() <= axis_left_px - 1
        assert scale_geo.right() <= axis_left_px - 1
    finally:
        track.widget.close()
        qt_app.processEvents()


def test_right_click_axis_uses_same_controls_menu_instance(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        controls = track.view.get_widget().findChild(YAxisControls)
        assert controls is not None
        assert controls.menu_btn.menu() is controls._menu

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
