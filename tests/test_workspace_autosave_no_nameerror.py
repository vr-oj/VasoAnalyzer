from types import SimpleNamespace

from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_autosave_close_path_no_nameerror(qt_app):
    window = VasoAnalyzerApp(check_updates=False)
    try:
        window.event_table_action = None
        window.ax = SimpleNamespace(get_ylabel=lambda: "")
        window._x_axis_for_style = lambda: SimpleNamespace(get_xlabel=lambda: "")
        state = window.gather_sample_state()
        assert "event_table_visible" in state
    finally:
        window.close()
