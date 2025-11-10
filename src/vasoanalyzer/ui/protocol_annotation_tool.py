"""Interactive protocol annotation tool for manual timeline markup.

Provides click-drag drawing tools for creating publication-ready protocol annotations:
- Boxes with text labels
- Lines and arrows
- Standalone text
- Icons and markers

Features:
- Click-drag to draw
- Click to select
- Drag to move
- Double-click to edit
- Delete to remove

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
from PyQt5.QtWidgets import QColorDialog, QInputDialog, QMenu
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

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

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point (x, y) is within this shape's bounds."""
        # Check row first
        row_y = AnnotationTool.ROW_POSITIONS[min(self.y_row, len(AnnotationTool.ROW_POSITIONS) - 1)]
        if abs(y - row_y) > AnnotationTool.ROW_HEIGHT:
            return False

        # Check x bounds
        if self.x_end is None:
            # TEXT shape - check if near x_start
            return abs(x - self.x_start) < 5.0  # 5 second tolerance
        else:
            # BOX, LINE, ARROW - check if within range
            x_min = min(self.x_start, self.x_end)
            x_max = max(self.x_start, self.x_end)
            return x_min <= x <= x_max

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
        self._dragging_shape: bool = False
        self._last_click_time: float = 0.0

        # Event connections
        self._cid_press: int | None = None
        self._cid_release: int | None = None
        self._cid_motion: int | None = None
        self._cid_key: int | None = None

        self._enabled = False

    def set_active_tool(self, tool: ShapeType | None) -> None:
        """Set the active drawing tool. None = selection mode."""
        self._active_tool = tool
        if not self._enabled:
            self._connect_events()

    def get_active_tool(self) -> ShapeType | None:
        """Get currently active tool."""
        return self._active_tool

    def enable_selection_mode(self) -> None:
        """Enable selection mode (no drawing tool active)."""
        self.set_active_tool(None)

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
            if self._selected_shape == shape:
                self._selected_shape = None
            self.canvas.draw_idle()

    def delete_selected(self) -> None:
        """Delete the currently selected shape."""
        if self._selected_shape is not None:
            self.remove_shape(self._selected_shape)

    def clear_all(self) -> None:
        """Clear all shapes."""
        for shape in self._shapes:
            self._clear_shape_artists(shape)
        self._shapes.clear()
        self._selected_shape = None
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

    def edit_selected_label(self) -> None:
        """Edit the label of the currently selected shape."""
        if self._selected_shape is None:
            return

        current_label = self._selected_shape.label
        label, ok = QInputDialog.getText(
            None,
            "Edit Label",
            f"Enter label for {self._selected_shape.shape_type.value}:",
            text=current_label
        )

        if ok:
            self._selected_shape.label = label
            self._redraw_shape(self._selected_shape)

    def change_selected_color(self) -> None:
        """Change the color of the currently selected shape."""
        if self._selected_shape is None:
            return

        # Parse current color
        current = QColor(self._selected_shape.color)
        color = QColorDialog.getColor(current, None, "Select Border Color")

        if color.isValid():
            self._selected_shape.color = color.name()
            self._redraw_shape(self._selected_shape)

    def change_selected_fill(self) -> None:
        """Change the fill color of the currently selected shape."""
        if self._selected_shape is None:
            return

        if self._selected_shape.shape_type != ShapeType.BOX:
            return  # Only boxes have fill

        current = QColor(self._selected_shape.fill_color)
        color = QColorDialog.getColor(current, None, "Select Fill Color")

        if color.isValid():
            self._selected_shape.fill_color = color.name()
            self._redraw_shape(self._selected_shape)

    def _connect_events(self) -> None:
        """Connect mouse event handlers."""
        if self._enabled:
            return
        self._cid_press = self.canvas.mpl_connect("button_press_event", self._on_press)
        self._cid_release = self.canvas.mpl_connect("button_release_event", self._on_release)
        self._cid_motion = self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._cid_key = self.canvas.mpl_connect("key_press_event", self._on_key)
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
        if self._cid_key is not None:
            self.canvas.mpl_disconnect(self._cid_key)
        self._enabled = False

    def _on_key(self, event) -> None:
        """Handle key press events."""
        if event.key == "delete" or event.key == "backspace":
            self.delete_selected()

    def _on_press(self, event: MouseEvent) -> None:
        """Handle mouse press - start drawing or select shape."""
        if event.inaxes != self.axes or event.xdata is None or event.ydata is None:
            return

        import time
        current_time = time.time()
        is_double_click = (current_time - self._last_click_time) < 0.3
        self._last_click_time = current_time

        # Double-click to edit
        if is_double_click and self._active_tool is None:
            self.edit_selected_label()
            return

        # Right-click for context menu
        if event.button == 3:  # Right click
            self._show_context_menu(event)
            return

        # Selection mode (no tool active)
        if self._active_tool is None:
            # Try to select a shape
            selected = self._find_shape_at(event.xdata, event.ydata)
            if selected:
                self._select_shape(selected)
                self._drag_start = (event.xdata, event.ydata)
                self._dragging_shape = True
            else:
                self._select_shape(None)
            return

        # Drawing mode
        row_idx = self._y_to_row(event.ydata)
        if row_idx is None:
            return

        self._drag_start = (event.xdata, event.ydata)
        self._drawing_shape = AnnotationShape(
            shape_type=self._active_tool,
            x_start=event.xdata,
            y_row=row_idx,
            x_end=event.xdata if self._active_tool != ShapeType.TEXT else None,
        )

    def _on_motion(self, event: MouseEvent) -> None:
        """Handle mouse motion - update drawing preview or move shape."""
        if event.xdata is None or event.ydata is None:
            return

        # Moving a selected shape
        if self._dragging_shape and self._selected_shape is not None and self._drag_start is not None:
            dx = event.xdata - self._drag_start[0]
            self._selected_shape.x_start += dx
            if self._selected_shape.x_end is not None:
                self._selected_shape.x_end += dx
            self._drag_start = (event.xdata, event.ydata)
            self._redraw_shape(self._selected_shape)
            return

        # Drawing a new shape
        if self._drawing_shape is None:
            return

        if self._drawing_shape.shape_type != ShapeType.TEXT:
            self._drawing_shape.x_end = event.xdata

        self._clear_shape_artists(self._drawing_shape)
        self._render_shape(self._drawing_shape)
        self.canvas.draw_idle()

    def _on_release(self, event: MouseEvent) -> None:
        """Handle mouse release - finish drawing or stop dragging."""
        # Stop dragging
        if self._dragging_shape:
            self._dragging_shape = False
            self._drag_start = None
            return

        # Finish drawing
        if self._drawing_shape is None:
            return

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
                self._clear_shape_artists(self._drawing_shape)
                self._drawing_shape = None
                self.canvas.draw_idle()
                return

        self._shapes.append(self._drawing_shape)
        self._drawing_shape = None
        self._drag_start = None
        self.canvas.draw_idle()

    def _find_shape_at(self, x: float, y: float) -> AnnotationShape | None:
        """Find shape at the given position."""
        # Search in reverse (top to bottom)
        for shape in reversed(self._shapes):
            if shape.contains_point(x, y):
                return shape
        return None

    def _select_shape(self, shape: AnnotationShape | None) -> None:
        """Select a shape (or deselect if None)."""
        # Deselect previous
        if self._selected_shape is not None:
            self._selected_shape._selected = False
            self._redraw_shape(self._selected_shape)

        # Select new
        self._selected_shape = shape
        if shape is not None:
            shape._selected = True
            self._redraw_shape(shape)

    def _show_context_menu(self, event: MouseEvent) -> None:
        """Show context menu for selected shape."""
        if self._selected_shape is None:
            return

        menu = QMenu()
        menu.addAction("Edit Label", self.edit_selected_label)
        menu.addAction("Change Color", self.change_selected_color)
        if self._selected_shape.shape_type == ShapeType.BOX:
            menu.addAction("Change Fill", self.change_selected_fill)
        menu.addSeparator()
        menu.addAction("Delete", self.delete_selected)

        # Show menu at cursor position
        cursor_pos = self.canvas.mapToGlobal(self.canvas.mapFromScene(event.x, event.y))
        menu.exec_(cursor_pos)

    def _redraw_shape(self, shape: AnnotationShape) -> None:
        """Redraw a single shape."""
        self._clear_shape_artists(shape)
        self._render_shape(shape)
        self.canvas.draw_idle()

    def _y_to_row(self, y_axes: float) -> int | None:
        """Convert axes y coordinate to row index."""
        if y_axes < 1.0:
            return None

        for idx, row_y in enumerate(self.ROW_POSITIONS):
            if abs(y_axes - row_y) < self.ROW_HEIGHT:
                return idx

        if y_axes > max(self.ROW_POSITIONS):
            return len(self.ROW_POSITIONS) - 1

        return 0

    def _render_shape(self, shape: AnnotationShape) -> None:
        """Render a single shape on the axes."""
        transform = self.axes.get_xaxis_transform()
        y = self.ROW_POSITIONS[min(shape.y_row, len(self.ROW_POSITIONS) - 1)]

        # Adjust rendering if selected (thicker border)
        linewidth = shape.linewidth
        if shape._selected:
            linewidth = shape.linewidth + 1.5

        if shape.shape_type == ShapeType.BOX:
            self._render_box(shape, y, transform, linewidth)
        elif shape.shape_type == ShapeType.LINE:
            self._render_line(shape, y, transform, linewidth)
        elif shape.shape_type == ShapeType.ARROW:
            self._render_arrow(shape, y, transform, linewidth)
        elif shape.shape_type == ShapeType.TEXT:
            self._render_text(shape, y, transform)

    def _render_box(self, shape: AnnotationShape, y: float, transform: Any, linewidth: float) -> None:
        """Render a box shape."""
        if shape.x_end is None:
            return

        width = abs(shape.x_end - shape.x_start)
        x_min = min(shape.x_start, shape.x_end)

        box = FancyBboxPatch(
            xy=(x_min, y),
            width=width,
            height=self.ROW_HEIGHT,
            boxstyle="round,pad=0.01",
            transform=transform,
            facecolor=shape.fill_color,
            edgecolor=shape.color,
            linewidth=linewidth,
            clip_on=False,
            zorder=20,
        )
        self.axes.add_patch(box)
        shape._artists.append(box)

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

    def _render_line(self, shape: AnnotationShape, y: float, transform: Any, linewidth: float) -> None:
        """Render a line shape."""
        if shape.x_end is None:
            return

        line = self.axes.plot(
            [shape.x_start, shape.x_end],
            [y + self.ROW_HEIGHT / 2, y + self.ROW_HEIGHT / 2],
            color=shape.color,
            linewidth=linewidth,
            transform=transform,
            clip_on=False,
            zorder=20,
        )[0]
        shape._artists.append(line)

    def _render_arrow(self, shape: AnnotationShape, y: float, transform: Any, linewidth: float) -> None:
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
            linewidth=linewidth,
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
