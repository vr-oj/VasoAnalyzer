"""Backend-agnostic interaction contexts for plot backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Set


@dataclass
class ClickContext:
    """Backend-agnostic description of a mouse click in plot data coordinates."""

    x_data: float
    y_data: float
    button: str  # "left", "right", "middle"
    modifiers: Set[str]  # e.g. {"shift", "ctrl"}
    track_id: Optional[str]
    in_gutter: bool
    double: bool


@dataclass
class MoveContext:
    """Backend-agnostic description of a mouse move in plot data coordinates."""

    x_data: float
    y_data: float
    track_id: Optional[str]


@dataclass
class ScrollContext:
    """Backend-agnostic description of a wheel scroll gesture.

    delta_y is positive when scrolling up/away from the user (e.g., wheel up)
    and negative when scrolling down/toward the user.
    """

    x_data: float
    y_data: float
    delta_y: float
    track_id: Optional[str]
    modifiers: Set[str]


class InteractionHost(Protocol):
    """Abstract interface for plot backends to expose user interactions."""

    def on_click(self, handler: Callable[[ClickContext], None]) -> None:
        ...

    def on_move(self, handler: Callable[[MoveContext], None]) -> None:
        ...

    def on_scroll(self, handler: Callable[[ScrollContext], None]) -> None:
        ...
