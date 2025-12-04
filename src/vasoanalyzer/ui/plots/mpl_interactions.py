"""Matplotlib-backed interaction host that emits backend-agnostic contexts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Iterable, Optional, Set

from vasoanalyzer.ui.plots.interactions_base import (
    ClickContext,
    InteractionHost,
    MoveContext,
    ScrollContext,
)

_MODIFIER_MAP = {
    "ctrl": "control",
    "cmd": "command",
    "option": "alt",
}


class MplInteractionHost:
    """Adapter that converts Matplotlib canvas events into interaction contexts."""

    def __init__(self, canvas: Any, track_lookup: Callable[[Any], Any] | None = None) -> None:
        self._canvas = canvas
        self._track_lookup = track_lookup

        self._click_handlers: list[Callable[[ClickContext], None]] = []
        self._move_handlers: list[Callable[[MoveContext], None]] = []
        self._scroll_handlers: list[Callable[[ScrollContext], None]] = []

        self._connection_ids: list[int] = []
        self._connect_events()

    # ------------------------------------------------------------------ public API
    def on_click(self, handler: Callable[[ClickContext], None]) -> None:
        self._click_handlers.append(handler)

    def on_move(self, handler: Callable[[MoveContext], None]) -> None:
        self._move_handlers.append(handler)

    def on_scroll(self, handler: Callable[[ScrollContext], None]) -> None:
        self._scroll_handlers.append(handler)

    def disconnect(self) -> None:
        """Disconnect all canvas callbacks."""
        mpl_disconnect = getattr(self._canvas, "mpl_disconnect", None)
        if mpl_disconnect is None:
            return
        for cid in self._connection_ids:
            try:
                mpl_disconnect(cid)
            except Exception:
                continue
        self._connection_ids.clear()

    # ------------------------------------------------------------------ event wiring
    def _connect_events(self) -> None:
        mpl_connect = getattr(self._canvas, "mpl_connect", None)
        if mpl_connect is None:
            return
        self._connection_ids.extend(
            [
                mpl_connect("button_press_event", self._handle_press),
                mpl_connect("button_release_event", self._handle_release),
                mpl_connect("motion_notify_event", self._handle_motion),
                mpl_connect("scroll_event", self._handle_scroll),
            ]
        )

    # ------------------------------------------------------------------ handlers
    def _handle_press(self, event: Any) -> None:
        ctx = self._build_click_context(event, pressed=True)
        self._dispatch(self._click_handlers, ctx)

    def _handle_release(self, event: Any) -> None:
        ctx = self._build_click_context(event, pressed=False)
        self._dispatch(self._click_handlers, ctx)

    def _handle_motion(self, event: Any) -> None:
        track, track_id = self._resolve_track(event)
        ctx = MoveContext(
            x_data=self._to_float(getattr(event, "xdata", None)),
            y_data=self._to_float(getattr(event, "ydata", None)),
            track_id=track_id,
        )
        # Attach pixel coordinates and button state for drag detection
        try:
            ctx.x_px = float(getattr(event, "x", float("nan")))  # type: ignore[attr-defined]
            ctx.y_px = float(getattr(event, "y", float("nan")))  # type: ignore[attr-defined]
        except Exception:
            ctx.x_px = float("nan")  # type: ignore[attr-defined]
            ctx.y_px = float("nan")  # type: ignore[attr-defined]

        gui_event = getattr(event, "guiEvent", None)
        buttons = gui_event.buttons() if gui_event is not None and hasattr(gui_event, "buttons") else None
        ctx.buttons = buttons  # type: ignore[attr-defined]

        self._dispatch(self._move_handlers, ctx)

    def _handle_scroll(self, event: Any) -> None:
        track, track_id = self._resolve_track(event)
        delta_y = self._scroll_delta(event)
        ctx = ScrollContext(
            x_data=self._to_float(getattr(event, "xdata", None)),
            y_data=self._to_float(getattr(event, "ydata", None)),
            delta_y=delta_y,
            track_id=track_id,
            modifiers=self._modifiers_from_event(event),
        )
        self._dispatch(self._scroll_handlers, ctx)

    # ------------------------------------------------------------------ helpers
    def _build_click_context(self, event: Any, *, pressed: bool) -> ClickContext:
        track, track_id = self._resolve_track(event)
        ctx = ClickContext(
            x_data=self._to_float(getattr(event, "xdata", None)),
            y_data=self._to_float(getattr(event, "ydata", None)),
            button=self._button_name(getattr(event, "button", None)),
            modifiers=self._modifiers_from_event(event),
            track_id=track_id,
            in_gutter=self._in_gutter(event, track),
            double=bool(getattr(event, "dblclick", False)),
        )
        # Attach extra context needed by consumers without changing the dataclass shape.
        try:
            ctx.x_px = float(getattr(event, "x", float("nan")))  # type: ignore[attr-defined]
            ctx.y_px = float(getattr(event, "y", float("nan")))  # type: ignore[attr-defined]
        except Exception:
            ctx.x_px = float("nan")  # type: ignore[attr-defined]
            ctx.y_px = float("nan")  # type: ignore[attr-defined]
        ctx.pressed = bool(pressed)  # type: ignore[attr-defined]
        gui_event = getattr(event, "guiEvent", None)
        buttons = gui_event.buttons() if gui_event is not None and hasattr(gui_event, "buttons") else None
        ctx.buttons = buttons  # type: ignore[attr-defined]
        return ctx

    def _dispatch(self, handlers: Iterable[Callable[[Any], None]], ctx: Any) -> None:
        for handler in handlers:
            try:
                handler(ctx)
            except Exception:
                continue

    def _resolve_track(self, event: Any) -> tuple[Optional[Any], Optional[str]]:
        track = None
        track_id = None
        axes = getattr(event, "inaxes", None)
        if self._track_lookup is not None and axes is not None:
            try:
                track = self._track_lookup(axes)
            except Exception:
                track = None
        if track is not None:
            track_id = getattr(track, "id", None)
        elif axes is not None:
            track_id = getattr(axes, "vaso_track_id", None)
        return track, track_id

    def _in_gutter(self, event: Any, track: Any, margin_px: float = 18.0) -> bool:
        if track is None:
            return False
        ax = getattr(track, "ax", None)
        if ax is None:
            return False
        try:
            bbox = ax.get_window_extent()
        except Exception:
            return False
        x_coord = float(getattr(event, "x", float("nan")))
        if not bbox:
            return False
        left = float(getattr(bbox, "x0", 0.0))
        right = float(getattr(bbox, "x1", 0.0))
        return (x_coord < left + margin_px) or (x_coord > right - margin_px)

    def _button_name(self, raw_button: Any) -> str:
        if raw_button == 1 or raw_button == "left":
            return "left"
        if raw_button == 2 or raw_button == "middle":
            return "middle"
        if raw_button == 3 or raw_button == "right":
            return "right"
        return str(raw_button) if raw_button is not None else ""

    def _modifiers_from_event(self, event: Any) -> Set[str]:
        key = getattr(event, "key", None)
        if not key:
            return set()
        parts = []
        for segment in str(key).lower().split("+"):
            parts.append(_MODIFIER_MAP.get(segment, segment))
        return set(parts)

    def _scroll_delta(self, event: Any) -> float:
        step = getattr(event, "step", None)
        if step is not None:
            return float(step)
        button = getattr(event, "button", None)
        if button == "up":
            return 1.0
        if button == "down":
            return -1.0
        return 0.0

    def _to_float(self, value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return float("nan")


__all__ = ["MplInteractionHost", "InteractionHost"]
