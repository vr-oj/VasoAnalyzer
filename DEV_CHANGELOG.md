# Development Changelog — VasoAnalyzer v2.5.1

This changelog documents all feature additions, fixes, and improvements implemented in VasoAnalyzer v2.5.1.

---

## v2.5.1 (May 2025)

### ✅ Application Core

* Full trace analysis support using `.csv` input and auto-loading of matching `_table.csv` event files.
* Interactive plot rendering using Matplotlib with:

  * Vertical markers for each event.
  * Zoom, pan, and reset controls.
  * Grid toggle and trace slider synchronization.
  * Mouse hover readouts of time and diameter.
  * Support for event-linked diameter sampling.
* Support for snapshot visualization with multi-frame TIFFs:

  * Frame slider navigation.
  * Synchronized red line on trace plot.
  * Graceful handling of corrupted/empty TIFF frames.

### 📁 File Management

* Recent file tracking with `QSettings` (up to 5 files).
* Support for:

  * Loading trace and event files from menu or button.
  * Restoring previous sessions from `.fig.pickle` state.
  * Drag-and-drop loading of `.fig.pickle` files.
* “Start New Analysis” fully clears session and UI elements.

### 📊 Event Table Features

* Editable event table with:

  * ID editing via double-click or context menu.
  * Row-based plot navigation and pinning.
  * Undo last replacement.
  * Add new events manually or from pins.
  * Delete events with confirmation.
* Auto-export of table to:

  * `eventDiameters_output.csv`
  * Optional Excel template with mapped columns.

### ✨ UI and Toolbar Improvements

* Fully integrated custom top toolbar using `QToolBar`:

  * Font/style editor (`Aa`) and grid toggle.
  * Save/export button with TIFF and SVG support.
* File load buttons below toolbar (Trace + TIFF + Excel).
* Consistent layout with compact spacing and VS Code-style visual language.

### 🎨 Plot Customization

* Tabbed **Plot Style Editor** (`Aa`) with five sections:

  * Axis Titles
  * Tick Labels
  * Event Labels
  * Pinned Labels
  * Trace Style
* Real-time style updates for:

  * Fonts, size, bold/italic toggles, line width, pin size.

### 🧪 Pin-Based Editing

* Add pins with left-click.
* Context menu on pins (right-click):

  * Replace event value with pin.
  * Undo replacement.
  * Add as new event.
  * Delete pin.
* Visual alignment of pins with red marker and annotation.

### 💾 Export & Session Save

* High-resolution plot export:

  * TIFF (600 DPI) and SVG with white background.
  * Auto-save to `tracePlot_output.fig.pickle`.
* Full session restore:

  * All trace data, events, pins, axis limits, and style.
  * Grid visibility and label fonts preserved.

### 🔍 Miscellaneous Enhancements

* File menu entries for all major actions.
* `version_checker.py` included (optional GitHub release checker).
* All paths and session files saved relative to the loaded trace.
* Clean UI theming and light-grey background consistent across widgets.

### 🧰 Development & Maintenance

* Restructured source files in `src/vasoanalyzer/`.
* Cleaned up `.gitignore` and removed `.vscode/`, `vasoenv/` from Git tracking.
* Ready for Windows/macOS build and standalone installer creation.

## \[Branch: `v2.5.1-dev`] Summary

* All features above completed and verified across platforms.
* Final build tagged as `v2.5.1` on GitHub.

### May 8, 2025 — Dual View Refactor & Plot Style Integration

* Fully migrated all dual-view logic into `dual_view.py`:

  * Modular functions for creating and managing Plot A and B.
  * Per-plot toolbars with functional `Aa` style editor and grid toggle.
  * Top-row layout and table view handled entirely within `dual_view.py`.

* Removed all dual-view layout, logic, and references from `gui.py` to prevent duplication and ensure modularity.

* Ensured the `PlotStyleDialog` remains centralized in `gui.py` and is compatible with both single and dual view modes:

  * Style updates now propagate in real time when clicking **Apply**.
  * Fixed issue where font/style edits were only applying on **OK**.
  * Improved robustness of style application per canvas and axis object.

* Fixed visual bug where grid toggle did not reflect properly in dual view.

* Cleaned and clarified logic for `open_plot_style_editor_for()` and toolbar button bindings for each view.

* Verified full dual-view functionality including:

  * Independent event table display.
  * Zoom, pan, and hover label support per plot.
  * Style customization and grid control per view.

### May 9, 2025 — Dual View Window Isolation + Stability Improvements

* Fully replaced in-place dual view with a separate `DualViewWindow` class (new window).

  * Dual view no longer overrides or clears the main window canvas.
  * Main view remains fully functional and stable.

* Added `dual_view_window.py` module for self-contained comparison interface:

  * Independent toolbars per plot.
  * Unified layout and button styling similar to main view.
  * Load Trace + Events, Aa editor, Grid toggle buttons all functional.

* Grid toggle partially working, but deprioritized due to low impact.

* Main view no longer crashes when toggling back from dual view.

🔜 **Next Steps:**

* Integrate hover label, pinning, and blue-line highlight behaviors into `DualViewWindow`.
* Match visual style and logic for event interaction with `main.py`.
* Refactor shared functions if needed for dual/single mode consistency.

### May 11, 2025 — Dual View Performance Planning

* Confirmed dual-view panels now fully mirror main view functionality (toolbars, load, styling, event-label repositioning, table sampling logic).
* Noted sluggish performance and UI unresponsiveness when both panels are active.
* Planned tomorrow: profile rendering and callback overhead, batch `draw_event` updates, and optimize shared resources to improve responsiveness.

## v2.5.2-dev (May 12, 2025)

### 🗂️ Menu Bar Enhancements

* Grouped export actions under **Export** submenu with clear naming:

  * High‑Res Plot…
  * Events as CSV…
  * To Excel Template…
* Added **Preferences…** stub placeholder (Ctrl+,).
* Updated File menu structure:

  * Start New Analysis…
  * Open Trace & Events…
  * Open Result TIFF…
  * Export ▶
  * Recent Files ▶
  * Preferences…
  * Exit (Ctrl+Q).

### ✏️ Edit Menu Improvements

* Integrated **Undo** (Ctrl+Z) and **Redo** (Ctrl+Y) via QUndoStack.
* Added **Clear All Pins** and **Clear All Events** actions.
* Introduced **Customize ▶** submenu for style editing with direct shortcuts:

  * Axis Titles… (Ctrl+Alt+A)
  * Tick Labels… (Ctrl+Alt+T)
  * Event Labels…
  * Pinned Labels…
  * Trace Style…

### 🖥️ View Menu Simplification

* Simplified to **Single View** and **Dual View** only; grid toggle removed.

### 📖 Help Menu Expansion

* Added:

  * Check for Updates
  * Keyboard Shortcuts
  * Report a Bug…
  * Release Notes

### 🛠️ Stubbed Features & Next Steps

* **Preferences** dialog implementation pending.
* Placeholder **Analysis** menu to be added:

  * Detect Peaks
  * Compute Statistics…
  * Generate Report…
* Plan to introduce smoothing and filtering tools in future release.

### 🐛 Style Editor Fixes

* Cancelling the **Plot Style** dialog now restores the previous fonts and line
  widths.
* Per-tab **Apply** buttons respect the dialog's callback so dual-view panels
  update correctly.
