# Chart-View Parity Contract v1

This contract defines behavior targets for channel display and navigation parity.
It is scoped to the PyQtGraph renderer and review-first timeline workflows.

## Scope

- Per-channel Y-axis controls and Y-axis gestures.
- Host-owned X-axis navigation and time compression controls.
- Overview strip + scrollbar + nav-bar synchronization.
- Toolbar/nav terminology consistency for scaling and compression.

## Frozen Terminology

- `Auto scale (once)`
- `Continuous autoscale`
- `Expand Y range`
- `Compress Y range`
- `Time compression`

## Precedence Rules

- X-window ownership is host-only.
- Y-axis actions must never mutate X-window state.
- Time compression requests must route through host APIs.

## Behavior Targets

1. Y-axis affordance parity
- Primary mini button triggers one-shot autoscale for that track.
- Axis right-click opens the same Y scale menu as the mini-menu button.
- Axis double-click triggers one-shot autoscale.
- Y scale menu includes one-shot autoscale, expand/compress, continuous autoscale, and set/reset range.

2. Y-axis drag scaling parity
- Left-axis press-drag scales Y deterministically:
`new_span = old_span * exp(dy * 0.006)`.
- Drag up compresses Y; drag down expands Y.
- Scaling center uses cursor Y when available, else current Y midpoint.
- First manual drag disables continuous autoscale for that track.

3. Time compression parity
- Compression out action uses factor `1.25`.
- Compression in action uses factor `0.8`.
- Presets: `0.5s, 1s, 2s, 5s, 10s, 30s, 60s, 120s, 5m, All`.
- Presets route through `set_time_compression_target(seconds | None)`.

4. Interaction alignment
- Wheel = pan X.
- Ctrl/Cmd + wheel = zoom X around cursor.
- Shift + wheel = Y pan.
- Alt + wheel = Y zoom.

5. Consistency
- No duplicate control surfaces for the same operation.
- No pyqtgraph default axis hover buttons visible.
- Navigation mode status hint shows `Pan` or `Select`, and appends `Review` when review mode is active.

## Non-Goals (v1)

- Live acquisition scroll/review mode switching.
- Pixel-perfect skin parity.
- Backend migration away from PyQtGraph.

## Feature Flag

- Gate: `ui.parity_chart_view_v1`
- Parser source: `VA_FEATURES` environment variable.
- Default state: enabled.
