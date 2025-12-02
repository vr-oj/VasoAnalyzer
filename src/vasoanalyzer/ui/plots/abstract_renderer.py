"""Abstract interface for trace rendering backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from vasoanalyzer.core.trace_model import TraceModel, TraceWindow


class AbstractTraceRenderer(ABC):
    """Abstract base class for trace rendering implementations.

    This interface allows VasoAnalyzer to support multiple rendering backends
    (matplotlib, PyQtGraph, etc.) while maintaining a consistent API.
    """

    @abstractmethod
    def get_widget(self) -> Any:
        """Return the Qt widget for embedding in the UI.

        Returns:
            QWidget compatible object (FigureCanvas, PlotWidget, etc.)
        """
        pass

    @abstractmethod
    def set_model(self, model: TraceModel) -> None:
        """Set the data model for this renderer.

        Args:
            model: TraceModel containing the trace data to render
        """
        pass

    @abstractmethod
    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
    ) -> None:
        """Set event markers to display.

        Args:
            times: Event timestamps
            colors: Optional colors for each event
            labels: Optional text labels for each event
        """
        pass

    @abstractmethod
    def update_window(
        self, x0: float, x1: float, *, pixel_width: int | None = None
    ) -> None:
        """Update the visible time window.

        This triggers rendering of the specified time range with appropriate
        level-of-detail selection.

        Args:
            x0: Start time of window
            x1: End time of window
            pixel_width: Viewport width in pixels (for LOD selection)
        """
        pass

    @abstractmethod
    def set_xlim(self, x0: float, x1: float) -> None:
        """Set the X-axis limits.

        Args:
            x0: Minimum x value
            x1: Maximum x value
        """
        pass

    @abstractmethod
    def set_ylim(self, y0: float, y1: float) -> None:
        """Set the Y-axis limits.

        Args:
            y0: Minimum y value
            y1: Maximum y value
        """
        pass

    @abstractmethod
    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits.

        Returns:
            Tuple of (xmin, xmax)
        """
        pass

    @abstractmethod
    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits.

        Returns:
            Tuple of (ymin, ymax)
        """
        pass

    @abstractmethod
    def autoscale_y(self) -> None:
        """Autoscale Y-axis to fit visible data."""
        pass

    @abstractmethod
    def set_autoscale_y(self, enabled: bool) -> None:
        """Enable/disable Y-axis autoscaling.

        Args:
            enabled: Whether to enable autoscaling
        """
        pass

    @abstractmethod
    def refresh(self) -> None:
        """Force a complete redraw of the view."""
        pass

    @abstractmethod
    def current_window(self) -> TraceWindow | None:
        """Get the currently displayed data window.

        Returns:
            TraceWindow with the data currently being rendered
        """
        pass

    @abstractmethod
    def data_limits(self) -> tuple[float, float] | None:
        """Get the Y-axis data limits for the current window.

        Returns:
            Tuple of (ymin, ymax) or None if no data
        """
        pass

    @abstractmethod
    def set_xlabel(self, label: str) -> None:
        """Set X-axis label.

        Args:
            label: Label text
        """
        pass

    @abstractmethod
    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label.

        Args:
            label: Label text
        """
        pass

    @abstractmethod
    def set_title(self, title: str) -> None:
        """Set plot title.

        Args:
            title: Title text
        """
        pass

    @abstractmethod
    def apply_style(self, style: dict[str, Any]) -> None:
        """Apply visual styling to the renderer.

        Args:
            style: Dictionary of style parameters (colors, fonts, etc.)
        """
        pass

    @abstractmethod
    def get_render_backend(self) -> str:
        """Get the name of the rendering backend.

        Returns:
            Backend identifier (e.g., "matplotlib", "pyqtgraph")
        """
        pass
