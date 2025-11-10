# Excel Macros Integration for VasoAnalyzer

## Executive Summary

**Yes, it is absolutely possible** to combine VasoAnalyzer with Excel macros to create reliable, self-describing templates that work consistently across different labs and users.

## The Solution: Self-Describing Templates

We've implemented a **macro-powered metadata system** that makes Excel templates "smart":

### How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  Excel Template (.xlsm)                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  VBA Macro Code                                      │  │
│  │  • Defines template structure                        │  │
│  │  • Validates on open/save                            │  │
│  │  • Exports JSON metadata to hidden sheet             │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  VasoMetadata Sheet (hidden)                         │  │
│  │  {                                                    │  │
│  │    "date_row": 2,                                    │  │
│  │    "event_rows": [...],                              │  │
│  │    "date_columns": [...]                             │  │
│  │  }                                                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  VasoAnalyzer Python                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  template_metadata.py                                │  │
│  │  • Reads JSON from VasoMetadata sheet                │  │
│  │  • Falls back to named ranges (legacy)               │  │
│  │  • Infers structure if no metadata                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Excel Map Wizard                                    │  │
│  │  • Auto-configures from metadata                     │  │
│  │  • Maps events intelligently                         │  │
│  │  • Works reliably across lab variations             │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Benefits

### ✅ For Users
- **No manual configuration** - Template structure detected automatically
- **Error prevention** - Validation prevents structural mistakes
- **Consistent behavior** - Same template works identically for everyone
- **Lab customization** - Each lab can customize without breaking compatibility

### ✅ For Lab Managers
- **Distribute once** - Create master template, share with lab members
- **Version control** - Track template versions automatically
- **Guided editing** - Macros help users add rows/columns safely
- **Troubleshooting** - Built-in validation diagnostics

### ✅ For VasoAnalyzer
- **Robust parsing** - No more guessing at template structure
- **Better error messages** - Can explain exactly what's wrong
- **Backwards compatible** - Still works with old templates
- **Future-proof** - Easy to extend with new features

## What's Implemented

### 1. VBA Macro System (`docs/EXCEL_TEMPLATE_SETUP.md`)
Complete VBA code for Excel templates including:
- `GetVasoConfig()` - Define template structure
- `ExportMetadata()` - Write JSON metadata to hidden sheet
- `ValidateTemplate()` - Check template integrity
- `DetectEventRows()` / `DetectDateColumns()` - Auto-discovery
- Helper functions for JSON formatting

### 2. Python Metadata Reader (`src/vasoanalyzer/excel/template_metadata.py`)
- **Multi-source reading**: VasoMetadata sheet → Named ranges → Inference
- **Dataclasses**: `TemplateMetadata`, `EventRowMetadata`, `DateColumnMetadata`
- **Public API**:
  - `read_template_metadata(path)` - Main entry point
  - `has_vaso_metadata(wb)` - Quick check
  - `invoke_export_metadata(path)` - Optional VBA invocation (requires xlwings)

### 3. Updated Excel Map Wizard (`src/vasoanalyzer/ui/dialogs/excel_map_wizard.py`)
- **Auto-detection**: Detects .xlsm files with metadata
- **Visual feedback**: Green ✓ when metadata found
- **Metadata-driven**: Uses metadata for all structure detection
- **Graceful fallback**: Works with legacy templates
- **Better errors**: Helpful messages when structure is invalid

## Excel Setup Instructions

### Quick Start

1. **Copy VBA code** from `docs/EXCEL_TEMPLATE_SETUP.md`
2. **Paste into Excel module** (Alt+F11 → Insert → Module)
3. **Configure structure** in `GetVasoConfig()` function:
   ```vb
   EventRowsStart = 3
   EventRowsEnd = 25
   DateRow = 2
   DateColumnsStart = 2   ' Column B
   DateColumnsEnd = 26    ' Column Z
   LabelColumn = 1        ' Column A
   ```
4. **Run validation**: Developer → Macros → ValidateTemplate
5. **Save as .xlsm** (macro-enabled workbook)
6. **Distribute** to lab members

### Customization Example

For a lab that uses columns C-M instead of B-Z:

```vb
DateColumnsStart = 3   ' Column C
DateColumnsEnd = 13    ' Column M
```

