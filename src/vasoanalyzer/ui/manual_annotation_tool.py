"""Interactive figure-level annotation tools for the Figure Composer."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal

from matplotlib import patches
from matplotlib.artist import Artist
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.text import Text
from PyQt5.QtCore import QObject, pyqtSignal

__all__ = ["ManualAnnotationController", "FigureAnnotation"]

AnnotationKind = Literal["line", "arrow", "box", "textbox", "text"]


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def _normalize_point(point: tuple[float, float]) -> tuple[float, float]:
    return (_clamp(point[0]), _clamp(point[1]))


def _coerce_point(value: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    raw = value if isinstance(value, list | tuple) and len(value) >= 2 else fallback
    try:
        return (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError, IndexError):
        return fallback


def _to_float(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


LINESTYLES = {
    "solid": "solid",
    "dashed": "--",
    "dotted": ":",
    "dashdot": "-.",
}

ARROW_STYLES = {
    "arrow": "->",
    "bar": "-|>",
    "fancy": "fancy",
    "none": "-",
}


@dataclass
class FigureAnnotation:
    """Serializable model for a manual annotation."""

    id: str
    kind: AnnotationKind
    start: tuple[float, float]
    end: tuple[float, float] | None = None
    text: str = ""
    stroke: str = "#111111"
    fill: str | None = None
    text_color: str = "#111111"
    line_width: float = 2.0
    font_size: float = 12.0
    linestyle: str = "solid"
    arrow_style: str = "arrow"
    opacity: float = 0.95

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "start": list(self.start),
            "end": list(self.end) if self.end is not None else None,
            "text": self.text,
            "stroke": self.stroke,
            "fill": self.fill,
            "text_color": self.text_color,
            "line_width": self.line_width,
            "font_size": self.font_size,
            "linestyle": self.linestyle,
            "arrow_style": self.arrow_style,
            "opacity": self.opacity,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FigureAnnotation:
        start = _coerce_point(payload.get("start"), (0.1, 0.9))
        end_raw = payload.get("end")
        norm_end = _coerce_point(end_raw, start) if end_raw is not None else None
        return cls(
            id=str(payload.get("id") or uuid.uuid4()),
            kind=payload.get("kind", "line"),
            start=_normalize_point(start),
            end=_normalize_point(norm_end) if norm_end else None,
            text=str(payload.get("text", "")),
            stroke=str(payload.get("stroke", "#111111")),
            fill=payload.get("fill"),
            text_color=str(payload.get("text_color", payload.get("stroke", "#111111"))),
            line_width=_to_float(payload.get("line_width"), 2.0),
            font_size=_to_float(payload.get("font_size"), 12.0),
            linestyle=str(payload.get("linestyle", "solid")),
            arrow_style=str(payload.get("arrow_style", "arrow")),
            opacity=_to_float(payload.get("opacity"), 0.95),
        )

    @classmethod
    def create(
        cls,
        kind: AnnotationKind,
        start: tuple[float, float],
        *,
        defaults: dict[str, Any],
    ) -> FigureAnnotation:
        payload = dict(defaults)
        payload.setdefault("text", "Label")
        payload.setdefault("stroke", "#111111")
        payload.setdefault("fill", "#FFFFFF")
        payload.setdefault("text_color", payload["stroke"])
        payload.setdefault("line_width", 2.0)
        payload.setdefault("font_size", 14.0)
        payload.setdefault("linestyle", "solid")
        payload.setdefault("arrow_style", "arrow")
        payload.setdefault("opacity", 0.95)
        return cls(
            id=str(uuid.uuid4()),
            kind=kind,
            start=_normalize_point(start),
            end=_normalize_point(start),
            text=str(payload.get("text", "Label")),
            stroke=str(payload.get("stroke")),
            fill=payload.get("fill"),
            text_color=str(payload.get("text_color")),
            line_width=_to_float(payload.get("line_width"), 2.0),
            font_size=_to_float(payload.get("font_size"), 14.0),
            linestyle=str(payload.get("linestyle")),
            arrow_style=str(payload.get("arrow_style")),
            opacity=_to_float(payload.get("opacity"), 0.95),
        )


@dataclass
class _AnnotationArtists:
    drawables: list[Artist] = field(default_factory=list)
    text: Text | None = None


class ManualAnnotationController(QObject):
    """Manages interactive figure annotations on top of the canvas."""

    annotations_changed = pyqtSignal(list)
    selection_changed = pyqtSignal(object)
    edit_requested = pyqtSignal(str)

    def __init__(
        self,
        figure: Figure,
        canvas: FigureCanvasQTAgg,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.figure = figure
        self.canvas = canvas
        self._annotations: dict[str, FigureAnnotation] = {}
        self._artists: dict[str, _AnnotationArtists] = {}
        self._selection_artist: patches.Rectangle | None = None
        self._selected_id: str | None = None
        self._active_tool: AnnotationKind | Literal["select"] = "select"
        self._defaults: dict[str, Any] = {
            "stroke": "#111111",
            "fill": "#FFFFFF",
            "text_color": "#111111",
            "line_width": 2.0,
            "font_size": 14.0,
            "linestyle": "solid",
            "arrow_style": "arrow",
            "opacity": 0.95,
        }
        self._drawing_id: str | None = None
        self._dragging: bool = False
        self._press_point: tuple[float, float] | None = None
        self._drag_role: str | None = None
        self._resize_tolerance = 0.02  # figure fraction targeted for resize handles
        self._canvas_cids = {
            "press": canvas.mpl_connect("button_press_event", self._on_press),
            "release": canvas.mpl_connect("button_release_event", self._on_release),
            "motion": canvas.mpl_connect("motion_notify_event", self._on_motion),
            "key": canvas.mpl_connect("key_press_event", self._on_key),
        }
        self._last_draw_ts: float = 0.0

    # ------------------------------------------------------------------ public API
    def set_tool(self, tool: AnnotationKind | Literal["select"]) -> None:
        self._active_tool = tool
        if tool != "select":
            self._clear_selection()

    def set_style_defaults(self, **kwargs: Any) -> None:
        cleaned: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is None and key not in {"fill"}:
                continue
            cleaned[key] = value
            self._defaults[key] = value
        if cleaned:
            self._apply_style_to_selected(**cleaned)

    def load_annotations(self, payload: Sequence[dict[str, Any]]) -> None:
        self.clear()
        for entry in payload or []:
            try:
                model = FigureAnnotation.from_payload(entry)
            except Exception:
                continue
            self._annotations[model.id] = model
            self._artists[model.id] = self._create_artists(model)
        self._request_canvas_update(force=True)

    def serialize(self) -> list[dict[str, Any]]:
        return [annotation.to_payload() for annotation in self._annotations.values()]

    def clear(self) -> None:
        for artist_bundle in self._artists.values():
            self._remove_artists(artist_bundle)
        self._annotations.clear()
        self._artists.clear()
        self._clear_selection()
        self._request_canvas_update(force=True)

    def delete_selected(self) -> None:
        if not self._selected_id:
            return
        bundle = self._artists.pop(self._selected_id, None)
        if bundle:
            self._remove_artists(bundle)
        self._annotations.pop(self._selected_id, None)
        self._clear_selection()
        self._request_canvas_update(force=True)
        self.annotations_changed.emit(self.serialize())

    # ------------------------------------------------------------------ event handlers
    def _on_press(self, event):
        if event.button != 1:
            return
        fig_point = self._event_to_fig_point(event)
        if fig_point is None:
            return
        if event.dblclick:
            hit = self._hit_test(event)
            if hit:
                self.edit_requested.emit(hit)
            return
        if self._active_tool == "select":
            hit = self._hit_test(event)
            self._select(hit)
            if hit:
                resize_role = self._detect_resize_role(hit, fig_point)
                self._dragging = True
                self._press_point = fig_point
                self._drag_role = resize_role or "move"
            return
        self._begin_drawing(fig_point)

    def _on_motion(self, event):
        fig_point = self._event_to_fig_point(event)
        if fig_point is None:
            return
        if self._drawing_id:
            model = self._annotations.get(self._drawing_id)
            if not model:
                return
            if model.kind in {"line", "box", "textbox", "arrow"}:
                model.end = _normalize_point(fig_point)
                self._refresh_artists(model)
                self._request_canvas_update()
            return
        if self._dragging and self._selected_id:
            model = self._annotations.get(self._selected_id)
            if not model:
                return
            if self._drag_role and self._drag_role.startswith("resize"):
                self._handle_resize(model, fig_point)
            else:
                anchor = self._press_point or fig_point
                dx = fig_point[0] - anchor[0]
                dy = fig_point[1] - anchor[1]
                self._press_point = fig_point
                self._translate_annotation(model, dx, dy)
            self._refresh_artists(model)
            self._update_selection_artist()
            self._request_canvas_update()

    def _on_release(self, event):
        if event.button != 1:
            return
        if self._drawing_id:
            model = self._annotations.get(self._drawing_id)
            self._finalize_drawing(model)
            self._drawing_id = None
            self.annotations_changed.emit(self.serialize())
        if self._dragging:
            self._dragging = False
            self._press_point = None
            self._drag_role = None
            self.annotations_changed.emit(self.serialize())

    def _on_key(self, event):
        if event.key in {"delete", "backspace"}:
            self.delete_selected()
        if event.key in {"escape", "esc"} and self._drawing_id:
            self._cancel_drawing()

    # ------------------------------------------------------------------ helpers
    def _begin_drawing(self, start_point: tuple[float, float]) -> None:
        kind = self._active_tool if self._active_tool != "select" else "line"
        model = FigureAnnotation.create(kind, start_point, defaults=self._defaults)
        if model.kind == "text":
            model.end = None
        self._annotations[model.id] = model
        self._artists[model.id] = self._create_artists(model)
        self._drawing_id = model.id
        self._select(model.id)

    def _finalize_drawing(self, model: FigureAnnotation | None) -> None:
        if model is None:
            return
        if model.kind in {"box", "textbox"} and model.end is not None:
            if (
                abs(model.end[0] - model.start[0]) < 0.005
                or abs(model.end[1] - model.start[1]) < 0.005
            ):
                self._annotations.pop(model.id, None)
                bundle = self._artists.pop(model.id, None)
                if bundle:
                    self._remove_artists(bundle)
                self._clear_selection()
                self._request_canvas_update(force=True)
                return
            self._ensure_box_orientation(model)
        if model.kind in {"line", "arrow"} and model.end is not None:
            delta_x = abs(model.end[0] - model.start[0])
            delta_y = abs(model.end[1] - model.start[1])
            if max(delta_x, delta_y) < 0.002:
                self._annotations.pop(model.id, None)
                bundle = self._artists.pop(model.id, None)
                if bundle:
                    self._remove_artists(bundle)
                self._clear_selection()
                self._request_canvas_update(force=True)
                return
        if model.kind == "text" or model.kind == "textbox":
            self.edit_requested.emit(model.id)

    def _cancel_drawing(self) -> None:
        if not self._drawing_id:
            return
        bundle = self._artists.pop(self._drawing_id, None)
        if bundle:
            self._remove_artists(bundle)
        self._annotations.pop(self._drawing_id, None)
        self._drawing_id = None
        self._clear_selection()
        self._request_canvas_update(force=True)

    def _translate_annotation(self, model: FigureAnnotation, dx: float, dy: float) -> None:
        model.start = _normalize_point((model.start[0] + dx, model.start[1] + dy))
        if model.end is not None:
            model.end = _normalize_point((model.end[0] + dx, model.end[1] + dy))

    def _apply_style_to_selected(self, **kwargs: Any) -> None:
        if not self._selected_id:
            return
        model = self._annotations.get(self._selected_id)
        if not model:
            return
        for key, value in kwargs.items():
            if hasattr(model, key) and value is not None:
                setattr(model, key, value)
        self._refresh_artists(model)
        self._update_selection_artist()
        self._request_canvas_update()
        self.annotations_changed.emit(self.serialize())

    def _event_to_fig_point(self, event) -> tuple[float, float] | None:
        if event is None:
            return None
        try:
            inv = self.figure.transFigure.inverted()
            point = inv.transform((event.x, event.y))
            return (_clamp(point[0]), _clamp(point[1]))
        except Exception:
            return None

    def _hit_test(self, event) -> str | None:
        for annotation_id in reversed(list(self._artists.keys())):
            bundle = self._artists.get(annotation_id)
            if not bundle:
                continue
            for artist in [*(bundle.drawables or []), bundle.text]:
                if artist is None:
                    continue
                contains, _ = artist.contains(event)
                if contains:
                    return annotation_id
        return None

    def _select(self, annotation_id: str | None) -> None:
        if annotation_id == self._selected_id:
            return
        self._selected_id = annotation_id
        self._drag_role = None
        self._update_selection_artist()
        model = self._annotations.get(annotation_id) if annotation_id else None
        self.selection_changed.emit(model.to_payload() if model else None)

    def _clear_selection(self) -> None:
        self._selected_id = None
        self._dragging = False
        self._press_point = None
        self._drag_role = None
        self._update_selection_artist()
        self.selection_changed.emit(None)

    def _update_selection_artist(self) -> None:
        if not self._selected_id:
            if self._selection_artist is not None:
                self._selection_artist.remove()
            self._selection_artist = None
            self._request_canvas_update(force=True)
            return
        model = self._annotations.get(self._selected_id)
        if not model:
            return
        bounds = self._annotation_bounds(model)
        if bounds is None:
            return
        if self._selection_artist is None:
            self._selection_artist = patches.Rectangle(
                (bounds[0], bounds[1]),
                bounds[2],
                bounds[3],
                linewidth=1.2,
                edgecolor="#FF9800",
                facecolor="none",
                linestyle=(0, (4, 2)),
                zorder=500,
                transform=self.figure.transFigure,
            )
            self.figure.add_artist(self._selection_artist)
        else:
            self._selection_artist.set_bounds(bounds[0], bounds[1], bounds[2], bounds[3])

    def _annotation_bounds(
        self, model: FigureAnnotation
    ) -> tuple[float, float, float, float] | None:
        if model.kind in {"line", "arrow"}:
            if not model.end:
                return None
            min_x = min(model.start[0], model.end[0])
            min_y = min(model.start[1], model.end[1])
            width = max(0.01, abs(model.end[0] - model.start[0]))
            height = max(0.01, abs(model.end[1] - model.start[1]))
            return (min_x, min_y, width, height)
        if model.kind in {"box", "textbox"}:
            if not model.end:
                return None
            self._ensure_box_orientation(model)
            width = max(0.01, model.end[0] - model.start[0])
            height = max(0.01, model.end[1] - model.start[1])
            return (model.start[0], model.start[1], width, height)
        bundle = self._artists.get(model.id)
        target = bundle.text if bundle else None
        if target is None:
            return None
        renderer = self.canvas.get_renderer()
        if renderer is None:
            self.canvas.draw()
            renderer = self.canvas.get_renderer()
        if renderer is None:
            return None
        bbox = target.get_window_extent(renderer)
        inv = self.figure.transFigure.inverted()
        x0, y0 = inv.transform((bbox.x0, bbox.y0))
        x1, y1 = inv.transform((bbox.x1, bbox.y1))
        return (x0, y0, max(0.01, x1 - x0), max(0.01, y1 - y0))

    def _create_artists(self, model: FigureAnnotation) -> _AnnotationArtists:
        bundle = _AnnotationArtists()
        if model.kind == "line":
            line = Line2D(
                [model.start[0], (model.end or model.start)[0]],
                [model.start[1], (model.end or model.start)[1]],
                color=model.stroke,
                linewidth=model.line_width,
                linestyle=LINESTYLES.get(model.linestyle, "solid"),
                solid_capstyle="round",
                transform=self.figure.transFigure,
                zorder=210,
                alpha=model.opacity,
            )
            self.figure.add_artist(line)
            bundle.drawables.append(line)
        elif model.kind == "arrow":
            end = model.end or model.start
            arrow = patches.FancyArrowPatch(
                posA=model.start,
                posB=end,
                arrowstyle=ARROW_STYLES.get(model.arrow_style, "->"),
                linewidth=model.line_width,
                linestyle=LINESTYLES.get(model.linestyle, "solid"),
                color=model.stroke,
                mutation_scale=12 + model.line_width * 2,
                transform=self.figure.transFigure,
                zorder=215,
                alpha=model.opacity,
            )
            self.figure.add_artist(arrow)
            bundle.drawables.append(arrow)
        elif model.kind in {"box", "textbox"}:
            self._ensure_box_orientation(model)
            end = model.end or model.start
            x0 = model.start[0]
            y0 = model.start[1]
            width = max(0.0, end[0] - x0)
            height = max(0.0, end[1] - y0)
            rect = patches.Rectangle(
                (x0, y0),
                width,
                height,
                linewidth=model.line_width,
                edgecolor=model.stroke,
                facecolor=model.fill or (0, 0, 0, 0),
                linestyle=LINESTYLES.get(model.linestyle, "solid"),
                transform=self.figure.transFigure,
                zorder=180,
                alpha=model.opacity,
            )
            self.figure.add_artist(rect)
            bundle.drawables.append(rect)
            if model.kind == "textbox":
                text = self.figure.text(
                    x0 + width / 2.0,
                    y0 + height / 2.0,
                    model.text or "Label",
                    fontsize=model.font_size,
                    color=model.text_color,
                    ha="center",
                    va="center",
                    transform=self.figure.transFigure,
                    zorder=rect.get_zorder() + 2,
                )
                bundle.text = text
        elif model.kind == "text":
            text = self.figure.text(
                model.start[0],
                model.start[1],
                model.text or "Label",
                fontsize=model.font_size,
                color=model.text_color,
                ha="center",
                va="center",
                transform=self.figure.transFigure,
                zorder=220,
            )
            bundle.text = text
        self._request_canvas_update(force=True)
        return bundle

    def _refresh_artists(self, model: FigureAnnotation) -> None:
        bundle = self._artists.get(model.id)
        if not bundle:
            return
        if model.kind == "line" and bundle.drawables:
            line = bundle.drawables[0]
            if isinstance(line, Line2D):
                end = model.end or model.start
                line.set_data([model.start[0], end[0]], [model.start[1], end[1]])
                line.set_color(model.stroke)
                line.set_linewidth(model.line_width)
                line.set_linestyle(LINESTYLES.get(model.linestyle, "solid"))
                line.set_alpha(model.opacity)
        elif model.kind == "arrow" and bundle.drawables:
            arrow = bundle.drawables[0]
            if isinstance(arrow, patches.FancyArrowPatch):
                end = model.end or model.start
                arrow.set_positions(model.start, end)
                arrow.set_color(model.stroke)
                arrow.set_linewidth(model.line_width)
                arrow.set_linestyle(LINESTYLES.get(model.linestyle, "solid"))
                arrow.set_arrowstyle(ARROW_STYLES.get(model.arrow_style, "->"))
                arrow.set_alpha(model.opacity)
        elif model.kind in {"box", "textbox"} and bundle.drawables:
            rect = bundle.drawables[0]
            if isinstance(rect, patches.Rectangle):
                self._ensure_box_orientation(model)
                end = model.end or model.start
                x0 = model.start[0]
                y0 = model.start[1]
                width = max(0.0, end[0] - x0)
                height = max(0.0, end[1] - y0)
                rect.set_bounds(x0, y0, width, height)
                rect.set_edgecolor(model.stroke)
                rect.set_facecolor(model.fill or (0, 0, 0, 0))
                rect.set_linewidth(model.line_width)
                rect.set_linestyle(LINESTYLES.get(model.linestyle, "solid"))
                rect.set_alpha(model.opacity)
                if model.kind == "textbox" and bundle.text is not None:
                    bundle.text.set_position((x0 + width / 2.0, y0 + height / 2.0))
        elif model.kind == "text" and bundle.text is not None:
            bundle.text.set_position(model.start)
        if bundle.text is not None:
            bundle.text.set_text(model.text)
            bundle.text.set_fontsize(model.font_size)
            bundle.text.set_color(model.text_color)
        self._request_canvas_update()

    def _remove_artists(self, bundle: _AnnotationArtists) -> None:
        for artist in bundle.drawables:
            with suppress(Exception):
                artist.remove()
        if bundle.text is not None:
            with suppress(Exception):
                bundle.text.remove()

    def _request_canvas_update(self, *, force: bool = False) -> None:
        """Throttle expensive redraws to keep interactions snappy."""
        if force:
            self._last_draw_ts = time.monotonic()
            self.canvas.draw_idle()
            return
        now = time.monotonic()
        if now - self._last_draw_ts < (1.0 / 60.0):
            return
        self._last_draw_ts = now
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ resize helpers
    def _detect_resize_role(self, annotation_id: str, point: tuple[float, float]) -> str | None:
        model = self._annotations.get(annotation_id)
        if not model:
            return None
        point = _normalize_point(point)
        tol = self._resize_tolerance
        if model.kind in {"line", "arrow"} and model.end is not None:
            if self._distance(point, model.start) <= tol:
                return "resize_line_start"
            if self._distance(point, model.end) <= tol:
                return "resize_line_end"
        if model.kind in {"box", "textbox"} and model.end is not None:
            self._ensure_box_orientation(model)
            corners = {
                "resize_box_bl": (model.start[0], model.start[1]),
                "resize_box_tl": (model.start[0], model.end[1]),
                "resize_box_br": (model.end[0], model.start[1]),
                "resize_box_tr": (model.end[0], model.end[1]),
            }
            for role, corner in corners.items():
                if self._distance(point, corner) <= tol:
                    return role
        return None

    def _handle_resize(self, model: FigureAnnotation, point: tuple[float, float]) -> None:
        point = _normalize_point(point)
        role = self._drag_role
        if not role:
            return
        if model.kind in {"line", "arrow"}:
            if model.end is None:
                model.end = model.start
            if role == "resize_line_start":
                model.start = point
            elif role == "resize_line_end":
                model.end = point
        elif model.kind in {"box", "textbox"}:
            self._resize_box(model, point, role)
        elif model.kind == "text" and role == "resize_text":
            model.start = point
        self._press_point = point

    def _resize_box(self, model: FigureAnnotation, point: tuple[float, float], role: str) -> None:
        if model.end is None:
            model.end = model.start
        self._ensure_box_orientation(model)
        x0, y0 = model.start
        x1, y1 = model.end
        px, py = point
        gap = 0.001
        if role == "resize_box_bl":
            x0 = min(px, x1 - gap)
            y0 = min(py, y1 - gap)
        elif role == "resize_box_br":
            x1 = max(px, x0 + gap)
            y0 = min(py, y1 - gap)
        elif role == "resize_box_tl":
            x0 = min(px, x1 - gap)
            y1 = max(py, y0 + gap)
        elif role == "resize_box_tr":
            x1 = max(px, x0 + gap)
            y1 = max(py, y0 + gap)
        model.start = (_clamp(min(x0, x1)), _clamp(min(y0, y1)))
        model.end = (_clamp(max(x0, x1)), _clamp(max(y0, y1)))

    def _ensure_box_orientation(self, model: FigureAnnotation) -> None:
        if model.kind not in {"box", "textbox"} or model.end is None:
            return
        x0 = min(model.start[0], model.end[0])
        y0 = min(model.start[1], model.end[1])
        x1 = max(model.start[0], model.end[0])
        y1 = max(model.start[1], model.end[1])
        model.start = (_clamp(x0), _clamp(y0))
        model.end = (_clamp(x1), _clamp(y1))

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # ------------------------------------------------------------------ external updates
    def update_annotation_text(self, annotation_id: str, text: str) -> None:
        model = self._annotations.get(annotation_id)
        if not model:
            return
        model.text = text
        if model.kind in {"text", "textbox"}:
            self._refresh_artists(model)
            self._update_selection_artist()
            self._request_canvas_update()
            self.annotations_changed.emit(self.serialize())

    def selected_annotation_id(self) -> str | None:
        return self._selected_id
