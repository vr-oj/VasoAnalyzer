# VasoAnalyzer Excel Template Setup Guide

## Overview

VasoAnalyzer can map event data to **self-describing Excel templates** that use VBA macros to expose their structure. This makes templates resilient to user modifications and eliminates manual configuration.

## Benefits of Macro-Enabled Templates

✅ **Auto-discovery** - Template describes its own structure
✅ **Self-validating** - Checks for structural issues on open
✅ **User-proof** - Guides users to add rows/columns safely
✅ **Lab-friendly** - Each lab can customize without breaking compatibility
✅ **Backwards compatible** - Falls back to named ranges if macros disabled

---

## Quick Start

### Option 1: Use the Provided Template

1. Download `VasoAnalyzer_Template.xlsm` from the templates folder
2. Enable macros when opening (click "Enable Content")
3. Customize event rows and date columns as needed
4. Use with VasoAnalyzer Excel Mapping wizard

### Option 2: Convert Existing Template

Follow the steps below to add VasoAnalyzer support to your existing Excel template.

---

## Step-by-Step: Creating a Smart Template

### 1. Enable Developer Tab in Excel

**Windows:**
1. File → Options → Customize Ribbon
2. Check "Developer" in right column
3. Click OK

**macOS:**
1. Excel → Preferences → Ribbon & Toolbar
2. Check "Developer" tab
3. Click Save

### 2. Save as Macro-Enabled Workbook

1. File → Save As
2. Choose format: **Excel Macro-Enabled Workbook (.xlsm)**
3. Save with descriptive name (e.g., `MyLab_VasoTemplate.xlsm`)

### 3. Open VBA Editor

- **Windows**: Press `Alt + F11`
- **macOS**: Press `Option + F11`

### 4. Insert VasoAnalyzer Module

1. In VBA Editor: Insert → Module
2. Copy and paste the **VasoAnalyzer VBA Code** (see below)
3. Save the workbook

### 5. Configure Your Template Structure

Edit the `GetVasoConfig()` function to describe your template:

```vb
' CUSTOMIZE THESE VALUES FOR YOUR TEMPLATE
EventRowsStart = 3          ' First event data row
EventRowsEnd = 25           ' Last event data row
DateRow = 2                 ' Row containing date headers
DateColumnsStart = 2        ' First date column (B)
DateColumnsEnd = 26         ' Last date column (Z)
LabelColumn = 1             ' Column with event labels (A)
```

### 6. Test the Template

1. Close VBA Editor
2. In Excel: Developer tab → Macros
3. Run `ValidateTemplate` macro
4. Check output in "VasoMetadata" sheet (auto-created)

---

## VasoAnalyzer VBA Code

Copy this entire code block into a new VBA module:

