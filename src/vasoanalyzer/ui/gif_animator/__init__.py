"""GIF Animator - Create synchronized animations of vessel movement and trace data.

This package provides tools for creating high-quality animated GIFs that combine
TIFF stack frames (vessel movement) with trace data (diameter measurements).

Main entry point:
    GifAnimatorWindow - Main window for animation creation and preview
"""

from .animator_window import GifAnimatorWindow
from .frame_synchronizer import FrameSynchronizer, FrameTimingInfo
from .renderer import AnimationRenderer, estimate_gif_size_mb, save_gif
from .specs import AnimationSpec, TracePanelSpec

__all__ = [
    "GifAnimatorWindow",
    "AnimationSpec",
    "TracePanelSpec",
    "AnimationRenderer",
    "save_gif",
    "estimate_gif_size_mb",
    "FrameSynchronizer",
    "FrameTimingInfo",
]
