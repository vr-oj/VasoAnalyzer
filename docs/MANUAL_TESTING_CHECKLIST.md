# VasoAnalyzer Manual Testing Checklist

## Overview
This checklist covers manual testing for the new container format (.vaso) and updated preferences system.

**Test Date:** __________
**Tester:** __________
**Platform:** ☐ macOS ☐ Windows ☐ Linux
**Build/Version:** __________

---

## 1. Container Format (.vaso) - Basic Operations

### 1.1 Create New Project
- [ ] File → New Project
- [ ] Enter project name: "Test Project 1"
- [ ] Verify file dialog defaults to **.vaso** extension
- [ ] Save to Desktop
- [ ] Verify single .vaso file is created (not a folder)
- [ ] **Expected:** One file named "Test Project 1.vaso" on Desktop

### 1.2 Save and Reopen Container
- [ ] Create new project "Test Project 2.vaso"
- [ ] Add some test data (traces, events, annotations)
- [ ] File → Save (or Cmd/Ctrl+S)
- [ ] Close project
- [ ] Reopen the .vaso file from Desktop
- [ ] **Expected:** All data is preserved and loads correctly

### 1.3 Autosave with Container
- [ ] Open or create a .vaso project
- [ ] Make changes (add data)
- [ ] Wait for autosave (check status bar or wait 1-2 minutes)
- [ ] Kill the app forcefully (Force Quit on macOS, Task Manager on Windows)
- [ ] Reopen the .vaso file
- [ ] **Expected:** Recent changes are recovered (within autosave interval)

### 1.4 Multiple Saves
- [ ] Create .vaso project
- [ ] Add data, save
- [ ] Add more data, save
- [ ] Add more data, save
- [ ] Repeat 5-10 times
- [ ] File size should grow gradually
- [ ] All saves complete quickly (< 2 seconds for typical project)
- [ ] **Expected:** No errors, no file corruption

### 1.5 Large Project Performance
- [ ] Create .vaso project with large dataset (100+ MB of traces)
- [ ] Save project
- [ ] Close and reopen
- [ ] **Expected:** Save and open times are reasonable (< 10 seconds)

---

## 2. Folder Bundle Format (.vasopack) - Compatibility

### 2.1 Create Folder Bundle
- [ ] File → Save As
- [ ] Change filter to "Folder Bundles (*.vasopack)"
- [ ] Save as "Test Folder Bundle.vasopack"
- [ ] **Expected:** Folder/bundle is created (appears as single item on macOS)

### 2.2 Convert .vasopack to .vaso
- [ ] Create or open a .vasopack project
- [ ] File → Save As
- [ ] Choose "VasoAnalyzer Projects (*.vaso)"
- [ ] Save as "Converted.vaso"
- [ ] **Expected:** Single .vaso file is created
- [ ] Open Converted.vaso
- [ ] **Expected:** All data is intact

---

## 3. File Icons and Associations

### 3.1 macOS File Icons
- [ ] Create .vaso file
- [ ] Create .vasopack folder
- [ ] View in Finder at different zoom levels (list, icons, gallery)
- [ ] **Expected:** Both show VasoAnalyzer app icon
- [ ] Double-click .vaso file
- [ ] **Expected:** Opens in VasoAnalyzer

### 3.2 Windows File Icons (Windows only)
- [ ] Create .vaso file
- [ ] View in File Explorer
- [ ] **Expected:** Shows VasoAnalyzer app icon
- [ ] Double-click to open
- [ ] **Expected:** Opens in VasoAnalyzer

### 3.3 File Type Info
- [ ] Right-click .vaso file → Get Info (macOS) or Properties (Windows)
- [ ] **Expected:** Shows as "VasoAnalyzer Project"
- [ ] Kind: VasoAnalyzer Project
- [ ] Opens with: VasoAnalyzer.app

---

## 4. Preferences Dialog - All Tabs

