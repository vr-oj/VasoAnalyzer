# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import logging
import os

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path
from utils.config import APP_VERSION

log = logging.getLogger(__name__)

from .. import resources_rc  # noqa: F401 - ensure Qt resources loaded
from .. import theme as ui_theme


class WelcomeGuideDialog(QDialog):
    # Guarded signals let parent windows hook into CTA actions without tight coupling.
    openRequested = pyqtSignal()
    createRequested = pyqtSignal()
    """Lightweight onboarding tour shown on first launch or after upgrades."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to VasoAnalyzer")
        self.setMinimumSize(900, 1000)
        self.setMinimumWidth(900)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._centered = False

        self.settings = QSettings("VasoAnalyzer", "VasoAnalyzer")
        self.hide_for_version = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 24)
        root.setSpacing(20)

        self._page_definitions = [
            ("Welcome", self._page_welcome),
            ("Getting Started", self._page_getting_started),
            ("Your Data", self._page_your_data),
            ("Navigation", self._page_navigation),
            ("Shortcuts", self._page_shortcuts),
        ]

        root.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.setContentsMargins(0, 4, 0, 0)
        for title, builder in self._page_definitions:
            page = builder()
            page.setObjectName("va-welcome-page")
            page.setProperty("va-step-title", title)

            scroll = QScrollArea()
            scroll.setObjectName("va-welcome-scroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            scroll.setProperty("va-step-title", title)

            self.stack.addWidget(scroll)
        root.addWidget(self.stack, 1)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(12)
        bottom.addWidget(self._build_stepper())
        bottom.addLayout(self._nav_bar())
        root.addLayout(bottom)

        self.stack.currentChanged.connect(self._update_nav_state)
        self._apply_style()
        self._update_nav_state(self.stack.currentIndex())

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._centered:
            self._center_on_screen()
            self._centered = True

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _brand_icon_widget(self) -> QWidget:
        search_roots = [
            ("src", "vasoanalyzer", "VasoAnalyzerIcon_hero.png"),
            ("vasoanalyzer", "VasoAnalyzerIcon_hero.png"),
            ("vasoanalyzer", "VasoAnalyzerIcon.png"),
            ("vasoanalyzer", "VasoAnalyzerIcon.svg"),
            ("src", "vasoanalyzer", "VasoAnalyzerIcon.svg"),
        ]

        icon_path = ""
        icon_ext = ""
        for parts in search_roots:
            candidate = resource_path(*parts)
            if os.path.exists(candidate):
                icon_path = candidate
                _, icon_ext = os.path.splitext(candidate)
                break

        if icon_path and icon_ext.lower() in {".png", ".jpg", ".jpeg"}:
            try:
                from PyQt6.QtGui import QPixmap

                label = QLabel()
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    label.setPixmap(scaled)
                label.setFixedSize(60, 60)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                return label
            except Exception:
                log.debug("Failed to load welcome dialog icon", exc_info=True)

        if icon_path and icon_ext.lower() == ".svg":
            try:
                widget = QSvgWidget(icon_path)
                widget.setFixedSize(60, 60)
                return widget
            except (OSError, RuntimeError):
                pass

        fallback = QLabel("VA")
        fallback.setObjectName("va-badge")
        fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fallback.setFixedSize(60, 60)
        return fallback

    def _workspace_illustration(self) -> QSvgWidget:
        svg = QSvgWidget(":/art/workspace_map.svg")
        svg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        svg.setFixedHeight(160)
        return svg

    def _build_header(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("va-hero")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        icon = self._brand_icon_widget()
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = QLabel("Welcome to VasoAnalyzer")
        title.setProperty("va-h0", True)

        version_chip = QLabel(f"Version {APP_VERSION}")
        version_chip.setProperty("va-chip", True)
        version_chip.setFixedHeight(20)
        version_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_chip.setMinimumWidth(96)

        title_row.addWidget(title, 1)
        title_row.addWidget(version_chip, 0, Qt.AlignmentFlag.AlignRight)

        subtitle = QLabel(
            "Take a quick tour to load traces, explore events, and share results confidently."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("va-body", True)

        text_column.addLayout(title_row)
        text_column.addWidget(subtitle)

        layout.addLayout(text_column, 1)

        hint = QLabel("Tip: Reopen this guide anytime with ⌘/Ctrl+/.")
        hint.setProperty("va-caption", True)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        hint.setMaximumWidth(240)
        layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignTop)

        return hero

    def _build_stepper(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("va-stepper")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        layout.addStretch(1)
        self._step_widgets = []

        for idx, (title, _) in enumerate(self._page_definitions, start=1):
            node = QWidget()
            node_layout = QVBoxLayout(node)
            node_layout.setContentsMargins(0, 0, 0, 0)
            node_layout.setSpacing(6)

            dot = QLabel(str(idx))
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(28, 28)
            dot.setProperty("va-step-dot", True)

            caption = QLabel(title)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
            caption.setProperty("va-step-label", True)

            node_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignCenter)
            node_layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignCenter)

            layout.addWidget(node)
            self._step_widgets.append((dot, caption))
        layout.addStretch(1)
        return frame

    def _advance(self, delta: int) -> None:
        new_index = self.stack.currentIndex() + delta
        if 0 <= new_index < self.stack.count():
            self.stack.setCurrentIndex(new_index)

    def _update_nav_state(self, index: int) -> None:
        if not hasattr(self, "prev_btn"):
            return

        self.prev_btn.setEnabled(index > 0)
        last_page = index == self.stack.count() - 1

        self.skip_btn.setVisible(not last_page)
        self.next_btn.setVisible(not last_page)
        self.next_btn.setDefault(not last_page)
        self.next_btn.setAutoDefault(not last_page)

        self.done_btn.setVisible(last_page)
        self.done_btn.setDefault(last_page)
        self.done_btn.setAutoDefault(last_page)

        if last_page:
            self.done_btn.setFocus(Qt.FocusReason.TabFocusReason)

        self._set_step_active(index)

    def _set_step_active(self, index: int) -> None:
        if not hasattr(self, "_step_widgets"):
            return

        for idx, (dot, caption) in enumerate(self._step_widgets):
            active = idx == index
            for widget in (dot, caption):
                widget.setProperty("va-step-active", active)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def _make_callout(self, title: str, body: str) -> QFrame:
        card = QFrame()
        card.setProperty("va-card", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        heading = QLabel(title)
        heading.setProperty("va-h2", True)

        blurb = QLabel(body)
        blurb.setWordWrap(True)
        blurb.setProperty("va-body", True)

        layout.addWidget(heading)
        layout.addWidget(blurb)
        card.setMinimumHeight(66)

        return card

    def _make_shortcut_grid(self, entries) -> QFrame:
        wrapper = QFrame()
        wrapper.setProperty("va-card", True)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        for tokens, action in entries:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            key_strip = self._make_key_sequence(tokens)
            row.addLayout(key_strip, 0)

            action_label = QLabel(action)
            action_label.setProperty("va-body", True)
            action_label.setWordWrap(True)
            action_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(action_label, 1)

            layout.addLayout(row)

        return wrapper

    def _make_key_sequence(self, tokens) -> QHBoxLayout:
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(2)

        normalized = []
        for token in tokens:
            if isinstance(token, tuple | list):
                options = [str(opt).strip() for opt in token if str(opt).strip()]
                if options:
                    normalized.append(" / ".join(options))
            else:
                text = str(token).strip()
                if text:
                    normalized.append(text)

        tokens = normalized
        for index, token in enumerate(tokens):
            capsule = QLabel(token)
            capsule.setProperty("va-key", True)
            capsule.setAlignment(Qt.AlignmentFlag.AlignCenter)
            capsule.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            strip.addWidget(capsule)

            if index != len(tokens) - 1:
                plus = QLabel("+")
                plus.setProperty("va-key-sep", True)
                plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
                strip.addWidget(plus)

        if not tokens:
            spacer = QLabel("—")
            spacer.setProperty("va-key-sep", True)
            strip.addWidget(spacer)

        return strip

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------
    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("What is VasoAnalyzer?")
        title.setProperty("va-h1", True)
        blurb = QLabel(
            "<p>VasoAnalyzer is a desktop app for analyzing pressure myography experiments. "
            "Everything lives in a single <code>.vaso</code> project file you can share with collaborators.</p>"
        )
        blurb.setWordWrap(True)
        blurb.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(blurb)

        for heading, body in (
            (
                "Trace viewer",
                "Inner diameter, outer diameter, pressure, and set-pressure in a synchronized, "
                "multi-track view with event markers. Smooth panning and zooming, even for long recordings.",
            ),
            (
                "Point Editor",
                "Clean artefacts and spikes interactively. All edits are recorded in an audit trail.",
            ),
            (
                "Events and Excel Mapper",
                "Import event files, view them as plot markers and table rows, then map results "
                "into your lab’s Excel templates for export.",
            ),
            (
                "Figure export",
                "Export publication-ready plots (PNG/TIFF/SVG) and vessel + trace GIF animations.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_getting_started(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Getting started")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "A typical workflow from a fresh VasoTracker recording to export-ready results."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "1. Create or open a project",
                "Start a new project from the Home screen, or open an existing .vaso file. "
                "You can also open a single trace CSV for a quick look without creating a project.",
            ),
            (
                "2. Import your data",
                "Load trace CSVs (time + diameter/pressure), event files (time + label), "
                "and optionally a TIFF stack for image context.",
            ),
            (
                "3. Clean and annotate",
                "Use the Point Editor to remove spikes, and the Events table to adjust labels "
                "and timing. All changes are tracked.",
            ),
            (
                "4. Export and save",
                "Export figures, fill Excel templates with the Excel Mapper, then save "
                "your project. Everything is bundled in the .vaso file.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_your_data(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Your data")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "VasoAnalyzer reads your raw VasoTracker files as-is and keeps analysis "
            "state inside the project."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Trace CSVs",
                "A time column and at least an inner diameter column. Outer diameter, "
                "pressure, and set-pressure channels are optional.",
            ),
            (
                "Event files",
                "CSV/TXT with Time and Label columns, plus optional metadata "
                "(e.g., Temp, P1, P2). Events appear as markers on the trace and rows "
                "in the Event Table.",
            ),
            (
                "TIFF stacks",
                "Image frames for visual context. Large stacks are down-sampled "
                "automatically for smooth preview.",
            ),
            (
                "Project files (.vaso)",
                "A single file that bundles your traces, events, edits, figures, and "
                "settings. Safe to copy, back up, or share.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_navigation(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Navigating the trace viewer")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "VasoAnalyzer has two toolbar modes that control how mouse and trackpad "
            "interactions work on the trace plot."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        # -- Toolbar modes --
        modes_title = QLabel("Toolbar modes")
        modes_title.setProperty("va-h2", True)
        layout.addWidget(modes_title)

        for heading, body in (
            (
                "Pan mode (P)",
                "The default mode. Drag left/right on the trace to pan through time with "
                "smooth momentum scrolling. The cursor shows an open hand.",
            ),
            (
                "Select mode (Z)",
                "Draw a rectangle on the trace to zoom into that time range. "
                "The cursor shows a crosshair. Press Z or click the Select button in the "
                "toolbar to activate.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        # -- Scroll / trackpad --
        scroll_title = QLabel("Scroll wheel and trackpad")
        scroll_title.setProperty("va-h2", True)
        layout.addWidget(scroll_title)

        layout.addWidget(
            self._make_shortcut_grid(
                [
                    (("Scroll",), "Pan left / right through time"),
                    ((("⌘", "Ctrl"), "Scroll"), "Zoom in / out at cursor position"),
                    (("Shift", "Scroll"), "Pan the Y-axis up / down"),
                    (("Alt / Option", "Scroll"), "Zoom the Y-axis in / out"),
                ]
            )
        )

        # -- Y-axis --
        yaxis_title = QLabel("Y-axis interactions")
        yaxis_title.setProperty("va-h2", True)
        layout.addWidget(yaxis_title)

        for heading, body in (
            (
                "Drag the Y-axis to scale (Pan mode only)",
                "In Pan mode, hover over the Y-axis labels on the left edge until the "
                "cursor changes to a vertical resize arrow (↕), then click and drag "
                "up or down to scale the amplitude range. This is disabled in Select "
                "mode so it doesn't interfere with rectangle zoom.",
            ),
            (
                "Shift + Scroll to pan the Y-axis",
                "Hold Shift and scroll to slide the Y-axis range up or down without "
                "changing the scale. This works in both Pan and Select modes and is "
                "the easiest way to reposition the vertical view.",
            ),
            (
                "Double-click the Y-axis",
                "Double-click the Y-axis to auto-scale it to fit the visible data. "
                "Works in both Pan and Select modes.",
            ),
            (
                "Right-click the Y-axis",
                "Right-click the Y-axis to open a context menu with autoscale and "
                "range options. Works in both modes.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        # -- Quick zoom --
        zoom_title = QLabel("Quick zoom shortcuts")
        zoom_title.setProperty("va-h2", True)
        layout.addWidget(zoom_title)

        layout.addWidget(
            self._make_shortcut_grid(
                [
                    (("+", "/ ="), "Zoom in"),
                    (("-",), "Zoom out"),
                    (("Backspace",), "Undo last zoom (zoom back)"),
                    (("A",), "Auto-scale Y-axis (one-shot)"),
                    (("Shift", "A"), "Toggle persistent Y auto-scale"),
                    (("0",), "Zoom to full range"),
                ]
            )
        )

        layout.addStretch(1)
        return page

    def _page_shortcuts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Essential shortcuts")
        title.setProperty("va-h1", True)
        intro = QLabel(
            "The shortcuts you'll use most often. For the complete list, "
            "use Help → Keyboard Shortcuts from the menu bar."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        # -- File --
        file_title = QLabel("File")
        file_title.setProperty("va-h2", True)
        layout.addWidget(file_title)
        layout.addWidget(
            self._make_shortcut_grid(
                [
                    ((("⌘", "Ctrl"), "O"), "Import trace CSV"),
                    ((("⌘", "Ctrl"), "Shift", "O"), "Open project (.vaso)"),
                    ((("⌘", "Ctrl"), "Shift", "S"), "Save project"),
                ]
            )
        )

        # -- Navigation --
        nav_title = QLabel("Navigation")
        nav_title.setProperty("va-h2", True)
        layout.addWidget(nav_title)
        layout.addWidget(
            self._make_shortcut_grid(
                [
                    (("P",), "Pan mode"),
                    (("Z",), "Select / rectangle zoom mode"),
                    (("0",), "Zoom to full range"),
                    (("A",), "Auto-scale Y-axis"),
                    (("Backspace",), "Undo last zoom"),
                    (("[", "]"), "Previous / next event"),
                    (("Left", "Right"), "Pan left / right"),
                ]
            )
        )

        # -- Editing --
        edit_title = QLabel("Editing")
        edit_title.setProperty("va-h2", True)
        layout.addWidget(edit_title)
        layout.addWidget(
            self._make_shortcut_grid(
                [
                    ((("⌘", "Ctrl"), "Z"), "Undo"),
                    ((("⌘", "Ctrl"), "Y"), "Redo"),
                    ((("⌘", "Ctrl"), "F"), "Fit data to window"),
                    ((("⌘", "Ctrl"), "/"), "Reopen this guide"),
                ]
            )
        )

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _nav_bar(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 12, 0, 0)
        nav.setSpacing(10)

        self.chk_hide = QCheckBox("Don't show at startup")
        nav.addWidget(self.chk_hide, 0, Qt.AlignmentFlag.AlignVCenter)

        support = QLabel(
            '<a href="https://github.com/vr-oj/VasoAnalyzer">Documentation & updates</a>'
        )
        support.setOpenExternalLinks(True)
        support.setProperty("va-caption", True)
        support.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        nav.addWidget(support, 0, Qt.AlignmentFlag.AlignVCenter)

        nav.addStretch(1)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setProperty("va-role", "secondary")
        self.skip_btn.setAutoDefault(False)
        self.skip_btn.clicked.connect(self._finish)
        nav.addWidget(self.skip_btn)

        self.prev_btn = QPushButton("Back")
        self.prev_btn.setProperty("va-role", "secondary")
        self.prev_btn.setAutoDefault(False)
        self.prev_btn.clicked.connect(lambda: self._advance(-1))
        nav.addWidget(self.prev_btn)

        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("va-role", "primary")
        self.next_btn.setAutoDefault(True)
        self.next_btn.clicked.connect(lambda: self._advance(+1))
        nav.addWidget(self.next_btn)

        self.done_btn = QPushButton("Finish")
        self.done_btn.setProperty("va-role", "primary")
        self.done_btn.setAutoDefault(True)
        self.done_btn.clicked.connect(self._finish)
        self.done_btn.hide()
        nav.addWidget(self.done_btn)

        return nav

    # ------------------------------------------------------------------
    def _finish(self) -> None:
        hide = bool(self.chk_hide.isChecked()) if hasattr(self, "chk_hide") else False
        self.hide_for_version = hide
        if hide:
            self.settings.setValue("ui/show_welcome", False)
            self.settings.setValue("general/show_onboarding", "false")
        else:
            self.settings.setValue("ui/show_welcome", True)
            self.settings.setValue("general/show_onboarding", "true")
        self.accept()

    def _apply_style(self) -> None:
        theme = ui_theme.CURRENT_THEME
        text = theme["text"]
        muted = theme.get("text_disabled", theme.get("grid_color", text))
        border = theme.get("grid_color", text)

        # Use the theme's main panel surface everywhere in this dialog
        panel_bg = theme.get("table_bg", theme.get("window_bg", "#ffffff"))

        # Surfaces
        bg = panel_bg
        card_bg = panel_bg
        hero_bg = panel_bg
        stepper_bg = panel_bg
        scroll_bg = panel_bg

        # Buttons and hover
        button_bg = theme.get("button_bg", card_bg)
        button_hover = theme.get(
            "button_hover_bg",
            theme.get("selection_bg", button_bg),
        )

        # Solid accent for CTAs and active step
        accent = theme.get(
            "accent_fill",
            theme.get("accent", "#1e4fe2"),
        )
        accent_hover = theme.get(
            "accent_fill_secondary",
            theme.get("accent_fill", accent),
        )

        # Shortcut keys and chips
        key_bg = theme.get("accent", theme.get("accent_fill", "#1e4fe2"))
        key_sep = theme.get("text_disabled", muted)
        chip_bg = theme.get("button_bg", card_bg)
        chip_text = text

        # Text on accent surfaces (badge + primary button)
        primary_text = theme.get("text_on_accent", "#ffffff")
        badge_text = primary_text

        self.setStyleSheet(
            f"""
        /* Dialog */
        QDialog {{
            background-color: {bg};
            color: {text};
        }}

        /* Scroll area + page content */
        QScrollArea#va-welcome-scroll {{
            border: none;
            background-color: {scroll_bg};
        }}
        QScrollArea#va-welcome-scroll > QWidget {{
            background-color: {scroll_bg};
        }}
        QWidget#va-welcome-page {{
            background-color: {scroll_bg};
            color: {text};
        }}

        QLabel {{
            background: transparent;
            color: {text};
        }}

        /* Hero */
        QFrame#va-hero {{
            background-color: {card_bg};
            border: 1px solid {border};
            border-radius: 16px;
        }}
        QLabel#va-badge {{
            background: {accent};
            color: {badge_text};
            font-size: 18px;
            font-weight: 700;
            border-radius: 30px;
        }}

        /* Type scale */
        QLabel[va-h0="true"] {{
            font-size: 22px;
            font-weight: 700;
            color: {text};
        }}
        QLabel[va-h1="true"] {{
            font-size: 22px;
            font-weight: 600;
            color: {text};
        }}
        QLabel[va-h2="true"] {{
            font-size: 16px;
            font-weight: 600;
            color: {text};
            letter-spacing: 0.1px;
        }}
        QLabel[va-body="true"] {{
            font-size: 14px;
            color: {text};
        }}
        QLabel[va-caption="true"] {{
            font-size: 12px;
            color: {text};
        }}
        QLabel[va-caption="true"]:hover {{
            color: {accent};
        }}
        QLabel[va-chip="true"] {{
            background: {chip_bg};
            color: {chip_text};
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}

        /* Cards */
        QFrame[va-card="true"] {{
            background-color: {card_bg};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        /* Stepper */
        QFrame#va-stepper {{
            background-color: {stepper_bg};
            border: 1px solid {border};
            border-radius: 12px;
        }}
        QLabel[va-step-dot="true"] {{
            background: {key_bg};
            background-color: {key_bg};
            color: {badge_text};
            border-radius: 14px;
            font-weight: 600;
            min-width: 28px;
            min-height: 28px;
            border: none;
        }}
        QLabel[va-step-dot="true"][va-step-active="true"] {{
            background: {key_bg};
            background-color: {key_bg};
            color: {badge_text};
        }}
        QLabel[va-step-label="true"] {{
            font-size: 11px;
            color: {muted};
        }}
        QLabel[va-step-label="true"][va-step-active="true"] {{
            color: {text};
            font-weight: 600;
        }}

        /* Shortcut keys */
        QLabel[va-key="true"] {{
            background: {key_bg};
            border: 1px solid {border};
            border-radius: 7px;
            padding: 3px 8px;
            font-family: "Menlo", "Courier New", monospace;
            font-size: 12px;
            color: {text};
        }}
        QLabel[va-key-sep="true"] {{
            color: {key_sep};
            font-size: 11px;
            padding: 0 2px;
        }}

        /* Checkbox */
        QCheckBox {{ color: {text}; }}

        /* Buttons */
        QPushButton {{
            padding: 10px 22px;
            min-height: 36px;
            border-radius: 10px;
            font-weight: 600;
            min-width: 88px;
            background-color: {button_bg};
            color: {text};
            border: 1px solid {border};
        }}
        QPushButton:hover {{
            background-color: {button_hover};
        }}
        QPushButton[va-role="primary"] {{
            background-color: {accent};
            color: {primary_text};
            border: none;
        }}
        QPushButton[va-role="primary"]:hover {{
            background-color: {accent_hover};
        }}
        QPushButton[va-role="secondary"] {{
            background-color: {button_bg};
            color: {text};
            border: 1px solid {border};
        }}
        QPushButton[va-role="secondary"]:hover {{
            background-color: {button_hover};
        }}
        """
        )
