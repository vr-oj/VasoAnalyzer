# Workspace Toolbar Recommendation (Plan Only)

## 1. Golden path summary
- Create/Open project: Home screen entry and File > Project actions; Save Project maintains state.
- Import data: Open Data dropdown (Import Trace CSV, Import Events CSV, Import Result TIFF, Import Folder, Dataset Package, Import from Project).
- Inspect: Plot toolbar Pan/Select, View dropdown (Zoom/Autoscale/Grid/Style), trace toggles (Inner/Outer/Pressure), Project/Details toggles, Review Events.
- Export: Excel mapper (toolbar) plus File > Export (CSV/Excel template/Bundle/etc.).

## 2. Grouping proposal
- Project/Data: Home screen, Open Data dropdown, Save Project, Project toggle, Details (metadata) toggle.
- View/Navigation: Pan, Select, View dropdown (Zoom to All, Zoom In/Out/Back, Autoscale, Y-Autoscale, Grid, Style), trace visibility toggles (Inner/Outer/Pressure/Set Pressure).
- Events: Review Events, Edit Points (view menu), event-related actions in menus.
- Export: Excel mapper (Export to Excel Template) and other export menu items.
- Help/Utilities: Welcome guide.

## 3. Proposed placement
- Primary toolbar (Always): Home screen, Open Data dropdown, Save Project.
- Secondary toolbar / overflow (Contextual/Rare): Review Events, Excel mapper, Welcome guide, direct Import Result TIFF button.
- Move to menu-only (Contextual/Rare): Import Dataset Package, Import from Project, Import Folder (keep in File > Open Data; optional in dropdown if space permits).
- Plot toolbar: keep Pan + Select and View dropdown always; keep trace visibility toggles grouped together; keep Project/Details toggles only if routinely used, otherwise move to View > Panels as primary.

## 4. Conflicts and duplicates (primary entry point recommendation)
- Import Trace / Events / Result TIFF: appears in toolbar dropdown and File > Open Data (separate QActions for trace/events/TIFF). Primary should be toolbar dropdown; avoid separate toolbar button for TIFF to reduce duplication.
- Import Folder / Dataset Package / Import from Project: same QAction appears in File > Open Data and toolbar dropdown. Pick one primary entry (suggest File > Open Data, keep dropdown only if high frequency).
- Save Project: toolbar and Project menu. Keep toolbar as primary; menu as secondary.
- Welcome guide: toolbar and Help menu. Keep Help menu as primary; remove from toolbar if space is needed.
- Home screen: toolbar and View menu. Keep toolbar as primary; menu as secondary.
- Excel mapper: toolbar and File > Export (same handler). Pick a single primary entry under Export; toolbar entry can be contextual or removed.
- Plot settings: View dropdown "Style" vs Tools > Plot Settings (different dialogs). Clarify naming to avoid perceived duplicates (no action rename yet; note for future).
- Trace visibility toggles (Inner/Outer/Pressure/Set Pressure): appear in toolbar row 2 and View > Panels. Keep toolbar as primary; View menu as secondary.
- Project/Details toggles: icon-only toolbar buttons and View > Panels dock toggle actions. Choose one primary location (toolbar if frequently used).

## 5. Risks
- Removing or hiding Open Data, Save Project, or Pan/Select breaks the core path (must remain top-level).
- Hiding the View dropdown removes access to backend-specific actions (PyQtGraph Zoom In/Out/Autoscale/Y-Autoscale).
- Moving Review Events or Excel mapper into menus may reduce discoverability for the event workflow.
- Removing trace visibility toggles from the toolbar can slow inspection when switching between Inner/Outer/Pressure traces.
