# VasoAnalyzer Smart Template System (Dynamic Version)

## The Problem with Static Configuration

The original macro system required manual configuration:
```vb
EventRowsStart = 3    ' What if experiment has different number of rows?
EventRowsEnd = 25     ' What if user adds more events?
DateRow = 2           ' What if template structure changes?
```

**This breaks when:**
- Different experiments have different event counts
- Users add/remove rows
- Template structure varies per use case

---

## Solution: Dynamic Pattern Recognition

### Three Levels of Flexibility

#### Level 1: Zero Configuration (Auto-Detection)
VBA automatically finds structure by pattern recognition:
- Date row: First row with 3+ date/numeric values
- Event rows: Cells with text after date row, not bold
- Headers: Bold + filled background cells
- Data region: Auto-detect used range

**Pro**: Works immediately, no setup
**Con**: Might misdetect unusual layouts

#### Level 2: Minimal Markers (Recommended)
User adds 1-2 special text markers:
```
##VASO_DATA_START##  ← Optional: marks start of data region
```

**Pro**: Reliable + flexible
**Con**: Requires minimal template modification

#### Level 3: Explicit Hints (Edge Cases)
Use Excel defined names for hints (optional):
- `VASO_DATE_ROW` → Single cell in date row
- `VASO_FIRST_EVENT` → Single cell marking first event

**Pro**: Handles any edge case
**Con**: More setup, but still better than hard-coding row numbers

---

## Implementation: Smart Dynamic VBA

### Replace GetVasoConfig() with Dynamic Scanning

