# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Loading routines for TIFF stacks used for trace snapshots."""

import logging
import json
import xml.etree.ElementTree as ET

import numpy as np
import tifffile

log = logging.getLogger(__name__)


def parse_description(desc: str) -> dict:
    """Parse TIFF page descriptions which may contain JSON or OME-XML."""

    if not desc:
        return {}

    try:
        return json.loads(desc)
    except json.JSONDecodeError:
        pass

    if desc.lstrip().startswith("<"):
        try:
            root = ET.fromstring(desc)
        except ET.ParseError:
            return {}

        meta: dict[str, object] = {}

        for elem in root.iter():
            if elem.text and elem.text.strip() and not list(elem):
                meta[elem.tag] = elem.text.strip()
            for key, val in elem.attrib.items():
                if key in meta:
                    existing = meta[key]
                    if isinstance(existing, list):
                        existing.append(val)
                    else:
                        meta[key] = [existing, val]
                else:
                    meta[key] = val

        for k, v in list(meta.items()):
            if isinstance(v, list) and len(v) == 1:
                meta[k] = v[0]

        return meta

    return {}


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
        OSError: If the file cannot be read as a TIFF.
    """

    log.info("Loading TIFF from %s", file_path)

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
            log.info("Loaded %d preview frames", len(frames))
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
                parsed = parse_description(page.description)
                if parsed:
                    frame_meta.update(parsed)
                else:
                    frame_meta["description_raw"] = page.description

            for tag in page.tags.values():
                frame_meta[tag.name] = tag.value

            frames_metadata.append(frame_meta)

    log.info("Loaded %d frames", len(frames))
    return frames, frames_metadata


def load_tiff_preview(file_path, max_frames=300):
    """Fast loading without metadata for quick previews."""

    log.info("Loading TIFF preview from %s", file_path)
    return load_tiff(file_path, max_frames=max_frames, metadata=False)
