"""Centralised plot interactions for cursor-centric zooming and panning."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

from PyQt5.QtCore import Qt

from vasoanalyzer.ui.plots.channel_track import ChannelTrack
from vasoanalyzer.ui.plots.interactions_base import (
    ClickContext,
    InteractionHost,
    MoveContext,
    ScrollContext,
)
from vasoanalyzer.ui.plots.plot_host import PlotHost

_MODIFIER_MAP = {
    "ctrl": "control",
    "cmd": "command",
    "option": "alt",
}

log = logging.getLogger(__name__)


def _parse_modifiers(key: str | None) -> list[str]:
    if not key:
        return []
    parts: list[str] = []
    for segment in key.lower().split("+"):
        parts.append(_MODIFIER_MAP.get(segment, segment))
    return parts


@dataclass
class _DragContext:
    mode: str
    track: ChannelTrack
    press_xy: tuple[float, float]
    start_window: tuple[float, float] | None
    start_ylim: tuple[float, float] | None
    start_xdata: float | None
    start_ydata: float | None


class InteractionController:
    """Handle mouse + keyboard interactions for the stacked trace figure."""

    DRAG_THRESHOLD_PX = 6

    def __init__(
        self,
        plot_host: PlotHost,
        interaction_host: InteractionHost,
        *,
        toolbar=None,
        on_drag_state: Callable[[bool], None] | None = None,
        set_cursor_callback: Callable[[str, float | None], None] | None = None,
        clear_cursors_callback: Callable[[], None] | None = None,
    ) -> None:
        self.plot_host = plot_host
        self._interaction_host = interaction_host
        self.canvas = plot_host.canvas
        self.toolbar = toolbar
        self._on_drag_state = on_drag_state or (lambda active: None)
        self._set_cursor_callback = set_cursor_callback
        self._clear_cursors_callback = clear_cursors_callback or (lambda: None)

        self._drag_ctx: _DragContext | None = None
        self._drag_active = False
        self._hover_track: ChannelTrack | None = None
        self._hover_time: float | None = None
        self._canvas_connection_ids: list[int] = []
        self._is_pyqtgraph = (
            getattr(self.plot_host, "get_render_backend", lambda: None)() == "pyqtgraph"
        )

        self._bind_interactions()
        self._bind_canvas_events()

    # ------------------------------------------------------------------ lifecycle
    def disconnect(self) -> None:
        disconnect_host = getattr(self._interaction_host, "disconnect", None)
        if callable(disconnect_host):
            disconnect_host()
        mpl_disconnect = getattr(self.canvas, "mpl_disconnect", None)
        if mpl_disconnect is None:
            self._canvas_connection_ids.clear()
            return
        for cid in self._canvas_connection_ids:
            mpl_disconnect(cid)
        self._canvas_connection_ids.clear()

    # ------------------------------------------------------------------ event wiring
    def _bind_interactions(self) -> None:
        self._interaction_host.on_scroll(self._on_scroll)
        self._interaction_host.on_click(self._on_click)
        self._interaction_host.on_move(self._on_motion)

    def _bind_canvas_events(self) -> None:
        mpl_connect = getattr(self.canvas, "mpl_connect", None)
        if mpl_connect is None:
            return
        self._canvas_connection_ids.extend(
            [
                mpl_connect("figure_leave_event", self._on_leave),
                mpl_connect("key_press_event", self._on_key_press),
            ]
        )

    # ------------------------------------------------------------------ helpers
    def _nav_active(self) -> bool:
        mode = getattr(self.toolbar, "mode", "") if self.toolbar is not None else ""
        return bool(mode)

    def _track_from_axes(self, axes) -> ChannelTrack | None:
        return self.plot_host.track_for_axes(axes)

    def _track_from_ctx(self, track_id: str | None) -> ChannelTrack | None:
        if track_id is None:
            return None
        track_lookup = getattr(self.plot_host, "track", None)
        if callable(track_lookup):
            try:
                return track_lookup(track_id)
            except Exception:
                return None
        return None

    def _set_drag_active(self, active: bool) -> None:
        if self._drag_active == active:
            return
        self._drag_active = active
        self._on_drag_state(active)

    def _scroll_factor(self, event) -> float:
        """Calculate zoom factor for scroll events.

        Uses gentler zoom factors (0.9/1.11 vs 0.8/1.25) for better
        trackpad control and less sensitive zooming.
        """
        step = getattr(event, "step", None)
        if step is not None:
            direction = 1 if step > 0 else -1
        else:
            direction = 1 if getattr(event, "button", "") == "up" else -1
        return 0.9 if direction > 0 else 1.11

    def _click_position(self, ctx: ClickContext) -> tuple[float, float]:
        x_px = getattr(ctx, "x_px", float("nan"))
        y_px = getattr(ctx, "y_px", float("nan"))
        if not math.isfinite(x_px):
            x_px = 0.0
        if not math.isfinite(y_px):
            y_px = 0.0
        return (x_px, y_px)

    def _pixel_delta(self, move_ctx: MoveContext, drag_ctx: _DragContext) -> tuple[float, float]:
        x_px = getattr(move_ctx, "x_px", float("nan"))
        y_px = getattr(move_ctx, "y_px", float("nan"))
        dx = x_px - drag_ctx.press_xy[0]
        dy = y_px - drag_ctx.press_xy[1]
        if not math.isfinite(dx):
            dx = 0.0
        if not math.isfinite(dy):
            dy = 0.0
        return dx, dy

    def _finite_or_none(self, value: float) -> float | None:
        try:
            if math.isfinite(value):
                return float(value)
        except Exception:
            return None
        return None

    def _active_track(self) -> ChannelTrack | None:
        if self._hover_track is not None:
            return self._hover_track
        tracks = self.plot_host.tracks()
        return tracks[0] if tracks else None

    # ------------------------------------------------------------------ handlers
    def _on_scroll(self, ctx: ScrollContext) -> None:
        """Handle scroll events - horizontal panning only (like LabChart).

        Simple and reliable:
        - Two-finger scroll = pan left/right
        - No modifiers, no complexity
        - Zoom via toolbar buttons instead
        """
        if self._nav_active():
            return

        # Get current time window
        window = self.plot_host.current_window()
        if window is None:
            return

        # Get scroll direction
        delta = ctx.delta_y
        if delta == 0:
            return
        direction = -1 if delta > 0 else 1

        log.debug(
            "InteractionController._on_scroll: delta=%r window_before=%r",
            delta,
            window,
        )

        # Pan amount: 10% of visible window
        window_span = window[1] - window[0]
        pan_amount = direction * window_span * 0.1

        log.info(f"📜 Scroll pan: direction={direction}, amount={pan_amount:.2f}s")
        self.plot_host.scroll_by(pan_amount)

    def _on_click(self, ctx: ClickContext) -> None:
        if not bool(getattr(ctx, "pressed", True)):
            self._on_release()
            return
        if self._nav_active():
            return
        if ctx.button not in {"left", 1, "1"}:
            return

        track = self._track_from_ctx(ctx.track_id)
        if track is None:
            return

        modifiers = list(ctx.modifiers)
        if ctx.double:
            full = self.plot_host.full_range()
            if full is None:
                return
            self.plot_host.set_time_window(*full)
            if "alt" in modifiers:
                self.plot_host.autoscale_all()
            else:
                track.autoscale()
                self.canvas.draw_idle()
            return

        if self._is_pyqtgraph:
            return

        mode = "y-pan" if ctx.in_gutter else "time-pan"
        press_xy = self._click_position(ctx)
        self._drag_ctx = _DragContext(
            mode=mode,
            track=track,
            press_xy=press_xy,
            start_window=self.plot_host.current_window(),
            start_ylim=track.ax.get_ylim(),
            start_xdata=self._finite_or_none(ctx.x_data),
            start_ydata=self._finite_or_none(ctx.y_data),
        )
        self._set_drag_active(False)

    def _on_release(self) -> None:
        self._drag_ctx = None
        self._set_drag_active(False)

    def _on_leave(self, _event) -> None:
        self._hover_track = None
        self._hover_time = None
        if self._drag_ctx is not None:
            self._on_release()

    def _on_motion(self, ctx: MoveContext) -> None:
        track = self._track_from_ctx(ctx.track_id)
        if track is not None:
            self._hover_track = track
        elif ctx.track_id is None:
            self._hover_track = None
        if math.isfinite(ctx.x_data):
            self._hover_time = float(ctx.x_data)
        elif track is None:
            self._hover_time = None

        drag_ctx = self._drag_ctx
        if drag_ctx is None:
            return

        buttons = getattr(ctx, "buttons", None)
        if buttons is not None and not (buttons & Qt.LeftButton):
            self._on_release()
            return

        dx, dy = self._pixel_delta(ctx, drag_ctx)
        dist2 = dx * dx + dy * dy
        if not self._drag_active:
            if dist2 < self.DRAG_THRESHOLD_PX * self.DRAG_THRESHOLD_PX:
                return
            self._set_drag_active(True)

        if drag_ctx.mode == "time-pan":
            x_data = self._finite_or_none(ctx.x_data)
            if drag_ctx.start_window is None or drag_ctx.start_xdata is None or x_data is None:
                return
            delta = x_data - drag_ctx.start_xdata
            self.plot_host.set_time_window(
                drag_ctx.start_window[0] - delta,
                drag_ctx.start_window[1] - delta,
            )
        elif drag_ctx.mode == "y-pan":
            y_data = self._finite_or_none(ctx.y_data)
            if drag_ctx.start_ylim is None or drag_ctx.start_ydata is None or y_data is None:
                return
            delta_y = y_data - drag_ctx.start_ydata
            drag_ctx.track.set_ylim(
                drag_ctx.start_ylim[0] - delta_y,
                drag_ctx.start_ylim[1] - delta_y,
            )
            self.canvas.draw_idle()

    def _on_key_press(self, event) -> None:
        import logging

        log = logging.getLogger(__name__)

        key = getattr(event, "key", None)
        if key is None:
            return
        parts = _parse_modifiers(key)
        base = parts[-1] if parts else key.lower()
        modifiers = set(parts[:-1]) if len(parts) > 1 else set()

        window = self.plot_host.current_window()
        if base == "escape":
            if self._clear_cursors_callback is not None:
                self._clear_cursors_callback()
            return

        if base in {"a", "b"} and not modifiers:
            if self._set_cursor_callback is None:
                return
            time_ref = self._hover_time
            if time_ref is None and window is not None:
                time_ref = (window[0] + window[1]) / 2.0
            if time_ref is not None:
                self._set_cursor_callback(base.upper(), time_ref)
            return

        if base in {"left", "right"} and window is not None:
            span = window[1] - window[0]
            if span <= 0:
                return
            fraction = 0.1
            if "shift" in modifiers:
                fraction = 0.5
            delta = span * fraction
            if base == "left":
                delta = -delta
            self.plot_host.scroll_by(delta)
            return

        if base == "0" and "control" in modifiers:
            track = self._active_track()
            if track is None:
                return
            track.autoscale()
            self.canvas.draw_idle()
            return

        if base == "0" and "alt" in modifiers:
            self.plot_host.autoscale_all()
            return

        # Zoom in/out with +/- keys (LabChart-style)
        if base in {"equal", "+", "minus", "-"} and window is not None:
            # Determine zoom direction
            zoom_in = base in {"equal", "+"}
            zoom_factor = 0.5 if zoom_in else 2.0  # 0.5 = zoom in, 2.0 = zoom out

            span = window[1] - window[0]
            new_span = span * zoom_factor

            # Center zoom on hover position if available, otherwise center of view
            center = (
                self._hover_time if self._hover_time is not None else (window[0] + window[1]) / 2.0
            )

            # Calculate new window bounds
            new_start = center - new_span / 2.0
            new_end = center + new_span / 2.0

            log.debug(
                "Zoom %s: %.2fs \u2192 %.2fs (center %.2fs)",
                "in" if zoom_in else "out",
                span,
                new_span,
                center,
            )
            self.plot_host.set_time_window(new_start, new_end)
            return
