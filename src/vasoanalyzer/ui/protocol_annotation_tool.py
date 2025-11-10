"""Interactive protocol annotation tool for manual timeline markup.

Provides click-drag drawing tools for creating publication-ready protocol annotations:
- Boxes with text labels
- Lines and arrows
- Standalone text
- Icons and markers

All annotations are manually placed by the user and saved with the project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from matplotlib.axes import Axes
from matplotlib.backend_bases import MouseEvent
from matplotlib.patches import FancyArrow, FancyBboxPatch, Rectangle
from matplotlib.text import Text
from PyQt5.QtWidgets import QInputDialog

log = logging.getLogger(__name__)

__all__ = ["AnnotationTool", "AnnotationShape", "ShapeType"]


class ShapeType(Enum):
    """Types of annotation shapes."""
    BOX = "box"  # Rectangle with text
    LINE = "line"  # Simple line
    ARROW = "arrow"  # Arrow pointing right
    TEXT = "text"  # Standalone text


@dataclass
class AnnotationShape:
    """A single annotation shape on the timeline."""

    shape_type: ShapeType
    x_start: float  # Data coordinates (seconds)
    y_row: int  # Row index (0=bottom, 1=middle, 2=top)
    x_end: float | None = None  # For boxes, lines, arrows
    label: str = ""
    color: str = "#000000"
    fill_color: str = "#FFFFFF"
    linewidth: float = 1.0
    font_size: float = 8.0

    # Internal state (not serialized)
    _artists: list[Any] = field(default_factory=list, repr=False, compare=False)
    _selected: bool = field(default=False, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for project storage."""
        return {
            "shape_type": self.shape_type.value,
            "x_start": self.x_start,
            "y_row": self.y_row,
            "x_end": self.x_end,
            "label": self.label,
            "color": self.color,
            "fill_color": self.fill_color,
            "linewidth": self.linewidth,
            "font_size": self.font_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationShape:
        """Deserialize from dictionary."""
        return cls(
            shape_type=ShapeType(data["shape_type"]),
            x_start=data["x_start"],
            y_row=data["y_row"],
            x_end=data.get("x_end"),
            label=data.get("label", ""),
            color=data.get("color", "#000000"),
            fill_color=data.get("fill_color", "#FFFFFF"),
            linewidth=data.get("linewidth", 1.0),
            font_size=data.get("font_size", 8.0),
        )


class AnnotationTool:
    """Interactive tool for drawing protocol annotations above traces."""

    # Row positions (in axes coordinates, y > 1.0 is above plot)
    ROW_POSITIONS = [1.02, 1.08, 1.14]  # Bottom, middle, top
    ROW_HEIGHT = 0.04  # Height of each row in axes coordinates

    def __init__(self, axes: Axes, canvas: Any):
        """Initialize annotation tool.

        Args:
            axes: Matplotlib axes to draw on
            canvas: Qt canvas for event handling
        """
        self.axes = axes
        self.canvas = canvas

        self._shapes: list[AnnotationShape] = []
        self._active_tool: ShapeType | None = None
        self._drawing_shape: AnnotationShape | None = None
        self._drag_start: tuple[float, float] | None = None
        self._selected_shape: AnnotationShape | None = None

        # Event connections
        self._cid_press: int | None = None
        self._cid_release: int | None = None
        self._cid_motion: int | None = None

        self._enabled = False

    def set_active_tool(self, tool: ShapeType | None) -> None:
        """Set the active drawing tool."""
        self._active_tool = tool
        if tool is not None and not self._enabled:
            self._connect_events()
        elif tool is None and self._enabled:
            self._disconnect_events()

    def get_active_tool(self) -> ShapeType | None:
        """Get currently active tool."""
        return self._active_tool

    def add_shape(self, shape: AnnotationShape) -> None:
        """Add a shape and render it."""
        self._shapes.append(shape)
        self._render_shape(shape)
        self.canvas.draw_idle()

    def remove_shape(self, shape: AnnotationShape) -> None:
        """Remove a shape."""
        if shape in self._shapes:
            self._shapes.remove(shape)
            self._clear_shape_artists(shape)
            self.canvas.draw_idle()

    def clear_all(self) -> None:
        """Clear all shapes."""
        for shape in self._shapes:
            self._clear_shape_artists(shape)
        self._shapes.clear()
        self.canvas.draw_idle()

    def get_shapes(self) -> list[AnnotationShape]:
        """Get all shapes."""
        return self._shapes.copy()

    def set_shapes(self, shapes: list[AnnotationShape]) -> None:
        """Set shapes (e.g., loading from project)."""
        self.clear_all()
        self._shapes = shapes.copy()
        for shape in self._shapes:
            self._render_shape(shape)
        self.canvas.draw_idle()

    def _connect_events(self) -> None:
        """Connect mouse event handlers."""
        if self._enabled:
            return
        self._cid_press = self.canvas.mpl_connect("button_press_event", self._on_press)
        self._cid_release = self.canvas.mpl_connect("button_release_event", self._on_release)
        self._cid_motion = self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._enabled = True

    def _disconnect_events(self) -> None:
        """Disconnect mouse event handlers."""
        if not self._enabled:
            return
        if self._cid_press is not None:
            self.canvas.mpl_disconnect(self._cid_press)
        if self._cid_release is not None:
            self.canvas.mpl_disconnect(self._cid_release)
        if self._cid_motion is not None:
            self.canvas.mpl_disconnect(self._cid_motion)
        self._enabled = False

    def _on_press(self, event: MouseEvent) -> None:
        """Handle mouse press - start drawing."""
        if event.inaxes != self.axes or self._active_tool is None:
            return

        # Determine which row was clicked
        if event.ydata is None:
            return

        # Convert y position to row index
        y_axes = event.ydata
        row_idx = self._y_to_row(y_axes)

        if row_idx is None:
            return

        # Start drawing
        self._drag_start = (event.xdata, y_axes)
        self._drawing_shape = AnnotationShape(
            shape_type=self._active_tool,
            x_start=event.xdata,
            y_row=row_idx,
            x_end=event.xdata if self._active_tool != ShapeType.TEXT else None,
        )

    def _on_motion(self, event: MouseEvent) -> None:
        """Handle mouse motion - update drawing preview."""
        if self._drawing_shape is None or event.xdata is None:
            return

        # Update end position
        if self._drawing_shape.shape_type != ShapeType.TEXT:
            self._drawing_shape.x_end = event.xdata

        # Redraw preview (clear and re-render)
        self._clear_shape_artists(self._drawing_shape)
        self._render_shape(self._drawing_shape)
        self.canvas.draw_idle()

    def _on_release(self, event: MouseEvent) -> None:
        """Handle mouse release - finish drawing."""
        if self._drawing_shape is None:
            return

        # Finalize shape
        if self._drawing_shape.shape_type != ShapeType.TEXT:
            if event.xdata is not None:
                self._drawing_shape.x_end = event.xdata

        # Prompt for label if it's a box or text
        if self._drawing_shape.shape_type in {ShapeType.BOX, ShapeType.TEXT}:
            label, ok = QInputDialog.getText(
                None,
                "Add Label",
                f"Enter label for {self._drawing_shape.shape_type.value}:"
            )
            if ok and label:
                self._drawing_shape.label = label
            elif not ok:
                # User cancelled
                self._clear_shape_artists(self._drawing_shape)
                self._drawing_shape = None
                self.canvas.draw_idle()
                return

        # Add to shapes list
        self._shapes.append(self._drawing_shape)
        self._drawing_shape = None
        self._drag_start = None

        self.canvas.draw_idle()

    def _y_to_row(self, y_axes: float) -> int | None:
        """Convert axes y coordinate to row index."""
        # Check if click is in annotation area
        if y_axes < 1.0:
            return None

        # Find closest row
        for idx, row_y in enumerate(self.ROW_POSITIONS):
            if abs(y_axes - row_y) < self.ROW_HEIGHT:
                return idx

        # Default to top row if above all rows
        if y_axes > max(self.ROW_POSITIONS):
            return len(self.ROW_POSITIONS) - 1

        return 0  # Default to bottom row

    def _render_shape(self, shape: AnnotationShape) -> None:
        """Render a single shape on the axes."""
        transform = self.axes.get_xaxis_transform()
        y = self.ROW_POSITIONS[min(shape.y_row, len(self.ROW_POSITIONS) - 1)]

        if shape.shape_type == ShapeType.BOX:
            self._render_box(shape, y, transform)
        elif shape.shape_type == ShapeType.LINE:
            self._render_line(shape, y, transform)
        elif shape.shape_type == ShapeType.ARROW:
            self._render_arrow(shape, y, transform)
        elif shape.shape_type == ShapeType.TEXT:
            self._render_text(shape, y, transform)

    def _render_box(self, shape: AnnotationShape, y: float, transform: Any) -> None:
        """Render a box shape."""
        if shape.x_end is None:
            return

        width = abs(shape.x_end - shape.x_start)
        x_min = min(shape.x_start, shape.x_end)

        # Create fancy box
        box = FancyBboxPatch(
            xy=(x_min, y),
            width=width,
            height=self.ROW_HEIGHT,
            boxstyle="round,pad=0.01",
            transform=transform,
            facecolor=shape.fill_color,
            edgecolor=shape.color,
            linewidth=shape.linewidth,
            clip_on=False,
            zorder=20,
        )
        self.axes.add_patch(box)
        shape._artists.append(box)

        # Add text label
        if shape.label:
            text = self.axes.text(
                x_min + width / 2,
                y + self.ROW_HEIGHT / 2,
                shape.label,
                transform=transform,
                fontsize=shape.font_size,
                color=shape.color,
                ha="center",
                va="center",
                clip_on=False,
                zorder=30,
            )
            shape._artists.append(text)

    def _render_line(self, shape: AnnotationShape, y: float, transform: Any) -> None:
        """Render a line shape."""
        if shape.x_end is None:
            return

        line = self.axes.plot(
            [shape.x_start, shape.x_end],
            [y + self.ROW_HEIGHT / 2, y + self.ROW_HEIGHT / 2],
            color=shape.color,
            linewidth=shape.linewidth,
            transform=transform,
            clip_on=False,
            zorder=20,
        )[0]
        shape._artists.append(line)

    def _render_arrow(self, shape: AnnotationShape, y: float, transform: Any) -> None:
        """Render an arrow shape."""
        if shape.x_end is None:
            return

        dx = shape.x_end - shape.x_start
        dy = 0

        arrow = FancyArrow(
            shape.x_start,
            y + self.ROW_HEIGHT / 2,
            dx,
            dy,
            width=0.01,
            head_width=0.02,
            head_length=abs(dx) * 0.1,
            transform=transform,
            facecolor=shape.color,
            edgecolor=shape.color,
            linewidth=shape.linewidth,
            clip_on=False,
            zorder=20,
        )
        self.axes.add_patch(arrow)
        shape._artists.append(arrow)

    def _render_text(self, shape: AnnotationShape, y: float, transform: Any) -> None:
        """Render standalone text."""
        if not shape.label:
            return

        text = self.axes.text(
            shape.x_start,
            y + self.ROW_HEIGHT / 2,
            shape.label,
            transform=transform,
            fontsize=shape.font_size,
            color=shape.color,
            ha="center",
            va="center",
            clip_on=False,
            zorder=30,
        )
        shape._artists.append(text)

    def _clear_shape_artists(self, shape: AnnotationShape) -> None:
        """Remove matplotlib artists for a shape."""
        for artist in shape._artists:
            try:
                artist.remove()
            except Exception:
                pass
        shape._artists.clear()
