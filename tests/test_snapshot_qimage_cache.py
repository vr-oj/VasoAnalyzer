import numpy as np

import vasoanalyzer.ui.snapshot_viewer.render_backends as render_backends
from vasoanalyzer.ui.snapshot_viewer.qimage_cache import QImageLruCache
from vasoanalyzer.ui.snapshot_viewer.render_backends import QtSnapshotRenderer


def test_qimage_cache_hits_reduce_conversion(monkeypatch, qt_app):
    cache = QImageLruCache(max_bytes=8 * 1024 * 1024)
    renderer = QtSnapshotRenderer(cache=cache)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    calls = {"count": 0}
    original = render_backends.numpy_rgb_to_qimage

    def wrapped(arr):
        calls["count"] += 1
        return original(arr)

    monkeypatch.setattr(render_backends, "numpy_rgb_to_qimage", wrapped)

    renderer.set_frame(frame, frame_index=1)
    assert calls["count"] == 1
    assert renderer.last_cache_hit is False

    renderer.set_frame(frame, frame_index=1)
    assert calls["count"] == 1
    assert renderer.last_cache_hit is True
