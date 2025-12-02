"""Factory for creating plot renderers (matplotlib or PyQtGraph)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from vasoanalyzer.app.flags import is_enabled

if TYPE_CHECKING:
    from vasoanalyzer.ui.plots.plot_host import PlotHost
    from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost

__all__ = ["create_plot_host", "get_default_renderer_type"]


def get_default_renderer_type() -> Literal["matplotlib", "pyqtgraph"]:
    """Get the default renderer type based on feature flags.

    The renderer can be controlled via the VA_FEATURES environment variable:
    - VA_FEATURES=pyqtgraph_renderer  -> Use PyQtGraph (GPU-accelerated, DEFAULT)
    - VA_FEATURES=!pyqtgraph_renderer -> Use matplotlib (legacy)

    Returns:
        "pyqtgraph" if enabled (default), otherwise "matplotlib"
    """
    # Main window should always use the high-performance PyQtGraph path.
    # Keep a single return to avoid accidentally flipping to matplotlib via flags.
    _ = is_enabled  # Keep import lint-happy; flags no longer drive renderer choice.
    return "pyqtgraph"


def create_plot_host(
    *,
    dpi: int = 100,
    renderer: Literal["matplotlib", "pyqtgraph"] | None = None,
) -> PlotHost | PyQtGraphPlotHost:
    """Create a plot host with the specified or default renderer.

    Args:
        dpi: Display DPI for matplotlib renderer
        renderer: Renderer type ("matplotlib" or "pyqtgraph").
                 If None, uses get_default_renderer_type()

    Returns:
        PlotHost instance (either matplotlib-based or PyQtGraph-based)

    Examples:
        # Use default renderer (controlled by VA_FEATURES)
        plot_host = create_plot_host(dpi=100)

        # Force matplotlib renderer
        plot_host = create_plot_host(renderer="matplotlib")

        # Force PyQtGraph renderer for maximum performance
        plot_host = create_plot_host(renderer="pyqtgraph")
    """
    if renderer is None:
        renderer = get_default_renderer_type()

    if renderer == "pyqtgraph":
        from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost

        use_opengl = is_enabled("pyqtgraph_opengl", default=False)
        return PyQtGraphPlotHost(dpi=dpi, enable_opengl=use_opengl)
    elif renderer == "matplotlib":
        from vasoanalyzer.ui.plots.plot_host import PlotHost

        return PlotHost(dpi=dpi)
    else:
        raise ValueError(
            f"Invalid renderer type: {renderer}. " f"Must be 'matplotlib' or 'pyqtgraph'"
        )


def supports_export(plot_host: PlotHost | PyQtGraphPlotHost) -> bool:
    """Check if the plot host supports high-quality export.

    Args:
        plot_host: PlotHost instance

    Returns:
        True if the plot host can export high-quality figures
    """
    backend = plot_host.get_render_backend()
    # Both backends now support high-quality export
    # PyQtGraph uses matplotlib export bridge for publication quality
    return backend in ("matplotlib", "pyqtgraph")
