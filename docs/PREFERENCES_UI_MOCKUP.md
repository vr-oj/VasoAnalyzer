# VasoAnalyzer Preferences Dialog - UI Mockup

This document shows the layout of the new comprehensive Preferences dialog.

---

## Window Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Preferences                                          ✕     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┬──────────┬───────────────────┬──────────┐     │
│  │ General │ Projects │ Autosave & Snap.. │ Advanced │     │
│  └─────────┴──────────┴───────────────────┴──────────┘     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │          [Tab Content Area - See Below]             │   │
│  │                                                      │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│                                     ┌──────┐  ┌────────┐   │
│                                     │ OK   │  │ Cancel │   │
│                                     └──────┘  └────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 1: General

```
┌─────────────────────────────────────────────────────────────┐
│  Default Directories                                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  Default save location:                             │   │
│  │  ┌─────────────────────────────────────┬──────────┐│   │
│  │  │ ~/Documents/VasoAnalyzer            │ Browse...││   │
│  │  └─────────────────────────────────────┴──────────┘│   │
│  │                                                      │   │
│  │  Default data location:                             │   │
│  │  ┌─────────────────────────────────────┬──────────┐│   │
│  │  │ ~/Documents                         │ Browse...││   │
│  │  └─────────────────────────────────────┴──────────┘│   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Startup                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  ☑ Show welcome dialog on startup                   │   │
│  │                                                      │   │
│  │  ☐ Restore last session on startup                  │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 2: Projects

```
┌─────────────────────────────────────────────────────────────┐
│  Project Format                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  ☑ Use single-file project format (.vaso) for      │   │
│  │    new projects                                      │   │
│  │                                                      │   │
│  │  Recommended (default): Single-file format (.vaso)  │   │
│  │  is crash-proof, works safely with cloud storage    │   │
│  │  (Dropbox, iCloud, Google Drive), and is easy to    │   │
│  │  share and backup like LabChart or Prism files.     │   │
│  │  Uses snapshot-based saves internally.              │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Migration & Compatibility                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  ☑ Automatically migrate legacy projects to new     │   │
│  │    format                                            │   │
│  │                                                      │   │
│  │  ☑ Keep legacy files after migration (.vaso.legacy)│   │
│  │                                                      │   │
│  │  When opening old .vaso or .vasopack projects,      │   │
│  │  automatically convert them to the new format and   │   │
│  │  keep backups for safety.                           │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 3: Autosave & Snapshots

```
┌─────────────────────────────────────────────────────────────┐
│  Autosave                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │                 ☑ Enable autosave                    │   │
│  │                                                      │   │
│  │  Autosave interval:  ┌──────────────┐               │   │
│  │                      │ 1 minute    ▼│               │   │
│  │                      └──────────────┘               │   │
│  │                      • 30 seconds                    │   │
│  │                      • 1 minute                      │   │
│  │                      • 2 minutes                     │   │
│  │                      • 5 minutes                     │   │
│  │                      • 10 minutes                    │   │
│  │                                                      │   │
│  │  Autosave creates periodic snapshots of your work.  │   │
│  │  If the app crashes, you'll only lose changes since │   │
│  │  the last autosave.                                  │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Snapshot Retention                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  Keep last:  ┌──────────────────┐                   │   │
│  │              │ 50 ▲▼│ snapshots  │                   │   │
│  │              └──────────────────┘                   │   │
│  │                                                      │   │
│  │  Projects keep multiple snapshots for recovery.     │   │
│  │  Older snapshots are automatically deleted when     │   │
│  │  this limit is reached. Each snapshot is a complete │   │
│  │  copy of your project.                              │   │
│  │                                                      │   │
│  │  Estimated disk usage: ~500 MB for typical project  │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Tab 4: Advanced

```
┌─────────────────────────────────────────────────────────────┐
│  Recovery & Cleanup                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │                 ☑ Enable automatic recovery          │   │
│  │                                                      │   │
│  │  Clean temp files   ┌──────────────┐                │   │
│  │  older than:        │ 24 ▲▼│ hours │                │   │
│  │                     └──────────────┘                │   │
│  │                                                      │   │
│  │  Temporary files from crashed sessions are          │   │
│  │  automatically cleaned up after this time.          │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Performance                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  ☐ Compress container files (slower saves,          │   │
│  │    smaller files)                                    │   │
│  │                                                      │   │
│  │  Enabling compression reduces file size by ~10-20%  │   │
│  │  but makes saves slower. Most SQLite data doesn't   │   │
│  │  compress well.                                      │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Maintenance                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  ┌──────────────────────────┐                       │   │
│  │  │ Clean Up Temp Files Now  │                       │   │
│  │  └──────────────────────────┘                       │   │
│  │                                                      │   │
│  │  Manually clean up temporary files from previous    │   │
│  │  sessions.                                           │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Color Scheme & Styling

**Group Boxes:**
- Border: 1px solid #CCC
- Background: White
- Title: Bold, 11pt

**Help Text:**
- Color: #666 (gray)
- Font: 9pt
- Italic: No
- Word wrap: Yes

**Checkboxes:**
- Standard Qt checkbox
- Label: 11pt regular
- Spacing: 8px between items

**Input Fields:**
- Border: 1px solid #CCC
- Height: 24px
- Padding: 4px
- Font: 11pt

**Buttons:**
- Primary (OK): Blue background, white text
- Secondary (Cancel, Browse): Gray background, black text
- Action (Clean Up): Standard button style
- Height: 28px
- Padding: 8px horizontal

