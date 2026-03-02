"""Frame synchronization logic for GIF animations.

This module handles the mapping between animation time, TIFF frame indices,
and trace data timestamps, ensuring proper synchronization across different
sampling rates.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Epsilon tolerance for float comparisons (1 nanosecond)
EPSILON = 1e-9


@dataclass
class FrameTimingInfo:
    """Maps animation time to TIFF frame indices and trace data.

    Attributes:
        tiff_frame_index: Index into the TIFF stack (0-based)
        tiff_timestamp_s: Timestamp of this TIFF frame in seconds
        trace_time_s: Time value for trace window extraction
        animation_time_s: Time relative to animation start (0-based)
    """

    tiff_frame_index: int
    tiff_timestamp_s: float
    trace_time_s: float
    animation_time_s: float


class FrameSynchronizer:
    """Handles time-to-frame mapping for synchronized playback.

    This class manages the relationship between:
    - Animation timeline (evenly spaced at target FPS)
    - TIFF frames (may have irregular timestamps)
    - Trace data (continuous time series)
    """

    def __init__(
        self,
        frame_times: list[float] | np.ndarray,
        trace_times: np.ndarray,
        animation_start: float,
        animation_end: float,
    ):
        """Initialize frame synchronizer.

        Args:
            frame_times: Timestamps for each TIFF frame in seconds
            trace_times: Full trace time array from TraceModel
            animation_start: Start time for animation in seconds
            animation_end: End time for animation in seconds
        """
        self.frame_times = np.array(frame_times)
        self.trace_times = trace_times
        self.animation_start = animation_start
        self.animation_end = animation_end
        self.duration = animation_end - animation_start

        # Validate inputs
        if len(self.frame_times) == 0:
            raise ValueError("frame_times cannot be empty")

        if self.animation_start >= self.animation_end:
            raise ValueError("animation_start must be before animation_end")

        # Find valid frame range for the animation window
        self._compute_valid_frame_range()

        logger.debug(
            "FrameSynchronizer created",
            extra={
                "n_frames": len(frame_times),
                "animation_start": animation_start,
                "animation_end": animation_end,
                "duration": self.duration,
                "valid_frames": len(self.valid_frame_indices),
            },
        )

    def _compute_valid_frame_range(self):
        """Compute the range of TIFF frames that fall within animation window."""
        # Find frames within the animation time range
        self.valid_frame_indices = np.where(
            (self.frame_times >= self.animation_start) & (self.frame_times <= self.animation_end)
        )[0]

        if len(self.valid_frame_indices) == 0:
            # No frames exactly in range, find closest
            idx_start = np.searchsorted(self.frame_times, self.animation_start)
            idx_end = np.searchsorted(self.frame_times, self.animation_end)
            idx_start = max(0, idx_start - 1)
            idx_end = min(len(self.frame_times), idx_end + 1)
            self.valid_frame_indices = np.arange(idx_start, idx_end)

    def get_frame_for_time(self, t: float) -> FrameTimingInfo:
        """Return the best TIFF frame for given animation time with deterministic tie-breaking.

        Uses epsilon tolerance for float comparisons to ensure deterministic behavior.
        When two frames are equidistant (within epsilon), consistently prefers the earlier frame.

        Args:
            t: Time in seconds (in animation coordinate system)

        Returns:
            FrameTimingInfo with appropriate frame index and timestamps
        """
        # Convert animation time to absolute time
        absolute_time = self.animation_start + t

        # Find nearest TIFF frame using binary search
        idx = np.searchsorted(self.frame_times, absolute_time)

        # Clamp to valid range
        idx = np.clip(idx, 0, len(self.frame_times) - 1)

        # Check if previous frame is closer (nearest neighbor)
        # Use epsilon tolerance for deterministic tie-breaking
        if idx > 0:
            dist_curr = abs(self.frame_times[idx] - absolute_time)
            dist_prev = abs(self.frame_times[idx - 1] - absolute_time)

            # Deterministic tie-breaking: prefer earlier frame if within epsilon
            if abs(dist_prev - dist_curr) < EPSILON:
                idx = idx - 1  # Tie: use earlier frame
                logger.debug(
                    "Frame selection tie (within epsilon)",
                    extra={
                        "absolute_time": absolute_time,
                        "prev_frame": idx,
                        "curr_frame": idx + 1,
                        "dist_diff": abs(dist_prev - dist_curr),
                    },
                )
            elif dist_prev < dist_curr:
                idx = idx - 1

        return FrameTimingInfo(
            tiff_frame_index=int(idx),
            tiff_timestamp_s=float(self.frame_times[idx]),
            trace_time_s=absolute_time,
            animation_time_s=t,
        )

    def get_animation_keyframes(
        self,
        target_fps: int,
        playback_speed: float = 1.0,
    ) -> list[FrameTimingInfo]:
        """Generate evenly-spaced keyframes for the animation.

        Args:
            target_fps: Target frames per second for the animation
            playback_speed: Playback speed multiplier (1.0 = real-time)

        Returns:
            List of FrameTimingInfo objects, one per animation frame
        """
        speed = float(playback_speed) if playback_speed is not None else 1.0
        if speed <= 0:
            speed = 1.0
        # Calculate number of frames needed
        n_frames = max(1, int(np.ceil(self.duration * target_fps / speed)))

        # Generate evenly-spaced animation times
        if n_frames == 1:
            anim_times = np.array([0.0])
        else:
            anim_times = np.linspace(0.0, self.duration, n_frames)

        # Map each animation time to a frame
        keyframes = []
        for anim_t in anim_times:
            timing = self.get_frame_for_time(anim_t)
            keyframes.append(timing)

        return keyframes

    def get_tiff_keyframes(
        self,
        playback_speed: float = 1.0,
    ) -> list[FrameTimingInfo]:
        """Generate keyframes based on TIFF frames within the animation window.

        Args:
            playback_speed: Playback speed multiplier (1.0 = real-time)

        Returns:
            List of FrameTimingInfo objects, one per selected TIFF frame
        """
        frame_indices = np.array(self.valid_frame_indices, dtype=int)
        if frame_indices.size == 0:
            return []

        speed = float(playback_speed) if playback_speed is not None else 1.0
        if speed <= 0:
            speed = 1.0

        if speed < 1.0:
            repeat = max(1, int(round(1.0 / speed)))
            sampled = np.repeat(frame_indices, repeat)
        else:
            sample_count = max(1, int(np.ceil(frame_indices.size / speed)))
            positions = np.linspace(0, frame_indices.size - 1, sample_count)
            sampled = frame_indices[np.round(positions).astype(int)]

        keyframes: list[FrameTimingInfo] = []
        for idx in sampled:
            tiff_time = float(self.frame_times[idx])
            keyframes.append(
                FrameTimingInfo(
                    tiff_frame_index=int(idx),
                    tiff_timestamp_s=tiff_time,
                    trace_time_s=tiff_time,
                    animation_time_s=max(0.0, tiff_time - self.animation_start),
                )
            )

        return keyframes

    def estimate_tiff_fps(self) -> float:
        """Estimate the average FPS of the TIFF stack.

        Returns:
            Estimated frames per second (or 0.0 if cannot determine)
        """
        if len(self.frame_times) < 2:
            return 0.0

        # Calculate mean interval between frames
        intervals = np.diff(self.frame_times)
        mean_interval = np.mean(intervals[intervals > 0])

        if mean_interval > 0:
            return 1.0 / mean_interval
        return 0.0

    def _median_interval_s(self) -> float:
        intervals = np.diff(self.frame_times)
        valid = intervals[np.isfinite(intervals) & (intervals > 0)]
        if valid.size:
            return float(np.median(valid))
        return 0.0

    def get_tiff_keyframe_durations_ms(
        self,
        timings: list[FrameTimingInfo],
        playback_speed: float = 1.0,
        min_duration_ms: int = 20,
    ) -> list[int]:
        """Compute per-frame durations (ms) for TIFF keyframes."""
        if not timings:
            return []
        speed = float(playback_speed) if playback_speed is not None else 1.0
        if speed <= 0:
            speed = 1.0

        times = np.array([t.tiff_timestamp_s for t in timings], dtype=float)
        base_interval = self._median_interval_s()
        if not np.isfinite(base_interval) or base_interval <= 0:
            base_interval = 0.1

        durations_s = np.zeros(len(times), dtype=float)
        prev_delta = base_interval
        i = 0
        while i < len(times):
            t0 = times[i]
            j = i + 1
            while j < len(times) and abs(times[j] - t0) < EPSILON:
                j += 1

            if j < len(times):
                delta = times[j] - t0
                if not np.isfinite(delta) or delta <= EPSILON:
                    delta = prev_delta
                else:
                    prev_delta = delta
            else:
                delta = prev_delta

            delta /= speed
            per_frame = delta / max(1, j - i)
            durations_s[i:j] = per_frame
            i = j

        durations_ms = [
            max(min_duration_ms, int(round(duration * 1000.0))) for duration in durations_s
        ]
        return durations_ms

    def get_frame_count_estimate(self, target_fps: int) -> int:
        """Estimate number of frames that will be generated.

        Args:
            target_fps: Target frames per second

        Returns:
            Estimated frame count
        """
        return max(1, int(self.duration * target_fps))

    def validate_time_range(self) -> tuple[bool, str]:
        """Validate that the animation time range is reasonable.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if animation range overlaps with TIFF data
        tiff_start = self.frame_times[0]
        tiff_end = self.frame_times[-1]

        if self.animation_end < tiff_start:
            return (
                False,
                f"Animation end ({self.animation_end:.2f}s) is before first TIFF frame ({tiff_start:.2f}s)",
            )

        if self.animation_start > tiff_end:
            return (
                False,
                f"Animation start ({self.animation_start:.2f}s) is after last TIFF frame ({tiff_end:.2f}s)",
            )

        # Check if range is too short
        if self.duration < 0.1:
            return False, f"Animation duration ({self.duration:.3f}s) is too short (minimum 0.1s)"

        return True, ""
