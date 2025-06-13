import numpy as np
import tifffile
from vasoanalyzer.tiff_loader import load_tiff


def test_load_tiff_parses_ome_xml(tmp_path):
    path = tmp_path / "stack.tif"
    data0 = np.zeros((2, 2), dtype=np.uint8)
    data1 = np.ones((2, 2), dtype=np.uint8)
    desc0 = """<OME><Image><Pixels><Plane DeltaT='0.0'/></Pixels></Image></OME>"""
    desc1 = """<OME><Image><Pixels><Plane DeltaT='1.5'/></Pixels></Image></OME>"""
    tifffile.imwrite(path, data0, description=desc0)
    tifffile.imwrite(path, data1, description=desc1, append=True)

    frames, meta = load_tiff(path, max_frames=10)
    assert len(frames) == 2
    assert meta[0]["DeltaT"] == "0.0"
    assert meta[1]["DeltaT"] == "1.5"

