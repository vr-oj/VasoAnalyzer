# Trace Navigation Manual Test Checklist

- Load a recording with events and confirm the nav bar + overview strip appear.
- Verify nav bar shows current position/total duration and view span updates on pan/zoom.
- Click 1s/10s/60s/All presets and ensure the main view clamps correctly.
- Step left/right moves by exactly one current-window width.
- Zoom +/- changes span by 2x centered on the current view.
- Overview strip shows full waveform, event markers, and a view rectangle that tracks the main view.
- Drag the overview window to scroll; click the overview to jump.
- Ctrl+G opens Go to Time; confirm formats parse and invalid input shows an error.
- Home/End jump to start/end without changing span; [ / ] jump to prev/next event.
- Smooth pan has momentum and stops cleanly at boundaries.
