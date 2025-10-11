# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
from PyQt5.QtSvg import QSvgWidget

from utils import resource_path

from utils.config import APP_VERSION
from .. import resources_rc  # noqa: F401 - ensure Qt resources loaded


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
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._centered = False

        self.settings = QSettings("VasoAnalyzer", "VasoAnalyzer")
        self.hide_for_version = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 24)
        root.setSpacing(20)

        self._page_definitions = [
            ("Welcome", self._page_intro),
            ("Workspace", self._page_anatomy),
            ("Workflow", self._page_workflow),
            ("Shortcuts", self._page_shortcuts),
        ]

        root.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.setContentsMargins(0, 4, 0, 0)
        for title, builder in self._page_definitions:
            page = builder()
            page.setProperty("va-step-title", title)
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        root.addWidget(self._build_stepper())
        root.addStretch(1)
        root.addLayout(self._nav_bar())

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
            ("icons", "VasoAnalyzerIcon.svg"),
            ("vasoanalyzer", "VasoAnalyzerIcon.svg"),
            ("src", "vasoanalyzer", "VasoAnalyzerIcon.svg"),
        ]

        icon_path = ""
        for parts in search_roots:
            candidate = resource_path(*parts)
            if os.path.exists(candidate):
                icon_path = candidate
                break

        if icon_path:
            try:
                widget = QSvgWidget(icon_path)
                widget.setFixedSize(60, 60)
                return widget
            except Exception:
                pass

        fallback = QLabel("VA")
        fallback.setObjectName("va-badge")
        fallback.setAlignment(Qt.AlignCenter)
        fallback.setFixedSize(60, 60)
        return fallback

    def _workspace_illustration(self) -> QSvgWidget:
        svg = QSvgWidget(":/art/workspace_map.svg")
        svg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        svg.setFixedHeight(160)
        return svg

    def _build_header(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("va-hero")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        icon = self._brand_icon_widget()
        layout.addWidget(icon, 0, Qt.AlignTop)

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
        version_chip.setAlignment(Qt.AlignCenter)
        version_chip.setMinimumWidth(96)

        title_row.addWidget(title, 1)
        title_row.addWidget(version_chip, 0, Qt.AlignRight)

        subtitle = QLabel(
            "Take a quick tour so you can load traces, explore events, and share results with confidence."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("va-body", True)

        text_column.addLayout(title_row)
        text_column.addWidget(subtitle)

        layout.addLayout(text_column, 1)

        hint = QLabel("Tip: Reopen this guide anytime with ⌘/Ctrl+/.")
        hint.setProperty("va-caption", True)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignRight | Qt.AlignTop)
        hint.setMaximumWidth(240)
        layout.addWidget(hint, 0, Qt.AlignTop)

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
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedSize(28, 28)
            dot.setProperty("va-step-dot", True)

            caption = QLabel(title)
            caption.setAlignment(Qt.AlignCenter)
            caption.setWordWrap(True)
            caption.setProperty("va-step-label", True)

            node_layout.addWidget(dot, 0, Qt.AlignCenter)
            node_layout.addWidget(caption, 0, Qt.AlignCenter)

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

        self.next_btn.setVisible(not last_page)
        self.next_btn.setDefault(not last_page)
        self.next_btn.setAutoDefault(not last_page)

        self.done_btn.setVisible(last_page)
        self.done_btn.setDefault(last_page)
        self.done_btn.setAutoDefault(last_page)

        if last_page:
            self.done_btn.setFocus(Qt.TabFocusReason)

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
            action_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(action_label, 1)

            layout.addLayout(row)

        return wrapper

    def _make_key_sequence(self, tokens) -> QHBoxLayout:
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(2)

        normalized = []
        for token in tokens:
            if isinstance(token, (tuple, list)):
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
            capsule.setAlignment(Qt.AlignCenter)
            capsule.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            strip.addWidget(capsule)

            if index != len(tokens) - 1:
                plus = QLabel("+")
                plus.setProperty("va-key-sep", True)
                plus.setAlignment(Qt.AlignCenter)
                strip.addWidget(plus)

        if not tokens:
            spacer = QLabel("—")
            spacer.setProperty("va-key-sep", True)
            strip.addWidget(spacer)

        return strip

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------
    def _page_intro(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Quick tour")
        title.setProperty("va-h1", True)
        blurb = QLabel(
            "See how VasoAnalyzer moves from raw traces to polished figures without losing project context."
        )
        blurb.setWordWrap(True)
        blurb.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(blurb)

        cta = QHBoxLayout()
        cta.setContentsMargins(0, 8, 0, 4)
        cta.setSpacing(8)

        open_btn = QPushButton("Open Project…")
        new_btn = QPushButton("Create Project…")
        open_btn.clicked.connect(self.openRequested)
        new_btn.clicked.connect(self.createRequested)

        cta.addStretch(1)
        cta.addWidget(open_btn)
        cta.addWidget(new_btn)
        layout.addLayout(cta)

        for heading, body in (
            (
                "Resume instantly",
                "Pick up where you left off — recent sessions live on the home screen.",
            ),
            (
                "Project-built",
                "Keep experiments, samples, attachments, and notes tied together.",
            ),
            (
                "Launch essentials",
                "Open the trace loader, Excel mapper, or this guide directly from the toolbar.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_anatomy(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Workspace anatomy")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "Each panel is purpose-built for vascular analysis, balancing quick toggles and deeper dives."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self._workspace_illustration(), 0, Qt.AlignCenter)

        for heading, body in (
            (
                "Header",
                "Project commands, autosave, and theme tools stay within reach.",
            ),
            (
                "Plot canvas",
                "ID/OD traces with event markers, zoom controls, and overlays.",
            ),
            (
                "Snapshot viewer",
                "Scrub TIFF frames, set pins, and compare context while annotating.",
            ),
            (
                "Event table",
                "Edit events inline, filter quickly, and export publication-ready tables.",
            ),
            (
                "Project sidebar",
                "Navigate experiments, manage attachments, and capture notes side-by-side.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_workflow(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Typical workflow")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "Follow this path from acquisition to communication while keeping collaborators aligned."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Create or open a project",
                "Projects are single .vaso files that remember your view and metadata.",
            ),
            (
                "Add trace data",
                "CSV with Time (s) and Inner Diameter (µm); Outer Diameter optional.",
            ),
            (
                "Load events (optional)",
                "CSV/TXT with Time + Label; extra columns like Temp/P1/P2 are fine.",
            ),
            (
                "Add a snapshot (optional)",
                "Load a TIFF stack; large stacks are previewed via sub-sampling for speed.",
            ),
            (
                "Explore & annotate",
                "Zoom/pan; insert or edit event pins; adjust fonts/axes in Plot Settings.",
            ),
            (
                "Export",
                "Event table (CSV), figure (TIFF/SVG), and session state (JSON).",
            ),
            (
                "Save",
                "Save updates the .vaso project so you reopen to the exact same view.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_shortcuts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Keyboard shortcuts")
        title.setProperty("va-h1", True)
        intro = QLabel("Blend keyboard and toolbar controls for a quicker workflow.")
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        self.chk_hide = QCheckBox("Don’t show this again")

        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(
            self._make_shortcut_grid(
                [
                    ((("⌘", "Ctrl"), "N"), "Start a new analysis session"),
                    ((("⌘", "Ctrl"), "O"), "Open trace and event files"),
                    ((("⌘", "Ctrl"), "Shift", "O"), "Open a saved project"),
                    ((("⌘", "Ctrl"), "Shift", "S"), "Save the active project"),
                    ((("⌘", "Ctrl"), "Shift", "T"), "Load a Vasotracker Result TIFF"),
                    ((("⌘", "Ctrl"), "Shift", "H"), "Return to the home screen"),
                    ((("⌘", "Ctrl"), "R"), "Reset the current plot view"),
                    ((("⌘", "Ctrl"), "/"), "Reopen this welcome guide"),
                ]
            )
        )
        layout.addStretch(1)
        layout.addWidget(self.chk_hide, alignment=Qt.AlignLeft)
        return page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _nav_bar(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 12, 0, 0)
        nav.setSpacing(10)

        support = QLabel(
            '<a href="https://github.com/vr-oj/VasoAnalyzer">Documentation & updates</a>'
        )
        support.setOpenExternalLinks(True)
        support.setProperty("va-caption", True)
        support.setTextInteractionFlags(Qt.TextBrowserInteraction)
        nav.addWidget(support, 0, Qt.AlignVCenter)

        nav.addStretch(1)

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
        self.setStyleSheet(
            """
        /* Dialog */
        QDialog {
            background-color: #fafbff;
        }

        QLabel {
            background: transparent;
        }

        /* Hero */
        QFrame#va-hero {
            background: #f1f4ff;
            border: 1px solid #c7d4ff;
            border-radius: 16px;
        }
        QLabel#va-badge {
            background: #1e4fe2;
            color: #ffffff;
            font-size: 18px;
            font-weight: 700;
            border-radius: 30px;
        }

        /* Type scale */
        QLabel[va-h0="true"] {
            font-size: 22px;
            font-weight: 700;
            color: #182132;
        }
        QLabel[va-h1="true"] {
            font-size: 22px;
            font-weight: 600;
            color: #1f2738;
        }
        QLabel[va-h2="true"] {
            font-size: 16px;
            font-weight: 600;
            color: #1f2738;
            letter-spacing: 0.1px;
        }
        QLabel[va-body="true"] {
            font-size: 14px;
            color: #2a2f3f;
        }
        QLabel[va-caption="true"] {
            font-size: 12px;
            color: #55607a;
        }
        QLabel[va-caption="true"]:hover {
            color: #1e4fe2;
        }
        QLabel[va-chip="true"] {
            background: #dbe4ff;
            color: #1e4fe2;
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }

        /* Cards */
        QFrame[va-card="true"] {
            background: #f8faff;
            border: 1px solid #d6e1ff;
            border-radius: 12px;
        }

        /* Stepper */
        QFrame#va-stepper {
            background: #f3f6ff;
            border: 1px solid #ccd9ff;
            border-radius: 12px;
        }
        QLabel[va-step-dot="true"] {
            background: #dce5ff;
            color: #2a3c7f;
            border-radius: 14px;
            font-weight: 600;
            min-width: 28px;
            min-height: 28px;
        }
        QLabel[va-step-dot="true"][va-step-active="true"] {
            background: #1e4fe2;
            color: #ffffff;
        }
        QLabel[va-step-label="true"] {
            font-size: 11px;
            color: #63708e;
        }
        QLabel[va-step-label="true"][va-step-active="true"] {
            color: #1f2738;
            font-weight: 600;
        }

        /* Shortcut keys */
        QLabel[va-key="true"] {
            background: #e8edff;
            border: 1px solid #c7d4ff;
            border-radius: 7px;
            padding: 3px 8px;
            font-family: "Menlo", "Courier New", monospace;
            font-size: 12px;
            color: #22335a;
        }
        QLabel[va-key-sep="true"] {
            color: #7b86a3;
            font-size: 11px;
            padding: 0 2px;
        }

        /* Checkbox */
        QCheckBox { color: #2a2f3f; }

        /* Buttons */
        QPushButton {
            padding: 10px 22px;
            min-height: 36px;
            border-radius: 10px;
            font-weight: 600;
            min-width: 88px;
        }
        QPushButton[va-role="primary"] {
            background-color: #1e4fe2;
            color: #ffffff;
            border: none;
        }
        QPushButton[va-role="primary"]:hover {
            background-color: #153fc1;
        }
        QPushButton[va-role="secondary"] {
            background-color: transparent;
            color: #1f2738;
            border: 1px solid #c1cffd;
        }
        QPushButton[va-role="secondary"]:hover {
            background-color: #ebf1ff;
        }
        """
        )
