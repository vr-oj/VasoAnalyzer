# UI Interaction Contract

Purpose
Ensure consistent, professional interaction feedback across all menus, tooltips, disabled states, and keyboard focus.

Interaction rules
- Menus must highlight the hovered/selected item.
- Disabled items must be legible and visually distinct.
- Tooltips must be readable in both dark and light modes.
- Keyboard focus must be visible; focus should never be invisible during navigation.

Styling source of truth
- Global QSS is assembled and applied in `src/vasoanalyzer/ui/theme.py` via `_build_complete_stylesheet()`.
- Shared base styles live in `style.qss` and are appended by the theme pipeline.
- Rule: no widget-specific styles unless explicitly approved.

Acceptance checklist
- Open Data dropdown hover highlight visible.
- File menu hover highlight visible.
- Right-click context menu highlight visible.
- Tooltip readable on hover over Open Data / Save / Review Events.
- Disabled menu items are readable.

Manual verification checklist
- Hover items in Open Data, File, View, and right-click menus; confirm clear highlight.
- Hover Open Data, Save Project, and Review Events buttons; confirm tooltip contrast is readable.
- Tab through key controls; confirm a visible focus outline on buttons, inputs, trees, and tables.