```vb
' ============================================================================
' VasoAnalyzer Template Integration
' Version 1.0
'
' This module makes Excel templates self-describing for VasoAnalyzer.
' The template structure is exposed via JSON metadata that VasoAnalyzer reads.
' ============================================================================

Option Explicit

' ----------------------------------------------------------------------------
' CONFIGURATION FUNCTION - CUSTOMIZE THIS FOR YOUR TEMPLATE
' ----------------------------------------------------------------------------
Public Function GetVasoConfig() As Object
    ' Create configuration dictionary
    Dim config As Object
    Set config = CreateObject("Scripting.Dictionary")

    ' --- CUSTOMIZE THESE VALUES ---
    Dim EventRowsStart As Long, EventRowsEnd As Long
    Dim DateRow As Long
    Dim DateColumnsStart As Long, DateColumnsEnd As Long
    Dim LabelColumn As Long

    EventRowsStart = 3          ' First row with event data
    EventRowsEnd = 25           ' Last possible event row
    DateRow = 2                 ' Row containing date headers
    DateColumnsStart = 2        ' First date column (B = 2)
    DateColumnsEnd = 26         ' Last date column (Z = 26)
    LabelColumn = 1             ' Column with event labels (A = 1)

    ' Store in config
    config("event_rows_start") = EventRowsStart
    config("event_rows_end") = EventRowsEnd
    config("date_row") = DateRow
    config("date_columns_start") = DateColumnsStart
    config("date_columns_end") = DateColumnsEnd
    config("label_column") = LabelColumn
    config("template_version") = "1.0"
    config("template_name") = ActiveWorkbook.Name

    Set GetVasoConfig = config
End Function

' ----------------------------------------------------------------------------
' METADATA EXPORT - Writes JSON metadata for VasoAnalyzer to read
' ----------------------------------------------------------------------------
Public Sub ExportMetadata()
    Dim config As Object
    Dim ws As Worksheet
    Dim metadataSheet As Worksheet
    Dim json As String
    Dim eventRows As Collection
    Dim dateColumns As Collection

    Set config = GetVasoConfig()
    Set ws = ActiveSheet

    ' Detect event rows
    Set eventRows = DetectEventRows(ws, config)

    ' Detect date columns
    Set dateColumns = DetectDateColumns(ws, config)

    ' Build JSON
    json = "{"
    json = json & """version"": ""1.0"","
    json = json & """template_name"": """ & EscapeJSON(config("template_name")) & ""","
    json = json & """date_row"": " & config("date_row") & ","
    json = json & """label_column"": " & config("label_column") & ","
    json = json & """event_rows"": [" & FormatEventRowsJSON(eventRows) & "],"
    json = json & """date_columns"": [" & FormatDateColumnsJSON(dateColumns) & "]"
    json = "}"

    ' Write to hidden metadata sheet
    On Error Resume Next
    Set metadataSheet = ThisWorkbook.Sheets("VasoMetadata")
    On Error GoTo 0

    If metadataSheet Is Nothing Then
        Set metadataSheet = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        metadataSheet.Name = "VasoMetadata"
        metadataSheet.Visible = xlSheetVeryHidden  ' Hide from users
    End If

    metadataSheet.Cells.Clear
    metadataSheet.Range("A1").Value = "VasoAnalyzer Template Metadata"
    metadataSheet.Range("A2").Value = "Last Updated: " & Now
    metadataSheet.Range("A4").Value = json

    ' Also store in custom document properties
    Call StoreInCustomProperties(json)

    MsgBox "Metadata exported successfully!" & vbCrLf & vbCrLf & "VasoAnalyzer can now auto-configure from this template.", vbInformation
End Sub

' ----------------------------------------------------------------------------
' EVENT ROW DETECTION
' ----------------------------------------------------------------------------
Private Function DetectEventRows(ws As Worksheet, config As Object) As Collection
    Dim rows As New Collection
    Dim r As Long
    Dim cell As Range
    Dim isHeader As Boolean
    Dim rowInfo As Object

    For r = config("event_rows_start") To config("event_rows_end")
        Set cell = ws.Cells(r, config("label_column"))

        ' Skip empty rows
        If Len(Trim(cell.Value)) = 0 Then GoTo NextRow

        ' Check if header (bold + filled background)
        isHeader = False
        If cell.Font.Bold And cell.Interior.Pattern <> xlNone Then
            isHeader = True
        End If

        ' Create row info
        Set rowInfo = CreateObject("Scripting.Dictionary")
        rowInfo("row") = r
        rowInfo("label") = Trim(cell.Value)
        rowInfo("is_header") = isHeader

        rows.Add rowInfo
NextRow:
    Next r

    Set DetectEventRows = rows
End Function

' ----------------------------------------------------------------------------
' DATE COLUMN DETECTION
' ----------------------------------------------------------------------------
Private Function DetectDateColumns(ws As Worksheet, config As Object) As Collection
    Dim cols As New Collection
    Dim c As Long
    Dim cell As Range
    Dim colInfo As Object
    Dim emptySlots As Long
    Dim r As Long

    For c = config("date_columns_start") To config("date_columns_end")
        Set cell = ws.Cells(config("date_row"), c)

        ' Count empty slots below this date header
        emptySlots = 0
        For r = config("event_rows_start") To config("event_rows_end")
            If Len(Trim(ws.Cells(r, c).Value)) = 0 Then
                emptySlots = emptySlots + 1
            End If
        Next r

        ' Create column info
        Set colInfo = CreateObject("Scripting.Dictionary")
        colInfo("column") = c
        colInfo("letter") = ColumnLetter(c)
        colInfo("value") = cell.Value
        colInfo("empty_slots") = emptySlots

        cols.Add colInfo
    Next c

    Set DetectDateColumns = cols
End Function

' ----------------------------------------------------------------------------
' VALIDATION - Check template structure
' ----------------------------------------------------------------------------
Public Sub ValidateTemplate()
    Dim config As Object
    Dim ws As Worksheet
    Dim eventRows As Collection
    Dim errors As String

    Set config = GetVasoConfig()
    Set ws = ActiveSheet
    Set eventRows = DetectEventRows(ws, config)

    errors = ""

    ' Check for event rows
    If eventRows.Count = 0 Then
        errors = errors & "- No event rows detected" & vbCrLf
    End If

    ' Check date row exists
    If ws.Cells(config("date_row"), config("date_columns_start")).Value = "" Then
        errors = errors & "- Date row appears empty" & vbCrLf
    End If

    ' Check label column exists
    If ws.Cells(config("event_rows_start"), config("label_column")).Value = "" Then
        errors = errors & "- Label column appears empty" & vbCrLf
    End If

    If Len(errors) > 0 Then
        MsgBox "Template validation found issues:" & vbCrLf & vbCrLf & errors, vbExclamation
    Else
        MsgBox "Template structure is valid!" & vbCrLf & vbCrLf & _
               "Detected " & eventRows.Count & " event rows.", vbInformation

        ' Auto-export metadata on successful validation
        Call ExportMetadata
    End If
End Sub

' ----------------------------------------------------------------------------
' HELPER FUNCTIONS
' ----------------------------------------------------------------------------
Private Function ColumnLetter(col As Long) As String
    ColumnLetter = Split(Cells(1, col).Address, "$")(1)
End Function

Private Function EscapeJSON(s As String) As String
    s = Replace(s, "\", "\\")
    s = Replace(s, """", "\""")
    s = Replace(s, vbCrLf, "\n")
    s = Replace(s, vbCr, "\n")
    s = Replace(s, vbLf, "\n")
    EscapeJSON = s
End Function

Private Function FormatEventRowsJSON(rows As Collection) As String
    Dim json As String
    Dim row As Object
    Dim first As Boolean

    first = True
    For Each row In rows
        If Not first Then json = json & ","
        json = json & "{"
        json = json & """row"": " & row("row") & ","
        json = json & """label"": """ & EscapeJSON(row("label")) & ""","
        json = json & """is_header"": " & IIf(row("is_header"), "true", "false")
        json = json & "}"
        first = False
    Next

    FormatEventRowsJSON = json
End Function

Private Function FormatDateColumnsJSON(cols As Collection) As String
    Dim json As String
    Dim col As Object
    Dim first As Boolean

    first = True
    For Each col In cols
        If Not first Then json = json & ","
        json = json & "{"
        json = json & """column"": " & col("column") & ","
        json = json & """letter"": """ & col("letter") & ""","
        json = json & """value"": """ & EscapeJSON(CStr(col("value"))) & ""","
        json = json & """empty_slots"": " & col("empty_slots")
        json = json & "}"
        first = False
    Next

    FormatDateColumnsJSON = json
End Function

Private Sub StoreInCustomProperties(json As String)
    Dim props As Object
    Dim propName As String

    propName = "VasoAnalyzerMetadata"
    Set props = ThisWorkbook.CustomDocumentProperties

    ' Delete existing property if present
    On Error Resume Next
    props(propName).Delete
    On Error GoTo 0

    ' Add new property (max 255 chars, so we use the sheet instead for full JSON)
    ' This is just a flag that metadata exists
    props.Add Name:=propName, LinkToContent:=False, _
              Type:=msoPropertyTypeString, Value:="v1.0"
End Sub

' ----------------------------------------------------------------------------
' AUTO-RUN ON OPEN (Optional)
' ----------------------------------------------------------------------------
' Uncomment to auto-export metadata when workbook opens
'
' Private Sub Workbook_Open()
'     Call ExportMetadata
' End Sub
```