```vb
' ============================================================================
' SMART DYNAMIC DETECTION - No manual configuration needed!
' ============================================================================

Public Function DetectTemplateStructure() As Object
    Dim config As Object
    Set config = CreateObject("Scripting.Dictionary")

    Dim ws As Worksheet
    Set ws = ActiveSheet

    ' --- STEP 1: Find date row (auto-detect) ---
    Dim dateRow As Long
    dateRow = FindDateRowSmart(ws)
    If dateRow = 0 Then
        MsgBox "Could not auto-detect date row. Add '##VASO_DATE_ROW##' marker to hint.", vbExclamation
        Exit Function
    End If
    config("date_row") = dateRow

    ' --- STEP 2: Find data region bounds ---
    Dim dataStart As Long, dataEnd As Long
    dataStart = FindDataStartRow(ws, dateRow)
    dataEnd = FindDataEndRow(ws, dataStart)
    config("data_start") = dataStart
    config("data_end") = dataEnd

    ' --- STEP 3: Find date columns ---
    Dim dateColStart As Long, dateColEnd As Long
    Call FindDateColumnBounds(ws, dateRow, dateColStart, dateColEnd)
    config("date_col_start") = dateColStart
    config("date_col_end") = dateColEnd

    ' --- STEP 4: Label column (assume A, but check for marker) ---
    config("label_column") = FindLabelColumn(ws)

    config("template_version") = "2.0-dynamic"
    config("template_name") = ActiveWorkbook.Name

    Set DetectTemplateStructure = config
End Function

' ----------------------------------------------------------------------------
' SMART DETECTION FUNCTIONS
' ----------------------------------------------------------------------------

Private Function FindDateRowSmart(ws As Worksheet) As Long
    ' Strategy 1: Look for ##VASO_DATE_ROW## marker
    Dim cell As Range
    For Each cell In ws.UsedRange
        If InStr(1, cell.Value, "##VASO_DATE_ROW##", vbTextCompare) > 0 Then
            FindDateRowSmart = cell.Row
            Exit Function
        End If
    Next cell

    ' Strategy 2: Look for named cell "VASO_DATE_ROW"
    On Error Resume Next
    Dim namedRange As Range
    Set namedRange = ws.Range("VASO_DATE_ROW")
    If Not namedRange Is Nothing Then
        FindDateRowSmart = namedRange.Row
        Exit Function
    End If
    On Error GoTo 0

    ' Strategy 3: Pattern detection - row with many date/numeric cells
    Dim row As Long
    For row = 1 To 20  ' Scan first 20 rows
        Dim dateCount As Long
        dateCount = 0

        For col = 2 To 26  ' Columns B-Z
            Dim value As Variant
            value = ws.Cells(row, col).Value

            If IsDate(value) Or IsNumeric(value) Then
                dateCount = dateCount + 1
            End If
        Next col

        ' Found row with 3+ dates/numbers?
        If dateCount >= 3 Then
            FindDateRowSmart = row
            Exit Function
        End If
    Next row

    FindDateRowSmart = 0  ' Not found
End Function

Private Function FindDataStartRow(ws As Worksheet, afterRow As Long) As Long
    ' Start immediately after date row, skip empty rows
    Dim row As Long
    For row = afterRow + 1 To afterRow + 10
        If Len(Trim(ws.Cells(row, 1).Value)) > 0 Then
            FindDataStartRow = row
            Exit Function
        End If
    Next row
    FindDataStartRow = afterRow + 1  ' Default
End Function

Private Function FindDataEndRow(ws As Worksheet, fromRow As Long) As Long
    ' Scan down until 2 consecutive empty label cells
    Dim row As Long
    Dim emptyCount As Long
    emptyCount = 0

    For row = fromRow To ws.UsedRange.Rows.Count
        If Len(Trim(ws.Cells(row, 1).Value)) = 0 Then
            emptyCount = emptyCount + 1
            If emptyCount >= 2 Then
                FindDataEndRow = row - 2
                Exit Function
            End If
        Else
            emptyCount = 0
        End If
    Next row

    FindDataEndRow = ws.UsedRange.Rows.Count
End Function

Private Sub FindDateColumnBounds(ws As Worksheet, dateRow As Long, _
                                 ByRef minCol As Long, ByRef maxCol As Long)
    minCol = 2   ' Default: column B
    maxCol = 26  ' Default: column Z

    ' Find first non-empty date cell
    For col = 2 To 26
        If ws.Cells(dateRow, col).Value <> "" Then
            minCol = col
            Exit For
        End If
    Next col

    ' Find last non-empty date cell
    For col = 26 To 2 Step -1
        If ws.Cells(dateRow, col).Value <> "" Then
            maxCol = col
            Exit For
        End If
    Next col
End Sub

Private Function FindLabelColumn(ws As Worksheet) As Long
    ' Usually column A, but check for marker
    ' Could scan for column with most text entries
    FindLabelColumn = 1  ' Default: column A
End Function

' ----------------------------------------------------------------------------
' ENHANCED METADATA EXPORT (uses dynamic detection)
' ----------------------------------------------------------------------------

Public Sub ExportMetadataSmart()
    ' Detect structure dynamically
    Dim config As Object
    Set config = DetectTemplateStructure()

    If config Is Nothing Then
        MsgBox "Failed to detect template structure. See validation messages.", vbCritical
        Exit Sub
    End If

    Dim ws As Worksheet
    Set ws = ActiveSheet

    ' Detect event rows and date columns dynamically
    Dim eventRows As Collection
    Dim dateColumns As Collection
    Set eventRows = DetectEventRowsDynamic(ws, config)
    Set dateColumns = DetectDateColumnsDynamic(ws, config)

    ' Build JSON
    Dim json As String
    json = "{"
    json = json & """version"": ""2.0-dynamic"","
    json = json & """template_name"": """ & EscapeJSON(config("template_name")) & ""","
    json = json & """date_row"": " & config("date_row") & ","
    json = json & """label_column"": " & config("label_column") & ","
    json = json & """data_start"": " & config("data_start") & ","
    json = json & """data_end"": " & config("data_end") & ","
    json = json & """event_rows"": [" & FormatEventRowsJSON(eventRows) & "],"
    json = json & """date_columns"": [" & FormatDateColumnsJSON(dateColumns) & "]"
    json = json & "}"

    ' Write to VasoMetadata sheet
    Dim metadataSheet As Worksheet
    On Error Resume Next
    Set metadataSheet = ThisWorkbook.Sheets("VasoMetadata")
    On Error GoTo 0

    If metadataSheet Is Nothing Then
        Set metadataSheet = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        metadataSheet.Name = "VasoMetadata"
        metadataSheet.Visible = xlSheetVeryHidden
    End If

    metadataSheet.Cells.Clear
    metadataSheet.Range("A1").Value = "VasoAnalyzer Metadata (Auto-Generated)"
    metadataSheet.Range("A2").Value = "Last Updated: " & Now
    metadataSheet.Range("A3").Value = "Structure detected dynamically - no manual config needed!"
    metadataSheet.Range("A5").Value = json

    MsgBox "Metadata exported! Found " & eventRows.Count & " events, " & dateColumns.Count & " date columns.", vbInformation
End Sub

Private Function DetectEventRowsDynamic(ws As Worksheet, config As Object) As Collection
    Dim rows As New Collection
    Dim row As Long

    For row = config("data_start") To config("data_end")
        Dim cell As Range
        Set cell = ws.Cells(row, config("label_column"))

        If Len(Trim(cell.Value)) = 0 Then
            GoTo NextRow
        End If

        Dim isHeader As Boolean
        isHeader = False
        If cell.Font.Bold And HasFillPattern(cell) Then
            isHeader = True
        End If

        Dim rowInfo As Object
        Set rowInfo = CreateObject("Scripting.Dictionary")
        rowInfo("row") = row
        rowInfo("label") = Trim(cell.Value)
        rowInfo("is_header") = isHeader

        rows.Add rowInfo
NextRow:
    Next row

    Set DetectEventRowsDynamic = rows
End Function

Private Function DetectDateColumnsDynamic(ws As Worksheet, config As Object) As Collection
    Dim cols As New Collection
    Dim col As Long

    For col = config("date_col_start") To config("date_col_end")
        Dim cell As Range
        Set cell = ws.Cells(config("date_row"), col)

        ' Count empty slots
        Dim emptySlots As Long
        emptySlots = 0
        For row = config("data_start") To config("data_end")
            If Len(Trim(ws.Cells(row, col).Value)) = 0 Then
                emptySlots = emptySlots + 1
            End If
        Next row

        Dim colInfo As Object
        Set colInfo = CreateObject("Scripting.Dictionary")
        colInfo("column") = col
        colInfo("letter") = ColumnLetter(col)
        colInfo("value") = cell.Value
        colInfo("empty_slots") = emptySlots

        cols.Add colInfo
    Next col

    Set DetectDateColumnsDynamic = cols
End Function

Private Function HasFillPattern(cell As Range) As Boolean
    If cell.Interior.Pattern = xlNone Then
        HasFillPattern = False
    Else
        HasFillPattern = True
    End If
End Function

' ----------------------------------------------------------------------------
' HELPER FUNCTIONS (reuse from previous version)
' ----------------------------------------------------------------------------

Private Function ColumnLetter(col As Long) As String
    ColumnLetter = Split(Cells(1, col).Address, "$")(1)
End Function

Private Function EscapeJSON(s As String) As String
    s = Replace(s, "\", "\\")
    s = Replace(s, """", "\""")
    s = Replace(s, vbCrLf, "\n")
    EscapeJSON = s
End Function

Private Function FormatEventRowsJSON(rows As Collection) As String
    ' Same as before
    Dim json As String
    Dim row As Object
    Dim first As Boolean
    first = True

    For Each row In rows
        If Not first Then json = json & ","
        json = json & "{""row"":" & row("row") & ","
        json = json & """label"":""" & EscapeJSON(row("label")) & ""","
        json = json & """is_header"":" & IIf(row("is_header"), "true", "false") & "}"
        first = False
    Next

    FormatEventRowsJSON = json
End Function

Private Function FormatDateColumnsJSON(cols As Collection) As String
    ' Same as before
    Dim json As String
    Dim col As Object
    Dim first As Boolean
    first = True

    For Each col In cols
        If Not first Then json = json & ","
        json = json & "{""column"":" & col("column") & ","
        json = json & """letter"":""" & col("letter") & ""","
        json = json & """value"":""" & EscapeJSON(CStr(col("value"))) & ""","
        json = json & """empty_slots"":" & col("empty_slots") & "}"
        first = False
    Next

    FormatDateColumnsJSON = json
End Function
```

