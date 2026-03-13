from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage, QPalette
from PyQt6.QtWidgets import QWidget

from vasoanalyzer.ui.plots.y_axis_controls import ICON_PX, YAxisControls


def _luminance(color: QColor) -> float:
    return 0.2126 * float(color.red()) + 0.7152 * float(color.green()) + 0.0722 * float(color.blue())


def _non_transparent_pixel_stats(icon, size: QSize) -> tuple[int, float]:
    image = icon.pixmap(size).toImage().convertToFormat(QImage.Format_ARGB32)
    visible = 0
    luminance_sum = 0.0
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor.fromRgba(image.pixel(x, y))
            if color.alpha() <= 0:
                continue
            visible += 1
            luminance_sum += _luminance(color)
    mean_luminance = luminance_sum / float(visible) if visible > 0 else 0.0
    return visible, mean_luminance


def _build_palette(*, button_text: str, text: str, button_bg: str, window_bg: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(window_bg))
    palette.setColor(QPalette.Base, QColor(window_bg))
    palette.setColor(QPalette.Button, QColor(button_bg))
    palette.setColor(QPalette.ButtonText, QColor(button_text))
    palette.setColor(QPalette.WindowText, QColor(text))
    palette.setColor(QPalette.Text, QColor(text))
    return palette


@pytest.mark.parametrize(
    ("name", "palette"),
    [
        (
            "light",
            _build_palette(
                button_text="#111827",
                text="#111827",
                button_bg="#F3F4F6",
                window_bg="#FFFFFF",
            ),
        ),
        (
            "dark",
            _build_palette(
                button_text="#E6EDF3",
                text="#E6EDF3",
                button_bg="#21262D",
                window_bg="#0D1117",
            ),
        ),
    ],
)
def test_y_axis_scale_icons_have_visible_pixels(qt_app, name: str, palette: QPalette) -> None:
    host = QWidget()
    controls = YAxisControls(
        parent=host,
        get_state=lambda: False,
        set_state=lambda _enabled: None,
        autoscale_once=lambda: None,
        zoom_out_scale=lambda: None,
        zoom_in_scale=lambda: None,
        set_scale_dialog=lambda: None,
        reset_scale=lambda: None,
    )
    size = QSize(ICON_PX, ICON_PX)
    threshold = 8
    try:
        host.setPalette(palette)
        controls.setPalette(palette)
        host.show()
        controls.show()
        controls._apply_icons()  # Validate rendered icon payload, not just button presence.
        qt_app.processEvents()

        button_bg_luma = _luminance(palette.color(QPalette.Button))
        for button in (controls.zoom_in_btn, controls.zoom_out_btn):
            icon = button.icon()
            visible_pixels, icon_luma = _non_transparent_pixel_stats(icon, size)
            assert visible_pixels > threshold, f"{name}: {button.objectName()} rendered blank icon"
            assert (
                abs(icon_luma - button_bg_luma) > 6.0
            ), f"{name}: {button.objectName()} icon lacks contrast with button bg"
    finally:
        host.close()
        qt_app.processEvents()


def test_y_axis_icon_tint_prefers_text_role_and_alpha_floor(qt_app) -> None:
    host = QWidget()
    controls = YAxisControls(
        parent=host,
        get_state=lambda: False,
        set_state=lambda _enabled: None,
        autoscale_once=lambda: None,
        zoom_out_scale=lambda: None,
        zoom_in_scale=lambda: None,
        set_scale_dialog=lambda: None,
        reset_scale=lambda: None,
    )
    palette = QPalette()
    palette.setColor(QPalette.ButtonText, QColor(240, 240, 240, 255))
    palette.setColor(QPalette.Text, QColor(17, 24, 39, 120))
    palette.setColor(QPalette.WindowText, QColor(230, 237, 243, 180))
    try:
        controls.setPalette(palette)
        color = controls._icon_tint_color()
        assert (color.red(), color.green(), color.blue()) == (17, 24, 39)
        assert color.alpha() >= int(round(255.0 * 0.85))
    finally:
        host.close()
        qt_app.processEvents()


def test_y_axis_icon_tint_falls_back_to_window_text(qt_app) -> None:
    host = QWidget()
    controls = YAxisControls(
        parent=host,
        get_state=lambda: False,
        set_state=lambda _enabled: None,
        autoscale_once=lambda: None,
        zoom_out_scale=lambda: None,
        zoom_in_scale=lambda: None,
        set_scale_dialog=lambda: None,
        reset_scale=lambda: None,
    )
    palette = QPalette()
    palette.setColor(QPalette.Text, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.WindowText, QColor(230, 237, 243, 140))
    palette.setColor(QPalette.ButtonText, QColor(120, 120, 120, 255))
    try:
        controls.setPalette(palette)
        color = controls._icon_tint_color()
        assert (color.red(), color.green(), color.blue()) == (230, 237, 243)
        assert color.alpha() >= int(round(255.0 * 0.85))
    finally:
        host.close()
        qt_app.processEvents()
