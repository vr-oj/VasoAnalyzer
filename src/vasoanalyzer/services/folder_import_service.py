# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""
Folder import service for batch loading trace files.

This service provides utilities for recursively scanning folders,
detecting trace files, matching event files, and determining import status.
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vasoanalyzer.core.project import Experiment, SampleN
from vasoanalyzer.io.events import find_matching_event_file

ImportStatus = Literal["NEW", "ALREADY_LOADED", "ALREADY_PROCESSED", "MODIFIED"]


@dataclass
class ImportCandidate:
    """Represents a potential import file with its metadata."""

    subfolder: str  # Name of the subfolder (e.g., "Vessel_1")
    subfolder_path: str  # Full path to subfolder
    trace_file: str  # Full path to trace CSV
    events_file: str | None  # Full path to matching events file (if found)
    status: ImportStatus
    existing_sample: SampleN | None = None  # Reference if already loaded


def scan_folder_for_traces(root_folder: str) -> list[tuple[str, str]]:
    """
    Recursively scan a folder for trace files.

    Args:
        root_folder: Root directory to scan

    Returns:
        List of tuples: (subfolder_path, trace_file_path)
    """
    candidates = []
    root_path = Path(root_folder)

    # Walk through all subdirectories
    for dirpath, _dirnames, filenames in os.walk(root_folder):
        dir_path = Path(dirpath)

        # Skip the root folder itself - only process subfolders
        if dir_path == root_path:
            continue

        # Look for trace files (CSV files that aren't event/output files)
        for filename in filenames:
            if filename.endswith(".csv"):
                # Skip known output files
                if (
                    filename.endswith("_eventDiameters_output.csv")
                    or filename == "eventDiameters_output.csv"
                ):
                    continue

                # Skip files that look like event tables
                lower_name = filename.lower()
                if "table" in lower_name or "_events" in lower_name:
                    continue

                # This looks like a trace file
                trace_path = dir_path / filename
                candidates.append((str(dir_path), str(trace_path)))

                # Only take the first trace file per folder
                break

    return candidates


def get_file_signature(file_path: str) -> str:
    """
    Get a signature (hash) of a file for change detection.

    Args:
        file_path: Path to the file

    Returns:
        MD5 hash of the file contents
    """
    if not os.path.exists(file_path):
        return ""

    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5.update(chunk)
    return md5.hexdigest()


def check_import_status(
    trace_file: str,
    events_file: str | None,
    experiment: Experiment | None,
) -> tuple[ImportStatus, SampleN | None]:
    """
    Determine the import status of a trace file.

    Args:
        trace_file: Path to the trace file
        events_file: Path to the matching events file (if any)
        experiment: The target experiment to check against

    Returns:
        Tuple of (status, existing_sample_if_found)
    """
    # Check if output file exists (indicates already processed)
    trace_dir = os.path.dirname(trace_file)
    base_name = os.path.splitext(os.path.basename(trace_file))[0]
    preferred_output = os.path.join(trace_dir, f"{base_name}_eventDiameters_output.csv")
    legacy_output = os.path.join(trace_dir, "eventDiameters_output.csv")
    output_file = preferred_output if os.path.exists(preferred_output) else legacy_output
    output_exists = os.path.exists(output_file)

    # Check if already loaded in the experiment
    existing_sample = None
    if experiment:
        for sample in experiment.samples:
            if sample.trace_path == trace_file:
                existing_sample = sample
                break

    # Determine status
    if existing_sample:
        # Already loaded in this experiment
        # Check if files have been modified since loading
        trace_sig = get_file_signature(trace_file)
        if (
            hasattr(existing_sample, "trace_sig")
            and existing_sample.trace_sig
            and trace_sig != existing_sample.trace_sig
        ):
            return ("MODIFIED", existing_sample)

        return ("ALREADY_LOADED", existing_sample)

    elif output_exists:
        # Not loaded but has output file - check if input files are newer
        output_mtime = os.path.getmtime(output_file)
        trace_mtime = os.path.getmtime(trace_file)

        if trace_mtime > output_mtime:
            return ("MODIFIED", None)

        if events_file and os.path.exists(events_file):
            events_mtime = os.path.getmtime(events_file)
            if events_mtime > output_mtime:
                return ("MODIFIED", None)

        return ("ALREADY_PROCESSED", None)

    else:
        # New unprocessed file
        return ("NEW", None)


def scan_folder_with_status(
    root_folder: str, experiment: Experiment | None = None
) -> list[ImportCandidate]:
    """
    Scan a folder and determine import status for all found trace files.

    Args:
        root_folder: Root directory to scan
        experiment: Target experiment to check against (for duplicate detection)

    Returns:
        List of ImportCandidate objects with status information
    """
    candidates = []
    trace_files = scan_folder_for_traces(root_folder)

    for subfolder_path, trace_file in trace_files:
        # Find matching event file
        events_file = find_matching_event_file(trace_file)

        # Determine status
        status, existing_sample = check_import_status(trace_file, events_file, experiment)

        # Get subfolder name for sample naming
        subfolder_name = os.path.basename(subfolder_path)

        candidate = ImportCandidate(
            subfolder=subfolder_name,
            subfolder_path=subfolder_path,
            trace_file=trace_file,
            events_file=events_file,
            status=status,
            existing_sample=existing_sample,
        )
        candidates.append(candidate)

    return candidates


__all__ = [
    "ImportCandidate",
    "ImportStatus",
    "scan_folder_with_status",
    "scan_folder_for_traces",
    "check_import_status",
]
