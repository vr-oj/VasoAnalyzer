import numpy as np
import pytest

from vasoanalyzer.analysis.contract import MyographyDataset, TimeSeries, Trace
from vasoanalyzer.analysis.errors import AnalysisError, InvalidTimebaseError


def test_contract_validation_units_and_lengths():
    time = TimeSeries(np.arange(0, 10, dtype=np.float64))
    diameter = Trace(np.ones(9, dtype=np.float64), unit="um")
    with pytest.raises(InvalidTimebaseError):
        MyographyDataset(
            dataset_id="bad-length",
            time=time,
            diameter_inner_um=diameter,
        )

    diameter_ok = Trace(np.ones(10, dtype=np.float64), unit="mm")
    with pytest.raises(AnalysisError):
        MyographyDataset(
            dataset_id="bad-unit",
            time=time,
            diameter_inner_um=diameter_ok,
        )