---

## Using the Template

### For End Users (Lab Members)

1. **Open template** - Double-click `.xlsm` file
2. **Enable macros** - Click "Enable Content" if prompted
3. **Customize safely**:
   - ✅ Add/remove event rows (plain text in column A)
   - ✅ Change date column labels (row 2)
   - ✅ Modify formulas in data cells
   - ❌ Don't move the date row or label column
   - ❌ Don't delete the VasoMetadata sheet

4. **Validate changes**:
   - Developer → Macros → ValidateTemplate
   - Or: Press `Alt + F8` (Windows) / `Option + F8` (macOS), run ValidateTemplate

### For VasoAnalyzer Users

1. In VasoAnalyzer Excel Mapping wizard
2. Load the `.xlsm` template
3. **Auto-configuration happens** - structure detected automatically
4. Map events as normal - wizard now understands your template perfectly

---

## Troubleshooting

### "Macros have been disabled"

**Windows:**
- File → Options → Trust Center → Trust Center Settings
- Macro Settings → Enable all macros (or "Disable with notification")

**macOS:**
- Excel → Preferences → Security & Privacy
- Macro Security → Enable all macros

### Template validation fails

- Verify event rows start at the configured row
- Ensure date row contains headers
- Check that label column (A) has event labels
- Make sure event rows use plain text (not bold+filled for non-headers)

### Metadata not detected by VasoAnalyzer

1. Run `ExportMetadata` macro manually
2. Save the workbook
3. Check "VasoMetadata" sheet exists
4. Ensure file is `.xlsm` format, not `.xlsx`

---

## Advanced: Custom Template Validation

Add custom validation rules to the `ValidateTemplate()` function:

```vb
' Check for specific event labels
Dim requiredEvents As Variant
requiredEvents = Array("Baseline", "PSS", "Recovery")

Dim found As Boolean
Dim req As Variant
For Each req In requiredEvents
    found = False
    For Each row In eventRows
        If InStr(1, row("label"), req, vbTextCompare) > 0 Then
            found = True
            Exit For
        End If
    Next
    If Not found Then
        errors = errors & "- Required event '" & req & "' not found" & vbCrLf
    End If
Next
```

---

## Template Distribution

### For Lab Managers

1. Create master template with lab-specific structure
2. Test with VasoAnalyzer
3. Distribute `.xlsm` file to lab members
4. Provide brief training on macro security settings

### Version Control

- Include template version in filename: `LabName_Template_v1.2.xlsm`
- Document changes in template comments
- Keep metadata updated with `ExportMetadata` macro

---

## Security Notes

- ⚠️ Only use templates from trusted sources
- VBA macros can be a security risk if from unknown sources
- VasoAnalyzer reads metadata **without executing macros** when possible
- Macro execution is only needed for template setup/validation

---

## Next Steps

1. ✅ Set up your first template using this guide
2. ✅ Test with VasoAnalyzer Excel Mapping wizard
3. ✅ Customize for your lab's workflow
4. ✅ Share template with lab members

Questions? See main VasoAnalyzer documentation or contact support.
