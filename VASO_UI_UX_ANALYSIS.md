# VasoAnalyzer UI/UX Consistency Analysis Report

## Summary
This report identifies 10 categories of UI/UX inconsistencies and issues found in the VasoAnalyzer codebase. The issues range from minor naming inconsistencies to potentially problematic accessibility gaps and missing user feedback mechanisms.

---

## 1. INCONSISTENT BUTTON TEXT (Capitalization, Naming, Ellipsis)

### Issue 1.1: Inconsistent Restore/Revert Action Naming
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:140` - "Revert to Snapshot"
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:143` - "Restore Style Defaults"
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:157` - "Restore"
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/main_window.py:~3400s` - "Restore axis labels"

**What's Inconsistent:**
- "Revert" vs "Restore" used interchangeably for similar actions
- Should use consistent terminology across the app

**User Impact:** 
- Users confused about whether "Revert" and "Restore" mean different things
- Reduces discoverability of undo/reset functionality

**Suggested Fix:**
- Standardize on either "Revert" or "Restore" (recommend "Revert to [X]" for clarity)
- Use consistently across all dialogs and panels

---

### Issue 1.2: Ampersand Escaping Inconsistency
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:176` - "Apply && Close" (double ampersand for literal &)

**What's Inconsistent:**
- Other buttons don't use this pattern for combined actions
- Makes the text display oddly: "Apply & Close" appears as "Apply & Close" instead of button text

**User Impact:**
- Button text may display incorrectly on some platforms
- Inconsistent with other multi-action buttons

**Suggested Fix:**
- Change to: "Apply and Close" (spell out "and")
- Or: "Apply & Close" (use single ampersand without escaping, if that's intended)

---

### Issue 1.3: Ellipsis Usage Inconsistency for Actions Requiring Additional Input
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:74` - "Load Excel Template" (missing …)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:136` - "Undo Last" (no ellipsis needed)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:139` - "Done" (no ellipsis)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_map_wizard.py` - "Load Events CSV…" (has ellipsis)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/metadata_panel.py:92` - "Add…" (has ellipsis)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/metadata_panel.py:93` - "Remove" (no ellipsis, correct)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/new_project_dialog.py:80` - "Browse…" (correct usage)

**What's Inconsistent:**
- Buttons that open file dialogs/dialogs are inconsistent with ellipsis
- "Load Excel Template" should be "Load Excel Template…"
- Some buttons correctly use ellipsis, others don't

**User Impact:**
- Users don't know which buttons will open dialogs vs. perform immediate actions
- Violates UI/UX standards (buttons that open dialogs should have …)

**Suggested Fix:**
- Add ellipsis (…) to all buttons that open additional dialogs:
  - "Load Excel Template…"
  - "Load Excel…"
  - "Browse…" (already correct)

---

### Issue 1.4: Parenthetical Explanations in Button Labels
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:153` - "Delete (NaN)"
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:155` - "Connect Across"
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:176` - "Apply && Close"

**What's Inconsistent:**
- "Delete (NaN)" uses parenthetical to explain what's being deleted
- Other buttons don't use this pattern
- This technical jargon (NaN) may not be clear to all users

**User Impact:**
- Inconsistent button naming conventions
- Technical terminology may confuse non-technical users
- Makes buttons harder to understand at a glance

**Suggested Fix:**
- Use tooltip instead of parenthetical: "Delete (mark as NaN)"
- Consider: "Delete Point" or "Delete Selected"
- Add tooltip: "Mark selected points as NaN (not a number)"

---

## 2. INCONSISTENT DIALOG TITLES

### Issue 2.1: Dialog Title Format Inconsistency
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/legend_settings_dialog.py:` - "Legend Settings" (Noun + Settings)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/axis_settings_dialog.py:` - "Axis Settings" (Noun + Settings)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:32` - "Map Events to Excel" (Verb phrase)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/figure_export_dialog.py:` - "Export Figure" (Verb + Noun)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/new_project_dialog.py:37` - "Create Project" (Verb + Noun)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:84` - "Plot Settings" (Noun + Settings)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/keyboard_shortcuts_dialog.py:` - "Keyboard Shortcuts" (Noun + Noun)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/crash_recovery_dialog.py:` - "Recover Unsaved Work" (Verb phrase)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/relink_dialog.py:` - "Relink Missing Files" (Verb phrase)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/subplot_layout_dialog.py:` - "Subplot Layout" (Noun + Noun)

**What's Inconsistent:**
- Mix of "Verb + Noun" (Create Project, Export Figure)
- Mix of "Noun + Settings" (Legend Settings, Plot Settings)
- Mix of "Verb phrase" (Map Events, Recover Work, Relink Files)
- No consistent naming pattern

**User Impact:**
- Dialog titles don't form a coherent visual language
- Users may not immediately understand what each dialog does
- Hard to scan menu for specific functionality

**Suggested Fix:**
- Standardize on one pattern. Recommendation: "Action Target" or "[Target] Settings"
- Option A (Settings suffix): "Legend Settings", "Axis Settings", "Subplot Layout", "Keyboard Shortcuts"
- Option B (Action-based): "Configure Legend", "Configure Axis", "Map Events to Excel", "Export Figure"
- Be consistent: either all "[X] Settings" or all "Action [X]"

---

## 3. MISSING KEYBOARD SHORTCUTS

### Issue 3.1: Non-obvious Controls Lack Shortcuts
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:140-143` - "Revert to Snapshot" button (no shortcut)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:143` - "Restore Style Defaults" button (no shortcut)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/metadata_panel.py:92-94` - "Add", "Remove", "Open" buttons (no shortcuts)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:142` - "Reset Overrides" button (no shortcut)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:153-176` - Most editor buttons lack shortcuts

