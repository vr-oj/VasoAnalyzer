from __future__ import annotations

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QColor, QImage, QPalette
from PyQt5.QtWidgets import QWidget

from vasoanalyzer.ui.plots.y_axis_controls import ICON_PX, YAxisControls


def _alpha_bbox_size(image: QImage) -> tuple[int, int]:
    left = image.width()
    top = image.height()
    right = -1
    bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if QColor.fromRgba(image.pixel(x, y)).alpha() <= 0:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return 0, 0
    return right - left + 1, bottom - top + 1


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
def test_y_axis_scale_icon_bbox_is_not_tiny(qt_app, name: str, palette: QPalette) -> None:
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
    target_px = ICON_PX
    min_major = 0.70
    max_major = 0.92
    plus_min_minor = 0.70
    plus_max_minor = 0.92
    minus_min_minor = 0.22
    minus_max_minor = 0.50
    try:
        host.setPalette(palette)
        controls.setPalette(palette)
        host.show()
        controls.show()
        controls._apply_icons()
        qt_app.processEvents()

        for button in (controls.zoom_in_btn, controls.zoom_out_btn):
            icon = button.icon()
            image = icon.pixmap(QSize(target_px, target_px)).toImage().convertToFormat(
                QImage.Format_ARGB32
            )
            bbox_width, bbox_height = _alpha_bbox_size(image)
            width_ratio = float(bbox_width) / float(target_px)
            height_ratio = float(bbox_height) / float(target_px)
            assert (
                min_major <= width_ratio <= max_major
            ), f"{name}: {button.objectName()} width bbox ratio out of range ({width_ratio:.3f})"

            if button is controls.zoom_in_btn:
                assert (
                    plus_min_minor <= height_ratio <= plus_max_minor
                ), f"{name}: {button.objectName()} height bbox ratio out of range ({height_ratio:.3f})"
            else:
                assert (
                    minus_min_minor <= height_ratio <= minus_max_minor
                ), f"{name}: {button.objectName()} height bbox ratio out of range ({height_ratio:.3f})"
    finally:
        host.close()
        qt_app.processEvents()
