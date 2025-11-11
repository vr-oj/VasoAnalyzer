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
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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
            ("Cloud-Safe", self._page_bundle_format),
            ("Workspace", self._page_anatomy),
            ("Your Data", self._page_understanding_data),
            ("Workflow", self._page_workflow),
            ("Pro Tips", self._page_pro_tips),
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
            except (OSError, RuntimeError):
                # Failed to load SVG, fall back to text badge
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

        title = QLabel("Quick tour")
        title.setProperty("va-h1", True)
        blurb = QLabel(
            "See VasoAnalyzer turn raw traces into polished figures while keeping context intact."
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
                "Pick up where you left off — recent projects appear on the home screen with quick access.",
            ),
            (
                "Cloud-safe projects",
                "New .vasopack format works safely with Dropbox, iCloud, and Google Drive without corruption.",
            ),
            (
                "Built for collaboration",
                "Keep experiments, samples, attachments, and notes organized in one cloud-synced package.",
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

        title = QLabel("Cloud-safe project format")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "VasoAnalyzer now uses .vasopack bundles—designed for cloud storage and crash protection."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "No more cloud corruption",
                "Old .vaso files corrupt in Dropbox/iCloud. New .vasopack bundles are cloud-safe by design.",
            ),
            (
                "Automatic snapshots",
                "Every save creates an immutable snapshot. Crashed? Recovered automatically from last good snapshot.",
            ),
            (
                "50 recovery points",
                "Keep 50 snapshots automatically. Extract any old version if you need to go back in time.",
            ),
            (
                "Auto-migration",
                "Opening old .vaso files automatically upgrades to .vasopack (keeps .vaso.legacy backup).",
            ),
            (
                "Command-line recovery",
                "Advanced recovery tool: python -m vasoanalyzer.cli.recover MyProject.vasopack",
            ),
            (
                "Choose your format",
                "Preferences → Project Format lets you default to .vasopack or .vaso. Bundle recommended.",
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
            "Each panel suits vascular analysis, balancing quick toggles with deeper dives."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self._workspace_illustration(), 0, Qt.AlignCenter)

        for heading, body in (
            (
                "Menu & Toolbar",
                "Quick access to projects, data loading, Excel mapping, figure composer, and preferences.",
            ),
            (
                "Plot Canvas",
                "Interactive ID/OD traces with event markers, zoom controls, pan tools, and grid overlays.",
            ),
            (
                "Snapshot Viewer",
                "Frame-by-frame TIFF viewer with pinning, diameter measurement visualization, and contrast controls.",
            ),
            (
                "Event Table",
                "Edit events inline, add temperature and pressure data, filter, sort, and export to Excel.",
            ),
            (
                "Project Sidebar",
                "Navigate experiments, switch samples, attach files, and take notes—all in one organized view.",
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
            "Know where your measurements come from and what they mean for confident analysis."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Where do diameter values come from?",
                "Inner Diameter (ID) and Outer Diameter (OD) are measured by VasoTracker from vessel boundaries in each video frame. Time values represent frame timestamps converted to seconds, while frame numbers provide sequential IDs from your TIFF stack.",
            ),
            (
                "How does VasoTracker measure diameters?",
                "Edge detection algorithms identify vessel boundaries with sub-pixel interpolation for accuracy down to 0.1 µm. Each frame produces one diameter measurement, exported as CSV with Time + Diameter columns for seamless import into VasoAnalyzer.",
            ),
            (
                "What's in the Event Table?",
                "Time: When you clicked or imported external markers. Label: Event name/type (e.g., 'Drug Application', 'Baseline'). Diameter at Event: ID/OD value interpolated from the nearest data point. Custom columns like Temperature, Pressure, and Notes can be added for richer context.",
            ),
            (
                "Interpolation and accuracy",
                "When you add an event marker, VasoAnalyzer finds the nearest time point in your trace data and records the diameter value. If the exact time isn't in your data, linear interpolation estimates the value between surrounding points for accuracy.",
            ),
            (
                "Data quality indicators",
                "Green checkmark: Clean data with no gaps. Yellow warning: Minor interpolation used to fill small gaps. Red alert: Significant gaps or statistical outliers detected—review these regions for data integrity before analysis.",
            ),
            (
                "Understanding calculated statistics",
                "Mean, median, and standard deviation are computed from your diameter trace over selected time windows. Event frequency counts markers per minute. Baseline vs. response comparisons help quantify vessel reactivity to stimuli.",
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
            "Follow this path from acquisition to communication and keep collaborators aligned."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "1. Create or open a project",
                "New projects use cloud-safe .vasopack bundles with automatic snapshots. Legacy .vaso files auto-upgrade on open.",
            ),
            (
                "2. Add trace data from VasoTracker",
                "Import CSV with Time (s) and Inner Diameter (µm) columns exported from VasoTracker. Outer Diameter and frame numbers are optional but recommended for complete analysis.",
            ),
            (
                "3. Load events (optional)",
                "Import CSV/TXT with Time + Label columns. Additional columns (Temperature °C, Pressure mmHg, Flow rate, Notes) are supported for richer experimental context.",
            ),
            (
                "4. Add snapshot TIFF (optional)",
                "Load TIFF stacks from VasoTracker for frame-by-frame viewing. Large files (>2GB) are intelligently sub-sampled for responsive performance without quality loss.",
            ),
            (
                "5. Analyze & annotate",
                "Zoom, pan, add event markers by clicking the plot, measure diameters, pin important frames, and customize appearance via Plot Settings.",
            ),
            (
                "6. Calculate statistics",
                "Use Tools → Analysis → Calculate Statistics to compute mean diameter, response amplitudes, event frequencies, and baseline comparisons over custom time windows.",
            ),
            (
                "7. Export to Excel",
                "Use Excel Mapping wizard (Tools → Map Events to Excel) to export event data to your analysis templates with smart column matching.",
            ),
            (
                "8. Create publication figures",
                "Open Figure Composer to design multi-panel figures with custom layouts, annotations, scale bars, and publication-quality styling (300+ DPI).",
            ),
            (
                "9. Autosave protects your work",
                "Bundle format saves snapshots automatically every 5 minutes. Crashes? Recover from any of the last 50 snapshots instantly on reopen.",
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

        title = QLabel("Pro tips & troubleshooting")
        title.setProperty("va-h1", True)

        intro = QLabel(
            "Expert techniques and solutions to common issues for a smooth workflow."
        )
        intro.setWordWrap(True)
        intro.setProperty("va-body", True)

        layout.addWidget(title)
        layout.addWidget(intro)

        for heading, body in (
            (
                "Performance optimization",
                "Switch to PyQtGraph renderer (View → Renderer → PyQtGraph) for smooth pan/zoom with large datasets (>10,000 points). Keep TIFF stacks under 2GB for responsive frame viewing. Autosave frequency is customizable in Preferences if you need faster/slower snapshots.",
            ),
            (
                "Cloud storage best practices",
                "Always use .vasopack bundles for cloud sharing (Dropbox, iCloud, Google Drive) as they're corruption-proof. Legacy .vaso files risk corruption during sync. Store active projects on local drives (Documents, Desktop) during analysis for best reliability, then move to cloud when done.",
            ),
            (
                "Collaboration workflow",
                "Export to single .vaso file (File → Export → Shareable Single File) for users without bundle support. Attach protocols, images, and notes directly to projects (right-click project/sample in sidebar → Add Attachment) to keep context together.",
            ),
            (
                "Keyboard power user tips",
                "Hold Shift while clicking the plot to add multiple events quickly. Use I/O keys to toggle Inner/Outer diameter visibility. Press Ctrl+R to reset zoom, Ctrl+F to fit data to window. Ctrl+Z/Y for undo/redo works on most operations.",
            ),
            (
                "Troubleshooting: File not found",
                "Use Tools → Relink Missing Files to reconnect moved data files. VasoAnalyzer stores relative paths when possible, but moving projects between computers or drives can break links. Embedding data (Preferences → Bundle format) prevents this.",
            ),
            (
                "Troubleshooting: Slow rendering",
                "Switch to PyQtGraph renderer (View → Renderer) for GPU acceleration. If plot feels sluggish, reduce TIFF stack resolution (VasoTracker export settings) or use sampling. Close unused experiments/samples to free memory.",
            ),
            (
                "Troubleshooting: Events misaligned",
                "Check that Time column units match in your CSV (seconds vs. minutes vs. frames). VasoAnalyzer assumes seconds by default. If importing frame numbers, convert to time: Time (s) = Frame / FPS.",
            ),
            (
                "Troubleshooting: Cloud corruption",
                "If you see 'Database corruption' errors, migrate to .vasopack format immediately (File → Export → Project Bundle). Bundle format is crash-proof with automatic recovery. Use python -m vasoanalyzer.cli.recover MyProject.vasopack for advanced recovery.",
            ),
            (
                "Data validation checklist",
                "Before analysis, verify: ✓ Time column is continuous without large gaps. ✓ Diameter values are reasonable (typically 10-200 µm). ✓ Frame numbers match TIFF stack if loaded. ✓ Event times fall within trace data range. Use Tools → Analysis → Data Validation to automate checks.",
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
                    ((("⌘", "Ctrl"), "Shift", "N"), "Create new project (uses .vasopack format)"),
                    ((("⌘", "Ctrl"), "O"), "Open trace and event files"),
                    ((("⌘", "Ctrl"), "Shift", "O"), "Open saved project (.vasopack or .vaso)"),
                    ((("⌘", "Ctrl"), "Shift", "S"), "Save project (creates snapshot)"),
                    ((("⌘", "Ctrl"), "Z"), "Undo last action"),
                    ((("⌘", "Ctrl"), "Y"), "Redo last undone action"),
                    ((("⌘", "Ctrl"), "C"), "Copy selected event(s)"),
                    ((("⌘", "Ctrl"), "V"), "Paste event(s)"),
                    ((("⌘", "Ctrl"), "D"), "Duplicate selected event"),
                    (("Del",), "Delete selected event(s)"),
                    ((("⌘", "Ctrl"), "A"), "Select all events"),
                    ((("⌘", "Ctrl"), "F"), "Find event / Fit data to window"),
                    ((("⌘", "Ctrl"), ","), "Open Preferences"),
                    ((("⌘", "Ctrl"), "Shift", "T"), "Load VasoTracker TIFF stack"),
                    ((("⌘", "Ctrl"), "Shift", "H"), "Return to home screen"),
                    ((("⌘", "Ctrl"), "R"), "Reset plot view"),
                    ((("⌘", "Ctrl"), "E"), "Zoom to selection"),
                    (("I",), "Toggle Inner diameter visibility"),
                    (("O",), "Toggle Outer diameter visibility"),
                    (("F11",), "Toggle full screen"),
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