**What's Missing:**
- No keyboard shortcuts for frequent actions
- Tooltips exist but don't mention shortcuts
- Power users can't speed up workflow with keyboard

**User Impact:**
- Slower workflow for experienced users
- No discoverable keyboard shortcuts for non-menu items
- Reduces accessibility for users who prefer keyboard navigation

**Suggested Fix:**
- Add keyboard shortcuts to frequently used buttons
- Example shortcuts:
  - Ctrl+R or Cmd+R for "Revert"
  - R for "Restore"
  - Del for "Delete"
- Add to tooltips: "Delete (Del key)" or include in button itself: "Delete (Del)"
- Document all shortcuts in Help menu

---

## 4. MODAL DIALOGS THAT SHOULD BE MODELESS (OR VICE VERSA)

### Issue 4.1: Some Settings Dialogs Unnecessarily Modal
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/legend_settings_dialog.py:` - Modal (setModal(True))
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/figure_export_dialog.py:` - Modal (setModal(True))
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/new_project_dialog.py:38` - Modal (setModal(True))
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:51` - Modal (setModal(True)) - **CORRECT**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:` - **NOT** explicitly set to modal

**What's the Problem:**
- Legend Settings being modal prevents users from comparing with the plot
- Users can't switch between plot and legend dialog
- However, Point Editor should be modal (and is)
- Unified Settings Dialog is modeless but maybe should show live preview

**User Impact:**
- Can't compare settings changes in real-time
- Users get locked into a single dialog until they close it
- Workflow interruption for users comparing options

**Suggested Fix:**
- Make settings dialogs modeless (allow interaction with main window)
- Keep Point Editor modal (correct decision)
- Ensure dialogs have "Apply" button (separate from "OK") for real-time preview
  - Status: Unified Settings has Apply button ✓
  - Legend Settings should add Apply button

---

## 5. MISSING PROGRESS INDICATORS FOR LONG OPERATIONS

### Issue 5.1: No Progress Feedback for File Loading Operations
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/main_window.py` - TIFF loading (found QProgressBar in use, but not comprehensive)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/mixins/sample_loader_mixin.py` - No progress indication for load operations
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:74` - Excel load (no progress)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_map_wizard.py` - Wizard steps (no progress)

**What's Missing:**
- Long operations (loading large TIFF files, processing Excel files) may have no visible progress
- Users don't know if the app is frozen or processing
- No estimated time remaining

**User Impact:**
- App appears unresponsive during long operations
- Users may force-quit the app thinking it's frozen
- No feedback during background processing

**Suggested Fix:**
- Add QProgressDialog for file loading operations
- Show progress bar for:
  - TIFF file loading (especially large stacks)
  - Excel template loading
  - CSV file processing
- Use threading with progress signals (already partially implemented)
- Add status messages: "Loading TIFF frames 1/500..."

---

## 6. MISSING ERROR DIALOGS / USER FEEDBACK

### Issue 6.1: Silent Failures in Some Operations
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:168` - Color dialog (no feedback if cancelled)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:103` - Cell click (may silently fail)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py` - Editor operations (some may silently fail)

