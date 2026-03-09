# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Palette-tinted SVG icon helpers."""

from __future__ import annotations

import os

from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets

from utils import resource_path
from vasoanalyzer.ui.theme import get_theme_mode

_SNAPSHOT_ICON_FALLBACKS = {
    "prev": "fast_rewind.svg",
    "next": "fast_forward.svg",
    "play": "play_arrow.svg",
    "pause": "pause.svg",
}


def themed_svg_icon(svg_path: str, palette: QtGui.QPalette, size: QtCore.QSize) -> QtGui.QIcon:
    """
    Load an SVG and tint it to match palette colors.

    - Normal: palette.windowText()
    - Disabled: palette.disabled().windowText() (falls back to mid)
    - Active: palette.highlightedText() (falls back to windowText)
    """
    if not svg_path:
        return QtGui.QIcon()

    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        return QtGui.QIcon(svg_path)

    base = _render_svg(renderer, size)
    if base is None:
        return QtGui.QIcon(svg_path)

    normal = palette.color(QtGui.QPalette.Active, QtGui.QPalette.WindowText)
    disabled = palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText)
    if disabled == normal:
        disabled = palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Mid)
    active = palette.color(QtGui.QPalette.Active, QtGui.QPalette.HighlightedText)
    if not active.isValid() or active == normal:
        active = normal

    icon = QtGui.QIcon()
    _add_icon_state(icon, base, normal, QtGui.QIcon.Normal)
    _add_icon_state(icon, base, active, QtGui.QIcon.Active)
    _add_icon_state(icon, base, disabled, QtGui.QIcon.Disabled)
    _add_icon_state(icon, base, normal, QtGui.QIcon.Selected)
    return icon


def snapshot_icon_path(name: str) -> str:
    """Return the theme-specific snapshot control icon path."""
    mode = get_theme_mode()
    candidate = resource_path("resources", "icons", "snapshot", mode, f"{name}.svg")
    if os.path.exists(candidate):
        return candidate

    fallback = _SNAPSHOT_ICON_FALLBACKS.get(name, name)
    fallback_path = resource_path("resources", "icons", fallback)
    if os.path.exists(fallback_path):
        return fallback_path
    return ""


def snapshot_icon(name: str) -> QtGui.QIcon:
    """Return a QIcon for snapshot transport controls (no tinting)."""
    path = snapshot_icon_path(name)
    return QtGui.QIcon(path) if path else QtGui.QIcon()


def _render_svg(renderer: QtSvg.QSvgRenderer, size: QtCore.QSize) -> QtGui.QImage | None:
    if size.width() <= 0 or size.height() <= 0:
        size = QtCore.QSize(16, 16)

    dpr = _device_pixel_ratio()
    target = QtCore.QSize(
        max(1, int(size.width() * dpr)),
        max(1, int(size.height() * dpr)),
    )
    image = QtGui.QImage(target, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    renderer.render(painter, QtCore.QRectF(0, 0, target.width(), target.height()))
    painter.end()

    image.setDevicePixelRatio(dpr)
    return image


def _add_icon_state(
    icon: QtGui.QIcon, base: QtGui.QImage, color: QtGui.QColor, mode: QtGui.QIcon.Mode
) -> None:
    pixmap = _tint_pixmap(base, color)
    icon.addPixmap(pixmap, mode, QtGui.QIcon.Off)
    icon.addPixmap(pixmap, mode, QtGui.QIcon.On)


def _tint_pixmap(base: QtGui.QImage, color: QtGui.QColor) -> QtGui.QPixmap:
    image = QtGui.QImage(base.size(), QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    painter.drawImage(0, 0, base)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), color)
    painter.end()
    image.setDevicePixelRatio(base.devicePixelRatio())
    pixmap = QtGui.QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(base.devicePixelRatio())
    return pixmap


def _device_pixel_ratio() -> float:
    app = QtWidgets.QApplication.instance()
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            return float(screen.devicePixelRatio())
    return 1.0
