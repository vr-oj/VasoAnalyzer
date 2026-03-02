from __future__ import annotations

from vasoanalyzer.ui.formatting.time_format import TimeFormatter, TimeMode


def test_auto_mode_thresholds() -> None:
    fmt = TimeFormatter(TimeMode.AUTO)

    assert fmt.format(119.99) == "119.99"
    assert fmt.format(120.0) == "02:00"
    assert fmt.format(3600.0) == "01:00:00"


def test_explicit_modes_no_unit_suffix() -> None:
    seconds_fmt = TimeFormatter(TimeMode.SECONDS)
    mmss_fmt = TimeFormatter(TimeMode.MMSS)
    hhmmss_fmt = TimeFormatter(TimeMode.HHMMSS)

    assert seconds_fmt.format(12.3) == "12.30"
    assert mmss_fmt.format(75.0) == "01:15"
    assert hhmmss_fmt.format(3723.0) == "01:02:03"
    assert seconds_fmt.format(3723.0).endswith("s") is False
    assert hhmmss_fmt.format(3723.0).endswith("s") is False


def test_format_range_uses_shared_formatter() -> None:
    fmt = TimeFormatter(TimeMode.HHMMSS)
    assert fmt.format_range(3600.0, 3723.0) == "01:00:00 - 01:02:03"
