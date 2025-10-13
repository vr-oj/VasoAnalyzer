"""Centralised plot interactions for cursor-centric zooming and panning."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import Qt

from vasoanalyzer.ui.plots.plot_host import PlotHost
from vasoanalyzer.ui.plots.channel_track import ChannelTrack


_MODIFIER_MAP = {
    "ctrl": "control",
    "cmd": "command",
    "option": "alt",
}


def _parse_modifiers(key: Optional[str]) -> List[str]:
    if not key:
        return []
    parts: List[str] = []
    for segment in key.lower().split("+"):
        parts.append(_MODIFIER_MAP.get(segment, segment))
    return parts


@dataclass
class _DragContext:
    mode: str
    track: ChannelTrack
    press_xy: Tuple[float, float]
    start_window: Optional[Tuple[float, float]]
    start_ylim: Optional[Tuple[float, float]]
    start_xdata: Optional[float]
    start_ydata: Optional[float]


class InteractionController:
    """Handle mouse + keyboard interactions for the stacked trace figure."""

    DRAG_THRESHOLD_PX = 6

    def __init__(
        self,
        plot_host: PlotHost,
        *,
        toolbar=None,
        on_drag_state: Optional[Callable[[bool], None]] = None,
        set_cursor_callback: Optional[Callable[[str, Optional[float]], None]] = None,
        clear_cursors_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.plot_host = plot_host
        self.canvas = plot_host.canvas
        self.toolbar = toolbar
        self._on_drag_state = on_drag_state or (lambda active: None)
        self._set_cursor_callback = set_cursor_callback
        self._clear_cursors_callback = clear_cursors_callback or (lambda: None)

        self._drag_ctx: Optional[_DragContext] = None
        self._drag_active = False
        self._hover_track: Optional[ChannelTrack] = None
        self._hover_time: Optional[float] = None
        self._connection_ids: List[int] = []

        self._connect_events()

    # ------------------------------------------------------------------ lifecycle
    def disconnect(self) -> None:
        for cid in self._connection_ids:
            self.canvas.mpl_disconnect(cid)
        self._connection_ids.clear()

    # ------------------------------------------------------------------ event wiring
    def _connect_events(self) -> None:
        mpl_connect = self.canvas.mpl_connect
        self._connection_ids.extend(
            [
                mpl_connect("scroll_event", self._on_scroll),
                mpl_connect("button_press_event", self._on_press),
                mpl_connect("button_release_event", self._on_release),
                mpl_connect("motion_notify_event", self._on_motion),
                mpl_connect("figure_leave_event", self._on_leave),
                mpl_connect("key_press_event", self._on_key_press),
            ]
        )

    # ------------------------------------------------------------------ helpers
    def _nav_active(self) -> bool:
        mode = getattr(self.toolbar, "mode", "") if self.toolbar is not None else ""
        return bool(mode)

    def _track_from_axes(self, axes) -> Optional[ChannelTrack]:
        return self.plot_host.track_for_axes(axes)

    def _track_from_event(self, event) -> Optional[ChannelTrack]:
        return self._track_from_axes(getattr(event, "inaxes", None))

    def _set_drag_active(self, active: bool) -> None:
        if self._drag_active == active:
            return
        self._drag_active = active
        self._on_drag_state(active)

    def _in_y_gutter(self, event, track: ChannelTrack, margin_px: float = 18.0) -> bool:
        if event.inaxes is None:
            return False
        bbox = track.ax.get_window_extent()
        return (event.x < bbox.x0 + margin_px) or (event.x > bbox.x1 - margin_px)

    def _scroll_factor(self, event) -> float:
        step = getattr(event, "step", None)
        if step is not None:
            direction = 1 if step > 0 else -1
        else:
            direction = 1 if getattr(event, "button", "") == "up" else -1
        return 0.8 if direction > 0 else 1.25

    def _active_track(self) -> Optional[ChannelTrack]:
        if self._hover_track is not None:
            return self._hover_track
        tracks = self.plot_host.tracks()
        return tracks[0] if tracks else None

    # ------------------------------------------------------------------ handlers
    def _on_scroll(self, event) -> None:
        if self._nav_active():
            return
        modifiers = _parse_modifiers(getattr(event, "key", None))
        factor = self._scroll_factor(event)
        track = self._track_from_event(event)

        if "shift" in modifiers and track is not None:
            if event.ydata is None:
                return
            track.zoom_y(event.ydata, factor)
            self.canvas.draw_idle()
            return

        if event.xdata is None:
            return
        self.plot_host.zoom_at(event.xdata, factor)

    def _on_press(self, event) -> None:
        if self._nav_active():
            return
        if getattr(event, "button", None) != 1:
            return

        track = self._track_from_event(event)
        if track is None:
            return

        modifiers = _parse_modifiers(getattr(event, "key", None))
        if getattr(event, "dblclick", False):
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

        gutter_mode = self._in_y_gutter(event, track)
        mode = "y-pan" if gutter_mode else "time-pan"
        self._drag_ctx = _DragContext(
            mode=mode,
            track=track,
            press_xy=(event.x, event.y),
            start_window=self.plot_host.current_window(),
            start_ylim=track.ax.get_ylim(),
            start_xdata=event.xdata,
            start_ydata=event.ydata,
        )
        self._set_drag_active(False)

    def _on_release(self, _event) -> None:
        self._drag_ctx = None
        self._set_drag_active(False)

    def _on_leave(self, _event) -> None:
        self._hover_track = None
        self._hover_time = None
        if self._drag_ctx is not None:
            self._drag_ctx = None
            self._set_drag_active(False)

    def _on_motion(self, event) -> None:
        track = self._track_from_event(event)
        if track is not None:
            self._hover_track = track
        if getattr(event, "xdata", None) is not None:
            self._hover_time = float(event.xdata)

        ctx = self._drag_ctx
        if ctx is None:
            return

        buttons = None
        if hasattr(event, "guiEvent") and event.guiEvent is not None:
            buttons = event.guiEvent.buttons()
        if buttons is not None and not (buttons & Qt.LeftButton):
            self._on_release(event)
            return

        dx = event.x - ctx.press_xy[0]
        dy = event.y - ctx.press_xy[1]
        dist2 = dx * dx + dy * dy
        if not self._drag_active:
            if dist2 < self.DRAG_THRESHOLD_PX * self.DRAG_THRESHOLD_PX:
                return
            self._set_drag_active(True)

        if ctx.mode == "time-pan":
            if ctx.start_window is None or ctx.start_xdata is None or event.xdata is None:
                return
            delta = event.xdata - ctx.start_xdata
            self.plot_host.set_time_window(
                ctx.start_window[0] - delta,
                ctx.start_window[1] - delta,
            )
        elif ctx.mode == "y-pan":
            if ctx.start_ylim is None or ctx.start_ydata is None or event.ydata is None:
                return
            delta_y = event.ydata - ctx.start_ydata
            ctx.track.set_ylim(
                ctx.start_ylim[0] - delta_y,
                ctx.start_ylim[1] - delta_y,
            )
            self.canvas.draw_idle()

    def _on_key_press(self, event) -> None:
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
