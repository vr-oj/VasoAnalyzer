# Trace Navigation Manual Test Checklist

- Load a recording with events and confirm the nav bar + overview strip appear.
- Verify nav bar shows current position/total duration and view span updates on pan/zoom.
- Click 1s/10s/60s/All presets and ensure the main view clamps correctly.
- Step left/right moves by exactly one current-window width.
- Zoom +/- changes span by 2x centered on the current view.
- Mouse wheel/trackpad zooms the X-axis without breaking pan momentum.
- Overview strip shows full waveform, event markers, and a view rectangle that tracks the main view.
- Drag the overview window to scroll; click the overview to jump.
- Ctrl+G opens Go to Time; confirm formats parse and invalid input shows an error.
- Home or Ctrl/Cmd+0 zooms to the full X range; [ / ] jump to prev/next event.
- Smooth pan has momentum and stops cleanly at boundaries.
- Toolbar shows only Pan, Select, and a View overflow menu (no duplicate zoom buttons).
- View overflow menu contains zoom history, grid, autoscale Y, and style actions.
