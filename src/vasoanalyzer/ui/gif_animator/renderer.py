"""Pure rendering functions for GIF animation (no Qt dependencies).

This module provides the core rendering logic for creating animated GIFs,
following the spec-based architecture pattern used across the UI.
"""

from collections.abc import Callable
from dataclasses import dataclass

import matplotlib
import numpy as np

matplotlib.use("Agg")  # Use non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from .frame_synchronizer import FrameTimingInfo
from .specs import AnimationSpec

ACTIVE_LINE_SCALE = 1.25
INACTIVE_LINE_SCALE = 0.85
INACTIVE_LINE_ALPHA = 0.6
ACTIVE_MARKER_SIZE = 110
ACTIVE_MARKER_RADIUS_PX = 7


@dataclass
class EventSpec:
    """Event marker specification for rendering."""

    time_s: float
    label: str
    color: str


@dataclass
class RenderContext:
    """Context data needed for rendering (similar to FigureSpec's RenderContext)."""

    trace_model: object  # TraceModel instance
    vessel_frames: np.ndarray  # TIFF stack subset (n_frames, H, W)
    events: list[EventSpec]  # Event markers
    sample_name: str = ""


class AnimationRenderer:
    """Pure renderer for creating GIF frames (independent of Qt for testing)."""

    def __init__(self, spec: AnimationSpec):
        """Initialize renderer with animation specification.

        Args:
            spec: AnimationSpec defining all rendering parameters
        """
        self.spec = spec
        self._trace_cache = None
        self._time_offset_s = 0.0
        if getattr(self.spec, "display_time_zero", False):
            try:
                self._time_offset_s = float(self.spec.start_time_s)
            except Exception:
                self._time_offset_s = 0.0

    def _display_time(self, t_val: float) -> float:
        if not self._time_offset_s:
            return float(t_val)
        return float(t_val) - self._time_offset_s

    def _display_times(self, arr: np.ndarray) -> np.ndarray:
        if not self._time_offset_s:
            return arr
        return arr - self._time_offset_s

    def render_frame(
        self,
        ctx: RenderContext,
        timing: FrameTimingInfo,
    ) -> np.ndarray:
        """Render a single animation frame as RGB numpy array.

        Args:
            ctx: RenderContext with trace model and vessel frames
            timing: FrameTimingInfo specifying which frame to render

        Returns:
            np.ndarray with shape (height, width, 3) and dtype uint8
        """
        # Render vessel panel
        vessel_img = self._render_vessel_panel(ctx, timing)

        # Render trace panel
        trace_img = self._render_trace_panel(ctx, timing)

        # Composite based on layout mode
        if self.spec.layout_mode == "side_by_side":
            if vessel_img.shape[0] != trace_img.shape[0]:
                target_h = max(vessel_img.shape[0], trace_img.shape[0])
                vessel_img = self._pad_to_height(vessel_img, target_h)
                trace_img = self._pad_to_height(trace_img, target_h)
            if self.spec.vessel_position == "left":
                composite = np.hstack([vessel_img, trace_img])
            else:
                composite = np.hstack([trace_img, vessel_img])
        else:  # stacked
            if vessel_img.shape[1] != trace_img.shape[1]:
                target_w = max(vessel_img.shape[1], trace_img.shape[1])
                vessel_img = self._pad_to_width(vessel_img, target_w)
                trace_img = self._pad_to_width(trace_img, target_w)
            composite = np.vstack([vessel_img, trace_img])

        return composite

    def _render_vessel_panel(
        self,
        ctx: RenderContext,
        timing: FrameTimingInfo,
    ) -> np.ndarray:
        """Render vessel frame with optional overlays.

        Returns:
            RGB numpy array of shape (vessel_height_px, vessel_width_px, 3)
        """
        # Get the appropriate TIFF frame
        frame_idx = timing.tiff_frame_index
        vessel_frame = ctx.vessel_frames[frame_idx]

        crop = getattr(self.spec, "vessel_crop_rect", None)
        if crop:
            x, y, w, h = crop
            x = max(0, int(x))
            y = max(0, int(y))
            w = max(1, int(w))
            h = max(1, int(h))
            y2 = min(vessel_frame.shape[0], y + h)
            x2 = min(vessel_frame.shape[1], x + w)
            if y2 > y and x2 > x:
                vessel_frame = vessel_frame[y:y2, x:x2]
        if self.spec.layout_mode == "stacked":
            vessel_frame = np.rot90(vessel_frame, k=1)

        # Convert to RGB if grayscale
        if vessel_frame.ndim == 2:
            vessel_frame = np.stack([vessel_frame, vessel_frame, vessel_frame], axis=2)
        elif vessel_frame.ndim == 3 and vessel_frame.shape[2] == 1:
            vessel_frame = np.repeat(vessel_frame, 3, axis=2)

        # Ensure uint8
        if vessel_frame.dtype != np.uint8:
            vmax = float(vessel_frame.max()) if vessel_frame.size else 0.0
            if vmax > 0:
                vessel_frame = (vessel_frame / vmax * 255).astype(np.uint8)
            else:
                vessel_frame = np.zeros_like(vessel_frame, dtype=np.uint8)

        # Resize to target dimensions (preserve aspect ratio)
        from PIL import Image

        pil_img = Image.fromarray(vessel_frame)

        # Map interpolation mode to PIL
        interpolation_map = {
            "nearest": Image.NEAREST,
            "bilinear": Image.BILINEAR,
            "bicubic": Image.BICUBIC,
        }
        interp_mode = interpolation_map.get(self.spec.vessel_interpolation, Image.BILINEAR)

        src_w, src_h = pil_img.size
        target_w = self.spec.vessel_width_px
        target_h = self.spec.vessel_height_px
        content_h = target_h
        if self.spec.layout_mode == "side_by_side" and self.spec.trace_spec.shape == "wide":
            ratio = self._wide_trace_height_ratio()
            content_h = max(1, int(round(target_h * ratio)))
        fit_mode = getattr(self.spec, "vessel_fit", "cover")
        if fit_mode == "contain":
            scale = min(target_w / src_w, content_h / src_h)
        else:
            scale = max(target_w / src_w, content_h / src_h)
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        pil_img = pil_img.resize((new_w, new_h), resample=interp_mode)

        if fit_mode == "contain" and (new_w != target_w or new_h != target_h):
            bg = Image.new(
                "RGB",
                (target_w, target_h),
                color=self._hex_to_rgb(self.spec.vessel_bg_color),
            )
            left = (target_w - new_w) // 2
            top = (target_h - new_h) // 2
            bg.paste(pil_img, (left, top))
            vessel_resized = np.array(bg)
        elif fit_mode != "contain" and (new_w != target_w or new_h != target_h):
            left = max(0, (new_w - target_w) // 2)
            top = max(0, (new_h - target_h) // 2)
            right = left + target_w
            bottom = top + target_h
            pil_img = pil_img.crop((left, top, right, bottom))
            vessel_resized = np.array(pil_img)
        else:
            vessel_resized = np.array(pil_img)

        # Add text overlays if requested
        if self.spec.vessel_show_timestamp or self.spec.vessel_show_frame_number:
            vessel_resized = self._add_vessel_overlays(vessel_resized, timing, frame_idx)

        return vessel_resized

    def _add_vessel_overlays(
        self,
        img: np.ndarray,
        timing: FrameTimingInfo,
        frame_idx: int,
    ) -> np.ndarray:
        """Add timestamp/frame number overlays to vessel image."""
        from PIL import Image, ImageDraw, ImageFont

        pil_img = Image.fromarray(img)
        draw = ImageDraw.Draw(pil_img)

        # Try to use a nice font, fall back to default
        try:
            font = ImageFont.truetype("Arial.ttf", int(self.spec.vessel_timestamp_fontsize))
        except:
            font = ImageFont.load_default()

        # Build overlay text
        text_lines = []
        if self.spec.vessel_show_timestamp:
            display_time = self._display_time(timing.trace_time_s)
            text_lines.append(f"t = {display_time:.3f}s")
        if self.spec.vessel_show_frame_number:
            text_lines.append(f"Frame {frame_idx}")

        # Draw text in top-left corner
        y_offset = 5
        for line in text_lines:
            # Draw black outline for visibility
            for offset in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text((5 + offset[0], y_offset + offset[1]), line, fill=(0, 0, 0), font=font)
            # Draw white text
            color_rgb = self._hex_to_rgb(self.spec.vessel_timestamp_color)
            draw.text((5, y_offset), line, fill=color_rgb, font=font)
            y_offset += int(self.spec.vessel_timestamp_fontsize * 1.5)

        return np.array(pil_img)

    def _render_trace_panel(
        self,
        ctx: RenderContext,
        timing: FrameTimingInfo,
    ) -> np.ndarray:
        """Render trace plot with progressive data reveal.

        Returns:
            RGB numpy array of shape (trace_height_px, trace_width_px, 3)
        """
        spec = self.spec.trace_spec
        if spec.fast_render:
            return self._render_trace_panel_fast(ctx, timing)

        # Create matplotlib figure
        dpi = 100
        fig_width_in = self.spec.trace_width_px / dpi
        fig_height_in = self.spec.trace_height_px / dpi

        fig = Figure(figsize=(fig_width_in, fig_height_in), dpi=dpi)
        ax = fig.add_subplot(111)
        # Attach an Agg canvas so buffer methods are available.
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        canvas = FigureCanvasAgg(fig)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # Extract progressive trace window (from start to current time)
        level_index = 0
        try:
            level_index = ctx.trace_model.best_level_for_window(
                self.spec.start_time_s,
                timing.trace_time_s,
                self.spec.trace_width_px,
            )
        except Exception:
            level_index = 0

        window = ctx.trace_model.window(
            level_index=level_index,
            x0=self.spec.start_time_s,
            x1=timing.trace_time_s,
        )
        window_time = self._display_times(window.time)

        active_channel = None
        if spec.show_inner and window.inner_mean is not None:
            active_channel = "inner"
        elif spec.show_outer and window.outer_mean is not None:
            active_channel = "outer"

        # Plot inner diameter
        if spec.show_inner and window.inner_mean is not None:
            if active_channel == "inner":
                line_width = spec.line_width * ACTIVE_LINE_SCALE
                line_alpha = 1.0
            elif active_channel is None:
                line_width = spec.line_width
                line_alpha = 1.0
            else:
                line_width = spec.line_width * INACTIVE_LINE_SCALE
                line_alpha = INACTIVE_LINE_ALPHA
            ax.plot(
                window_time,
                window.inner_mean,
                color=spec.inner_color,
                linewidth=line_width,
                alpha=line_alpha,
                label="Inner Diameter",
                antialiased=spec.antialias,
            )

        # Plot outer diameter
        if spec.show_outer and window.outer_mean is not None:
            if active_channel == "outer":
                line_width = spec.line_width * ACTIVE_LINE_SCALE
                line_alpha = 1.0
            elif active_channel is None:
                line_width = spec.line_width
                line_alpha = 1.0
            else:
                line_width = spec.line_width * INACTIVE_LINE_SCALE
                line_alpha = INACTIVE_LINE_ALPHA
            ax.plot(
                window_time,
                window.outer_mean,
                color=spec.outer_color,
                linewidth=line_width,
                alpha=line_alpha,
                label="Outer Diameter",
                antialiased=spec.antialias,
            )

        # Plot pressure channels (if available)
        if spec.show_avg_pressure and window.avg_pressure_mean is not None:
            # Create second y-axis for pressure
            ax2 = ax.twinx()
            ax2.plot(
                window_time,
                window.avg_pressure_mean,
                color=spec.avg_pressure_color,
                linewidth=spec.line_width,
                label="Avg Pressure",
                linestyle="--",
                antialiased=spec.antialias,
            )
            ax2.set_ylabel(
                "Pressure (mmHg)",
                fontsize=spec.label_fontsize,
                color="black",
                fontweight="bold",
            )

        # Add event markers
        if spec.show_events:
            for event in ctx.events:
                if event.time_s <= timing.trace_time_s:
                    event_time = self._display_time(event.time_s)
                    ax.axvline(
                        event_time,
                        color=event.color,
                        linewidth=1.0,
                        linestyle="--",
                        alpha=0.5,
                        zorder=50,
                        antialiased=spec.antialias,
                    )
                    if spec.show_event_labels:
                        y_pos = ax.get_ylim()[1] * 0.95
                        ax.text(
                            event_time,
                            y_pos,
                            event.label,
                            rotation=90,
                            va="top",
                            ha="right",
                            fontsize=spec.event_label_fontsize,
                            color=event.color,
                        )

        # Set axis limits
        if spec.x_range is not None:
            x_min, x_max = spec.x_range
            ax.set_xlim(x_min, x_max)
        else:
            x_min = self._display_time(self.spec.start_time_s)
            x_max = self._display_time(self.spec.end_time_s)
            ax.set_xlim(x_min, x_max)

        if spec.y_range is not None:
            ax.set_ylim(spec.y_range)

        # Add time indicator (vertical line at current time)
        if spec.show_time_indicator:
            linestyle_map = {
                "solid": "-",
                "dashed": "--",
                "dotted": ":",
            }
            t_val = self._display_time(timing.trace_time_s)
            if np.isfinite(t_val):
                if t_val < x_min:
                    t_val = x_min
                elif t_val > x_max:
                    t_val = x_max
                ax.axvline(
                    t_val,
                    color=spec.indicator_color,
                    linewidth=spec.indicator_width,
                    linestyle=linestyle_map.get(spec.indicator_style, "-"),
                    zorder=100,
                    antialiased=spec.antialias,
                )
                marker_series = None
                if active_channel == "inner" and window.inner_mean is not None:
                    marker_series = window.inner_mean
                elif active_channel == "outer" and window.outer_mean is not None:
                    marker_series = window.outer_mean
                if marker_series is not None and window.time.size:
                    idx = int(np.argmin(np.abs(window_time - t_val)))
                    y_val = float(marker_series[idx])
                    if np.isfinite(y_val):
                        ax.scatter(
                            [window_time[idx]],
                            [y_val],
                            s=ACTIVE_MARKER_SIZE,
                            color=spec.indicator_color,
                            edgecolors="black",
                            linewidths=1.0,
                            zorder=200,
                            antialiaseds=spec.antialias,
                        )

        # Labels and styling
        ax.set_xlabel(
            spec.xlabel,
            fontsize=spec.label_fontsize,
            color="black",
            fontweight="bold",
        )
        ax.set_ylabel(
            spec.ylabel,
            fontsize=spec.label_fontsize,
            color="black",
            fontweight="bold",
        )
        ax.tick_params(labelsize=spec.tick_fontsize, colors="black")
        ax.grid(spec.show_grid, alpha=0.04, color="black")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

        if spec.show_legend:
            ax.legend(fontsize=spec.tick_fontsize, loc="upper right")

        # Tight layout to maximize data area
        fig.tight_layout()
        self._apply_trace_shape(ax, spec.shape)

        # Convert figure to numpy array
        canvas.draw()
        img_array = self._canvas_to_rgb(canvas)

        # Close figure to free memory
        plt.close(fig)

        return img_array

    def _render_trace_panel_fast(
        self,
        ctx: RenderContext,
        timing: FrameTimingInfo,
    ) -> np.ndarray:
        """Render a static trace panel and only animate the time indicator."""
        spec = self.spec.trace_spec
        if self._trace_cache is None:
            self._trace_cache = self._build_trace_cache(ctx)

        base = self._trace_cache["img"]
        if not spec.show_time_indicator:
            return base.copy()

        xlim = self._trace_cache["xlim"]
        ylim = self._trace_cache.get("ylim")
        bbox = self._trace_cache["bbox"]
        width, height = self._trace_cache["size"]

        x_min, x_max = xlim
        if x_max == x_min:
            return base.copy()

        x0, y0, x1, y1 = bbox
        axis_width = max(1.0, x1 - x0)
        scale = axis_width / (x_max - x_min)
        t_val_abs = float(timing.trace_time_s)
        t_val = self._display_time(t_val_abs)
        if not np.isfinite(t_val):
            return base.copy()
        if t_val < x_min:
            t_val = x_min
        elif t_val > x_max:
            t_val = x_max
        x_disp = x0 + (t_val - x_min) * scale
        x_disp = max(x0, min(x1, x_disp))
        x_disp = max(0.0, min(float(width - 1), x_disp))

        x_img = int(round(x_disp))
        y_top = int(round(height - y1))
        y_bottom = int(round(height - y0))

        if y_bottom < y_top:
            y_top, y_bottom = y_bottom, y_top

        frame = base.copy()
        from PIL import Image, ImageDraw

        pil_img = Image.fromarray(frame)
        draw = ImageDraw.Draw(pil_img)
        color = self._hex_to_rgb(spec.indicator_color)
        line_width = max(1, int(round(spec.indicator_width)))

        if spec.indicator_style == "dashed":
            dash_len = 6
            gap_len = 4
        elif spec.indicator_style == "dotted":
            dash_len = 2
            gap_len = 3
        else:
            dash_len = 0
            gap_len = 0

        if dash_len > 0:
            y = y_top
            while y < y_bottom:
                y_end = min(y_bottom, y + dash_len)
                draw.line((x_img, y, x_img, y_end), fill=color, width=line_width)
                y = y_end + gap_len
        else:
            draw.line((x_img, y_top, x_img, y_bottom), fill=color, width=line_width)

        if ylim is not None:
            y_min, y_max = ylim
            if y_max != y_min:
                marker_series = None
                if spec.show_inner:
                    marker_series = ctx.trace_model.inner_full
                elif spec.show_outer and ctx.trace_model.outer_full is not None:
                    marker_series = ctx.trace_model.outer_full
                if marker_series is not None and marker_series.size:
                    time_full = ctx.trace_model.time_full
                    if time_full.size:
                        idx = int(np.searchsorted(time_full, t_val_abs))
                        if idx <= 0:
                            idx = 0
                        elif idx >= time_full.size:
                            idx = time_full.size - 1
                        else:
                            prev_idx = idx - 1
                            if abs(time_full[prev_idx] - t_val_abs) <= abs(
                                time_full[idx] - t_val_abs
                            ):
                                idx = prev_idx
                        y_val = float(marker_series[idx])
                        if np.isfinite(y_val):
                            axis_height = max(1.0, y1 - y0)
                            y_scale = axis_height / (y_max - y_min)
                            y_disp = y0 + (y_val - y_min) * y_scale
                            y_img = int(round(height - y_disp))
                            y_img = max(0, min(height - 1, y_img))
                            radius = ACTIVE_MARKER_RADIUS_PX
                            draw.ellipse(
                                (
                                    x_img - radius - 1,
                                    y_img - radius - 1,
                                    x_img + radius + 1,
                                    y_img + radius + 1,
                                ),
                                fill=(0, 0, 0),
                            )
                            draw.ellipse(
                                (
                                    x_img - radius,
                                    y_img - radius,
                                    x_img + radius,
                                    y_img + radius,
                                ),
                                fill=color,
                            )

        return np.array(pil_img)

    def _build_trace_cache(self, ctx: RenderContext) -> dict[str, object]:
        """Render the full trace once and cache pixel mapping for fast overlays."""
        spec = self.spec.trace_spec

        dpi = 100
        fig_width_in = self.spec.trace_width_px / dpi
        fig_height_in = self.spec.trace_height_px / dpi

        fig = Figure(figsize=(fig_width_in, fig_height_in), dpi=dpi)
        ax = fig.add_subplot(111)
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        canvas = FigureCanvasAgg(fig)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        x0 = self.spec.start_time_s
        x1 = self.spec.end_time_s
        level_index = 0
        try:
            level_index = ctx.trace_model.best_level_for_window(
                x0,
                x1,
                self.spec.trace_width_px,
            )
        except Exception:
            level_index = 0

        window = ctx.trace_model.window(
            level_index=level_index,
            x0=x0,
            x1=x1,
        )
        window_time = self._display_times(window.time)

        active_channel = None
        if spec.show_inner and window.inner_mean is not None:
            active_channel = "inner"
        elif spec.show_outer and window.outer_mean is not None:
            active_channel = "outer"

        if spec.show_inner and window.inner_mean is not None:
            if active_channel == "inner":
                line_width = spec.line_width * ACTIVE_LINE_SCALE
                line_alpha = 1.0
            elif active_channel is None:
                line_width = spec.line_width
                line_alpha = 1.0
            else:
                line_width = spec.line_width * INACTIVE_LINE_SCALE
                line_alpha = INACTIVE_LINE_ALPHA
            ax.plot(
                window_time,
                window.inner_mean,
                color=spec.inner_color,
                linewidth=line_width,
                alpha=line_alpha,
                label="Inner Diameter",
                antialiased=spec.antialias,
            )

        if spec.show_outer and window.outer_mean is not None:
            if active_channel == "outer":
                line_width = spec.line_width * ACTIVE_LINE_SCALE
                line_alpha = 1.0
            elif active_channel is None:
                line_width = spec.line_width
                line_alpha = 1.0
            else:
                line_width = spec.line_width * INACTIVE_LINE_SCALE
                line_alpha = INACTIVE_LINE_ALPHA
            ax.plot(
                window_time,
                window.outer_mean,
                color=spec.outer_color,
                linewidth=line_width,
                alpha=line_alpha,
                label="Outer Diameter",
                antialiased=spec.antialias,
            )

        if spec.show_avg_pressure and window.avg_pressure_mean is not None:
            ax2 = ax.twinx()
            ax2.plot(
                window_time,
                window.avg_pressure_mean,
                color=spec.avg_pressure_color,
                linewidth=spec.line_width,
                label="Avg Pressure",
                linestyle="--",
                antialiased=spec.antialias,
            )
            ax2.set_ylabel(
                "Pressure (mmHg)",
                fontsize=spec.label_fontsize,
                color="black",
                fontweight="bold",
            )

        if spec.show_events:
            for event in ctx.events:
                event_time = self._display_time(event.time_s)
                ax.axvline(
                    event_time,
                    color=event.color,
                    linewidth=1.0,
                    linestyle="--",
                    alpha=0.5,
                    zorder=50,
                    antialiased=spec.antialias,
                )
                if spec.show_event_labels:
                    y_pos = ax.get_ylim()[1] * 0.95
                    ax.text(
                        event_time,
                        y_pos,
                        event.label,
                        rotation=90,
                        va="top",
                        ha="right",
                        fontsize=spec.event_label_fontsize,
                        color=event.color,
                    )

        if spec.x_range is not None:
            ax.set_xlim(spec.x_range)
        else:
            ax.set_xlim(
                self._display_time(self.spec.start_time_s), self._display_time(self.spec.end_time_s)
            )

        if spec.y_range is not None:
            ax.set_ylim(spec.y_range)

        ax.set_xlabel(
            spec.xlabel,
            fontsize=spec.label_fontsize,
            color="black",
            fontweight="bold",
        )
        ax.set_ylabel(
            spec.ylabel,
            fontsize=spec.label_fontsize,
            color="black",
            fontweight="bold",
        )
        ax.tick_params(labelsize=spec.tick_fontsize, colors="black")
        ax.grid(spec.show_grid, alpha=0.04, color="black")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

        if spec.show_legend:
            ax.legend(fontsize=spec.tick_fontsize, loc="upper right")

        fig.tight_layout()
        self._apply_trace_shape(ax, spec.shape)
        canvas.draw()
        img_array = self._canvas_to_rgb(canvas)

        bbox = ax.get_window_extent()
        w_px, h_px = canvas.get_width_height()
        cache = {
            "img": img_array,
            "xlim": ax.get_xlim(),
            "ylim": ax.get_ylim(),
            "bbox": (float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)),
            "size": (int(w_px), int(h_px)),
        }

        plt.close(fig)
        return cache

    def _apply_trace_shape(self, ax, shape: str) -> None:
        if shape != "wide":
            return
        pos = ax.get_position()
        ratio = self._wide_trace_height_ratio()
        target_height = pos.height * ratio
        y0 = pos.y0 + (pos.height - target_height) * 0.5
        ax.set_position([pos.x0, y0, pos.width, target_height])

    def _wide_trace_height_ratio(self) -> float:
        width_px = max(1, int(self.spec.trace_width_px))
        height_px = max(1, int(self.spec.trace_height_px))
        target_height = width_px / 3.0
        ratio = target_height / height_px
        return min(0.6, max(0.3, ratio))

    @staticmethod
    def _canvas_to_rgb(canvas) -> np.ndarray:
        img_array = None
        if hasattr(canvas, "buffer_rgba"):
            try:
                buf = canvas.buffer_rgba()
                if hasattr(buf, "shape"):
                    img_array = np.asarray(buf, dtype=np.uint8)
                else:
                    w, h = canvas.get_width_height()
                    img_array = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
            except Exception:
                img_array = None

        if img_array is None and hasattr(canvas, "tostring_rgb"):
            w, h = canvas.get_width_height()
            buf = canvas.tostring_rgb()
            img_array = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 3))

        if img_array is None:
            w, h = canvas.get_width_height()
            renderer = canvas.get_renderer()
            buf = renderer.buffer_rgba()
            img_array = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))

        if img_array.shape[-1] == 4:
            return img_array[:, :, :3]
        return img_array

    def render_all_frames(
        self,
        ctx: RenderContext,
        timings: list[FrameTimingInfo],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[np.ndarray]:
        """Render all frames for the animation.

        Args:
            ctx: RenderContext with trace model and vessel frames
            timings: List of FrameTimingInfo for each frame
            progress_callback: Optional callback function(current_frame, total_frames)

        Returns:
            List of RGB numpy arrays, one per frame
        """
        frames = []
        total = len(timings)

        for i, timing in enumerate(timings):
            frame = self.render_frame(ctx, timing)
            frames.append(frame)

            if progress_callback is not None:
                progress_callback(i + 1, total)

        return frames

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

    def _pad_to_height(self, img: np.ndarray, target_h: int) -> np.ndarray:
        if img.shape[0] == target_h:
            return img
        pad_total = max(0, target_h - img.shape[0])
        pad_top = pad_total // 2
        pad_bottom = pad_total - pad_top
        return np.pad(
            img,
            ((pad_top, pad_bottom), (0, 0), (0, 0)),
            mode="constant",
            constant_values=255,
        )

    def _pad_to_width(self, img: np.ndarray, target_w: int) -> np.ndarray:
        if img.shape[1] == target_w:
            return img
        pad_total = max(0, target_w - img.shape[1])
        pad_left = pad_total // 2
        pad_right = pad_total - pad_left
        return np.pad(
            img,
            ((0, 0), (pad_left, pad_right), (0, 0)),
            mode="constant",
            constant_values=255,
        )


def save_gif(
    frames: list[np.ndarray],
    output_path: str,
    fps: int,
    loop_count: int = 0,
    optimize: bool = True,
    quality: int = 80,
    durations_ms: list[int] | None = None,
    shared_palette: bool = True,
    dither: str = "none",
) -> None:
    """Save frames as animated GIF using Pillow.

    Args:
        frames: List of RGB numpy arrays (H, W, 3)
        output_path: Destination file path
        fps: Frames per second
        loop_count: 0 = infinite loop, N = loop N times
        optimize: Enable GIF optimization (reduces file size)
        quality: 1-100 compression quality (not directly used by GIF)
        durations_ms: Optional per-frame durations in milliseconds
        shared_palette: Use a shared adaptive palette across frames for sharper output
        dither: "none" or "floyd"
    """
    from PIL import Image

    if not frames:
        raise ValueError("Cannot save empty frame list")

    duration_arg: int | list[int]
    if durations_ms is not None:
        if len(durations_ms) != len(frames):
            raise ValueError("durations_ms length does not match frames")
        duration_arg = durations_ms
    else:
        safe_fps = max(1, int(fps))
        duration_arg = int(1000 / safe_fps)

    # Convert numpy arrays to PIL Images
    pil_frames = [Image.fromarray(frame) for frame in frames]

    if shared_palette:
        base = pil_frames[0].convert("P", palette=Image.ADAPTIVE, colors=256)
        dither_mode = None
        dither_name = dither.lower() if isinstance(dither, str) else ""
        if hasattr(Image, "Dither"):
            dither_mode = (
                Image.Dither.NONE if dither_name == "none" else Image.Dither.FLOYDSTEINBERG
            )
        else:
            none_mode = getattr(Image, "NONE", 0)
            floyd_mode = getattr(Image, "FLOYDSTEINBERG", 3)
            dither_mode = none_mode if dither_name == "none" else floyd_mode
        pal_frames = [base]
        for frame in pil_frames[1:]:
            pal_frames.append(frame.convert("P", palette=base, dither=dither_mode))
        pil_frames = pal_frames

    # Save as animated GIF
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_arg,
        loop=loop_count,
        optimize=optimize,
    )


def estimate_gif_size_mb(
    width_px: int,
    height_px: int,
    n_frames: int,
) -> float:
    """Estimate GIF file size in megabytes.

    Args:
        width_px: Frame width in pixels
        height_px: Frame height in pixels
        n_frames: Number of frames

    Returns:
        Estimated size in MB (rough approximation)
    """
    # Typical GIF compression: ~0.5 to 2 KB per frame depending on complexity
    # Use conservative estimate of 1 KB per frame per megapixel
    megapixels = (width_px * height_px) / 1_000_000
    bytes_per_frame = megapixels * 1024 * 1024 * 0.5
    estimated_bytes = bytes_per_frame * n_frames
    return estimated_bytes / (1024 * 1024)
