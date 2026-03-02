# Windows & Mission Control Boundaries

## Roles and responsibilities
- `HomePage` is a UI-only widget that emits user intent signals (create/open/import/resume).
- `HomeDashboardWindow` hosts `HomePage`, wires intents to `WindowManager`, and renders recents UI.
- `WindowManager` owns all top-level windows and lifecycle dialogs (create/open/import).
- `MainWindow` (class `VasoAnalyzerApp`) is the analysis workspace and should focus on project work.

## Allowed dependencies
- `HomePage` → UI helpers (`theme`, icons) and Qt widgets only.
- `HomeDashboardWindow` → `HomePage`, `WindowManager` (for intent routing), and UI helpers.
- `WindowManager` → `HomeDashboardWindow`, `MainWindow`, and create/open/import dialogs.
- `MainWindow` → project/analysis UI and services (no dashboard creation).

## Forbidden imports
- `HomePage` must not import `vasoanalyzer.ui.main_window` or `vasoanalyzer.core.project`.
- `HomeDashboardWindow` must not import project open/save logic; it only calls `WindowManager`.
- `MainWindow` must not import or instantiate `HomeDashboardWindow`.

## Lifecycle rules
- App launch shows the Home Dashboard first.
- Opening/creating a workspace hides the dashboard.
- When the last workspace closes, the dashboard is shown again.
- Create/open/import dialogs that affect window lifecycle (open/create a workspace) are
  created by `WindowManager` and parented to the active dashboard or workspace window.
