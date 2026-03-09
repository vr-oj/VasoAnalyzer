from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.config import APP_VERSION
from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)


class _HomeWindowProtocol(Protocol):
    def _brand_icon_path(self, extension: str) -> str: ...

    def icon_path(self, filename: str) -> str: ...

    def _make_home_button(
        self,
        text: str,
        icon_name: str,
        callback,
        *,
        primary: bool = False,
        secondary: bool = False,
    ) -> QWidget: ...

    def show_analysis_workspace(self) -> None: ...

    def home_open_project(self) -> None: ...

    def home_open_data(self) -> None: ...

    def show_welcome_guide(self, modal: bool = False) -> None: ...

    def clear_recent_files(self, checked: bool = False) -> None: ...

    def clear_recent_projects(self, checked: bool = False) -> None: ...


class HomePage(QWidget):
    """Standalone widget for the launcher/home experience."""

    create_project_requested = pyqtSignal()

    def __init__(self, window: _HomeWindowProtocol) -> None:
        super().__init__(parent=window)
        self._window = window
        self.setObjectName("HomePage")
        self._settings = QSettings("TykockiLab", "VasoAnalyzer")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName("HomeScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self._scroll_area, 1)

        scroll_host = QWidget()
        scroll_host.setObjectName("HomeScrollHost")
        self._scroll_area.setWidget(scroll_host)

        scroll_layout = QVBoxLayout(scroll_host)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        self._content = QWidget(scroll_host)
        self._content.setObjectName("HomeContent")
        self._content.setMaximumWidth(1120)
        self._content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(32, 32, 32, 24)
        content_layout.setSpacing(24)
        content_layout.addWidget(self._build_hero_section(), stretch=0)
        content_layout.addWidget(self._build_cards_row(), stretch=0)

        scroll_layout.addWidget(self._content, 0, Qt.AlignHCenter | Qt.AlignTop)

        self._banner_container = QFrame(self)
        self._banner_container.setObjectName("HomeBannerContainer")
        banner_layout = QVBoxLayout(self._banner_container)
        banner_layout.setContentsMargins(32, 8, 32, 24)
        banner_layout.setSpacing(0)
        banner_layout.addWidget(self.cloud_storage_warning)
        root.addWidget(self._banner_container, 0)

        self._apply_cloud_storage_visibility()
        self._apply_stylesheet()
        self._update_responsive_layout()

    # ---- layout helpers -------------------------------------------------
    def _build_hero_section(self) -> QFrame:
        window = self._window
        hero = QFrame(self)
        hero.setObjectName("HeroFrame")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)

        brand_icon_path = window._brand_icon_path("svg")
        hero_icon = (
            QSvgWidget(brand_icon_path)
            if brand_icon_path
            else QSvgWidget(window.icon_path("Home.svg"))
        )
        hero_icon.setFixedSize(72, 72)
        layout.addWidget(hero_icon, alignment=Qt.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(12)

        title = QLabel("Welcome to VasoAnalyzer", hero)
        title.setObjectName("HeroTitle")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_row.addWidget(title)

        badge = QLabel(APP_VERSION, hero)
        badge.setObjectName("BetaBadgeLabel")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(24)
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        badge.setToolTip("Current release")
        title_row.addWidget(badge, 0, Qt.AlignVCenter)
        title_row.addStretch(1)

        subtitle = QLabel(
            "Open data, manage projects, and continue your vessel analyses.",
            hero,
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("HeroSubtitle")

        cloud_warning = QFrame(self)
        cloud_warning.setObjectName("CloudStorageWarning")
        cloud_layout = QHBoxLayout(cloud_warning)
        cloud_layout.setContentsMargins(12, 8, 12, 8)
        cloud_layout.setSpacing(12)

        cloud_text = QLabel(
            (
                "<b>Storage recommendation</b><br>"
                "Store active projects on your local drive (Documents, Desktop) for best reliability. "
                "Cloud storage sync can interrupt database writes, potentially causing corruption. "
                "Copy .vaso files to cloud storage for backup and sharing."
            ),
            cloud_warning,
        )
        cloud_text.setWordWrap(True)
        cloud_text.setObjectName("CloudStorageWarningText")
        cloud_layout.addWidget(cloud_text, 1)

        dismiss_btn = QToolButton(cloud_warning)
        dismiss_btn.setObjectName("CloudStorageWarningDismiss")
        dismiss_btn.setText("Got it, don't show again")
        dismiss_btn.setAutoRaise(True)
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.clicked.connect(self._dismiss_cloud_storage_warning)
        cloud_layout.addWidget(dismiss_btn, 0, Qt.AlignTop)

        self.cloud_storage_warning = cloud_warning

        text_column.addLayout(title_row)
        text_column.addWidget(subtitle)
        text_column.addWidget(self._build_primary_actions())
        text_column.addWidget(self._build_secondary_actions())
        text_column.addStretch()

        layout.addLayout(text_column)
        return hero

    def _build_primary_actions(self) -> QWidget:
        window = self._window
        container = QWidget(self)
        container.setObjectName("HomePrimaryActions")
        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        container.setLayout(row)

        window.home_resume_btn = window._make_home_button(
            "Return to workspace",
            "Back.svg",
            lambda: window.show_analysis_workspace(),
            secondary=True,
        )
        window.home_resume_btn.setObjectName("HomeSecondaryButton")
        window.home_resume_btn.hide()
        row.addWidget(window.home_resume_btn)

        open_btn = window._make_home_button(
            "Open Project…",
            "folder-open.svg",
            window.home_open_project,
            primary=True,
        )
        open_btn.setObjectName("HomePrimaryButton")
        row.addWidget(open_btn)

        create_btn = window._make_home_button(
            "Create New Project",
            "folder-plus.svg",
            self.create_project_requested.emit,
            primary=True,
        )
        create_btn.setObjectName("HomePrimaryButton")
        row.addWidget(create_btn)

        self._primary_actions_layout = row
        self._primary_actions_widget = container
        self._primary_action_buttons = [window.home_resume_btn, open_btn, create_btn]
        for button in self._primary_action_buttons:
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        return container

    def _build_secondary_actions(self) -> QWidget:
        window = self._window
        container = QWidget(self)
        container.setObjectName("HomeSecondaryActions")
        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        container.setLayout(row)

        import_btn = window._make_home_button(
            "Open Data…",
            "folder-open.svg",
            window.home_open_data,
            secondary=True,
        )
        import_btn.setObjectName("HomeSecondaryButton")
        import_btn.setToolTip(
            "Quick view: open data without creating a project. You can save as a project later."
        )
        row.addWidget(import_btn)

        self._secondary_actions_spacer = QSpacerItem(
            0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        row.addItem(self._secondary_actions_spacer)

        welcome_btn = QToolButton(self)
        welcome_btn.setObjectName("HomeHelpButton")
        welcome_btn.setText("Welcome Guide")
        welcome_btn.setAutoRaise(True)
        welcome_btn.setCursor(Qt.PointingHandCursor)
        welcome_btn.clicked.connect(lambda: window.show_welcome_guide(modal=False))
        row.addWidget(welcome_btn)

        self._secondary_actions_layout = row
        self._secondary_actions_widget = container
        self._secondary_import_button = import_btn
        self._secondary_help_button = welcome_btn
        import_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        return container

    def _build_cards_row(self) -> QWidget:
        container = QWidget(self)
        container.setObjectName("HomeCardsRow")
        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(24)
        container.setLayout(row)

        sessions_card = self._build_recent_sessions_card()
        projects_card = self._build_recent_projects_card()
        row.addWidget(sessions_card, 1)
        row.addWidget(projects_card, 1)

        self._cards_layout = row
        self._cards_widget = container
        self._cards = [sessions_card, projects_card]
        return container

    def _build_recent_sessions_card(self) -> QFrame:
        window = self._window
        card = QFrame(self)
        card.setObjectName("HomeCard")
        card.setProperty("variant", "sessions")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Recent Imports", card)
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        window.home_clear_sessions_button = self._make_clear_button(
            "Clear all", window.clear_recent_files
        )
        window.home_clear_sessions_button.setVisible(False)
        header.addWidget(window.home_clear_sessions_button, 0, Qt.AlignRight)
        layout.addLayout(header)

        subtitle = QLabel(
            "Files and folders recently brought into projects",
            card,
        )
        subtitle.setObjectName("CardSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        window.home_recent_sessions_layout = QVBoxLayout()
        window.home_recent_sessions_layout.setSpacing(6)
        layout.addLayout(window.home_recent_sessions_layout)
        layout.addStretch()
        return card

    def _build_recent_projects_card(self) -> QFrame:
        window = self._window
        card = QFrame(self)
        card.setObjectName("HomeCard")
        card.setProperty("variant", "projects")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Recent Projects", card)
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        window.home_clear_projects_button = self._make_clear_button(
            "Clear all", window.clear_recent_projects
        )
        window.home_clear_projects_button.setVisible(False)
        header.addWidget(window.home_clear_projects_button, 0, Qt.AlignRight)
        layout.addLayout(header)

        subtitle = QLabel("Projects you've worked on recently", card)
        subtitle.setObjectName("CardSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        window.home_recent_projects_layout = QVBoxLayout()
        window.home_recent_projects_layout.setSpacing(6)
        layout.addLayout(window.home_recent_projects_layout)
        layout.addStretch()
        return card

    def _apply_cloud_storage_visibility(self) -> None:
        show = self._settings.value("home/show_storage_warning", True, type=bool)
        if hasattr(self, "cloud_storage_warning"):
            self.cloud_storage_warning.setVisible(bool(show))
        if hasattr(self, "_banner_container"):
            self._banner_container.setVisible(bool(show))

    def _dismiss_cloud_storage_warning(self) -> None:
        self._settings.setValue("home/show_storage_warning", False)
        if hasattr(self, "cloud_storage_warning"):
            self.cloud_storage_warning.hide()
        if hasattr(self, "_banner_container"):
            self._banner_container.hide()

    def _make_clear_button(self, text: str, callback: Callable[[], None]) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("HomeClearButton")
        button.setText(text)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _needs_stack(
        self,
        widgets: list[QWidget],
        spacing: int,
        available_width: int,
    ) -> bool:
        if available_width <= 0:
            return False
        visible = [widget for widget in widgets if widget.isVisible()]
        if not visible:
            return False
        total = sum(widget.sizeHint().width() for widget in visible)
        total += spacing * max(len(visible) - 1, 0)
        return total > available_width

    def _set_action_button_policy(self, buttons: list[QWidget], *, expand: bool) -> None:
        policy = QSizePolicy.Expanding if expand else QSizePolicy.Preferred
        for button in buttons:
            button.setSizePolicy(policy, QSizePolicy.Fixed)

    def _update_responsive_layout(self) -> None:
        if not hasattr(self, "_content"):
            return

        if hasattr(self, "_primary_actions_layout"):
            available_width = self._primary_actions_widget.contentsRect().width()
            stack = self._needs_stack(
                self._primary_action_buttons,
                self._primary_actions_layout.spacing(),
                available_width,
            )
            direction = QBoxLayout.TopToBottom if stack else QBoxLayout.LeftToRight
            self._primary_actions_layout.setDirection(direction)
            self._primary_actions_layout.setSpacing(10 if stack else 12)
            self._set_action_button_policy(self._primary_action_buttons, expand=stack)

        if hasattr(self, "_secondary_actions_layout"):
            available_width = self._secondary_actions_widget.contentsRect().width()
            stack = self._needs_stack(
                [self._secondary_import_button, self._secondary_help_button],
                self._secondary_actions_layout.spacing(),
                available_width,
            )
            direction = QBoxLayout.TopToBottom if stack else QBoxLayout.LeftToRight
            self._secondary_actions_layout.setDirection(direction)
            self._secondary_actions_layout.setSpacing(8 if stack else 12)
            if hasattr(self, "_secondary_actions_spacer"):
                if stack:
                    self._secondary_actions_spacer.changeSize(
                        0, 0, QSizePolicy.Fixed, QSizePolicy.Fixed
                    )
                else:
                    self._secondary_actions_spacer.changeSize(
                        0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum
                    )
            self._secondary_actions_layout.setAlignment(
                self._secondary_help_button,
                Qt.AlignLeft if stack else (Qt.AlignRight | Qt.AlignVCenter),
            )
            self._secondary_import_button.setSizePolicy(
                QSizePolicy.Expanding if stack else QSizePolicy.Preferred,
                QSizePolicy.Fixed,
            )
            self._secondary_actions_layout.invalidate()

        if hasattr(self, "_cards_layout"):
            available_width = self._cards_widget.contentsRect().width()
            stack = self._needs_stack(self._cards, self._cards_layout.spacing(), available_width)
            direction = QBoxLayout.TopToBottom if stack else QBoxLayout.LeftToRight
            self._cards_layout.setDirection(direction)
            self._cards_layout.setSpacing(16 if stack else 24)

    def _apply_stylesheet(self) -> None:
        window = self._window
        border_color: str = CURRENT_THEME["grid_color"]
        text_color: str = CURRENT_THEME["text"]
        window_bg: str = CURRENT_THEME["window_bg"]
        content_bg: str = CURRENT_THEME.get("table_bg", window_bg)
        page_bg: str = window_bg
        hero_bg: str = content_bg

        def rgba_from_hex(color: str, alpha: float) -> str:
            color = color.strip()
            if color.startswith("rgba"):
                return color
            color = color.lstrip("#")
            if len(color) == 3:
                color = "".join(ch * 2 for ch in color)
            try:
                r, g, b = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return text_color
            alpha = max(0.0, min(1.0, alpha))
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"

        def mix_hex(color_a: str, color_b: str, ratio: float) -> str:
            raw_a = color_a.strip()
            raw_b = color_b.strip()
            if raw_a.startswith(("rgba", "rgb")):
                return color_a
            if raw_b.startswith(("rgba", "rgb")):
                return color_a
            color_a = raw_a.lstrip("#")
            color_b = raw_b.lstrip("#")
            if len(color_a) == 3:
                color_a = "".join(ch * 2 for ch in color_a)
            if len(color_b) == 3:
                color_b = "".join(ch * 2 for ch in color_b)
            try:
                a = [int(color_a[i : i + 2], 16) for i in (0, 2, 4)]
                b = [int(color_b[i : i + 2], 16) for i in (0, 2, 4)]
            except ValueError:
                return raw_a
            ratio = max(0.0, min(1.0, ratio))
            mixed = [round(a[i] * (1 - ratio) + b[i] * ratio) for i in range(3)]
            return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

        card_bg = mix_hex(content_bg, window_bg, 0.18)

        subtitle_color = rgba_from_hex(text_color, 0.7)
        card_title_color = text_color
        placeholder_color = rgba_from_hex(text_color, 0.5)
        muted_action_color = rgba_from_hex(text_color, 0.55)
        accent = CURRENT_THEME.get("accent", text_color)
        accent_fill = CURRENT_THEME.get("accent_fill", accent)
        row_hover_color = rgba_from_hex(accent_fill, 0.12)
        info_bg = rgba_from_hex(accent_fill, 0.08)
        info_border = rgba_from_hex(accent_fill, 0.35)
        card_border_color = rgba_from_hex(border_color, 0.55)
        hero_border_color = rgba_from_hex(border_color, 0.85)
        button_bg = CURRENT_THEME.get("button_bg", window_bg)
        button_hover_bg = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active_bg = CURRENT_THEME.get("button_active_bg", accent_fill)
        if window_bg.lower() == "#ffffff":
            hero_primary_bg = "#1774FF"
            hero_primary_hover = "#CCE0FF"
        else:
            hero_primary_bg = accent
            hero_primary_hover = accent_fill
        hero_primary_text = "#FFFFFF"
        hero_secondary_bg = mix_hex(content_bg, window_bg, 0.06)
        hero_secondary_hover = button_hover_bg
        hero_secondary_text = text_color
        hero_secondary_border = rgba_from_hex(border_color, 0.65)

        # Clear stylesheet first to ensure fresh evaluation
        self.setStyleSheet("")

        # Apply new stylesheet with updated theme colors
        self.setStyleSheet(
            window._shared_button_css()
            + f"""
QWidget#HomePage {{
    background: {page_bg};
}}
QScrollArea#HomeScrollArea,
QWidget#HomeScrollHost,
QWidget#HomeContent,
QFrame#HomeBannerContainer {{
    background: {page_bg};
}}
QFrame#HeroFrame {{
    background: {hero_bg};
    border: 1px solid {hero_border_color};
    border-radius: 16px;
}}
QFrame#HomeCard {{
    background: {card_bg};
    border: 1px solid {card_border_color};
    border-radius: 14px;
}}
QLabel#HeroTitle {{
    font-size: 24px;
    font-weight: 600;
}}
QLabel#HeroSubtitle {{
    color: {subtitle_color};
    font-size: 14px;
}}
QLabel#BetaBadgeLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {card_title_color};
    background: {rgba_from_hex(text_color, 0.08)};
    border-radius: 12px;
    padding: 2px 10px;
}}
QLabel#CardTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {card_title_color};
}}
QLabel#CardSubtitle {{
    font-size: 12px;
    color: {subtitle_color};
}}
QPushButton#HomePrimaryButton {{
    background-color: {hero_primary_bg};
    color: {hero_primary_text};
    border: none;
    border-radius: 10px;
    padding: 9px 20px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#HomePrimaryButton:hover {{
    background-color: {hero_primary_hover};
}}
QPushButton#HomePrimaryButton:pressed {{
    background-color: {button_active_bg};
}}
QPushButton#HomeSecondaryButton {{
    background-color: {hero_secondary_bg};
    color: {hero_secondary_text};
    border: 1px solid {hero_secondary_border};
    border-radius: 10px;
    padding: 7px 18px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#HomeSecondaryButton:hover {{
    background-color: {hero_secondary_hover};
}}
QPushButton#HomeSecondaryButton:pressed {{
    background-color: {button_active_bg};
}}
QLabel#CardPlaceholder {{
    color: {placeholder_color};
    font-size: 12px;
}}
QToolButton#HomeClearButton,
QToolButton#HomeRemoveButton {{
    background: transparent;
    color: {muted_action_color};
    border: none;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 500;
}}
QToolButton#HomeClearButton:hover,
QToolButton#HomeRemoveButton:hover {{
    color: {card_title_color};
    text-decoration: underline;
}}
QToolButton#HomeHelpButton {{
    background: transparent;
    color: {muted_action_color};
    border: none;
    padding: 2px 4px;
    font-size: 12px;
    font-weight: 500;
}}
QToolButton#HomeHelpButton:hover {{
    color: {card_title_color};
    text-decoration: underline;
}}
QFrame#CloudStorageWarning {{
    background-color: {info_bg};
    border: 1px solid {info_border};
    border-radius: 10px;
    padding: 1px;
}}
QLabel#CloudStorageWarningText {{
    color: {text_color};
    font-size: 12px;
}}
QToolButton#CloudStorageWarningDismiss {{
    background: transparent;
    color: {muted_action_color};
    border: none;
    padding: 2px 4px;
    font-size: 11px;
    font-weight: 500;
}}
QToolButton#CloudStorageWarningDismiss:hover {{
    color: {card_title_color};
    text-decoration: underline;
}}
QWidget#HomeRecentRow {{
    border: 1px solid {card_border_color};
    border-radius: 10px;
}}

/* Make recent file/project rows clearly readable */
QWidget#HomeRecentRow QPushButton[isGhost="true"] {{
    color: {card_title_color};
    background-color: transparent;
    border: none;
    padding: 7px 12px;
    min-height: 32px;
    font-size: 13px;
    text-align: left;
}}

/* Keep ghost buttons transparent on hover inside recent rows */
QWidget#HomeRecentRow QPushButton[isGhost="true"]:hover {{
    background-color: transparent;
}}

/* Subtle hover background for the whole row */
QWidget#HomeRecentRow:hover {{
    background: {row_hover_color};
}}
"""
        )

        # Force widget refresh to pick up new colors
        self.update()
        QApplication.processEvents()

    def apply_theme(self, mode: str | None = None) -> None:
        """Apply the current theme tokens to the Home page."""
        log.debug(
            "[THEME-DEBUG] HomePage.apply_theme called, mode=%r, id(self)=%s",
            mode,
            id(self),
        )
        self._apply_stylesheet()