### 4.1 Open Preferences
- [ ] **macOS:** VasoAnalyzer menu → Preferences (Cmd+,)
- [ ] **Windows/Linux:** Edit menu → Preferences (Ctrl+,)
- [ ] **Expected:** Dialog opens with 4 tabs visible

### 4.2 General Tab
- [ ] Click "General" tab
- [ ] **Default save location:** Click Browse, select folder
- [ ] **Default data location:** Click Browse, select folder
- [ ] Toggle "Show welcome dialog on startup"
- [ ] Toggle "Restore last session on startup"
- [ ] Click OK
- [ ] Reopen preferences
- [ ] **Expected:** All settings are saved

### 4.3 Projects Tab
- [ ] Click "Projects" tab
- [ ] **Use single-file format:** Should be checked by default
- [ ] **Auto-migrate legacy projects:** Should be checked
- [ ] **Keep legacy files after migration:** Should be checked
- [ ] Uncheck all, click OK, reopen
- [ ] **Expected:** Settings are preserved

### 4.4 Autosave & Snapshots Tab
- [ ] Click "Autosave & Snapshots" tab
- [ ] **Enable autosave:** Toggle on/off
- [ ] **Autosave interval:** Try different values (30s, 1min, 5min)
- [ ] **Keep last snapshots:** Change from 50 to 20
- [ ] **Expected:** Disk usage estimate updates in real-time
- [ ] Click OK, reopen
- [ ] **Expected:** Settings are saved

### 4.5 Advanced Tab
- [ ] Click "Advanced" tab
- [ ] Toggle "Enable automatic recovery"
- [ ] Change temp cleanup hours (default: 24)
- [ ] Toggle "Compress container files"
- [ ] Click "Clean Up Temp Files Now" button
- [ ] **Expected:** Shows success message dialog
- [ ] Click OK, reopen
- [ ] **Expected:** Settings are saved

### 4.6 Keyboard Navigation
- [ ] Open Preferences
- [ ] Press Tab repeatedly
- [ ] **Expected:** Focus moves through all controls
- [ ] Press Ctrl+Tab (Windows/Linux) or Cmd+Tab (macOS)
- [ ] **Expected:** Switches between tabs
- [ ] Press Esc
- [ ] **Expected:** Dialog closes (Cancel)

### 4.7 Cancel vs OK
- [ ] Open Preferences
- [ ] Change several settings across tabs
- [ ] Click Cancel
- [ ] Reopen Preferences
- [ ] **Expected:** No changes were saved
- [ ] Change settings again
- [ ] Click OK
- [ ] Reopen Preferences
- [ ] **Expected:** Changes ARE saved

---

## 5. Legacy Format Migration

### 5.1 Open Old .vaso SQLite File
- [ ] Locate an old-style .vaso project (single SQLite file from old version)
- [ ] Open it in VasoAnalyzer
- [ ] **Expected:** Auto-migration prompt or automatic conversion
- [ ] **Expected:** Original file renamed to .vaso.legacy
- [ ] **Expected:** New .vaso container format is created
- [ ] **Expected:** All data is preserved

### 5.2 Export to Legacy Format
- [ ] Open a new-format .vaso project
- [ ] File → Export to Legacy Format (if available)
- [ ] **Expected:** Single-file SQLite .vaso is created
- [ ] Open exported file in old version of VasoAnalyzer (if available)
- [ ] **Expected:** Works in old version

---

## 6. Snapshot Management

### 6.1 View Snapshots (Developer/Advanced)
- [ ] Create .vaso project, make several saves
- [ ] Extract .vaso file (rename to .zip, unzip)
- [ ] Look inside: snapshots/ folder should contain multiple .sqlite files
- [ ] **Expected:** 000001.sqlite, 000002.sqlite, etc.
- [ ] **Expected:** HEAD.json points to latest

### 6.2 Snapshot Pruning
- [ ] Set "Keep last snapshots" to 5 in Preferences
- [ ] Create project, save 10 times (add data between saves)
- [ ] Extract .vaso and check snapshots/ folder
- [ ] **Expected:** Only 5 most recent snapshots remain

---

