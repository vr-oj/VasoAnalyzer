# Custom Icon Guide for VasoAnalyzer Project Files

This guide explains how to create custom icons for `.vaso` and `.vasopack` project files.

## Overview

VasoAnalyzer now supports distinct icons for:
- **`.vaso` files** (single-file container format) → `VasoProjectIcon.icns`
- **`.vasopack` bundles** (folder format) → `VasoBundleIcon.icns`

These icons will appear in:
- Finder (macOS)
- File Explorer (Windows)
- File open/save dialogs
- Dock (when files are opened)

---

## Icon Requirements

### macOS (.icns format)

**Required sizes in iconset:**
- 16x16 (standard and @2x)
- 32x32 (standard and @2x)
- 128x128 (standard and @2x)
- 256x256 (standard and @2x)
- 512x512 (standard and @2x)

**Location:** `packaging/macos/`
- `VasoProjectIcon.icns` - For .vaso container files
- `VasoBundleIcon.icns` - For .vasopack folder bundles

### Windows (.ico format)

**Required sizes:**
- 16x16, 32x32, 48x48, 256x256

**Location:** `packaging/windows/`

---

## Creating Icons

### Method 1: Using Sketch/Figma/Illustrator (Recommended)

1. **Design your icon** at 1024x1024 px
   - Suggested design for `.vaso`:
     - Base: Document/file icon
     - Badge: Small icon showing snapshots/history
     - Color: Blue or teal (to match VasoAnalyzer branding)
   - Suggested design for `.vasopack`:
     - Base: Folder/bundle icon
     - Badge: Same as `.vaso` but on folder
     - Color: Slightly darker shade

2. **Export as PNG** at all required sizes

3. **Convert to .icns (macOS)**:
   ```bash
   # Create iconset folder
   mkdir VasoProjectIcon.iconset

   # Add all required sizes (example for 512x512)
   cp icon_512x512.png VasoProjectIcon.iconset/icon_256x256@2x.png
   cp icon_256x256.png VasoProjectIcon.iconset/icon_128x128@2x.png
   cp icon_256x256.png VasoProjectIcon.iconset/icon_256x256.png
   cp icon_128x128.png VasoProjectIcon.iconset/icon_128x128.png
   # ... (repeat for all sizes)

   # Convert to .icns
   iconutil -c icns VasoProjectIcon.iconset

   # Move to packaging folder
   mv VasoProjectIcon.icns packaging/macos/
   ```

4. **Convert to .ico (Windows)**:
   - Use online tool: https://convertio.co/png-ico/
   - Or use ImageMagick:
     ```bash
     convert icon_*.png VasoProjectIcon.ico
     ```

### Method 2: Using Icon Composer (macOS)

1. Open **Icon Composer** (part of Xcode)
2. Drag PNG files into appropriate size slots
3. Save as `.icns`

### Method 3: Using SF Symbols (macOS - Simple)

For a quick solution using Apple's SF Symbols:

```bash
# Use SF Symbols app to export symbol as PNG
# Then convert to iconset as shown above
```

---

## Design Recommendations

### .vaso Container Icon

**Concept:** Modern, clean file document with a "snapshot" or "layers" badge

**Visual elements:**
- Document/file shape (rounded corners)
- Small badge/overlay showing:
  - Stacked layers (representing snapshots)
  - OR circular arrow (representing versioning)
  - OR clock/history icon
