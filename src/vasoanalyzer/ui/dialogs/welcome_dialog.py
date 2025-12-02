# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import os

from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import (
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
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._centered = False

        self.settings = QSettings("VasoAnalyzer", "VasoAnalyzer")
        self.hide_for_version = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 24)
        root.setSpacing(20)

        self._page_definitions = [
            ("Overview", self._page_intro),
            ("Projects & Files", self._page_bundle_format),
            ("Your Data", self._page_anatomy),
            ("Data Details", self._page_understanding_data),
            ("Workflow", self._page_workflow),
            ("Tips", self._page_pro_tips),
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
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
            ("vasoanalyzer", "VasoAnalyzerIcon.png"),
            ("icons", "VasoAnalyzerIcon_hero.png"),
            ("icons", "VasoAnalyzerIcon.png"),
            ("vasoanalyzer", "VasoAnalyzerIcon.svg"),
            ("icons", "VasoAnalyzerIcon.svg"),
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
                from PyQt5.QtGui import QPixmap

                label = QLabel()
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    label.setPixmap(scaled)
                label.setFixedSize(60, 60)
                label.setAlignment(Qt.AlignCenter)
                return label
            except Exception:
                pass

        if icon_path and icon_ext.lower() == ".svg":
            try:
                widget = QSvgWidget(icon_path)
                widget.setFixedSize(60, 60)
                return widget
            except (OSError, RuntimeError):
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

        title = QLabel("What is VasoAnalyzer?")
        title.setProperty("va-h1", True)
        blurb = QLabel(
            "<p>VasoAnalyzer is a cross-platform <b>desktop app</b> (Windows / macOS) for analyzing pressure myography experiments. It focuses on:</p>"
            "<ul>"
            "<li>fast, responsive trace visualization</li>"
            "<li>rich event annotation</li>"
            "<li>careful point editing with an audit trail</li>"
            "<li>export-ready figures and tables</li>"
            "</ul>"
            "<p>Everything for an experiment lives in a single project file (<code>.vaso</code>) so you can send a whole analysis to a collaborator as one file.</p>"
        )
        blurb.setWordWrap(True)
        blurb.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(blurb)

        for heading, body in (
            (
                "Multi-track trace viewer",
                "Inner diameter, outer diameter, pressure, and set-pressure stacked in a synchronized view. Level-of-detail rendering keeps navigation smooth even for long recordings. Event strip above the trace shows numbered event markers aligned in time.",
            ),
            (
                "Point Editor with audit history",
                "Interactive editor for cleaning artefacts and spikes in diameter traces. Connect-across and delete-with-NaN operations are recorded as structured actions and summarized in the dataset Edit History panel.",
            ),
            (
                "Event management",
                "CSV-based event import (time + label, plus optional metadata). Events stay tied to the trace and appear in both the Event Table and plots, with default labels using numbered indices that match the table.",
            ),
            (
                "Excel Mapper",
                "Map event- and trace-level data into your lab’s Excel templates and reuse mappings so you don’t have to redo column wiring every time.",
            ),
            (
                "Figure Composer",
                "Build publication-ready multi-panel figures from your plots and share layouts inside the .vaso project for reproducibility.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_bundle_format(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Projects vs single files")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "Use VasoAnalyzer as a full project hub or as a quick viewer for individual traces."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Projects (recommended)",
                "Create a project to keep traces, events, TIFF snapshots, notes, and figures together. Projects are saved as .vaso files and, when enabled, .vasopack bundles for cloud-friendly storage.",
            ),
            (
                "Single-file sessions",
                "Open a trace CSV, event file, or TIFF stack directly when you just want to inspect or sanity-check a dataset without setting up a full project.",
            ),
            (
                "Save when it matters",
                "You can start from single files and later choose Save Project to capture your datasets, edits, and layout inside a new .vaso project file.",
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

        title = QLabel("Where your data lives")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "VasoAnalyzer keeps your analysis state inside the project file while reading your raw VasoTracker outputs as-is."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Project files (.vaso / .vasopack)",
                "A .vaso project is a ZIP container that holds metadata, a staging database, views and settings, snapshots, and edit history—all bundled together for portability.",
            ),
            (
                "Raw VasoTracker files",
                "Trace CSVs contain time and diameter/pressure columns; TIFF stacks contain the original frames. VasoAnalyzer reads these inputs but never overwrites them.",
            ),
            (
                "Safe to backup and share",
                "You can back up or version a project by copying the .vaso file. Advanced users can even unzip it for debugging with standard ZIP tools.",
            ),
            (
                "Cloud-friendly bundles",
                ".vasopack bundles are designed for Dropbox, iCloud, and Google Drive and reduce the risk of corruption when syncing between machines.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_understanding_data(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Understanding your data")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "Know what each input file contributes so you can interpret plots and statistics with confidence."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Trace CSVs",
                "Traces come from CSV files that contain a time column and at least an inner diameter column, plus optional outer diameter, pressure channels, and extra numeric or categorical fields.",
            ),
            (
                "Event files",
                "Event CSV/TXT files include Time, Label, and optional metadata columns (e.g., Temp, P1, P2, Caliper). Events appear in the Event Table and as markers on the plot.",
            ),
            (
                "TIFF snapshots",
                "TIFF stacks provide image context. VasoAnalyzer down-samples large stacks for preview so you can browse frames without slowing down navigation.",
            ),
            (
                "Multi-track viewer",
                "Inner diameter, outer diameter, pressure, and set-pressure are stacked in a synchronized view, with an event strip above the trace so events and responses stay aligned in time.",
            ),
            (
                "Interpolation and timing",
                "When events fall between samples, diameters are interpolated from neighboring points to keep event timing consistent with your protocol.",
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

        title = QLabel("From VasoTracker to results")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "A typical workflow from a fresh recording to export-ready figures and tables."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "1. Create or open a project",
                "From the Home screen, start a new project/experiment or open an existing .vaso file.",
            ),
            (
                "2. Import traces",
                "Use Import data… to load trace CSVs with time and diameter (and optionally pressure) channels. The trace viewer will show stacked tracks and an event strip.",
            ),
            (
                "3. Import events and images",
                "Add event CSV/TXT for protocol markers and, optionally, a TIFF stack for snapshot/preview frames.",
            ),
            (
                "4. Clean and annotate",
                "Open the Point Editor to clean spikes and artefacts; edits are recorded in the project’s Edit History. Adjust event times and labels in the Events table.",
            ),
            (
                "5. Adjust plots",
                "Use plot settings to tweak grid, axes, fonts, and event label appearance until the trace clearly communicates your experiment.",
            ),
            (
                "6. Export tables and figures",
                "Export event tables, use Excel Mapper to fill your lab templates, or build multi-panel figures with Figure Composer.",
            ),
            (
                "7. Save and resume later",
                "Use Save Project to persist everything into the .vaso file so you can reopen it later and pick up exactly where you left off.",
            ),
        ):
            layout.addWidget(self._make_callout(heading, body))

        layout.addStretch(1)
        return page

    def _page_pro_tips(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        title = QLabel("Tips & troubleshooting")
        title.setProperty("va-h1", True)

        intro = QLabel("Habits that keep projects fast, safe, and reproducible.")
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Keep raw and analysis separate",
                "Archive VasoTracker CSVs and TIFFs as your ground truth. Use .vaso / .vasopack project files for analysis so you can always trace back what was done.",
            ),
            (
                "Use projects for real experiments",
                "Single-file sessions are fine for quick checks; for experiments you care about, create a project early so events, edits, and figures are saved together.",
            ),
            (
                "Performance tips",
                "Large traces and TIFF stacks are most responsive on a local SSD. Closing unused experiments and hiding unnecessary tracks can improve navigation.",
            ),
            (
                "Cloud & collaboration",
                "When using Dropbox, iCloud, or Google Drive, prefer .vasopack bundles and avoid editing the same project on multiple machines before sync finishes.",
            ),
            (
                "Sanity-check before analysis",
                "Make sure time is continuous, diameters are in a realistic range, and events line up with your protocol before running statistics or exports.",
            ),
            (
                "Local by design",
                "All analysis happens on your machine—no traces or images are uploaded by default.",
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
        intro = QLabel(
            "Use shortcuts for common actions like importing data, editing points, and reopening this guide."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        self.chk_hide = QCheckBox("Don’t show this again")

        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(
            self._make_shortcut_grid(
                [
                    ((("⌘", "Ctrl"), "Shift", "N"), "Create new project"),
                    ((("⌘", "Ctrl"), "O"), "Open trace and event files"),
                    (
                        (("⌘", "Ctrl"), "Shift", "O"),
                        "Open saved project (.vaso / .vasopack)",
                    ),
                    ((("⌘", "Ctrl"), "Shift", "S"), "Save project (creates snapshot)"),
                    ((("⌘", "Ctrl"), "Z"), "Undo last action"),
                    ((("⌘", "Ctrl"), "Y"), "Redo last undone action"),
                    ((("⌘", "Ctrl"), "C"), "Copy selected event(s)"),
                    ((("⌘", "Ctrl"), "V"), "Paste selected event(s)"),
                    ((("⌘", "Ctrl"), "D"), "Duplicate selected event(s)"),
                    (("Del",), "Delete selected event(s)"),
                    ((("⌘", "Ctrl"), "A"), "Select all events"),
                    ((("⌘", "Ctrl"), "F"), "Find event / Fit data to window"),
                    ((("⌘", "Ctrl"), ","), "Open Preferences"),
                    ((("⌘", "Ctrl"), "Shift", "T"), "Load VasoTracker TIFF stack"),
                    ((("⌘", "Ctrl"), "Shift", "H"), "Return to home screen"),
                    ((("⌘", "Ctrl"), "R"), "Reset plot view"),
                    ((("⌘", "Ctrl"), "E"), "Zoom to selection"),
                    (("I",), "Toggle inner diameter visibility"),
                    (("O",), "Toggle outer diameter visibility"),
                    (("F11",), "Toggle full screen"),
                    ((("⌘", "Ctrl"), "/"), "Reopen this Welcome Guide"),
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
