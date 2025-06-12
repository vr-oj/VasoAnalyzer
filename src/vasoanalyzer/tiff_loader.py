"""Loading routines for TIFF stacks used for trace snapshots."""

import logging
import tifffile
import numpy as np
import json

log = logging.getLogger(__name__)


def load_tiff(file_path, max_frames=300, metadata=True):
    """Load a subset of frames from a TIFF file.

    Args:
        file_path (str or Path): Path to the TIFF stack.
        max_frames (int, optional): Maximum number of frames to load. Frames are
            sampled evenly across the stack if it contains more than this value.
            Defaults to ``300``.
        metadata (bool, optional): If ``True`` extract metadata for each frame.
            Disabling metadata speeds up loading for preview-only usage.

    Returns:
        tuple[list[numpy.ndarray], list[dict]]: Extracted frames and metadata for
            each sampled frame.

    Raises:
        json.JSONDecodeError: If a frame description contains invalid JSON.
        OSError: If the file cannot be read as a TIFF.
    """

    frames = []
    frames_metadata = []

    with tifffile.TiffFile(file_path) as tif:
        total_frames = len(tif.pages)
        skip = max(1, round(total_frames / max_frames))

        if not metadata:
            indices = list(range(0, total_frames, skip))
            frames_array = tif.asarray(key=indices)
            if frames_array.ndim == 2:
                frames.append(np.array(frames_array))
            else:
                for frame in frames_array:
                    frames.append(np.array(frame))
            return frames, frames_metadata

        for i in range(0, total_frames, skip):
            page = tif.pages[i]
            frame = page.asarray()
            frames.append(frame)

            frame_meta = {}
            frame_meta["index"] = i
            frame_meta["shape"] = frame.shape
            frame_meta["dtype"] = str(frame.dtype)

            if hasattr(page, "description") and page.description:
                try:
                    json_metadata = json.loads(page.description)
                    frame_meta.update(json_metadata)
                    log.info("Found JSON metadata in frame %s", i)
                except json.JSONDecodeError:
                    log.warning(
                        "Frame %s has description but not valid JSON: %s...",
                        i,
                        page.description[:100],
                    )

            for tag in page.tags.values():
                frame_meta[tag.name] = tag.value

            frames_metadata.append(frame_meta)

    return frames, frames_metadata


def load_tiff_preview(file_path, max_frames=300):
    """Fast loading without metadata for quick previews."""

    return load_tiff(file_path, max_frames=max_frames, metadata=False)