- Primary color: **Teal** (#00BCD4) or **Blue** (#2196F3)
- Gradient optional but recommended for depth

**Reference inspiration:**
- LabChart `.adicht` file icon (if available)
- Prism project file icon
- macOS Pages document icon style

### .vasopack Folder Bundle Icon

**Concept:** macOS-style package/bundle icon with same badge

**Visual elements:**
- Folder shape with "bundle" style (white paper texture)
- Same badge as `.vaso` icon
- Slightly darker color scheme
- Should look like a macOS "app bundle" or "package"

**Reference inspiration:**
- Xcode `.xcodeproj` bundle icon
- Keynote `.key` bundle icon
- Adobe `.indd` package icon

---

## Example: Creating Icons from Scratch

### Using Figma (Free)

1. **Create new file** (1024x1024 px artboard)

2. **Draw base shape:**
   ```
   For .vaso:
   - Rectangle with rounded corners (900x1100 px)
   - Fill: Linear gradient (teal → darker teal)
   - Shadow: Soft drop shadow

   For .vasopack:
   - Use macOS folder template
   - Fill: Light gray gradient
   ```

3. **Add badge overlay:**
   ```
   - Circle (200x200 px) in bottom-right
   - White background
   - Icon: 3 stacked rectangles (representing snapshots)
   - Color: Match main icon color
   ```

4. **Add text (optional):**
   ```
   - "VASO" text at top
   - Font: SF Pro Display Bold
   - Size: 120 pt
   - Color: White or light gray
   ```

5. **Export:**
   - Export at 1024x1024, 512x512, 256x256, etc.
   - PNG format with transparency

### Using macOS Preview (Quick & Easy)

1. Open `VasoAnalyzerIcon.icns` (if you have it) in Preview
2. **File → Export** as PNG at large size
3. **Edit in Preview:**
   - Add badge overlay using Markup tools
   - Change colors using Adjust Color
4. Save and convert to .icns

---

## Testing Icons

### macOS

1. **Place icons in packaging folder:**
   ```bash
   cp VasoProjectIcon.icns packaging/macos/
   cp VasoBundleIcon.icns packaging/macos/
   ```

2. **Rebuild app** (PyInstaller or your build script)

3. **Test file associations:**
   ```bash
   # Create test file
   touch ~/Desktop/TestProject.vaso

   # Check icon in Finder
   open ~/Desktop
   ```

4. **Force icon cache refresh** (if needed):
   ```bash
   # Kill Finder and icon cache
   sudo rm -rf /Library/Caches/com.apple.iconservices.store
   killall Finder
   ```

### Windows

1. Place `.ico` files in `packaging/windows/`
2. Rebuild installer
3. Test by creating `.vaso` and `.vasopack` files

---

## Icon Design Tools

### Free Tools
- **Figma** - https://figma.com (best for custom design)
- **Canva** - https://canva.com (templates available)
- **SF Symbols** (macOS) - Built into Xcode
- **GIMP** - https://gimp.org (free Photoshop alternative)

### Paid Tools
- **Sketch** - https://sketch.com (macOS only, $99)
- **Adobe Illustrator** - Part of Creative Cloud
- **Affinity Designer** - https://affinity.serif.com ($70, one-time)

### Conversion Tools
- **ImageMagick** - Command-line (free)
- **IconUtil** - Built into macOS
- **Icon Composer** - Part of Xcode
- **Image2Icon** - https://img2icnsapp.com (free macOS app)

---

## Troubleshooting

### Icons not showing on macOS

**Problem:** New icons don't appear in Finder

**Solutions:**
1. Clear icon cache:
   ```bash
   sudo rm -rf /Library/Caches/com.apple.iconservices.store
   killall Finder
   ```

2. Touch the Info.plist:
   ```bash
   touch packaging/macos/Info.plist
   ```

3. Rebuild the app bundle completely

### Icons not showing on Windows

**Problem:** `.vaso` files show generic icon

**Solutions:**
1. Check registry entries (Windows installer should handle this)
2. Run as administrator when installing
3. Restart Explorer.exe

### Icon looks blurry

**Problem:** Icon appears pixelated at certain sizes

**Solutions:**
1. Ensure you've included all required sizes
2. Design at highest resolution (1024x1024) and scale down
3. Use vector graphics if possible
4. Test at multiple zoom levels

---

## Quick Start (No Design Skills Required)

If you want a simple solution without designing from scratch:

1. **Use emoji as placeholder** (surprisingly good-looking):
   ```bash
   # macOS: Use emoji → PNG → iconset
   # 📊 (chart emoji) or 📁 (folder) work well
   ```

2. **Modify existing icon:**
   - Copy `VasoAnalyzerIcon.icns`
   - Add small badge in Preview (Markup tools)
   - Export and convert

3. **Hire designer on Fiverr:**
   - Search: "macOS app icon design"
   - Provide requirements from this doc
   - Cost: ~$20-50

---

## Integration with Build System

### PyInstaller

Your `.spec` file should include:

```python
app = BUNDLE(
    exe,
    name='VasoAnalyzer.app',
    icon='packaging/macos/VasoAnalyzerIcon.icns',
    bundle_identifier='org.vasoanalyzer.app',
    info_plist={
        'CFBundleDocumentTypes': [
            # ... (already configured in Info.plist)
        ]
    }
)
```

### Windows Installer (NSIS/Inno Setup)

```nsi
[Setup]
AppName=VasoAnalyzer
...

[Icons]
Name: "{group}\VasoAnalyzer"; Filename: "{app}\VasoAnalyzer.exe"; IconFilename: "{app}\VasoAnalyzer.ico"

[Registry]
; Associate .vaso files
Root: HKCR; Subkey: ".vaso"; ValueType: string; ValueName: ""; ValueData: "VasoAnalyzer.Project"
Root: HKCR; Subkey: "VasoAnalyzer.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\VasoProjectIcon.ico"
```

---

## Current State

**Status:** Icon configuration is ready in `Info.plist`, but icons need to be created.

**What's configured:**
- ✅ `Info.plist` references both icon files
- ✅ File type associations set up
- ✅ UTI (Uniform Type Identifier) declarations complete

**What's needed:**
- ⚠️ Create `VasoProjectIcon.icns` (for .vaso files)
- ⚠️ Create `VasoBundleIcon.icns` (for .vasopack bundles)
- ⚠️ Create Windows `.ico` versions

**Fallback:** Until custom icons are created, files will use the default `VasoAnalyzerIcon.icns` or system default document icon.

---

## Example Icon Concepts (Text Description)

### Option A: "Layered Document" Theme

**.vaso file:**
```
┌─────────────┐
│    VASO     │  ← Clean modern document
│  ┌───┬───┐  │  ← Three stacked lines representing snapshots
│  ├───┼───┤  │
│  └───┴───┘  │
│             │
└─────────────┘
Color: Teal gradient (#00BCD4 → #0097A7)
Badge: Small circular "clock" or "history" icon
```

**.vasopack bundle:**
```
  ┌────────────┐
 ╱            ╱│  ← Folder/package style
│  VASOPACK  │ │
│  [badge]   │╱
└────────────┘
Color: Gray-blue gradient
Badge: Same as .vaso
```

### Option B: "Scientific" Theme

**.vaso file:**
```
Document shape with:
- Waveform/trace graphic (represents physiological data)
- Small "V" monogram
- Modern minimalist style
Color: Medical blue (#1976D2)
```

---

## Need Help?

If you need assistance creating icons:

1. **Community resources:** Post in VasoAnalyzer discussions
2. **Design services:** 99designs, Fiverr, Upwork
3. **Templates:** Search "macOS document icon template Figma"

**Recommended approach:** Start with Method 3 (SF Symbols) for a quick MVP, then commission professional icons later.
