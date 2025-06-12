"""Loading routines for TIFF stacks used for trace snapshots."""

import logging
import tifffile
import numpy as np
import json

log = logging.getLogger(__name__)


def load_tiff(file_path, max_frames=300):
    """Load a subset of frames from a TIFF file.

    Args:
        file_path (str or Path): Path to the TIFF stack.
        max_frames (int, optional): Maximum number of frames to load. Frames are
            sampled evenly across the stack if it contains more than this value.
            Defaults to ``300``.

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
        
        for i in range(0, total_frames, skip):
            # Get the page
            page = tif.pages[i]
            
            # Extract frame
            frame = page.asarray()
            frames.append(frame)
            
            # Extract metadata for this frame
            frame_meta = {}
            
            # Get basic page info
            frame_meta['index'] = i
            frame_meta['shape'] = frame.shape
            frame_meta['dtype'] = str(frame.dtype)
            
            # Try to extract the JSON metadata from the description field
            if hasattr(page, 'description') and page.description:
                try:
                    # Parse JSON from description string
                    json_metadata = json.loads(page.description)
                    # Add all JSON metadata to our frame metadata
                    frame_meta.update(json_metadata)
                    log.info("Found JSON metadata in frame %s", i)
                except json.JSONDecodeError:
                    log.warning(
                        "Frame %s has description but not valid JSON: %s...",
                        i,
                        page.description[:100],
                    )
            
            # Also get regular TIFF tags
            for tag in page.tags.values():
                frame_meta[tag.name] = tag.value
            
            frames_metadata.append(frame_meta)
    
    return frames, frames_metadata
