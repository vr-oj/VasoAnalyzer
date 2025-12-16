"""
Phase 1: Data Reality Check
Verify the canonical relationships between trace CSV, events CSV, and TIFF files.

Usage:
    python verify_data_relationships.py <path_to_folder_with_trace_and_events_and_tiff>

Expected files in folder:
    - *_trace.csv (VasoTracker trace export)
    - *_events.csv (VasoTracker events export)
    - *.tif or *.tiff (TIFF image stack)
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from PIL import Image

REQUIRED_TRACE_COLUMNS = [
    "Time (s)",
    "Time (hh:mm:ss)",
    "FrameNumber",
    "Saved",
    "TiffPage",
    "Inner Diameter",
    "Outer Diameter",
    "Table Marker / Temperature (oC)",
    "Pressure 1 (mmHg)",
    "Avg Pressure (mmHg)",
    "Set Pressure (mmHg)",
]


def load_data(folder_path):
    """Load trace, events, and TIFF from a folder."""
    folder = Path(folder_path)

    # Find files
    trace_files = list(folder.glob("*.csv"))
    event_files = list(folder.glob("*_table.csv"))
    tiff_files = list(folder.glob("*.tif")) + list(folder.glob("*.tiff"))

    if not trace_files:
        raise FileNotFoundError(f"No trace CSV found in {folder}")
    if not event_files:
        raise FileNotFoundError(f"No events CSV found in {folder}")
    if not tiff_files:
        raise FileNotFoundError(f"No TIFF found in {folder}")

    trace_df = pd.read_csv(trace_files[0])
    events_df = pd.read_csv(event_files[0])
    tiff_path = tiff_files[0]

    print(f"✓ Loaded trace: {trace_files[0].name}")
    print(f"✓ Loaded events: {event_files[0].name}")
    print(f"✓ Found TIFF: {tiff_path.name}")

    return trace_df, events_df, tiff_path


def count_tiff_frames(tiff_path):
    """Count frames in TIFF stack."""
    with Image.open(tiff_path) as img:
        n_frames = 0
        try:
            while True:
                img.seek(n_frames)
                n_frames += 1
        except EOFError:
            pass
    return n_frames


def check_trace_columns(trace_df):
    """Report whether expected VasoTracker trace columns are present."""

    missing = [c for c in REQUIRED_TRACE_COLUMNS if c not in trace_df.columns]
    if missing:
        print(f"✗ Missing expected trace columns: {missing}")
        print(f"  Present columns: {list(trace_df.columns)}")
        return False

    print("✓ Trace includes all expected VasoTracker columns")
    return True


def verify_event_mappings(trace_df, events_df):
    """
    Verify that each event maps correctly:
    events["Frame"] -> trace["FrameNumber"] -> trace["Time (s)"]
    """
    print("\n" + "=" * 80)
    print("VERIFYING EVENT MAPPINGS")
    print("=" * 80)

    # Check required columns
    required_trace_cols = ["Time (s)", "FrameNumber", "Time (hh:mm:ss)"]
    required_event_cols = ["Frame", "Time"]

    missing_trace = [c for c in required_trace_cols if c not in trace_df.columns]
    missing_event = [c for c in required_event_cols if c not in events_df.columns]

    if missing_trace:
        print(f"✗ Missing trace columns: {missing_trace}")
        print(f"  Available: {list(trace_df.columns)}")
        return False, None

    if missing_event:
        print(f"✗ Missing event columns: {missing_event}")
        print(f"  Available: {list(events_df.columns)}")
        return False, None

    print(f"✓ All required columns present")
    print(f"  Trace rows: {len(trace_df)}")
    print(f"  Events: {len(events_df)}")

    # Build frame number to trace index mapping
    frame_to_idx = {}
    for idx, row in trace_df.iterrows():
        frame_num = row["FrameNumber"]
        if pd.notna(frame_num):
            frame_to_idx[int(frame_num)] = idx

    print(f"✓ Frame numbers in trace: {len(frame_to_idx)}")

    # Verify each event
    all_valid = True
    event_times = []

    for j, event_row in events_df.iterrows():
        event_frame = int(event_row["Frame"])
        event_time_str = event_row["Time"]

        # Check if frame exists in trace
        if event_frame not in frame_to_idx:
            print(f"✗ Event {j}: Frame {event_frame} not found in trace FrameNumber")
            all_valid = False
            continue

        # Get corresponding trace row
        trace_idx = frame_to_idx[event_frame]
        trace_time_s = trace_df.loc[trace_idx, "Time (s)"]
        trace_time_str = trace_df.loc[trace_idx, "Time (hh:mm:ss)"]

        # Verify time string matches
        if str(trace_time_str).strip() != str(event_time_str).strip():
            print(f"✗ Event {j}: Time mismatch")
            print(f"    Event time: {event_time_str}")
            print(f"    Trace time: {trace_time_str}")
            all_valid = False
            continue

        event_times.append(trace_time_s)

        if j < 5:  # Show first 5
            print(
                f"  Event {j}: Frame {event_frame} → Time {trace_time_s:.3f}s ({event_time_str})"
            )

    if all_valid:
        print(f"✓ All {len(events_df)} events map correctly to trace times")
    else:
        print(f"✗ Some events have mapping errors")

    return all_valid, np.array(event_times) if all_valid else None


def verify_tiff_mappings(trace_df, tiff_path):
    """
    Verify that TIFF frames map correctly:
    TiffPage index -> trace row with TiffPage == index -> Time (s)
    """
    print("\n" + "=" * 80)
    print("VERIFYING TIFF FRAME MAPPINGS")
    print("=" * 80)

    n_tiff = count_tiff_frames(tiff_path)
    print(f"✓ TIFF has {n_tiff} frames")

    # Check if TiffPage column exists
    if "TiffPage" not in trace_df.columns:
        print(f"✗ TiffPage column not found in trace")
        print(f"  Available columns: {list(trace_df.columns)}")
        return False, None, None

    # Get all TiffPage values
    tiff_pages = trace_df["TiffPage"].dropna()
    n_pages = len(tiff_pages)

    print(f"✓ Trace has {n_pages} non-null TiffPage values")

    if n_pages != n_tiff:
        print(
            f"✗ Mismatch: TIFF has {n_tiff} frames but trace has {n_pages} TiffPage entries"
        )
        return False, None, None

    # Build mapping: frame_index -> (trace_index, time_s)
    frame_trace_index = np.full(n_tiff, -1, dtype=int)
    frame_trace_time = np.full(n_tiff, np.nan, dtype=float)

    all_valid = True
    for idx, row in trace_df.iterrows():
        tiff_page = row["TiffPage"]
        if pd.notna(tiff_page):
            page_idx = int(tiff_page)

            if page_idx < 0 or page_idx >= n_tiff:
                print(f"✗ Row {idx}: TiffPage {page_idx} out of range [0, {n_tiff-1}]")
                all_valid = False
                continue

            if frame_trace_index[page_idx] != -1:
                print(f"✗ TiffPage {page_idx} appears multiple times in trace")
                all_valid = False
                continue

            frame_trace_index[page_idx] = idx
            frame_trace_time[page_idx] = row["Time (s)"]

    # Check all frames are mapped
    missing = np.where(frame_trace_index == -1)[0]
    if len(missing) > 0:
        print(f"✗ {len(missing)} TIFF frames not mapped in trace:")
        print(
            f"    Missing indices: {missing[:10]}..."
            if len(missing) > 10
            else f"    Missing indices: {missing}"
        )
        all_valid = False
    else:
        print(f"✓ All {n_tiff} TIFF frames map to unique trace rows")

    # Show first few mappings
    for f in range(min(5, n_tiff)):
        if frame_trace_index[f] != -1:
            print(
                f"  Frame {f} → trace[{frame_trace_index[f]}] → Time {frame_trace_time[f]:.3f}s"
            )

    if all_valid:
        print(f"✓ All TIFF frames map correctly to trace times")
        return True, frame_trace_index, frame_trace_time
    else:
        return False, None, None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nPlease provide path to folder containing VasoTracker data")
        sys.exit(1)

    folder_path = sys.argv[1]
    print(f"Verifying VasoTracker data in: {folder_path}\n")

    try:
        # Load data
        trace_df, events_df, tiff_path = load_data(folder_path)

        trace_cols_ok = check_trace_columns(trace_df)

        # Verify events
        events_ok, event_times = verify_event_mappings(trace_df, events_df)

        # Verify TIFF
        tiff_ok, frame_trace_index, frame_trace_time = verify_tiff_mappings(
            trace_df, tiff_path
        )

        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        if trace_cols_ok and events_ok and tiff_ok:
            print("✓ ALL VERIFICATIONS PASSED")
            print("\nCanonical mappings:")
            print(f"  - trace_time = trace['Time (s)']  # shape: ({len(trace_df)},)")
            print(f"  - event_times = [...]  # shape: ({len(events_df)},)")
            print(f"  - frame_trace_time = [...]  # shape: ({len(frame_trace_time)},)")
            print("\nThese mappings satisfy:")
            print("  1. events['Frame'] → trace['FrameNumber'] → trace['Time (s)']")
            print("  2. tiff_frame_index → trace['TiffPage'] → trace['Time (s)']")
            print("  3. trace['Time (s)'] is the SINGLE source of truth")
            return 0
        else:
            print("✗ SOME VERIFICATIONS FAILED")
            if not trace_cols_ok:
                print("  - Missing expected trace columns")
            if not events_ok:
                print("  - Event mapping issues detected")
            if not tiff_ok:
                print("  - TIFF mapping issues detected")
            return 1

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