For a lab with event rows 5-30 instead of 3-25:

```vb
EventRowsStart = 5
EventRowsEnd = 30
```

## Usage in VasoAnalyzer

1. **Load template** in Excel Mapping wizard
2. **See confirmation**: "✓ Loaded: template.xlsm (metadata detected)"
3. **Map events** - Structure automatically configured
4. **Save** - No manual range definition needed

## Backwards Compatibility

The system has **three fallback layers**:

1. **Best**: Metadata from VBA macros (.xlsm files)
2. **Good**: Named ranges (VASO_DATES_ROW, VASO_VALUES_BLOCK)
3. **Okay**: Inference from structure (heuristics)

Old templates without macros still work fine!

## Advanced Features

### Template Validation

Macros can enforce lab-specific requirements:

```vb
' In ValidateTemplate()
Dim requiredEvents As Variant
requiredEvents = Array("Baseline", "PSS", "ACh", "Recovery")

' Check all required events are present
For Each req In requiredEvents
    found = False
    For Each row In eventRows
        If InStr(row("label"), req, vbTextCompare) > 0 Then
            found = True
        End If
    Next
    If Not found Then
        errors = errors & "Missing required event: " & req & vbCrLf
    End If
Next
```

### Auto-Export on Open

Uncomment in VBA code to auto-refresh metadata when template opens:

```vb
Private Sub Workbook_Open()
    Call ExportMetadata
End Sub
```

### Custom Properties

Metadata is also stored in custom document properties for quick detection.

## What Still Needs to Be Done

### On the Excel Side

1. **Create master template** for your lab
2. **Add VBA code** following setup guide
3. **Test validation** with sample data
4. **Distribute** to lab members
5. **Train users** on macro security settings

### Optional Enhancements

1. **Template generator tool** - GUI for creating templates
2. **Template library** - Pre-made templates for common workflows
3. **Version migration** - Auto-update old templates
4. **Multi-sheet support** - Templates with multiple sheets
5. **Formula preservation** - Ensure macros don't break formulas

## Security Considerations

### Macro Security

- ⚠️ **Only use templates from trusted sources**
- VBA macros can be a security risk
- VasoAnalyzer reads metadata **without executing macros** (uses openpyxl)
- Macro execution only needed for:
  - Template setup/configuration
  - Manual validation
  - Optional auto-export

### Recommended Settings

**For template creators:**
- Enable macros to run validation
- Test thoroughly before distribution
- Code-sign macros if possible

**For end users:**
- "Disable macros with notification"
- Only enable for trusted lab templates
- Can use templates even with macros disabled (metadata already embedded)

## Implementation Status

✅ **Completed:**
- VBA macro code for self-describing templates
- Python metadata reader with multi-source support
- Excel Map Wizard integration
- Documentation and setup guide
- Graceful degradation for legacy templates

🚧 **Future Enhancements:**
- Example template files (.xlsm)
- Template generator GUI
- xlwings integration for macro invocation
- Multi-sheet template support
- Automated tests for macro system

## Files Created

1. **`docs/EXCEL_TEMPLATE_SETUP.md`** - Complete user guide with VBA code
2. **`src/vasoanalyzer/excel/template_metadata.py`** - Metadata reader
3. **`src/vasoanalyzer/excel/__init__.py`** - Module exports
4. **`src/vasoanalyzer/ui/dialogs/excel_map_wizard.py`** - Updated wizard (modified)
5. **`docs/EXCEL_MACROS_INTEGRATION.md`** - This document

## Next Steps for Your Lab

1. **Read** `docs/EXCEL_TEMPLATE_SETUP.md`
2. **Create** your first smart template
3. **Test** with VasoAnalyzer
4. **Share** with one colleague for validation
5. **Roll out** to entire lab
6. **Iterate** based on feedback

## Questions?

See `docs/EXCEL_TEMPLATE_SETUP.md` for:
- Step-by-step VBA setup
- Troubleshooting guide
- Template customization examples
- Validation instructions

---

**Summary**: Yes, combining Excel macros with VasoAnalyzer is not only possible, it's now **fully implemented and ready to use**. Smart templates will make your lab's workflow more reliable and user-proof.