**What's Missing:**
- Some operations don't show error messages if they fail
- User doesn't know if action succeeded or failed
- No feedback for cancellations (e.g., color dialog)

**User Impact:**
- Users confused about operation results
- Can't tell if something went wrong
- Reduced confidence in the app

**Suggested Fix:**
- Add QMessageBox for error conditions
- Show success messages for important operations
- Example: After "Reset Overrides" → "Label defaults restored"
- Provide context in error messages (not just error code)

---

## 7. INCONSISTENT WIDGET STYLING OR THEMES

### Issue 7.1: Inconsistent Button Styling Across Dialogs
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:33-57` - Custom QPushButton stylesheet
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:140-160` - Uses style() for icons
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/main_window.py:~3850s` - Custom QPushButton styles (isPrimary, isSecondary, isGhost)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:352-357` - Color button inline stylesheet

**What's Inconsistent:**
- Some dialogs have custom stylesheets
- Some use inline styles
- Some use theme objects
- No centralized button styling

**User Impact:**
- Buttons look different in different dialogs
- Hard to maintain consistent look and feel
- Difficult to update theme across entire app

**Suggested Fix:**
- Create a central button styling system (theme.py)
- Define button classes: PrimaryButton, SecondaryButton, GhostButton
- Use consistent colors from CURRENT_THEME
- Remove inline stylesheets in favor of centralized styling

---

## 8. MISSING TOOLTIPS ON NON-OBVIOUS CONTROLS

### Issue 8.1: Buttons and Controls Lack Descriptive Tooltips
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:142` - "Reset Overrides" (no tooltip)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:153-176` - Most editor buttons lack tooltips
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:134-142` - "Skip", "Undo Last", "Done" (no tooltips)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/metadata_panel.py:92-94` - Add/Remove/Open buttons (no tooltips despite setEnabled calls)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/scope_view.py:132-133` - Capture and Export buttons (no tooltips)

**What's Missing:**
- No tooltips explaining what these buttons do
- No tooltips showing keyboard shortcuts (if they exist)
- No context-sensitive help text

**User Impact:**
- Users don't understand what non-obvious buttons do
- No help for new users
- Inconsistent with toolbar buttons (which have tooltips)

**Suggested Fix:**
- Add setToolTip() to all non-obvious buttons:
  - "Reset Overrides" → "Reset all per-event customizations to defaults"
  - "Delete (NaN)" → "Mark selected points as NaN (invalid)"
  - "Connect Across" → "Interpolate across selected gap"
  - "Skip" → "Skip this event without mapping to Excel"
  - "Capture" → "Capture sweep data using trigger settings (Enter key)"

---

## 9. INCONSISTENT LAYOUT PATTERNS

### Issue 9.1: Inconsistent Dialog Margins and Spacing
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py:112` - Margins (14, 16, 14, 16)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/new_project_dialog.py:56` - Margins (16, 16, 16, 16)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:68-69` - Spacing (12)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/point_editor_view.py:69` - Margins (12, 12, 12, 12)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/figure_export_dialog.py` - Different margins

**What's Inconsistent:**
- Dialog margins vary: (14,16,14,16), (16,16,16,16), (12,12,12,12), etc.
- Spacing between elements varies: 6, 8, 12 pixels
- No consistent design grid

**User Impact:**
- Dialogs look visually inconsistent
- Makes app feel unpolished
- Hard to align elements across dialogs
- Difficult to maintain visual hierarchy

**Suggested Fix:**
- Define standard spacing constants (e.g., SPACING_XS=4, SPACING_S=8, SPACING_M=12, SPACING_L=16)
- Use consistent margins in all dialogs: (12, 12, 12, 12) or (14, 14, 14, 14)
- Use consistent spacing: 8 or 12 pixels between elements
- Create a style guide document

---