## 7. Cloud Storage Compatibility

### 7.1 Save to Dropbox/iCloud/OneDrive
- [ ] Create .vaso project
- [ ] Save to Dropbox/iCloud Drive/OneDrive folder
- [ ] Wait for sync to complete
- [ ] Make changes, save
- [ ] **Expected:** Sync indicator shows activity
- [ ] **Expected:** No conflicts or duplicate files created

### 7.2 Open from Cloud Storage
- [ ] Save .vaso project to cloud folder on Computer A
- [ ] Wait for sync
- [ ] On Computer B, open the same .vaso file from cloud folder
- [ ] **Expected:** Project opens correctly
- [ ] **Expected:** All data is intact

### 7.3 Simultaneous Edits (Conflict Test)
- [ ] Open same .vaso project on two computers simultaneously
- [ ] Edit on Computer A, save
- [ ] Edit on Computer B, save
- [ ] **Expected:** Cloud provider should detect conflict
- [ ] **Expected:** Conflict file created (depends on cloud provider)

---

## 8. Error Handling and Edge Cases

### 8.1 Disk Full Error
- [ ] Create .vaso project on drive with limited space
- [ ] Add large amount of data
- [ ] Try to save
- [ ] **Expected:** Clear error message about disk space

### 8.2 Corrupted File Recovery
- [ ] Create .vaso project, save
- [ ] Manually corrupt the .vaso file (edit with hex editor or truncate)
- [ ] Try to open
- [ ] **Expected:** Error message about corruption
- [ ] **Expected:** Option to recover if possible

### 8.3 Permission Denied
- [ ] Create .vaso project
- [ ] Change file permissions to read-only (chmod 444 on Unix)
- [ ] Try to save changes
- [ ] **Expected:** Clear error message about write permission

### 8.4 Read-Only Mode
- [ ] Open .vaso project from read-only location (CD, read-only network share)
- [ ] **Expected:** Opens in read-only mode
- [ ] Try to make changes
- [ ] **Expected:** Save is disabled or prompts for different location

---

## 9. Multi-Platform Testing

### 9.1 Cross-Platform File Transfer
- [ ] Create .vaso project on macOS
- [ ] Copy to Windows machine
- [ ] Open in VasoAnalyzer on Windows
- [ ] **Expected:** Opens correctly
- [ ] Make changes, save
- [ ] Copy back to macOS
- [ ] **Expected:** Opens with changes intact

### 9.2 Network File Shares
- [ ] Save .vaso project to SMB/NFS network share
- [ ] Open from network share
- [ ] Make changes, save multiple times
- [ ] **Expected:** No corruption or performance issues

---

## 10. Performance Benchmarks

### 10.1 Save Performance
- [ ] Small project (< 1 MB): ____ seconds
- [ ] Medium project (10 MB): ____ seconds
- [ ] Large project (100 MB): ____ seconds
- [ ] Very large project (1 GB): ____ seconds
- [ ] **Expected:** Linear scaling, no exponential slowdown

### 10.2 Open Performance
- [ ] Small project: ____ seconds
- [ ] Medium project: ____ seconds
- [ ] Large project: ____ seconds
- [ ] **Expected:** Opens in reasonable time (< 10s for typical project)

---

## 11. User Experience

### 11.1 First-Time User
- [ ] Launch VasoAnalyzer for first time
- [ ] Create new project
- [ ] **Expected:** Saves as .vaso by default
- [ ] File dialog is intuitive
- [ ] No confusing options

### 11.2 Existing User Upgrade
- [ ] User with old .vaso or .vasopack projects
- [ ] Open old project
- [ ] **Expected:** Seamless migration
- [ ] **Expected:** Clear messaging about format upgrade
- [ ] **Expected:** Legacy backup is kept

### 11.3 Help and Documentation
- [ ] Open Preferences
- [ ] Read help text under each setting
- [ ] **Expected:** Text is clear and helpful
- [ ] **Expected:** No typos or confusing language

---

## 12. Regression Testing

