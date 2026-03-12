# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""ThemeManager -- theme/styling logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QPalette, QAction
from PyQt6.QtWidgets import QApplication, QPushButton, QToolButton

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class ThemeManager(QObject):
    """Manages theme switching, icon refresh, and stylesheet application."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    # ------------------------------------------------------------------
    # Status bar theme
    # ------------------------------------------------------------------

    def _apply_status_bar_theme(self) -> None:
        """Apply palette-aware styling to status and progress bars.

        Delegates to the host's inline implementation since this method
        is also called during __init__ before managers are ready.
        """
        self._host._apply_status_bar_theme()

    # ------------------------------------------------------------------
    # Action / menu checks
    # ------------------------------------------------------------------

    def _update_theme_action_checks(self, mode: str) -> None:
        """Sync Color Theme menu checkboxes with the active mode."""
        h = self._host
        scheme = (mode or "light").lower()
        if scheme in ("system", "auto"):
            scheme = "light"

        action_map = {
            "light": getattr(h, "action_theme_light", None),
            "dark": getattr(h, "action_theme_dark", None),
        }

        for key, action in action_map.items():
            if isinstance(action, QAction):
                action.setChecked(scheme == key)

    def _update_action_icons(self) -> None:
        """Update action icons to match current theme (light/dark)."""
        h = self._host
        if hasattr(h, "id_toggle_act"):
            h.id_toggle_act.setIcon(QIcon(h.icon_path("ID.svg")))
        if hasattr(h, "od_toggle_act"):
            h.od_toggle_act.setIcon(QIcon(h.icon_path("OD.svg")))
        if hasattr(h, "avg_pressure_toggle_act"):
            h.avg_pressure_toggle_act.setIcon(QIcon(h.icon_path("P.svg")))
        if hasattr(h, "set_pressure_toggle_act"):
            h.set_pressure_toggle_act.setIcon(QIcon(h.icon_path("SP.svg")))

        if hasattr(h, "home_action"):
            h.home_action.setIcon(QIcon(h.icon_path("Home.svg")))
        if hasattr(h, "save_session_action"):
            h.save_session_action.setIcon(QIcon(h.icon_path("Save.svg")))
        if hasattr(h, "review_events_action"):
            h.review_events_action.setIcon(QIcon(h.icon_path("review-events.svg")))
        if hasattr(h, "excel_action"):
            h.excel_action.setIcon(QIcon(h.icon_path("excel-mapper.svg")))
        if hasattr(h, "sync_clip_action"):
            h.sync_clip_action.setIcon(QIcon(h.icon_path("play_arrow.svg")))

    # ------------------------------------------------------------------
    # Main apply_theme
    # ------------------------------------------------------------------

    def apply_theme(self, mode: str, *, persist: bool = False) -> None:
        """Apply light or dark theme at runtime and refresh all UI widgets."""
        h = self._host
        from vasoanalyzer.ui.theme import CURRENT_THEME

        log.debug(
            "[THEME-DEBUG] App.apply_theme called with mode=%r, persist=%s, id(self)=%s",
            mode,
            persist,
            id(h),
        )

        scheme = (mode or "light").lower()
        if scheme in ("system", "auto"):
            scheme = "light"

        if persist:
            try:
                from vasoanalyzer.ui import theme as theme_module

                theme_module.apply_theme(scheme, persist=True)
            except Exception:
                return
            return

        h._active_theme_mode = scheme
        current_name = (
            CURRENT_THEME.get("name") if isinstance(CURRENT_THEME, dict) else CURRENT_THEME
        )
        log.debug("[THEME-DEBUG] CURRENT_THEME=%r", current_name)

        self._update_theme_action_checks(h._active_theme_mode)
        self._update_action_icons()
        self._apply_status_bar_theme()
        apply_data_page_style = getattr(h, "_apply_data_page_style", None)
        if callable(apply_data_page_style):
            apply_data_page_style()

        if hasattr(h, "home_page") and h.home_page is not None:
            apply_theme_fn = getattr(h.home_page, "apply_theme", None)
            if callable(apply_theme_fn):
                apply_theme_fn(scheme)
            else:
                h.home_page._apply_stylesheet()

        if hasattr(h, "event_table") and h.event_table is not None:
            apply_theme_fn = getattr(h.event_table, "apply_theme", None)
            if callable(apply_theme_fn):
                apply_theme_fn()

        review_panel = getattr(h, "review_panel", None)
        apply_review_theme = getattr(review_panel, "apply_theme", None)
        if callable(apply_review_theme):
            with contextlib.suppress(Exception):
                apply_review_theme()

        if hasattr(h, "_apply_event_table_card_theme"):
            with contextlib.suppress(Exception):
                h._apply_event_table_card_theme()

        project_dock = getattr(h, "project_dock", None)
        apply_project_theme = getattr(project_dock, "apply_theme", None)
        if callable(apply_project_theme):
            apply_project_theme()

        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "apply_theme"):
            with contextlib.suppress(Exception):
                plot_host.apply_theme()
        overview = getattr(h, "overview_strip", None)
        if overview is not None and hasattr(overview, "apply_theme"):
            with contextlib.suppress(Exception):
                overview.apply_theme()
        nav_bar = getattr(h, "trace_nav_bar", None)
        if nav_bar is not None and hasattr(nav_bar, "apply_theme"):
            with contextlib.suppress(Exception):
                nav_bar.apply_theme()

        for dock_name in (
            "layout_dock",
            "preset_library_dock",
            "advanced_style_dock",
            "export_queue_dock",
        ):
            dock = getattr(h, dock_name, None)
            apply_method = getattr(dock, "_apply_theme", None)
            if not callable(apply_method):
                apply_method = getattr(dock, "apply_theme", None)
            if callable(apply_method):
                apply_method()

        for dock_name in ("scope_dock", "zoom_dock"):
            dock = getattr(h, dock_name, None)
            apply_method = getattr(dock, "apply_theme", None)
            if callable(apply_method):
                apply_method()

        if hasattr(h, "_apply_snapshot_theme"):
            with contextlib.suppress(Exception):
                h._apply_snapshot_theme()

        toolbar = getattr(h, "toolbar", None)
        if toolbar is not None and hasattr(toolbar, "apply_theme"):
            with contextlib.suppress(Exception):
                toolbar.apply_theme()

        if hasattr(h, "_apply_primary_toolbar_theme"):
            with contextlib.suppress(Exception):
                h._apply_primary_toolbar_theme()

        # Force complete repaint to ensure all widgets pick up new colors
        h.update()
        QApplication.processEvents()
        log.debug("[THEME-DEBUG] Forced repaint after theme change")

    def set_color_scheme(self, scheme: str):
        """Set application color scheme (light or dark)."""
        self.apply_theme(scheme, persist=True)

    # ------------------------------------------------------------------
    # Card / panel themes
    # ------------------------------------------------------------------

    def _apply_event_table_card_theme(self) -> None:
        """Apply theme styling to the event table container card."""
        h = self._host
        from vasoanalyzer.ui.theme import CURRENT_THEME

        log.debug(
            "[THEME-DEBUG] _apply_event_table_card_theme called, card_exists=%s",
            hasattr(h, "event_table_card") and h.event_table_card is not None,
        )

        card = getattr(h, "event_table_card", None)
        if card is None:
            return

        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
        bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("window_bg", "#ffffff"))
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        text = CURRENT_THEME.get("text", "#000000")
        card.setStyleSheet(
            f"""
            QFrame#TableCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QFrame#TableCard QWidget {{
                color: {text};
            }}
        """
        )
        style = card.styleSheet() if card is not None else ""
        log.debug("[THEME-DEBUG] EventTableCard styleSheet length=%s", len(style))

    def _apply_snapshot_theme(self) -> None:
        """Apply theme styling to the snapshot card and controls."""
        h = self._host
        from vasoanalyzer.ui.theme import CURRENT_THEME

        card = getattr(h, "snapshot_card", None)
        if card is None:
            return

        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
        bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("window_bg", "#ffffff"))
        text = CURRENT_THEME.get("text", "#000000")
        status = CURRENT_THEME.get("text_disabled", text)
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        panel_bg = CURRENT_THEME.get("panel_bg", bg)
        panel_border = CURRENT_THEME.get("panel_border", border)
        button_bg = CURRENT_THEME.get("button_bg", bg)
        button_hover = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active = CURRENT_THEME.get(
            "button_active_bg", CURRENT_THEME.get("selection_bg", button_hover)
        )

        card.setStyleSheet(
            f"""
            QFrame#SnapshotCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QFrame#SnapshotCard QLabel {{
                color: {text};
            }}
            QFrame#SnapshotCard QFrame#TiffViewerHeader {{
                background: transparent;
                border: none;
            }}
            QFrame#SnapshotCard QWidget#TiffTransportBar {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: {radius}px;
            }}
            QLabel#SnapshotSpeedLabel,
            QLabel#SnapshotTimeLabel {{
                color: {text};
                font-size: 10px;
            }}
            QLabel#SnapshotTimeLabel {{
                font-family: Menlo, Consolas, "Courier New", monospace;
            }}
            QLabel#SnapshotStatusLabel {{
                color: {status};
                font-size: 10px;
            }}
            QLabel#SnapshotSubsampleLabel {{
                background: {button_hover};
                color: {text};
                border-radius: {radius}px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QFrame#SnapshotCard QToolButton {{
                background: {button_bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 0px;
                min-height: 30px;
                min-width: 30px;
                font-size: 12px;
            }}
            QFrame#SnapshotCard QToolButton:hover {{
                background: {button_hover};
            }}
            QFrame#SnapshotCard QToolButton:pressed,
            QFrame#SnapshotCard QToolButton:checked {{
                background: {button_active};
            }}
            QFrame#SnapshotCard QToolButton:disabled {{
                background: {panel_bg};
                border-color: {panel_border};
                color: {status};
            }}
            QFrame#SnapshotCard QComboBox#SnapshotSpeedCombo {{
                background: transparent;
                border: none;
                padding: 2px 4px;
                min-height: 22px;
                font-size: 11px;
                color: {text};
            }}
        """
        )

        with contextlib.suppress(Exception):
            h._update_snapshot_playback_icons()

    # ------------------------------------------------------------------
    # Primary toolbar theme
    # ------------------------------------------------------------------

    def _apply_primary_toolbar_theme(self) -> None:
        """Refresh primary toolbar styles and icons from the current theme."""
        h = self._host

        toolbar = getattr(h, "primary_toolbar", None)
        if toolbar is None:
            return

        icon_actions = {
            "home_action": "Home.svg",
            "load_trace_action": "folder-open.svg",
            "load_snapshot_action": "empty-box.svg",
            "excel_action": "excel-mapper.svg",
            "review_events_action": None,
            "load_events_action": "folder-plus.svg",
            "save_session_action": "Save.svg",
            "welcome_action": "info-circle.svg",
        }
        for attr, icon_name in icon_actions.items():
            action = getattr(h, attr, None)
            if not isinstance(action, QAction) or not icon_name:
                continue
            try:
                action.setIcon(QIcon(h.icon_path(icon_name)))
            except Exception:
                continue

        try:
            import_button = toolbar.findChild(QToolButton, "ImportDataButton")
            if import_button and hasattr(h, "load_trace_action"):
                import_button.setIcon(h.load_trace_action.icon())
        except Exception:
            log.debug("Failed to assign icon to import button", exc_info=True)

        if hasattr(h, "_shared_button_css"):
            toolbar.setStyleSheet(h._shared_button_css())
            for action in toolbar.actions():
                widget = toolbar.widgetForAction(action)
                if isinstance(widget, QPushButton):
                    h._apply_button_style(widget)
