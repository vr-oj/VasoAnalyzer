import numpy as np
import pandas as pd

from vasoanalyzer.core.timebase import derive_tiff_page_times, page_for_time


def test_tiff_page_time_mapping_from_trace():
    n_pages = 114
    times = np.arange(n_pages, dtype=float) * 100.1
    trace_df = pd.DataFrame(
        {
            "Time_s_exact": times,
            "Saved": np.ones(n_pages, dtype=int),
            "TiffPage": np.arange(n_pages, dtype=int),
        }
    )

    result = derive_tiff_page_times(trace_df, expected_page_count=n_pages)

    assert result.valid is True
    assert len(result.tiff_page_times) == n_pages
    assert 99.0 <= float(result.median_interval_s) <= 101.0
    assert page_for_time(98.7, result.tiff_page_times, mode="nearest") == 1
    assert page_for_time(0.0, result.tiff_page_times, mode="nearest") == 0
    assert page_for_time(times[-1], result.tiff_page_times, mode="nearest") == (n_pages - 1)
    for idx, time_val in enumerate(result.tiff_page_times):
        assert page_for_time(time_val, result.tiff_page_times, mode="nearest") == idx


def test_page_for_time_midpoints():
    times = [0.0, 1.0, 2.0, 3.0]
    assert page_for_time(0.49, times, mode="nearest") == 0
    assert page_for_time(0.51, times, mode="nearest") == 1
    assert page_for_time(1.5, times, mode="nearest") == 1
    assert page_for_time(2.51, times, mode="nearest") == 3
