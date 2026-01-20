# Workspace Look & Feel Contract

Purpose
Define the visual and interaction rules for the analysis workspace so that always-present elements are coherent, calm, and reliable before per-surface polish.

Scope (always-present workspace elements)
- Main toolbar (Row 1)
- Navigation/plot toolbar (Row 2)
- Project panel (left)
- PyQtGraph plot area (center)
- Event table (right)
- TIFF stack / snapshot viewer
- Status bar

Visual hierarchy
Primary focus: data (plot area)
Secondary: controls (toolbars)
Tertiary: metadata (project tree, event table, status)

Rules
- Plot area has the highest contrast and the lowest visual noise.
- Panels and tables never compete with the plot for attention.

Panel chrome rules (Project, Event table, TIFF viewer)
Definition
- Background: `panel_bg` (theme token, aligned with content surface).
- Border: 1px solid `panel_border` (theme token), no shadows.
- Corner radius: `panel_radius` (theme token; default 6px).
- Header styling: font weight 600, size 10-11pt, restrained padding (4-6px).

Rules
- Panels feel like containers, not cards.
- Headers are readable but quiet.
- No heavy shadows or accent borders.

Toolbar density and grouping
Definition
- Button padding: 5px 8px, min-width 48px, radius 6px.
- Toolbar padding: 4px 6px, border 1px, radius 6px.
- No mixed density between toolbar rows.
- Use separators/spacers for grouping.

Rules
- Toolbars never dominate the plot.
- Row 1 = Project and Workflow.
- Row 2 = Inspect and View.
- Toolbars are visually separated from content by a single thin border.

PyQtGraph consistency contract
Defaults (deterministic unless user changes them)
- Background: `plot_bg` from theme.
- Grid: visible on X/Y, alpha 0.10, color `grid_color`.
- Axis text: color `text`, font family "Arial".
- Axis sizing: label size 20; tick size auto-clamped to 10-18.
- Tick density: default PyQtGraph tick calculation; bottom track shows X labels.
- Label placement: bottom axis shows "Time (s)" only on the lowest visible track.
- Hover/selection: hover label uses `hover_label_bg` + `hover_label_border`.
- Event markers: `event_line` color, width 2, dash line, alpha 1.0, z above traces.

Rules
- Deterministic appearance by default.
- No dataset-specific styling bleed-through.

Event table rules
Definition
- Row height: 28px (fixed), vertical header centered.
- Selection: `selection_bg` + `text` (visible, not loud).
- Column alignment: status centered, event left, numeric right.
- Header styling: 11pt, weight 600, padding 6px 10px, bottom rule only.

Rules
- Readable at a glance.
- Selection is obvious but not loud.
- Table does not visually outweigh the plot.

TIFF snapshot viewer rules
Definition
- Visible only when snapshots are available and the viewer is toggled on.
- Container uses `panel_bg` and `panel_border` like other panels.
- Preview frame uses a thin dashed border; no selection highlight state.
- Max visual weight equals other panels; never higher than plot.

Rules
- Contextual aid only.
- Never competes with the plot for attention.

Status bar behavior
Definition
- Allowed: mode, progress, performance, and passive state text.
- Not allowed: primary actions, alerts that require immediate response.
- Visual weight: thin top border, minimal padding, quiet contrast.

Rules
- Communicates state, never demands action.
- Always readable, never distracting.

Non-goals (explicit)
- No toolbar reordering here.
- No modal or dialog changes.
- No deep per-panel polish in this task.
- No export or save UX changes.

Implementation references
- Theme tokens: `src/vasoanalyzer/ui/theme.py`
- Global QSS: `style.qss`
- Workspace panel chrome: `src/vasoanalyzer/ui/shell/init_ui.py`, `src/vasoanalyzer/ui/project_explorer.py`
- Plot defaults: `src/vasoanalyzer/ui/plots/pyqtgraph_plot_host.py`, `src/vasoanalyzer/ui/plots/pyqtgraph_trace_view.py`
- Event table styling: `src/vasoanalyzer/ui/event_table.py`
