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

import logging

from vasoanalyzer.core.project import Experiment, SampleN
from vasoanalyzer.io.events import find_matching_event_file, find_matching_tiff_file, find_matching_trace_file

log = logging.getLogger(__name__)

ImportStatus = Literal["NEW", "ALREADY_LOADED", "ALREADY_PROCESSED", "MODIFIED"]


@dataclass
class ImportCandidate:
    """Represents a potential VasoTracker import with auto-discovered files.

    Supports full file discovery: user can drop any file (trace, event, or TIFF)
    and the app will find siblings using pattern matching.
    """

    subfolder: str  # Name of the subfolder (e.g., "Vessel_1")
    subfolder_path: str  # Full path to subfolder
    trace_file: str | None  # Full path to trace CSV
    events_file: str | None  # Full path to matching events file (if found)
    tiff_file: str | None  # Full path to matching TIFF (if found)
    status: ImportStatus
    existing_sample: SampleN | None = None  # Reference if already loaded


def scan_folder_for_traces(root_folder: str) -> list[tuple[str, str, str | None]]:
    """
    Recursively scan a folder for VasoTracker files with full auto-discovery.

    Discovers ALL file types (trace CSV, event table, TIFF) and uses pattern
    matching to find siblings. User can drop any file and the app will find others.

    Args:
        root_folder: Root directory to scan

    Returns:
        List of tuples: (subfolder_path, trace_file_path, tiff_file_path)
        Note: Returns ONLY experiments with a trace file (required)
    """
    log.info("IMPORT: scan_folder_for_traces start root=%s", root_folder)
    discovered_experiments = {}  # Key: base experiment name, Value: dict of files
    root_path = Path(root_folder)

    # Phase 1: Discover all potential VasoTracker files
    for dirpath, _dirnames, filenames in os.walk(root_folder):
        dir_path = Path(dirpath)

        # Skip the root folder itself - only process subfolders
        if dir_path == root_path:
            continue

        for filename in filenames:
            file_path = dir_path / filename
            base_name = _extract_experiment_base(filename)

            if not base_name:
                continue

            # Create experiment entry if not exists
            exp_key = f"{dir_path}::{base_name}"
            if exp_key not in discovered_experiments:
                discovered_experiments[exp_key] = {
                    "dir": str(dir_path),
                    "base": base_name,
                    "trace": None,
                    "events": None,
                    "tiff": None,
                }

            # Categorize file type
            file_type = _detect_file_type(filename)
            if file_type and not discovered_experiments[exp_key][file_type]:
                discovered_experiments[exp_key][file_type] = str(file_path)

    # Phase 2: Use discovery functions to find missing siblings
    candidates = []
    for exp_key, files in discovered_experiments.items():
        trace_file = files["trace"]
        events_file = files["events"]
        tiff_file = files["tiff"]

        # If no trace found directly, try reverse discovery from events/TIFF
        if not trace_file and (events_file or tiff_file):
            reference = events_file or tiff_file
            trace_file = find_matching_trace_file(reference)
            if trace_file:
                files["trace"] = trace_file

        # If we have a trace, find missing siblings
        if trace_file:
            if not events_file:
                events_file = find_matching_event_file(trace_file)
                if events_file:
                    files["events"] = events_file

            if not tiff_file:
                tiff_file = find_matching_tiff_file(trace_file)
                if tiff_file:
                    files["tiff"] = tiff_file

            # Add to candidates (must have trace to import)
            candidates.append((files["dir"], trace_file, tiff_file))

    log.info(
        "IMPORT: scan_folder_for_traces finished root=%s experiments=%d candidates=%d",
        root_folder,
        len(discovered_experiments),
        len(candidates),
    )
    return candidates


def _extract_experiment_base(filename: str) -> str | None:
    """Extract base experiment name from a VasoTracker file.

    Examples:
        "20251202_Exp01.csv" → "20251202_Exp01"
        "20251202_Exp01_table.csv" → "20251202_Exp01"
        "20251202_Exp01_Result.tiff" → "20251202_Exp01"
    """
    stem = Path(filename).stem

    # Remove known suffixes
    for suffix in ["_table", "_Table", "_events", "_Events", "_Result", "_Raw", "_output"]:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]

    # Must have some content left
    return stem if stem else None


def _detect_file_type(filename: str) -> str | None:
    """Detect if file is a trace, events, or TIFF.

    Returns:
        "trace", "events", "tiff", or None
    """
    lower = filename.lower()

    # Skip known output files
    if "output" in lower and lower.endswith(".csv"):
        return None

    # Event table patterns
    if "table" in lower or "_events" in lower:
        return "events"

    # TIFF patterns
    if lower.endswith((".tiff", ".tif")):
        return "tiff"

    # Trace CSV (must be .csv and not events/output)
    if lower.endswith(".csv"):
        return "trace"

    return None


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
    log.info(
        "IMPORT: scan_folder_with_status start root=%s experiment=%s",
        root_folder,
        getattr(experiment, "name", None),
    )
    candidates = []
    trace_files = scan_folder_for_traces(root_folder)

    for subfolder_path, trace_file, tiff_file in trace_files:
        # Find matching event file (already searched by scan_folder_for_traces, but re-check)
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
            tiff_file=tiff_file,
            status=status,
            existing_sample=existing_sample,
        )
        candidates.append(candidate)

    status_counts: dict[str, int] = {}
    for cand in candidates:
        status_counts[cand.status] = status_counts.get(cand.status, 0) + 1
    log.info(
        "IMPORT: scan_folder_with_status finished root=%s candidates=%d status_counts=%s",
        root_folder,
        len(candidates),
        status_counts,
    )
    return candidates


__all__ = [
    "ImportCandidate",
    "ImportStatus",
    "scan_folder_with_status",
    "scan_folder_for_traces",
    "check_import_status",
]
