import pandas as pd

from vasoanalyzer.ui.tiff_viewer_v2.page_time_map import (
    PageTimeMap,
    derive_page_time_map_from_trace,
)


def test_page_time_map_from_times_valid():
    page_map = PageTimeMap.from_times([0.0, 1.0, 2.0])
    assert page_map.valid is True
    assert page_map.page_count == 3
    assert page_map.time_for_page(0) == 0.0
    assert page_map.time_for_page(2) == 2.0
    assert page_map.page_for_time(1.4) == 1


def test_derive_page_time_map_missing_tiff_column():
    df = pd.DataFrame({"Time_s_exact": [0.0, 1.0], "Saved": [1, 1]})
    page_map = derive_page_time_map_from_trace(df)
    assert page_map.valid is False
    assert "missing TiffPage" in page_map.status


def test_derive_page_time_map_partial_coverage_invalid():
    df = pd.DataFrame(
        {
            "Time_s_exact": [0.0, 1.0],
            "Saved": [1, 1],
            "TiffPage": [0, 2],
        }
    )
    page_map = derive_page_time_map_from_trace(df, expected_page_count=3)
    assert page_map.valid is False
    assert "coverage mismatch" in page_map.status


def test_derive_page_time_map_valid_sequence():
    df = pd.DataFrame(
        {
            "Time_s_exact": [0.0, 1.0, 2.0],
            "Saved": [1, 1, 1],
            "TiffPage": [0, 1, 2],
        }
    )
    page_map = derive_page_time_map_from_trace(df, expected_page_count=3)
    assert page_map.valid is True
    assert page_map.page_count == 3
    assert page_map.page_for_time(0.2) == 0
    assert page_map.page_for_time(1.6) == 2