### 12.1 Existing Features Still Work
- [ ] Open old-format projects
- [ ] Import data from files
- [ ] Export data
- [ ] Analysis functions
- [ ] Plot rendering
- [ ] Event labeling
- [ ] **Expected:** All existing features work as before

### 12.2 No New Bugs
- [ ] Run through typical workflow
- [ ] No crashes
- [ ] No data loss
- [ ] No UI glitches
- [ ] Menus work correctly

---

## 13. Temp File Cleanup

### 13.1 Normal Session Cleanup
- [ ] Create .vaso project
- [ ] Save and close normally
- [ ] Check system temp directory (e.g., /tmp on Mac/Linux, %TEMP% on Windows)
- [ ] **Expected:** No VasoAnalyzer-container-* folders left behind

### 13.2 Crash Recovery Cleanup
- [ ] Open .vaso project
- [ ] Force quit app (without saving)
- [ ] Restart app
- [ ] Check system temp directory
- [ ] **Expected:** Stale temp folder is cleaned up after 24 hours (or configured time)

### 13.3 Manual Cleanup Button
- [ ] Preferences → Advanced → "Clean Up Temp Files Now"
- [ ] **Expected:** Success dialog with count of cleaned directories
- [ ] Check temp directory
- [ ] **Expected:** Old temp folders are gone

---

## 14. Stress Testing

### 14.1 Rapid Save/Open Cycles
- [ ] Create project, save, close
- [ ] Repeat 50 times in quick succession
- [ ] **Expected:** No crashes, no file corruption

### 14.2 Many Projects Open
- [ ] Open 10+ .vaso projects simultaneously
- [ ] Switch between them
- [ ] Make changes, save all
- [ ] **Expected:** No crashes, no data mixing between projects

### 14.3 Long-Running Session
- [ ] Open project
- [ ] Leave app running for several hours
- [ ] Make occasional changes
- [ ] **Expected:** Autosave continues working
- [ ] **Expected:** No memory leaks or slowdown

---

## 15. Accessibility

### 15.1 Screen Reader Compatibility
- [ ] Enable VoiceOver (macOS) or NVDA/JAWS (Windows)
- [ ] Navigate Preferences dialog
- [ ] **Expected:** All controls are announced correctly
- [ ] **Expected:** Tab order is logical

### 15.2 Keyboard-Only Usage
- [ ] Perform all operations without mouse
- [ ] Open project: Cmd+O, select file, Enter
- [ ] Save: Cmd+S
- [ ] Open Preferences: Cmd+,
- [ ] Navigate tabs: Ctrl+Tab
- [ ] **Expected:** Everything is keyboard-accessible

### 15.3 High Contrast Mode
- [ ] Enable high contrast or dark mode
- [ ] Open Preferences dialog
- [ ] **Expected:** Text is readable
- [ ] **Expected:** Borders and controls are visible

---

## Issues Found

| # | Date | Issue Description | Severity | Platform | Status |
|---|------|-------------------|----------|----------|--------|
| 1 | | | ☐ Critical ☐ Major ☐ Minor | | ☐ Open ☐ Fixed |
| 2 | | | ☐ Critical ☐ Major ☐ Minor | | ☐ Open ☐ Fixed |
| 3 | | | ☐ Critical ☐ Major ☐ Minor | | ☐ Open ☐ Fixed |
| 4 | | | ☐ Critical ☐ Major ☐ Minor | | ☐ Open ☐ Fixed |
| 5 | | | ☐ Critical ☐ Minor ☐ Minor | | ☐ Open ☐ Fixed |

---

## Testing Summary

**Total Test Cases:** 100+
**Passed:** ____
**Failed:** ____
**Skipped:** ____

**Overall Status:**
☐ **PASS** - Ready for release
☐ **PASS WITH MINOR ISSUES** - Can release with known minor bugs
☐ **FAIL** - Critical issues found, do not release

**Notes:**
_______________________________________________________________________
_______________________________________________________________________
_______________________________________________________________________

**Tester Signature:** _____________________ **Date:** ______________
