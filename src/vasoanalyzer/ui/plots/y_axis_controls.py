"""Compact Y-axis control widgets for per-track scaling actions."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable

from PyQt5 import QtSvg
from PyQt5.QtCore import QEvent, QFile, QPoint, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import QApplication, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from utils import resource_path

log = logging.getLogger(__name__)

BUTTON_PX = 18
ICON_PX = 14
OUTER_GUTTER_PX = BUTTON_PX + 2

_BTN_SIZE = QSize(BUTTON_PX, BUTTON_PX)
_ICON_SIZE = QSize(ICON_PX, ICON_PX)
_SVG_ICON_CACHE: dict[tuple[str, int, int, float, float, float], QIcon] = {}
_ICON_RENDER_DEBUG_LOGGED: set[tuple[str, int, float, float, float]] = set()
_ICON_REFRESH_EVENT_TYPES = {
    QEvent.PaletteChange,
    QEvent.ApplicationPaletteChange,
    QEvent.StyleChange,
    QEvent.Show,
}
_SCREEN_CHANGE_EVENT = getattr(QEvent, "ScreenChangeInternal", None)
if _SCREEN_CHANGE_EVENT is not None:
    _ICON_REFRESH_EVENT_TYPES.add(_SCREEN_CHANGE_EVENT)

__all__ = [
    "BUTTON_PX",
    "ICON_PX",
    "OUTER_GUTTER_PX",
    "required_outer_gutter_px",
    "YAxisControls",
]


def _logical_size(base_px: int, dpr: float) -> int:
    """Scale logical control size for high-DPI while capping growth."""
    factor = min(max(float(dpr), 1.0), 1.5)
    return max(int(round(float(base_px) * factor)), 1)


def _alpha_bbox(image: QImage, alpha_threshold: int = 0) -> tuple[int, int, int, int] | None:
    left = image.width()
    top = image.height()
    right = -1
    bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if QColor.fromRgba(image.pixel(x, y)).alpha() <= alpha_threshold:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return None
    return left, top, right, bottom


def _trim_and_rescale_icon(
    image: QImage,
    *,
    render_px: int,
    min_bbox_width_ratio: float = 0.0,
    min_bbox_height_ratio: float = 0.0,
) -> QImage:
    bbox = _alpha_bbox(image)
    if bbox is None:
        return image

    left, top, right, bottom = bbox
    bbox_w = right - left + 1
    bbox_h = bottom - top + 1
    target = max(1, int(render_px))
    width_ratio = float(bbox_w) / float(target)
    height_ratio = float(bbox_h) / float(target)

    margin_l = left
    margin_r = max(0, target - 1 - right)
    margin_t = top
    margin_b = max(0, target - 1 - bottom)
    margin_floor = max(2, int(round(target * 0.12)))
    has_large_symmetric_margins = (
        abs(margin_l - margin_r) <= 1 and margin_l >= margin_floor
    ) or (
        abs(margin_t - margin_b) <= 1 and margin_t >= margin_floor
    )
    too_small = width_ratio < 0.75 or height_ratio < 0.75
    if not too_small and not has_large_symmetric_margins:
        return image

    cropped = image.copy(left, top, bbox_w, bbox_h)
    content_target = max(1, int(round(float(target) * 0.8)))
    scaled = cropped.scaled(
        content_target,
        content_target,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )

    if min_bbox_width_ratio > 0.0 or min_bbox_height_ratio > 0.0:
        min_w = max(1, int(round(float(target) * float(min_bbox_width_ratio))))
        min_h = max(1, int(round(float(target) * float(min_bbox_height_ratio))))
        adjusted_w = max(scaled.width(), min_w)
        adjusted_h = max(scaled.height(), min_h)
        adjusted_w = min(adjusted_w, content_target)
        adjusted_h = min(adjusted_h, content_target)
        if adjusted_w != scaled.width() or adjusted_h != scaled.height():
            scaled = cropped.scaled(
                adjusted_w,
                adjusted_h,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )

    normalized = QImage(target, target, QImage.Format_ARGB32_Premultiplied)
    normalized.fill(Qt.transparent)
    painter = QPainter(normalized)
    x = max(0, (target - scaled.width()) // 2)
    y = max(0, (target - scaled.height()) // 2)
    painter.drawImage(x, y, scaled)
    painter.end()
    return normalized


def _template_svg_icon(
    svg_path: str,
    px: int,
    color: QColor,
    dpr: float,
    *,
    min_bbox_width_ratio: float = 0.0,
    min_bbox_height_ratio: float = 0.0,
) -> QIcon:
    """Render a template SVG as a palette-tinted icon at device resolution."""
    px_value = max(int(px), 1)
    dpr_value = max(float(dpr), 1.0)
    min_bbox_width_ratio_value = max(0.0, float(min_bbox_width_ratio))
    min_bbox_height_ratio_value = max(0.0, float(min_bbox_height_ratio))
    color_value = QColor(color)
    if not color_value.isValid():
        color_value = QColor(127, 127, 127)
    key = (
        str(svg_path),
        px_value,
        int(color_value.rgba()),
        round(dpr_value, 2),
        round(min_bbox_width_ratio_value, 3),
        round(min_bbox_height_ratio_value, 3),
    )
    cached = _SVG_ICON_CACHE.get(key)
    if cached is not None:
        return cached

    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        return QIcon()

    render_px = max(1, int(round(px_value * dpr_value)))
    pixmap = QPixmap(render_px, render_px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0.0, 0.0, float(render_px), float(render_px)))
    painter.end()

    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    image = _trim_and_rescale_icon(
        image,
        render_px=render_px,
        min_bbox_width_ratio=min_bbox_width_ratio_value,
        min_bbox_height_ratio=min_bbox_height_ratio_value,
    )

    tint_painter = QPainter(image)
    tint_painter.setRenderHint(QPainter.Antialiasing, True)
    tint_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    tint_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    tint_painter.fillRect(image.rect(), color_value)
    tint_painter.end()

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr_value)

    debug_key = (
        str(svg_path),
        px_value,
        round(dpr_value, 2),
        round(min_bbox_width_ratio_value, 2),
        round(min_bbox_height_ratio_value, 2),
    )
    if debug_key not in _ICON_RENDER_DEBUG_LOGGED:
        pm_dpr = float(pixmap.devicePixelRatioF())
        if pm_dpr <= 0.0:
            pm_dpr = 1.0
        logical_w = float(pixmap.width()) / pm_dpr
        logical_h = float(pixmap.height()) / pm_dpr
        log.info(
            (
                "[Y-axis icon debug] svg=%s px=%d render_px=%d pixmap.size=%dx%d "
                "pixmap.dpr=%.3f logical_size=%.2fx%.2f"
            ),
            svg_path,
            px_value,
            render_px,
            int(pixmap.width()),
            int(pixmap.height()),
            pm_dpr,
            logical_w,
            logical_h,
        )
        _ICON_RENDER_DEBUG_LOGGED.add(debug_key)

    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Normal, QIcon.Off)
    icon.addPixmap(pixmap, QIcon.Active, QIcon.Off)
    icon.addPixmap(pixmap, QIcon.Selected, QIcon.Off)

    disabled = QColor(color_value)
    disabled.setAlpha(max(40, int(round(color_value.alpha() * 0.6))))
    disabled_image = QImage(image)
    disabled_painter = QPainter(disabled_image)
    disabled_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    disabled_painter.fillRect(disabled_image.rect(), disabled)
    disabled_painter.end()
    disabled_pixmap = QPixmap.fromImage(disabled_image)
    disabled_pixmap.setDevicePixelRatio(dpr_value)
    icon.addPixmap(disabled_pixmap, QIcon.Disabled, QIcon.Off)

    _SVG_ICON_CACHE[key] = icon
    return icon


def required_outer_gutter_px() -> int:
    """Minimum per-plot left gutter required by the Y control widgets."""
    dpr = 1.0
    app = QApplication.instance()
    if app is not None:
        with contextlib.suppress(Exception):
            screen = app.primaryScreen()
            if screen is not None:
                ratio = float(screen.devicePixelRatio())
                if ratio > 0.0:
                    dpr = ratio
    padding_px = max(int(OUTER_GUTTER_PX - BUTTON_PX), 0)
    return int(_logical_size(BUTTON_PX, dpr) + padding_px)


class YAxisControls(QWidget):
    """Axis-adjacent Y controls with top menu and bottom +/- scaling buttons."""

    def __init__(
        self,
        *,
        parent: QWidget,
        get_state: Callable[[], bool],
        set_state: Callable[[bool], None],
        autoscale_once: Callable[[], None],
        zoom_out_scale: Callable[[], None],
        zoom_in_scale: Callable[[], None],
        set_scale_dialog: Callable[[], None],
        reset_scale: Callable[[], None],
        include_in_global_get: Callable[[], bool] | None = None,
        include_in_global_set: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_state = get_state
        self._set_state = set_state
        self._autoscale_once = autoscale_once
        self._zoom_out_scale = zoom_out_scale
        self._zoom_in_scale = zoom_in_scale
        self._set_scale_dialog = set_scale_dialog
        self._reset_scale = reset_scale
        self._include_in_global_get = include_in_global_get
        self._include_in_global_set = include_in_global_set

        self.setObjectName("YAxisControls")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.hide()

        self._menu_icon_resource = ":/icons/chevron-down.svg"
        self._plus_icon_resource = ":/icons/plus.svg"
        self._minus_icon_resource = ":/icons/minus.svg"
        self._menu_icon_path = resource_path("icons", "chevron-down.svg")
        self._plus_icon_path = resource_path("icons", "plus.svg")
        self._minus_icon_path = resource_path("icons", "minus.svg")
        initial_dpr = self._current_dpr()
        btn_px = _logical_size(BUTTON_PX, initial_dpr)
        icon_px = _logical_size(ICON_PX, initial_dpr)
        self._btn_size = QSize(btn_px, btn_px)
        self._icon_size = QSize(icon_px, icon_px)

        self.menu_button_widget = QWidget(self)
        self.menu_button_widget.setObjectName("YAxisMenuButtonWidget")
        self.menu_button_widget.setAttribute(Qt.WA_StyledBackground, False)
        menu_layout = QVBoxLayout(self.menu_button_widget)
        menu_layout.setContentsMargins(0, 0, 0, 0)
        menu_layout.setSpacing(0)

        self.scale_menu_btn = QToolButton(self.menu_button_widget)
        self.scale_menu_btn.setObjectName("YAxisScaleMenuButton")
        self.scale_menu_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.scale_menu_btn.setAutoRaise(True)
        self.scale_menu_btn.setFocusPolicy(Qt.NoFocus)
        self.scale_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.scale_menu_btn.setToolTip("Y scale options")
        self.scale_menu_btn.setFixedSize(self._btn_size)
        self.scale_menu_btn.setIconSize(self._icon_size)
        menu_layout.addWidget(self.scale_menu_btn)
        self.menu_button_widget.adjustSize()

        self.scale_buttons_widget = QWidget(self)
        self.scale_buttons_widget.setObjectName("YAxisScaleButtonsWidget")
        self.scale_buttons_widget.setAttribute(Qt.WA_StyledBackground, False)
        scale_layout = QVBoxLayout(self.scale_buttons_widget)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(2)

        self.zoom_in_btn = QToolButton(self.scale_buttons_widget)
        self.zoom_in_btn.setObjectName("YAxisZoomInButton")
        self.zoom_in_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.zoom_in_btn.setAutoRaise(True)
        self.zoom_in_btn.setFocusPolicy(Qt.NoFocus)
        self.zoom_in_btn.setToolTip("Scale up (+): bigger waveform")
        self.zoom_in_btn.setFixedSize(self._btn_size)
        self.zoom_in_btn.setIconSize(self._icon_size)
        self.zoom_in_btn.clicked.connect(self._handle_zoom_in_triggered)
        scale_layout.addWidget(self.zoom_in_btn)

        self.zoom_out_btn = QToolButton(self.scale_buttons_widget)
        self.zoom_out_btn.setObjectName("YAxisZoomOutButton")
        self.zoom_out_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.zoom_out_btn.setAutoRaise(True)
        self.zoom_out_btn.setFocusPolicy(Qt.NoFocus)
        self.zoom_out_btn.setToolTip("Scale down (-): smaller waveform")
        self.zoom_out_btn.setFixedSize(self._btn_size)
        self.zoom_out_btn.setIconSize(self._icon_size)
        self.zoom_out_btn.clicked.connect(self._handle_zoom_out_triggered)
        scale_layout.addWidget(self.zoom_out_btn)
        self.scale_buttons_widget.adjustSize()

        self._menu = QMenu(self.scale_menu_btn)
        self.scale_menu_btn.setMenu(self._menu)
        self._menu.aboutToShow.connect(self.refresh_state)

        self._autoscale_once_action = self._menu.addAction("Autoscale once")
        self._autoscale_once_action.triggered.connect(self._handle_autoscale_once_triggered)

        self._continuous_action = self._menu.addAction("Continuous autoscale")
        self._continuous_action.setCheckable(True)
        self._continuous_action.toggled.connect(self._handle_auto_toggled)

        self._set_scale_action = self._menu.addAction("Set Y scale...")
        self._set_scale_action.triggered.connect(self._set_scale_dialog)

        self._reset_scale_action = self._menu.addAction("Reset Y scale")
        self._reset_scale_action.triggered.connect(self._reset_scale)

        self._menu.addSeparator()
        self._expand_action = self._menu.addAction("Expand Y range")
        self._expand_action.triggered.connect(self._handle_zoom_out_triggered)
        self._compress_action = self._menu.addAction("Compress Y range")
        self._compress_action.triggered.connect(self._handle_zoom_in_triggered)

        self._include_in_global_action = None
        if callable(self._include_in_global_get) and callable(self._include_in_global_set):
            self._menu.addSeparator()
            self._include_in_global_action = self._menu.addAction("Include in Auto Y (All)")
            self._include_in_global_action.setCheckable(True)
            self._include_in_global_action.toggled.connect(self._handle_include_in_global_toggled)

        self.setStyleSheet(
            """
            QToolButton {
                padding: 0px;
                margin: 0px;
                background: transparent;
            }
            QToolButton#YAxisScaleMenuButton,
            QToolButton#YAxisZoomInButton,
            QToolButton#YAxisZoomOutButton {
                border: 1px solid palette(mid);
                background: palette(base);
                border-radius: 2px;
                font-weight: 600;
                font-size: 11px;
            }
            QToolButton#YAxisScaleMenuButton[continuousEnabled="true"] {
                border: 1px solid palette(highlight);
                background: palette(button);
            }
            QToolButton#YAxisScaleMenuButton:hover,
            QToolButton#YAxisZoomInButton:hover,
            QToolButton#YAxisZoomOutButton:hover {
                background: palette(button);
            }
            QToolButton#YAxisScaleMenuButton:pressed,
            QToolButton#YAxisZoomInButton:pressed,
            QToolButton#YAxisZoomOutButton:pressed {
                background: palette(midlight);
            }
            """
        )

        self._apply_icons()
        self.refresh_state()

    @property
    def menu_btn(self) -> QToolButton:
        """Backward-compatible alias for scale menu button."""
        return self.scale_menu_btn

    def event(self, event) -> bool:
        handled = super().event(event)
        if event is not None and event.type() in _ICON_REFRESH_EVENT_TYPES:
            self._apply_icons()
        return handled

    def refresh_state(self) -> None:
        """Sync checked states with the underlying autoscale settings."""
        enabled = bool(self._get_state())
        self.scale_menu_btn.setProperty("continuousEnabled", enabled)
        self.scale_menu_btn.style().unpolish(self.scale_menu_btn)
        self.scale_menu_btn.style().polish(self.scale_menu_btn)

        self._continuous_action.blockSignals(True)
        self._continuous_action.setChecked(enabled)
        self._continuous_action.blockSignals(False)

        if self._include_in_global_action is not None and self._include_in_global_get is not None:
            include = bool(self._include_in_global_get())
            self._include_in_global_action.blockSignals(True)
            self._include_in_global_action.setChecked(include)
            self._include_in_global_action.blockSignals(False)

    def popup_menu(self, global_pos: QPoint | None = None) -> None:
        """Show the controls menu at a global position."""
        self.refresh_state()
        if global_pos is None:
            global_pos = self.scale_menu_btn.mapToGlobal(self.scale_menu_btn.rect().bottomLeft())
        self._menu.popup(global_pos)

    def _handle_auto_toggled(self, enabled: bool) -> None:
        self._set_state(bool(enabled))
        self.refresh_state()

    def _handle_autoscale_once_triggered(self, _checked: bool = False) -> None:
        _ = _checked
        self._autoscale_once()
        self.refresh_state()

    def _handle_zoom_in_triggered(self, _checked: bool = False) -> None:
        _ = _checked
        self._zoom_in_scale()
        self.refresh_state()

    def _handle_zoom_out_triggered(self, _checked: bool = False) -> None:
        _ = _checked
        self._zoom_out_scale()
        self.refresh_state()

    def _handle_include_in_global_toggled(self, enabled: bool) -> None:
        if self._include_in_global_set is None:
            return
        self._include_in_global_set(bool(enabled))
        self.refresh_state()

    def _apply_icons(self) -> None:
        self._apply_dpr_sizes()
        color = self._icon_tint_color()
        dpr = self._current_dpr()

        self._apply_button_icon(
            self.scale_menu_btn,
            resource_name=self._menu_icon_resource,
            fallback_path=self._menu_icon_path,
            fallback_text="",
            color=color,
            dpr=dpr,
        )
        self._apply_button_icon(
            self.zoom_in_btn,
            resource_name=self._plus_icon_resource,
            fallback_path=self._plus_icon_path,
            fallback_text="+",
            color=color,
            dpr=dpr,
        )
        self._apply_button_icon(
            self.zoom_out_btn,
            resource_name=self._minus_icon_resource,
            fallback_path=self._minus_icon_path,
            fallback_text="-",
            color=color,
            dpr=dpr,
        )

    def _apply_dpr_sizes(self) -> None:
        dpr = self._current_dpr()
        btn_px = _logical_size(BUTTON_PX, dpr)
        icon_px = _logical_size(ICON_PX, dpr)
        next_btn_size = QSize(btn_px, btn_px)
        next_icon_size = QSize(icon_px, icon_px)
        if next_btn_size == self._btn_size and next_icon_size == self._icon_size:
            return
        self._btn_size = next_btn_size
        self._icon_size = next_icon_size
        for button in (self.scale_menu_btn, self.zoom_in_btn, self.zoom_out_btn):
            button.setFixedSize(self._btn_size)
            button.setIconSize(self._icon_size)

    def _apply_button_icon(
        self,
        button: QToolButton,
        *,
        resource_name: str,
        fallback_path: str,
        fallback_text: str,
        color: QColor,
        dpr: float,
    ) -> None:
        px = max(int(button.iconSize().width()), ICON_PX)
        if fallback_text == "+":
            min_bbox_width_ratio = 0.70
            min_bbox_height_ratio = 0.70
        elif fallback_text == "-":
            min_bbox_width_ratio = 0.70
            min_bbox_height_ratio = 0.24
        else:
            min_bbox_width_ratio = 0.0
            min_bbox_height_ratio = 0.0
        icon = self._load_tinted_icon(
            resource_name=resource_name,
            fallback_path=fallback_path,
            px=px,
            color=color,
            dpr=dpr,
            min_bbox_width_ratio=min_bbox_width_ratio,
            min_bbox_height_ratio=min_bbox_height_ratio,
        )
        if not icon.isNull():
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setText("")
            button.setIcon(icon)
            return

        if fallback_text:
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setIcon(QIcon())
            font = button.font()
            font.setBold(True)
            point_size = int(font.pointSize())
            if point_size <= 0:
                point_size = 11
            font.setPointSize(max(point_size, 11))
            button.setFont(font)
            button.setText(fallback_text)
        else:
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(QIcon())
            button.setText("")

    def _load_tinted_icon(
        self,
        *,
        resource_name: str,
        fallback_path: str,
        px: int,
        color: QColor,
        dpr: float,
        min_bbox_width_ratio: float = 0.0,
        min_bbox_height_ratio: float = 0.0,
    ) -> QIcon:
        for svg_path in (resource_name, fallback_path):
            if not svg_path:
                continue
            if svg_path.startswith(":/"):
                if not QFile.exists(svg_path):
                    continue
            elif not os.path.exists(svg_path):
                continue
            icon = _template_svg_icon(
                svg_path,
                px,
                color,
                dpr,
                min_bbox_width_ratio=min_bbox_width_ratio,
                min_bbox_height_ratio=min_bbox_height_ratio,
            )
            if not icon.isNull():
                return icon
        if fallback_path and os.path.exists(fallback_path):
            return QIcon(fallback_path)
        if resource_name:
            return QIcon(resource_name)
        return QIcon()

    def _icon_tint_color(self) -> QColor:
        palette = self.palette()
        color = QColor()
        for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
            candidate = palette.color(role)
            if candidate.isValid() and candidate.alpha() > 0:
                color = QColor(candidate)
                break
        if not color.isValid() or color.alpha() <= 0:
            color = QColor(127, 127, 127)
        min_alpha = int(round(255.0 * 0.85))
        if color.alpha() < min_alpha:
            color.setAlpha(min_alpha)
        return color

    def _current_dpr(self) -> float:
        window = self.window()
        if window is not None:
            with contextlib.suppress(Exception):
                handle = window.windowHandle()
                if handle is not None:
                    screen = handle.screen()
                    if screen is not None:
                        ratio = float(screen.devicePixelRatio())
                        if ratio > 0.0:
                            return ratio

        with contextlib.suppress(Exception):
            ratio = float(self.devicePixelRatioF())
            if ratio > 0.0:
                return ratio

        app = QApplication.instance()
        if app is not None:
            with contextlib.suppress(Exception):
                screen = app.primaryScreen()
                if screen is not None:
                    ratio = float(screen.devicePixelRatio())
                    if ratio > 0.0:
                        return ratio
        return 1.0