**Tabs:**
- Active: White background, blue bottom border
- Inactive: Light gray background
- Font: 11pt
- Padding: 8px

---

## Responsive Behavior

**Minimum Size:**
- Width: 600px
- Height: 500px

**Maximum Size:**
- Width: Unconstrained (can grow)
- Height: Unconstrained (can grow)

**Scroll Behavior:**
- If content exceeds window height, tabs scroll individually
- Window chrome (title, buttons) always visible

**Window Position:**
- Centered on parent window
- Modal (blocks main window)

---

## Keyboard Shortcuts

**Navigation:**
- `Tab` - Next field
- `Shift+Tab` - Previous field
- `Ctrl+Tab` - Next tab
- `Ctrl+Shift+Tab` - Previous tab
- `Space` - Toggle checkbox/activate button
- `Enter` - Press focused button

**Actions:**
- `Cmd+,` / `Ctrl+,` - Open preferences (from main window)
- `Cmd+W` / `Ctrl+W` - Close preferences (Cancel)
- `Enter` - Accept and close (OK)
- `Esc` - Cancel and close

---

## Validation & Feedback

### Real-Time Validation

**Snapshot Count:**
- Range: 10-500
- Default: 50
- Updates disk usage estimate immediately

**Temp Cleanup Age:**
- Range: 1-168 hours
- Default: 24
- Suffix: " hours" auto-appended

**Autosave Interval:**
- Dropdown selection only
- No invalid values possible

### User Feedback

**On "Clean Up Temp Files Now":**
```
┌─────────────────────────────┐
│  Cleanup Complete           │
├─────────────────────────────┤
│                             │
│  Cleaned up 3 temporary     │
│  directory(ies).            │
│                             │
│          ┌────┐             │
│          │ OK │             │
│          └────┘             │
└─────────────────────────────┘
```

**On Cleanup Failure:**
```
┌─────────────────────────────┐
│  Cleanup Failed        ⚠    │
├─────────────────────────────┤
│                             │
│  Failed to clean up temp    │
│  files:                     │
│                             │
│  Permission denied: /tmp/.. │
│                             │
│          ┌────┐             │
│          │ OK │             │
│          └────┘             │
└─────────────────────────────┘
```

---

## Platform Differences

### macOS

**Title:** "Preferences"
**Access:** `VasoAnalyzer → Preferences` (Cmd+,)
**Button Order:** Cancel | OK
**Appearance:** Native macOS style (Aqua)

### Windows

**Title:** "Preferences"
**Access:** `Edit → Preferences` (Ctrl+,)
**Button Order:** OK | Cancel
**Appearance:** Windows native style

### Linux

**Title:** "Preferences"
**Access:** `Edit → Preferences` (Ctrl+,)
**Button Order:** OK | Cancel
**Appearance:** Qt native style (matches desktop environment)

---

## Accessibility

**Screen Reader Support:**
- All labels properly associated with controls
- Tab order follows visual flow
- Checkboxes have descriptive labels
- Help text is associated with parent group

**Keyboard Navigation:**
- Full keyboard control (no mouse required)
- Tab order: top to bottom, left to right
- Focus indicators visible on all controls

**High Contrast:**
- Respects system high-contrast settings
- All text readable against background
- Borders visible in high-contrast mode

---

## Settings Persistence

**When User Clicks OK:**
1. Validate all inputs
2. Save to QSettings
3. Apply changes to global config
4. Close dialog
5. Show confirmation in status bar (optional)

**When User Clicks Cancel:**
1. Discard all changes
2. Close dialog
3. No confirmation needed

**When User Changes Value:**
- No immediate save (changes are pending)
- Disk usage estimate updates immediately (visual only)
- No validation errors shown until OK clicked

---

## Future Enhancements

**Visual:**
- [ ] Icons next to tab names
- [ ] Expandable "Advanced" sections
- [ ] Search/filter for settings
- [ ] "What's This?" help tooltips

**Functional:**
- [ ] "Reset to Defaults" per-tab or global
- [ ] Import/Export settings
- [ ] Settings profiles (Work, Home, etc.)
- [ ] Per-project override indicators

**Organization:**
- [ ] More tabs as features grow
- [ ] Tree-based navigation for many settings
- [ ] "Recently Changed" indicator

---

## Example Usage Scenarios

### Scenario 1: User Wants to Save Disk Space

1. Open Preferences → Autosave & Snapshots
2. Change "Keep last:" from 50 to 20
3. Note disk usage estimate: ~500 MB → ~200 MB
4. Go to Advanced tab
5. Enable "Compress container files"
6. Click OK
7. Result: ~40% disk space savings

### Scenario 2: User on Slow Network Drive

1. Open Preferences → Autosave & Snapshots
2. Change interval from "1 minute" to "5 minutes"
3. Go to Advanced tab
4. Enable compression (slower saves but smaller network transfers)
5. Click OK
6. Result: Less frequent network I/O

### Scenario 3: User Cleaning Up After Crash

1. Open Preferences → Advanced
2. Click "Clean Up Temp Files Now"
3. See: "Cleaned up 5 temporary directory(ies)."
4. Close preferences
5. Result: 500 MB of temp files removed

---

## Summary

**Total Settings:** 15 configurable options
**Total Tabs:** 4 organized categories
**Total Actions:** 1 manual action button
**Lines of Code:** ~400 (dialog implementation)

**User Experience:**
- Professional, familiar interface
- Clear organization
- Helpful explanations
- Live feedback
- Sensible defaults

**Developer Experience:**
- Easy to extend
- Type-safe
- Well-documented
- Consistent patterns
- Platform-agnostic
