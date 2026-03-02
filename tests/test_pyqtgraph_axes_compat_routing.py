from __future__ import annotations

from vasoanalyzer.ui.plots.pyqtgraph_axes_compat import PyQtGraphAxesCompat


class _DummyViewBox:
    def __init__(self, request_result: bool) -> None:
        self._x_range = (0.0, 1.0)
        self._y_range = (0.0, 1.0)
        self.request_result = bool(request_result)
        self.request_calls: list[tuple[float, float, str]] = []
        self.setx_calls: list[tuple[float, float, float]] = []

    def viewRange(self):
        return [list(self._x_range), list(self._y_range)]

    def request_set_window(self, x0: float, x1: float, reason: str = "external") -> bool:
        self.request_calls.append((float(x0), float(x1), str(reason)))
        self._x_range = (float(x0), float(x1))
        return self.request_result

    def setXRange(self, left: float, right: float, padding: float = 0.0):
        self.setx_calls.append((float(left), float(right), float(padding)))
        self._x_range = (float(left), float(right))

    def setYRange(self, _bottom: float, _top: float, padding: float = 0.0):
        _ = padding


class _DummyPlotItem:
    def __init__(self, viewbox: _DummyViewBox) -> None:
        self._viewbox = viewbox

    def getViewBox(self) -> _DummyViewBox:
        return self._viewbox


def test_axes_compat_routes_xlim_to_host_requester() -> None:
    vb = _DummyViewBox(request_result=True)
    ax = PyQtGraphAxesCompat(_DummyPlotItem(vb))

    ax.set_xlim(2.0, 5.0)

    assert vb.request_calls == [(2.0, 5.0, "axes_compat")]
    assert vb.setx_calls == []


def test_axes_compat_falls_back_to_setxrange_when_not_routed() -> None:
    vb = _DummyViewBox(request_result=False)
    ax = PyQtGraphAxesCompat(_DummyPlotItem(vb))

    ax.set_xlim(3.0, 7.0)

    assert vb.request_calls == [(3.0, 7.0, "axes_compat")]
    assert vb.setx_calls == [(3.0, 7.0, 0.0)]
