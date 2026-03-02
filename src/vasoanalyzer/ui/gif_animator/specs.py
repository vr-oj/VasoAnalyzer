"""Data models for GIF animation configuration.

This module defines the specification data structures for the GIF Animator,
following the spec-based architecture pattern used across the UI.
"""

from dataclasses import dataclass, field


@dataclass
class FrameTimeExtractionResult:
    """Result of frame time extraction with metadata for auditability.

    This dataclass captures not just the extracted frame times, but also
    important metadata about how they were derived, enabling better debugging
    and reproducibility.

    Attributes:
        frame_times: List of timestamps for each TIFF frame in seconds
        source: Data source used ("tiff_page", "ui_state", "estimation")
        confidence: Confidence level in the data ("high", "medium", "low")
        warnings: List of issues encountered during extraction
        mapping_coverage: Fraction of frames with actual data (vs estimated) in range [0.0, 1.0]
    """

    frame_times: list[float]
    source: str
    confidence: str
    warnings: list[str]
    mapping_coverage: float


@dataclass
class TracePanelSpec:
    """Configuration for trace visualization in animation."""

    # Channel visibility
    show_inner: bool = True
    show_outer: bool = True
    show_avg_pressure: bool = False
    show_set_pressure: bool = False

    # Trace styling
    inner_color: str = "#000000"
    outer_color: str = "#000000"
    avg_pressure_color: str = "#000000"
    set_pressure_color: str = "#000000"
    line_width: float = 3.5

    # Time indicator (moving vertical line showing current time)
    show_time_indicator: bool = True
    indicator_color: str = "#FF6B00"
    indicator_width: float = 3.0
    indicator_style: str = "solid"  # "solid", "dashed", "dotted"

    # Event markers
    show_events: bool = True
    show_event_labels: bool = False
    fast_render: bool = False
    shape: str = "balanced"  # "balanced" or "wide"
    antialias: bool = True

    # Display settings
    show_grid: bool = True
    show_legend: bool = False
    xlabel: str = "Time (s)"
    ylabel: str = "Diameter (μm)"

    # Axis ranges (None = auto)
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None

    # Font sizes
    label_fontsize: float = 14.0
    tick_fontsize: float = 12.0
    event_label_fontsize: float = 10.0


@dataclass
class AnimationSpec:
    """Top-level animation configuration (pure data, no UI dependencies)."""

    # Time range (from event selection)
    start_time_s: float
    end_time_s: float
    start_event_label: str | None = None
    end_event_label: str | None = None
    display_time_zero: bool = False

    # Frame configuration
    fps: int = 10
    playback_speed: float = 1.0
    loop_count: int = 0  # 0 = infinite loop

    # Layout configuration
    layout_mode: str = "side_by_side"  # "side_by_side" or "stacked"
    vessel_position: str = "left"  # "left" or "right" (for side_by_side)
    auto_vessel_width: bool = True

    # Frame sampling
    use_tiff_frames: bool = False

    # Size configuration
    output_width_px: int = 800
    output_height_px: int = 400
    vessel_width_ratio: float = 0.5  # Fraction of total width for vessel panel

    # Vessel panel settings
    vessel_interpolation: str = "nearest"  # "nearest", "bilinear", "bicubic"
    vessel_colormap: str | None = None  # None = grayscale
    vessel_show_timestamp: bool = True
    vessel_show_frame_number: bool = False
    vessel_timestamp_color: str = "#FFFFFF"
    vessel_timestamp_fontsize: float = 10.0
    vessel_bg_color: str = "#FFFFFF"
    vessel_fit: str = "contain"  # "cover" or "contain"
    vessel_crop_rect: tuple[int, int, int, int] | None = None

    # Trace panel settings
    trace_spec: TracePanelSpec = field(default_factory=TracePanelSpec)

    # Export settings
    export_path: str | None = None
    export_format: str = "gif"  # "gif" or potentially "mp4" in future
    quality: int = 80  # 1-100 for compression quality
    optimize: bool = True  # Enable GIF optimization

    @property
    def duration_s(self) -> float:
        """Return animation duration in seconds."""
        return self.end_time_s - self.start_time_s

    @property
    def vessel_width_px(self) -> int:
        """Return vessel panel width in pixels."""
        if self.layout_mode == "side_by_side":
            return int(self.output_width_px * self.vessel_width_ratio)
        else:  # stacked
            return self.output_width_px

    @property
    def vessel_height_px(self) -> int:
        """Return vessel panel height in pixels."""
        if self.layout_mode == "side_by_side":
            return self.output_height_px
        else:  # stacked
            return int(self.output_height_px * self.vessel_width_ratio)

    @property
    def trace_width_px(self) -> int:
        """Return trace panel width in pixels."""
        if self.layout_mode == "side_by_side":
            return self.output_width_px - self.vessel_width_px
        else:  # stacked
            return self.output_width_px

    @property
    def trace_height_px(self) -> int:
        """Return trace panel height in pixels."""
        if self.layout_mode == "side_by_side":
            return self.output_height_px
        else:  # stacked
            return self.output_height_px - self.vessel_height_px

    def validate(self) -> list[str]:
        """Validate specification and return list of error messages."""
        errors = []

        if self.start_time_s >= self.end_time_s:
            errors.append("Start time must be before end time")

        if self.fps < 1 or self.fps > 120:
            errors.append("FPS must be between 1 and 120")

        if self.playback_speed < 0.1 or self.playback_speed > 20:
            errors.append("Playback speed must be between 0.1 and 20x")

        if self.output_width_px < 100 or self.output_width_px > 4000:
            errors.append("Output width must be between 100 and 4000 pixels")

        if self.output_height_px < 100 or self.output_height_px > 4000:
            errors.append("Output height must be between 100 and 4000 pixels")

        if self.vessel_width_ratio < 0.1 or self.vessel_width_ratio > 0.9:
            errors.append("Vessel width ratio must be between 0.1 and 0.9")

        if self.quality < 1 or self.quality > 100:
            errors.append("Quality must be between 1 and 100")

        return errors
