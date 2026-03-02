"""Poster-focused renderer for trace-dominant figures (static)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PIL import Image

TRACE_RATIO = 0.8
TRACE_LINE_WIDTH = 3.6
TRACE_INNER_COLOR = "#000000"
TRACE_OUTER_COLOR = "#4d4d4d"
LABEL_FONT_SIZE = 16.0
TICK_FONT_SIZE = 13.0
GRID_ALPHA = 0.05


class PosterFigureRenderer:
    """Render a trace-dominant figure for posters/e-posters."""

    def __init__(self, output_width_px: int, output_height_px: int) -> None:
        self.output_width_px = int(output_width_px)
        self.output_height_px = int(output_height_px)

    def render(
        self,
        *,
        trace_model: object,
        start_time_s: float,
        end_time_s: float,
        show_inner: bool,
        show_outer: bool,
        y_range: tuple[float, float] | None,
        vessel_frame: np.ndarray | None,
        time_offset_s: float = 0.0,
    ) -> np.ndarray:
        trace_width = int(round(self.output_width_px * TRACE_RATIO))
        trace_width = max(1, min(self.output_width_px - 1, trace_width))
        vessel_width = self.output_width_px - trace_width
        trace_img = self._render_trace_panel(
            trace_model=trace_model,
            width_px=trace_width,
            height_px=self.output_height_px,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            show_inner=show_inner,
            show_outer=show_outer,
            y_range=y_range,
            time_offset_s=time_offset_s,
        )
        vessel_img = self._render_vessel_panel(
            vessel_frame=vessel_frame,
            width_px=vessel_width,
            height_px=self.output_height_px,
        )
        return np.hstack([trace_img, vessel_img])

    def _render_trace_panel(
        self,
        *,
        trace_model: object,
        width_px: int,
        height_px: int,
        start_time_s: float,
        end_time_s: float,
        show_inner: bool,
        show_outer: bool,
        y_range: tuple[float, float] | None,
        time_offset_s: float = 0.0,
    ) -> np.ndarray:
        dpi = 100
        fig_width_in = width_px / dpi
        fig_height_in = height_px / dpi
        fig = Figure(figsize=(fig_width_in, fig_height_in), dpi=dpi)
        ax = fig.add_subplot(111)
        canvas = FigureCanvasAgg(fig)

        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        level_index = 0
        try:
            level_index = trace_model.best_level_for_window(
                start_time_s,
                end_time_s,
                width_px,
            )
        except Exception:
            level_index = 0

        window = trace_model.window(
            level_index=level_index,
            x0=start_time_s,
            x1=end_time_s,
        )

        window_time = window.time
        if time_offset_s:
            window_time = window_time - float(time_offset_s)

        series = []
        if show_inner and window.inner_mean is not None:
            ax.plot(
                window_time,
                window.inner_mean,
                color=TRACE_INNER_COLOR,
                linewidth=TRACE_LINE_WIDTH,
                antialiased=True,
            )
            series.append(window.inner_mean)

        if show_outer and window.outer_mean is not None:
            ax.plot(
                window_time,
                window.outer_mean,
                color=TRACE_OUTER_COLOR,
                linewidth=TRACE_LINE_WIDTH,
                antialiased=True,
            )
            series.append(window.outer_mean)

        ax.set_xlim(start_time_s - time_offset_s, end_time_s - time_offset_s)
        if y_range is not None:
            ax.set_ylim(y_range)
        else:
            y_auto = self._auto_y_range(series)
            if y_auto is not None:
                ax.set_ylim(y_auto)

        ax.set_xlabel("Time (s)", fontsize=LABEL_FONT_SIZE, fontweight="bold", color="black")
        ax.set_ylabel("Diameter (um)", fontsize=LABEL_FONT_SIZE, fontweight="bold", color="black")
        ax.tick_params(labelsize=TICK_FONT_SIZE, colors="black")
        ax.grid(True, alpha=GRID_ALPHA, color="black")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

        fig.tight_layout()
        canvas.draw()
        img = self._canvas_to_rgb(canvas)
        return img

    def _render_vessel_panel(
        self,
        *,
        vessel_frame: np.ndarray | None,
        width_px: int,
        height_px: int,
    ) -> np.ndarray:
        if width_px <= 0 or height_px <= 0:
            return np.zeros((0, 0, 3), dtype=np.uint8)

        if vessel_frame is None:
            return np.full((height_px, width_px, 3), 255, dtype=np.uint8)

        frame = vessel_frame
        if frame.ndim == 2:
            frame = np.stack([frame, frame, frame], axis=2)
        elif frame.ndim == 3 and frame.shape[2] == 1:
            frame = np.repeat(frame, 3, axis=2)

        if frame.dtype != np.uint8:
            vmax = float(frame.max()) if frame.size else 0.0
            if vmax > 0:
                frame = (frame / vmax * 255).astype(np.uint8)
            else:
                frame = np.zeros_like(frame, dtype=np.uint8)

        pil_img = Image.fromarray(frame)
        src_w, src_h = pil_img.size
        if src_w <= 0 or src_h <= 0:
            return np.full((height_px, width_px, 3), 255, dtype=np.uint8)

        scale = min(width_px / src_w, height_px / src_h)
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        resized = pil_img.resize((new_w, new_h), resample=Image.NEAREST)

        bg = Image.new("RGB", (width_px, height_px), color=(255, 255, 255))
        left = (width_px - new_w) // 2
        top = (height_px - new_h) // 2
        bg.paste(resized, (left, top))
        return np.array(bg)

    @staticmethod
    def _auto_y_range(series: Iterable[np.ndarray]) -> tuple[float, float] | None:
        values = [arr for arr in series if arr is not None and np.asarray(arr).size]
        if not values:
            return None
        data = np.concatenate(values)
        if data.size == 0 or not np.isfinite(data).any():
            return None
        y_min = float(np.nanmin(data))
        y_max = float(np.nanmax(data))
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return None
        if y_min == y_max:
            pad = max(abs(y_min) * 0.05, 1.0)
        else:
            pad = (y_max - y_min) * 0.05
        return (y_min - pad, y_max + pad)

    @staticmethod
    def _canvas_to_rgb(canvas: FigureCanvasAgg) -> np.ndarray:
        buf = np.asarray(canvas.buffer_rgba())
        if buf.shape[2] == 4:
            return buf[:, :, :3].copy()
        return buf.copy()
