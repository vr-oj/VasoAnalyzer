# Testing Guide: Embedded Events Fix

## What Was Fixed

We fixed the issue where events weren't loading from embedded data on project reopen. The root cause was that `ProjectContext` wasn't being created when opening projects, so background jobs had to create their own context (and thus a different staging database).

## Files Modified

1. **src/vasoanalyzer/app/openers.py** - Added comprehensive logging to `open_project_file()`
2. **src/vasoanalyzer/ui/main_window.py** - Fixed `open_recent_project()` method (line 3581) and added logging to background job
3. **src/vasoanalyzer/ui/mixins/project_mixin.py** - Fixed `open_recent_project()` method (line 1350)

## How to Test

### 1. Run the Verification Script

```bash
python3 test_embedded_events.py
```

This will verify that the fix is in place (but won't test the full workflow).

### 2. Manual Testing Workflow

**First Run (Create Project):**
```bash
python3 src/main.py
```

1. Create a new project
2. Import data with events
3. Close the app

**Second Run (Reopen Project):**
```bash
python3 src/main.py 2>&1 | grep -E "(📂|🔑|✅|🚨|⚠️)" | tee test_output.log
```

## What to Look For in Logs

### ✅ GOOD SIGNS (Fix Working)

When reopening the project, you should see:

```
📂 open_project_file called with path: /path/to/project.vaso
🔑 Creating ProjectContext for: /path/to/project.vaso
✅ ProjectContext created successfully: ProjectContext(...)
✅ ProjectContext attached to window
   window.project_ctx = ProjectContext(...)
   window.project_ctx.repo = <vasoanalyzer.services.project_service.SQLiteProjectRepository object>
```

Then when loading samples:

```
🔍 load_sample_into_view: ctx type = <class 'vasoanalyzer.core.project_context.ProjectContext'>
🔍 load_sample_into_view: repo = <vasoanalyzer.services.project_service.SQLiteProjectRepository object>
✅ Background job: Using EXISTING repo from window.project_ctx
   EXISTING staging DB files: [(0, 'main', '/var/folders/.../bundle/.staging/XXXXX.sqlite')]
🔍 Background job: Loading events for dataset_id=1
✅ Successfully loaded 15 event rows
```

### ❌ BAD SIGNS (Fix NOT Working)

If you see these, the fix isn't working:

```
🔍 load_sample_into_view: ctx type = <class 'NoneType'>, ctx = None
🔍 load_sample_into_view: repo = None
⚠️  Background job will create a NEW project context, which means a NEW staging database!
🚨 Background job: repo is None! Creating new context...
⚠️  Created NEW context: ProjectContext(...)
   NEW staging DB files: [(0, 'main', '/var/folders/.../bundle/.staging/YYYYY.sqlite')]
```

Notice:
- `ctx` is `None` ❌
- `repo` is `None` ❌
- Background job creates NEW context ❌
- Different staging DB file (YYYYY vs XXXXX) ❌

## Expected Results

### First Run (Create Project)

- Events embedded: ✅ (verified by logs showing "15 events now in database")
- ProjectContext: ⚠️ None (expected, not needed during initial creation)
- Events load from: 📊 Memory (events_data DataFrame)

### Second Run (Reopen Project)

- Events embedded: ✅ (already in database from first run)
- ProjectContext: ✅ Created by `open_project_file()`
- Events load from: 🗄️ **Embedded database** (same staging DB)

## Troubleshooting

If logs show `ctx = None` after reopen:

1. Check if `open_project_file()` was actually called:
   ```bash
   grep "📂 open_project_file" test_output.log
   ```

2. Check if there's an exception during ProjectContext creation:
   ```bash
   grep -A5 "🔑 Creating ProjectContext" test_output.log
   ```

3. Check if `open_recent_project()` is calling `open_project_file()`:
   ```bash
   grep "open_recent_project" test_output.log
   ```

## Success Criteria

The fix is working if:

1. ✅ After reopening project, logs show ProjectContext was created
2. ✅ After reopening project, logs show `ctx type = <class '...ProjectContext'>`
3. ✅ When loading samples, logs show "Using EXISTING repo"
4. ✅ Same staging DB file is used throughout the session
5. ✅ Events load successfully from embedded data (no "file is not a database" error)

## Quick Test Command

Run this single command to test everything:

```bash
# Delete old project if exists
rm -f "/Users/valdovegarodr/Documents/VasoAnalyzer Files/TestProjectSavingPath.vaso"

# First run: Create and populate
python3 src/main.py 2>&1 | grep -E "(📂|🔑|✅|📝|🔍)" > first_run.log &
# (manually create project, import data, close)

# Second run: Reopen and verify
python3 src/main.py 2>&1 | grep -E "(📂|🔑|✅|🚨|⚠️|🔍)" > second_run.log &
# (manually open project, select samples)

# Check results
echo "=== FIRST RUN (should show events embedded) ==="
grep "📝 Prepared.*event rows" first_run.log
echo ""
echo "=== SECOND RUN (should show ProjectContext created and used) ==="
grep "📂 open_project_file" second_run.log
grep "✅ ProjectContext" second_run.log
grep -E "(Using EXISTING|repo is None)" second_run.log
```
