"""Matplotlib trace view with level-of-detail rendering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory

from vasoanalyzer.core.trace_model import TraceModel, TraceWindow
from vasoanalyzer.ui.theme import CURRENT_THEME


@dataclass
class EventLayer:
    times: np.ndarray
    colors: np.ndarray
    labels: np.ndarray | None = None


class TraceView:
    """Owns the Matplotlib artists used to render diameter traces."""

    def __init__(
        self,
        ax: Axes,
        canvas: FigureCanvasQTAgg,
        *,
        mode: str = "dual",
        y_label: str | None = None,
    ) -> None:
        if mode not in {"inner", "outer", "dual", "avg_pressure", "set_pressure"}:
            raise ValueError(f"Unsupported trace view mode: {mode}")
        self.ax = ax
        self.canvas = canvas
        self.ax2: Axes | None = None
        self.model: TraceModel | None = None
        self.inner_line: Line2D | None = None
        self.outer_line: Line2D | None = None
        self.inner_band: PolyCollection | None = None
        self.outer_band: PolyCollection | None = None
        self.event_collection: LineCollection | None = None
        self._background = None
        self._last_xlim: tuple[float, float] | None = None
        self._event_layer: EventLayer | None = None
        self._current_window: TraceWindow | None = None
        self._mode = mode
        self._explicit_ylabel = y_label
        self._draw_cid = self.canvas.mpl_connect("draw_event", self._on_canvas_draw)
        self._ensure_base_artists()

    def _ensure_base_artists(self) -> None:
        # Set different colors for different modes
        if self._mode == "avg_pressure":
            line_color = "tab:blue"
        elif self._mode == "set_pressure":
            line_color = "tab:purple"
        elif self._mode == "outer":
            line_color = "tab:orange"
        else:
            line_color = "k"  # black for inner

        if self.inner_line is None:
            self.inner_line = Line2D([], [], color=line_color, linewidth=1.5, animated=True)
            self.ax.add_line(self.inner_line)
        else:
            # Update color if mode changed
            self.inner_line.set_color(line_color)

        if self.inner_band is None:
            band = PolyCollection(
                [],
                facecolors=[CURRENT_THEME.get("accent_fill", "#BBD7FF")],
                edgecolors="none",
                alpha=0.3,
                animated=True,
            )
            self.inner_band = band
            self.ax.add_collection(band)
        if self.event_collection is None:
            transform = blended_transform_factory(self.ax.transData, self.ax.transAxes)
            col = LineCollection(
                [],
                colors=[CURRENT_THEME.get("event_line", "#8A8A8A")],
                linewidths=1.2,
                linestyles=[(0, (4, 4))],
                alpha=0.75,
                transform=transform,
                animated=True,
            )
            col.set_zorder(5.0)
            col.set_clip_on(False)
            self.event_collection = col
            self.ax.add_collection(col)
        if self._mode == "dual":
            if self.outer_line is None:
                line = Line2D([], [], color="tab:orange", linewidth=1.2, animated=True)
                self.outer_line = line
            if self.outer_band is None:
                band = PolyCollection(
                    [],
                    facecolors=[CURRENT_THEME.get("accent_fill_secondary", "#FFD1A9")],
                    edgecolors="none",
                    alpha=0.2,
                    animated=True,
                )
                self.outer_band = band
        else:
            self.outer_line = None
            self.outer_band = None

    def set_model(self, model: TraceModel) -> None:
        self.model = model
        if self._mode == "dual":
            self._setup_secondary_axis(model)
        else:
            if self.ax2 is not None:
                self.ax2.remove()
                self.ax2 = None
        if not (self.ax.get_xlabel() or "").strip():
            self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel(self._explicit_ylabel or self._default_ylabel())
        self.ax.grid(True, color=CURRENT_THEME["grid_color"])
        self._last_xlim = None
        self._background = None
        self._current_window = None

    def _setup_secondary_axis(self, model: TraceModel) -> None:
        if self._mode != "dual":
            return
        if model.outer_full is None:
            if self.ax2 is not None:
                self.ax2.remove()
                self.ax2 = None
                self.outer_line = None
                self.outer_band = None
            return
        if self.ax2 is None:
            self.ax2 = self.ax.twinx()
            self.ax2.set_ylabel("Outer Diameter (µm)")
            self.ax2.tick_params(colors=CURRENT_THEME["text"])
        if self.outer_line is not None and self.outer_line.axes is not self.ax2:
            self.ax2.add_line(self.outer_line)
        if self.outer_band is not None and self.outer_band.axes is not self.ax2:
            self.ax2.add_collection(self.outer_band)

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
    ) -> None:
        if not times:
            self._event_layer = None
            if self.event_collection is not None:
                self.event_collection.set_segments([])
            return
        times_arr = np.asarray(times, dtype=float)
        if colors is None:
            colors_arr = np.full_like(
                times_arr, CURRENT_THEME.get("event_line", "#8A8A8A"), dtype=object
            )
        else:
            colors_arr = np.asarray(list(colors), dtype=object)
        labels_arr = None
        if labels is not None:
            labels_arr = np.asarray(list(labels), dtype=object)
        self._event_layer = EventLayer(times=times_arr, colors=colors_arr, labels=labels_arr)
        self._update_events(None)

    def update_window(self, x0: float, x1: float, *, pixel_width: int | None = None) -> None:
        if self.model is None:
            return
        if pixel_width is None:
            bbox = self.ax.bbox
            pixel_width = max(int(bbox.width), 1)
        level_idx = self.model.best_level_for_window(x0, x1, pixel_width)
        window = self.model.window(level_idx, x0, x1)
        self._current_window = window
        self._apply_window(window)
        self._update_events(window)
        self._last_xlim = (x0, x1)

    def _default_ylabel(self) -> str:
        if self._mode == "outer":
            return "Outer Diameter (µm)"
        elif self._mode == "avg_pressure":
            return "Avg Pressure (mmHg)"
        elif self._mode == "set_pressure":
            return "Set Pressure (mmHg)"
        return "Inner Diameter (µm)"

    def _primary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        if self._mode == "outer":
            if window.outer_mean is None or window.outer_min is None or window.outer_max is None:
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        elif self._mode == "avg_pressure":
            if window.avg_pressure_mean is None or window.avg_pressure_min is None or window.avg_pressure_max is None:
                return None
            return window.avg_pressure_mean, window.avg_pressure_min, window.avg_pressure_max
        elif self._mode == "set_pressure":
            if window.set_pressure_mean is None or window.set_pressure_min is None or window.set_pressure_max is None:
                return None
            return window.set_pressure_mean, window.set_pressure_min, window.set_pressure_max
        return window.inner_mean, window.inner_min, window.inner_max

    def _secondary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        if self._mode == "dual":
            if window.outer_mean is None or window.outer_min is None or window.outer_max is None:
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        return None

    def _apply_window(self, window: TraceWindow) -> None:
        time = window.time
        if time.size == 0:
            return
        primary = self._primary_series(window)
        if primary is None or self.inner_line is None or self.inner_band is None:
            if self.inner_line is not None:
                self.inner_line.set_data([], [])
            if self.inner_band is not None:
                self.inner_band.set_verts([])
            return
        mean, ymin, ymax = primary
        self.inner_line.set_data(time, mean)
        # Disable uncertainty bands - show raw data only (no shadow effect)
        self.inner_band.set_verts([])

        y_min = np.nanmin(ymin)
        y_max = np.nanmax(ymax)

        secondary = self._secondary_series(window)
        if secondary and self.outer_line and self.outer_band:
            mean2, ymin2, ymax2 = secondary
            self.outer_line.set_data(time, mean2)
            # Disable outer uncertainty bands too
            self.outer_band.set_verts([])
            y_min = min(y_min, np.nanmin(ymin2))
            y_max = max(y_max, np.nanmax(ymax2))
        elif self.outer_line:
            self.outer_line.set_data([], [])
            if self.outer_band:
                self.outer_band.set_verts([])
        if self.ax.get_autoscaley_on():
            self.ax.set_ylim(y_min, y_max)
        ax2 = self.ax2
        if ax2 is not None and secondary:
            get_auto = getattr(ax2, "get_autoscaley_on", None)
            if get_auto is None or get_auto():
                ax2.set_ylim(y_min, y_max)
        self._draw_artists()

    def _update_events(self, window: TraceWindow | None) -> None:
        if self._event_layer is None or self.event_collection is None:
            return
        times = self._event_layer.times
        if times.size == 0:
            self.event_collection.set_segments([])
            return
        x0, x1 = self.ax.get_xlim()
        mask = (times >= x0) & (times <= x1)
        if not np.any(mask):
            self.event_collection.set_segments([])
            return
        indices = np.flatnonzero(mask)
        if indices.size == 0:
            self.event_collection.set_segments([])
            return
        ordered = indices[np.argsort(times[indices])]
        segments = [((float(times[idx]), 0.0), (float(times[idx]), 1.0)) for idx in ordered]
        self.event_collection.set_segments(segments)
        colors = self._event_layer.colors
        try:
            if colors.size == times.size:
                color_subset = colors[ordered]
                self.event_collection.set_colors(list(color_subset))
            elif colors.size:
                self.event_collection.set_colors([colors[0]])
        except Exception:
            pass

    def current_window(self) -> TraceWindow | None:
        """Return the most recently rendered window."""

        return self._current_window

    def data_limits(self) -> tuple[float, float] | None:
        """Return data limits for the active component in the current window."""

        window = self._current_window
        if window is None:
            return None

        if self._mode == "outer":
            series_min = window.outer_min
            series_max = window.outer_max
        elif self._mode == "avg_pressure":
            series_min = window.avg_pressure_min
            series_max = window.avg_pressure_max
        elif self._mode == "set_pressure":
            series_min = window.set_pressure_min
            series_max = window.set_pressure_max
        elif self._mode == "dual":
            parts = []
            if window.inner_min is not None and window.inner_max is not None:
                parts.append(
                    (
                        np.nanmin(window.inner_min),
                        np.nanmax(window.inner_max),
                    )
                )
            if window.outer_min is not None and window.outer_max is not None:
                parts.append(
                    (
                        np.nanmin(window.outer_min),
                        np.nanmax(window.outer_max),
                    )
                )
            if not parts:
                return None
            ymin = min(p[0] for p in parts)
            ymax = max(p[1] for p in parts)
            if not np.isfinite(ymin) or not np.isfinite(ymax):
                return None
            return float(ymin), float(ymax)
        else:
            series_min = window.inner_min
            series_max = window.inner_max

        if series_min is None or series_max is None:
            return None

        try:
            ymin = float(np.nanmin(series_min))
            ymax = float(np.nanmax(series_max))
        except ValueError:
            return None

        if not np.isfinite(ymin) or not np.isfinite(ymax):
            return None
        return ymin, ymax

    def _draw_artists(self) -> None:
        canvas = self.canvas
        ax = self.ax
        figure_bbox = ax.figure.bbox
        if self._background is None:
            if getattr(canvas, "renderer", None) is None:
                canvas.draw()
            self._background = canvas.copy_from_bbox(figure_bbox)
        else:
            canvas.restore_region(self._background)
        if self.inner_band is not None:
            ax.draw_artist(self.inner_band)
        if self.inner_line is not None:
            ax.draw_artist(self.inner_line)
        if self.event_collection is not None:
            ax.draw_artist(self.event_collection)
        if self.ax2 is not None:
            if self.outer_band is not None:
                self.ax2.draw_artist(self.outer_band)
            if self.outer_line is not None:
                self.ax2.draw_artist(self.outer_line)
        canvas.blit(figure_bbox)

    def refresh_background(self) -> None:
        self._background = None

    def current_xlim(self) -> tuple[float, float] | None:
        return self._last_xlim

    def _on_canvas_draw(self, event) -> None:
        if event is not None and event.canvas is not self.canvas:
            return
        if getattr(self.canvas, "renderer", None) is None:
            return
        try:
            self._background = self.canvas.copy_from_bbox(self.ax.figure.bbox)
        except Exception:
            self._background = None
            return
        if self._current_window is None:
            return
        self._draw_artists()


def _band_vertices(x: np.ndarray, y_min: np.ndarray, y_max: np.ndarray) -> np.ndarray:
    upper = np.column_stack((x, y_max))
    lower = np.column_stack((x[::-1], y_min[::-1]))
    return np.vstack([upper, lower])
