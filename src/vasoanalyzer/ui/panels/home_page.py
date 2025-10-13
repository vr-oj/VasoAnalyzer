from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtSvg import QSvgWidget

from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


class HomePage(QWidget):
    """Standalone widget for the launcher/home experience."""

    def __init__(self, window: "VasoAnalyzerApp") -> None:
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
        window._refresh_home_recent()

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

        subtitle = QLabel(
            "Follow the buttons below to import traces, continue a project, or review the welcome guide.",
            hero,
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("HeroSubtitle")

        text_column.addWidget(title)
        text_column.addWidget(subtitle)
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
            window.show_analysis_workspace,
            secondary=True,
        )
        window.home_resume_btn.hide()
        row.addWidget(window.home_resume_btn)

        row.addWidget(
            window._make_home_button(
                "Load trace & events",
                "folder-open.svg",
                window._handle_load_trace,
                primary=True,
            )
        )
        row.addWidget(
            window._make_home_button(
                "Open Project",
                "folder-open.svg",
                window.open_project_file,
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
                "Create Project",
                "folder-plus.svg",
                window.new_project,
                secondary=True,
            )
        )
        row.addWidget(
            window._make_home_button(
                "Welcome guide",
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
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _apply_stylesheet(self) -> None:
        window = self._window
        border_color = CURRENT_THEME["grid_color"]
        text_color = CURRENT_THEME["text"]
        window_bg = CURRENT_THEME["window_bg"]
        hero_bg = CURRENT_THEME.get("button_bg", window_bg)
        card_bg = CURRENT_THEME.get("table_bg", window_bg)
        hover_bg = CURRENT_THEME.get("button_hover_bg", border_color)

        def rgba_from_hex(color: str, alpha: float) -> str:
            color = color.strip()
            if color.startswith("rgba"):
                return color
            color = color.lstrip("#")
            if len(color) == 3:
                color = "".join(ch * 2 for ch in color)
            try:
                r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return text_color
            alpha = max(0.0, min(1.0, alpha))
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"

        subtitle_color = rgba_from_hex(text_color, 0.72)
        card_title_color = rgba_from_hex(text_color, 0.86)
        placeholder_color = rgba_from_hex(text_color, 0.55)
        muted_action_color = rgba_from_hex(text_color, 0.68)

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
    padding: 4px 6px;
    font-weight: 500;
}}
QToolButton#HomeClearButton:hover,
QToolButton#HomeRemoveButton:hover {{
    color: {card_title_color};
    background: {hover_bg};
    border-radius: 6px;
}}
"""
        )

