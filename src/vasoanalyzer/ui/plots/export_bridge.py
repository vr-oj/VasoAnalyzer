"""Export bridge for PyQtGraph renderer using matplotlib for high-quality output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["ExportViewState", "MatplotlibExportRenderer"]


@dataclass
class ExportViewState:
    """Captures the current view state from PyQtGraph for export.

    This allows us to recreate the exact view in matplotlib for
    high-quality export while maintaining PyQtGraph for display.
    """

    # Data model
    trace_model: TraceModel | None = None

    # View range
    xlim: tuple[float, float] = (0.0, 1.0)
    ylim: tuple[float, float] = (0.0, 1.0)

    # Channel configuration
    channel_specs: list[Any] = field(default_factory=list)
    visible_tracks: list[str] = field(default_factory=list)

    # Events
    event_times: list[float] = field(default_factory=list)
    event_colors: list[str] | None = None
    event_labels: list[str] | None = None

    # Style
    style: dict[str, Any] = field(default_factory=dict)

    # Layout
    height_ratios: dict[str, float] = field(default_factory=dict)

    # Display mode
    mode: str = "dual"  # "inner", "outer", or "dual"

    # Additional metadata for export
    title: str | None = None
    show_grid: bool = True
    show_legend: bool = False


class MatplotlibExportRenderer:
    """High-quality matplotlib renderer for exporting PyQtGraph views.

    This renderer recreates the PyQtGraph view using matplotlib,
    allowing high-quality exports (TIFF, SVG, etc.) while maintaining
    the performance benefits of PyQtGraph for interactive display.
    """

    def __init__(self, dpi: int = 300) -> None:
        """Initialize export renderer.

        Args:
            dpi: Export DPI (default: 300 for high quality)
        """
        self._dpi = dpi
        self._figure: Figure | None = None
        self._canvas: FigureCanvasQTAgg | None = None

    def render(
        self,
        view_state: ExportViewState,
        figsize: tuple[float, float] | None = None,
    ) -> Figure:
        """Render the view state using matplotlib.

        Args:
            view_state: Captured PyQtGraph view state
            figsize: Figure size in inches (width, height)

        Returns:
            Matplotlib Figure ready for export
        """
        # Create figure
        if figsize is None:
            figsize = (8, 6)  # Default size

        self._figure = Figure(figsize=figsize, dpi=self._dpi)
        self._canvas = FigureCanvasQTAgg(self._figure)

        # Apply style
        if view_state.style:
            self._apply_style(view_state.style)

        # Create subplots for stacked tracks
        n_tracks = len(view_state.visible_tracks)
        if n_tracks == 0:
            return self._figure

        # Calculate height ratios
        height_ratios = [
            view_state.height_ratios.get(track_id, 1.0)
            for track_id in view_state.visible_tracks
        ]

        # Create subplot grid
        gs = self._figure.add_gridspec(
            nrows=n_tracks,
            ncols=1,
            height_ratios=height_ratios,
            hspace=0.05 if n_tracks > 1 else 0.0,
        )

        # Render each track
        shared_ax = None
        for i, track_id in enumerate(view_state.visible_tracks):
            # Find channel spec for this track
            spec = next(
                (s for s in view_state.channel_specs if s.track_id == track_id),
                None,
            )
            if spec is None:
                continue

            # Create axis
            if shared_ax is None:
                ax = self._figure.add_subplot(gs[i, 0])
                shared_ax = ax
            else:
                ax = self._figure.add_subplot(gs[i, 0], sharex=shared_ax)
                ax.tick_params(labelbottom=False)

            # Render trace for this track
            self._render_track(ax, view_state, spec)

        # Set overall labels
        if shared_ax is not None:
            shared_ax.set_xlabel("Time (s)")

        # Set title if provided
        if view_state.title:
            self._figure.suptitle(view_state.title)

        # Adjust layout
        self._figure.tight_layout()

        return self._figure

    def _render_track(
        self,
        ax,
        view_state: ExportViewState,
        spec,
    ) -> None:
        """Render a single track on the given axes.

        Args:
            ax: Matplotlib axes
            view_state: View state
            spec: Channel track spec
        """
        if view_state.trace_model is None:
            return

        # Get data window
        x0, x1 = view_state.xlim
        pixel_width = int(self._figure.get_figwidth() * self._dpi)
        level_idx = view_state.trace_model.best_level_for_window(x0, x1, pixel_width)
        window = view_state.trace_model.window(level_idx, x0, x1)

        time = window.time
        if time.size == 0:
            return

        # Determine which data to plot based on component
        if spec.component == "inner" or spec.component == "dual":
            # Plot inner diameter
            mean = window.inner_mean
            ymin = window.inner_min
            ymax = window.inner_max

            ax.plot(time, mean, 'k-', linewidth=1.5, label="Inner Diameter")

            # Add uncertainty band if requested
            if view_state.style.get("show_uncertainty", False):
                ax.fill_between(
                    time,
                    ymin,
                    ymax,
                    alpha=0.3,
                    color="#BBD7FF",
                    label="Uncertainty",
                )

        if spec.component == "outer":
            # Plot outer diameter
            if window.outer_mean is not None:
                mean = window.outer_mean
                ymin = window.outer_min
                ymax = window.outer_max

                ax.plot(time, mean, color="tab:orange", linewidth=1.2, label="Outer Diameter")

                if view_state.style.get("show_uncertainty", False):
                    ax.fill_between(
                        time,
                        ymin,
                        ymax,
                        alpha=0.2,
                        color="#FFD1A9",
                    )

        # Plot outer diameter on secondary axis if dual mode
        if spec.component == "dual" and window.outer_mean is not None:
            ax2 = ax.twinx()
            ax2.plot(
                time,
                window.outer_mean,
                color="tab:orange",
                linewidth=1.2,
                label="Outer Diameter",
            )
            ax2.set_ylabel("Outer Diameter (µm)")

        # Plot event markers
        if view_state.event_times:
            for i, event_time in enumerate(view_state.event_times):
                if x0 <= event_time <= x1:
                    color = "gray"
                    if view_state.event_colors and i < len(view_state.event_colors):
                        color = view_state.event_colors[i]

                    ax.axvline(
                        event_time,
                        color=color,
                        linestyle="--",
                        linewidth=1.2,
                        alpha=0.75,
                    )

                    # Add label if provided
                    if view_state.event_labels and i < len(view_state.event_labels):
                        label = view_state.event_labels[i]
                        # Place label at top of plot
                        ylim = ax.get_ylim()
                        ax.text(
                            event_time,
                            ylim[1],
                            label,
                            rotation=90,
                            verticalalignment="bottom",
                            fontsize=10,
                        )

        # Set labels and limits
        ax.set_ylabel(spec.label or "Diameter (µm)")
        ax.set_xlim(view_state.xlim)

        if view_state.show_grid:
            ax.grid(True, alpha=0.3)

        if view_state.show_legend and spec.component == "dual":
            ax.legend(loc="upper right")

    def _apply_style(self, style: dict[str, Any]) -> None:
        """Apply style dictionary to figure.

        Args:
            style: Style parameters
        """
        # Apply background color
        if "background_color" in style:
            self._figure.patch.set_facecolor(style["background_color"])

        # Apply font settings
        if "font_family" in style:
            plt.rcParams["font.family"] = style["font_family"]
        if "font_size" in style:
            plt.rcParams["font.size"] = style["font_size"]

    def save(
        self,
        filename: str,
        format: str | None = None,
        dpi: int | None = None,
        **kwargs,
    ) -> None:
        """Save the rendered figure to file.

        Args:
            filename: Output filename
            format: File format (tiff, svg, png, pdf, etc.)
            dpi: Export DPI (overrides constructor DPI)
            **kwargs: Additional arguments for savefig
        """
        if self._figure is None:
            raise RuntimeError("No figure rendered. Call render() first.")

        save_dpi = dpi if dpi is not None else self._dpi

        self._figure.savefig(
            filename,
            format=format,
            dpi=save_dpi,
            bbox_inches="tight",
            **kwargs,
        )

    def get_figure(self) -> Figure | None:
        """Get the rendered matplotlib figure.

        Returns:
            Matplotlib Figure or None if not rendered
        """
        return self._figure

    def close(self) -> None:
        """Close and cleanup the figure."""
        if self._figure is not None:
            plt.close(self._figure)
            self._figure = None
            self._canvas = None
