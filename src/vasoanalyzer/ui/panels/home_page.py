from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.config import APP_VERSION
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


class HomePage(QWidget):
    """Standalone widget for the launcher/home experience."""

    def __init__(self, window: VasoAnalyzerApp) -> None:
        super().__init__(parent=window)
        self._window = window
        self.setObjectName("HomePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(24)

        root.addWidget(self._build_hero_section(), stretch=0)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)
        cards_row.addWidget(self._build_recent_sessions_card(), 1)
        cards_row.addWidget(self._build_recent_projects_card(), 1)
        root.addLayout(cards_row)
        root.addStretch()

        self._apply_stylesheet()

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
            "Import traces, manage projects, and continue your vessel analyses.",
            hero,
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("HeroSubtitle")

        # Cloud storage warning
        cloud_warning = QLabel(
            (
                "<b>Storage recommendation</b><br><br>"
                "Store active projects on your local drive (Documents, Desktop) for best reliability. "
                "Cloud storage sync can interrupt database writes, potentially causing corruption. "
                "Use .vasopack exports for cloud backup and sharing."
            ),
            hero,
        )
        cloud_warning.setWordWrap(True)
        cloud_warning.setObjectName("CloudStorageWarning")
        cloud_warning.setStyleSheet(f"""
            QLabel#CloudStorageWarning {{
                background-color: {CURRENT_THEME.get('warning_bg', '#FFF4E5')};
                color: {CURRENT_THEME.get('warning_text', '#663C00')};
                padding: 12px;
                border-radius: 8px;
                border: 1px solid {CURRENT_THEME.get('warning_border', '#FFD6A5')};
            }}
        """)

        text_column.addLayout(title_row)
        text_column.addWidget(subtitle)
        text_column.addWidget(cloud_warning)
        text_column.addLayout(self._build_primary_actions())
        text_column.addLayout(self._build_secondary_actions())
        text_column.addStretch()

        layout.addLayout(text_column)
        return hero

    def _build_primary_actions(self) -> QHBoxLayout:
        window = self._window
        row = QHBoxLayout()
        row.setSpacing(12)

        window.home_resume_btn = window._make_home_button(
            "Return to workspace",
            "Back.svg",
            lambda: window.show_analysis_workspace(),
            secondary=True,
        )
        window.home_resume_btn.hide()
        row.addWidget(window.home_resume_btn)

        row.addWidget(
            window._make_home_button(
                "Create new project…",
                "folder-plus.svg",
                lambda: window.new_project(),
                primary=True,
            )
        )
        row.addWidget(
            window._make_home_button(
                "Open project…",
                "folder-open.svg",
                lambda: window.open_project_file(),
                secondary=True,
            )
        )
        return row

    def _build_secondary_actions(self) -> QHBoxLayout:
        window = self._window
        row = QHBoxLayout()
        row.setSpacing(12)

        row.addWidget(
            window._make_home_button(
                "Import trace/events file…",
                "folder-open.svg",
                lambda: window._handle_load_trace(),
                secondary=True,
            )
        )
        row.addWidget(
            window._make_home_button(
                "Open welcome guide",
                "info-circle.svg",
                lambda: window.show_welcome_guide(modal=False),
                secondary=True,
            )
        )
        return row

    def _build_recent_sessions_card(self) -> QFrame:
        window = self._window
        card = QFrame(self)
        card.setObjectName("HomeCard")
        card.setProperty("variant", "sessions")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Recent Sessions", card)
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        window.home_clear_sessions_button = self._make_clear_button(
            "Clear all", window.clear_recent_files
        )
        window.home_clear_sessions_button.setVisible(False)
        header.addWidget(window.home_clear_sessions_button, 0, Qt.AlignRight)
        layout.addLayout(header)

        window.home_recent_sessions_layout = QVBoxLayout()
        window.home_recent_sessions_layout.setSpacing(8)
        layout.addLayout(window.home_recent_sessions_layout)
        layout.addStretch()
        return card

    def _build_recent_projects_card(self) -> QFrame:
        window = self._window
        card = QFrame(self)
        card.setObjectName("HomeCard")
        card.setProperty("variant", "projects")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

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

        window.home_recent_projects_layout = QVBoxLayout()
        window.home_recent_projects_layout.setSpacing(8)
        layout.addLayout(window.home_recent_projects_layout)
        layout.addStretch()
        return card

    def _make_clear_button(self, text: str, callback: Callable[[], None]) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("HomeClearButton")
        button.setText(text)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _apply_stylesheet(self) -> None:
        window = self._window
        border_color: str = CURRENT_THEME["grid_color"]
        text_color: str = CURRENT_THEME["text"]
        window_bg: str = CURRENT_THEME["window_bg"]
        hero_bg: str = CURRENT_THEME.get("button_bg", window_bg)
        card_bg: str = CURRENT_THEME.get("table_bg", window_bg)

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

        subtitle_color = rgba_from_hex(text_color, 0.72)
        card_title_color = rgba_from_hex(text_color, 0.86)
        placeholder_color = rgba_from_hex(text_color, 0.55)
        muted_action_color = rgba_from_hex(text_color, 0.68)
        row_hover_color = rgba_from_hex(text_color, 0.08)

        self.setStyleSheet(
            window._shared_button_css()
            + f"""
QWidget#HomePage {{
    background: {window_bg};
}}
QFrame#HeroFrame {{
    background: {hero_bg};
    border: 1px solid {border_color};
    border-radius: 16px;
}}
QFrame#HomeCard {{
    background: {card_bg};
    border: 1px solid {border_color};
    border-radius: 14px;
}}
QLabel#HeroTitle {{
    font-size: 24px;
    font-weight: 600;
}}
QLabel#HeroSubtitle {{
    color: {subtitle_color};
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
QLabel#CardPlaceholder {{
    color: {placeholder_color};
}}
QToolButton#HomeClearButton,
QToolButton#HomeRemoveButton {{
    background: transparent;
    color: {muted_action_color};
    border: none;
    padding: 0 4px;
    font-weight: 500;
}}
QToolButton#HomeClearButton:hover,
QToolButton#HomeRemoveButton:hover {{
    color: {card_title_color};
    text-decoration: underline;
}}
#CloudStorageWarning {{
    padding-top: 4px;
    padding-bottom: 4px;
}}
QWidget#HomeRecentRow {{
    border-radius: 10px;
}}
"""
        )