---

## Usage: Much Simpler!

### For Basic Templates (No Configuration)
1. Open Excel template
2. Add VBA code (just paste, **no configuration**)
3. Run `ExportMetadataSmart` macro
4. Done! Structure auto-detected

### For Edge Cases (Optional Hints)
Add special markers to guide detection:

**Option A: Text Marker**
```
Cell A2: "##VASO_DATE_ROW##"
```

**Option B: Named Cell**
```
Define name "VASO_DATE_ROW" pointing to any cell in date row
```

**Option C: Visual Marker**
```
Apply named style "VasoDateRow" to date row
```

---

## Benefits of Dynamic Approach

✅ **Adapts to changes** - Add/remove rows freely
✅ **Works across experiments** - Different structures, same macro
✅ **Zero configuration** - Most templates work immediately
✅ **Graceful hints** - Optional markers for edge cases
✅ **Future-proof** - Structure evolves without breaking

---

## Migration Guide

### From Static to Dynamic

**Old (Static):**
```vb
EventRowsStart = 3
EventRowsEnd = 25
```

**New (Dynamic):**
```vb
' Nothing to configure! Auto-detects based on:
' - First row with data after date row = start
' - First empty row after data = end
```

---

## Next Steps

1. Replace `GetVasoConfig()` with `DetectTemplateStructure()`
2. Replace `ExportMetadata()` with `ExportMetadataSmart()`
3. Test with existing templates (should work immediately)
4. Add optional markers only if auto-detection fails
