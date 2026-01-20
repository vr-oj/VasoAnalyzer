from vasoanalyzer.analysis.contract import AnalysisParamsV1, StepWindows
from vasoanalyzer.analysis.provenance import stable_params_hash


def test_provenance_hash_stable():
    params = AnalysisParamsV1()
    hash1 = stable_params_hash(params)
    hash2 = stable_params_hash(params)
    assert hash1 == hash2

    params_changed = AnalysisParamsV1(step_windows=StepWindows(transient_exclude_s=10.0))
    hash3 = stable_params_hash(params_changed)
    assert hash1 != hash3