### Issue 9.2: Inconsistent Form Layout Alignment
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/new_project_dialog.py:64` - `form.setLabelAlignment(Qt.AlignRight)`
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/legend_settings_dialog.py` - Form layout (check alignment)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/settings/event_labels_tab.py:110` - `setLabelAlignment(Qt.AlignRight)`

**What's Inconsistent:**
- Form layouts use different label alignments
- Some may use AlignLeft, some AlignRight
- No consistent form field alignment

**User Impact:**
- Forms look visually inconsistent
- Hard to read form fields
- Tab order may be inconsistent

**Suggested Fix:**
- Standardize form layout alignment to AlignRight (professional look)
- Ensure consistent label widths in all forms
- Document form layout standards

---

## 10. ACCESSIBILITY ISSUES (Missing Labels, Accessible Names)

### Issue 10.1: Missing Accessible Names and Descriptions
**Files & Lines:**
- Most button controls lack setAccessibleName()
- Most spinboxes and textboxes lack setAccessibleName()
- Color buttons have no accessible description
- Example from `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py`:
  - Line 95: `self.color_button = QPushButton("Text Color…")` (no accessible name)
  - Line 119: `self.x_offset_spin` (no accessible name)
  - Line 127: `self.y_offset_spin` (no accessible name)

**Found Files Using Accessibility (partial):**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/settings/event_labels_tab.py:98` - Uses setObjectName but not setAccessibleName
- Only 10 files use setAccessibleName/setAccessibleDescription out of 50+ UI files

**What's Missing:**
- Screen reader support is minimal
- Controls don't have semantic labels for accessibility tools
- No ARIA-like descriptions for users with visual impairments
- Tab order may be unclear

**User Impact:**
- Users relying on screen readers get poor experience
- Keyboard-only navigation may be confusing
- Non-visual users can't determine what controls do
- App is not compliant with accessibility standards (WCAG 2.1)

**Suggested Fix:**
- Add setAccessibleName() to all controls:
  ```python
  self.color_button = QPushButton("Text Color…")
  self.color_button.setAccessibleName("Event label text color picker")
  self.color_button.setAccessibleDescription("Click to choose a custom color for the event label")
  ```
- Add accessible names for form fields:
  ```python
  self.x_offset_spin = QDoubleSpinBox()
  self.x_offset_spin.setAccessibleName("Horizontal offset in pixels")
  ```
- Test with screen reader (NVDA, JAWS)
- Ensure tab order is logical (add setTabOrder if needed)
- Add keyboard shortcuts with accessible descriptions

---

### Issue 10.2: Form Labels May Be Missing for Some Controls
**Files & Lines:**
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:119-133` - Spinboxes have labels (OK)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/event_label_editor.py:82` - QLineEdit for label text (labeled by layout)
- `/home/user/VasoAnalyzer/src/vasoanalyzer/ui/dialogs/excel_mapping_dialog.py:82-83` - Column selector has label

**What's Correct:**
- Most form controls have associated QLabel
- Layout provides semantic grouping

**Suggested Fix:**
- Verify all form fields have associated labels
- Use setLabelAlignment and addRow consistently
- Test with accessibility tools

---

## SUMMARY TABLE

| Category | Severity | Files Affected | Issue Count |
|----------|----------|-----------------|------------|
| 1. Inconsistent Button Text | Medium | 8 | 4 |
| 2. Inconsistent Dialog Titles | Medium | 10 | 1 |
| 3. Missing Keyboard Shortcuts | Medium | 5 | 1 |
| 4. Modal Dialog Issues | Low | 3 | 1 |
| 5. Missing Progress Indicators | Medium | 4 | 1 |
| 6. Missing Error Dialogs | Low | 3 | 1 |
| 7. Inconsistent Widget Styling | Medium | 4 | 1 |
| 8. Missing Tooltips | High | 10+ | 1 |
| 9. Inconsistent Layout Patterns | Low | 10+ | 2 |
| 10. Accessibility Issues | High | 50+ | 2 |
| **TOTAL** | | **50+** | **15** |

---

## PRIORITY RECOMMENDATIONS

### HIGH PRIORITY (Implement First)
1. **Add tooltips to all non-obvious buttons** (Issue 8.1)
   - Affects user understanding
   - Quick to implement
   - High impact on UX
   
2. **Fix accessibility issues** (Issue 10.1-10.2)
   - Legal/compliance requirement
   - Affects users with disabilities
   - Improves overall code quality

3. **Standardize button naming** (Issue 1.1-1.4)
   - Reduces user confusion
   - Creates consistent UI language
   - Supports accessibility

### MEDIUM PRIORITY (Implement Soon)
4. **Standardize dialog titles** (Issue 2.1)
5. **Add keyboard shortcuts** (Issue 3.1)
6. **Create centralized button styling** (Issue 7.1)
7. **Standardize spacing and layout** (Issue 9.1-9.2)

### LOW PRIORITY (Nice to Have)
8. **Add progress indicators for long operations** (Issue 5.1)
9. **Make settings dialogs modeless** (Issue 4.1)
10. **Enhance error feedback** (Issue 6.1)

