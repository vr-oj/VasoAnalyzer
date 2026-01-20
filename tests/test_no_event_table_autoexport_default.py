from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_no_event_table_autoexport_default(tmp_path, qt_app, monkeypatch):
    monkeypatch.delenv("VASO_ENABLE_EVENT_TABLE_AUTOEXPORT", raising=False)
    window = VasoAnalyzerApp(check_updates=False)
    try:
        window._suppress_review_prompt = True
        trace_path = tmp_path / "trace.csv"
        trace_path.write_text("placeholder")
        window.trace_file_path = str(trace_path)
        labels = ["a"]
        times = ["0.5"]
        frames = ["1"]
        diam = ["10.0"]
        window.load_project_events(
            labels,
            times,
            frames,
            diam,
            None,
            refresh_plot=False,
            auto_export=True,
        )
        outputs = list(tmp_path.glob("*_eventDiameters_output.csv"))
        assert outputs == []
    finally:
        window.close()
