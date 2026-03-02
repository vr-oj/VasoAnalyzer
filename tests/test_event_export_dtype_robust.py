import pandas as pd

from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def test_event_export_dtype_robust(tmp_path, qt_app):
    window = VasoAnalyzerApp(check_updates=False)
    try:
        window.trace_data = pd.DataFrame(
            {
                "Time (s)": [0.0, 1.0],
                "Inner Diameter": [10.0, 11.0],
                "Outer Diameter": [20.0, 21.0],
            }
        )
        window.event_table_data = [
            ("A", "0.5", "60.0", "80.0", "120.0", "130.0", 1),
            ("B", "1.0", "", None, "bad", "140.0", 2),
            ("C", None, None, "90.0", None, None, 3),
        ]
        out_path = tmp_path / "events.csv"
        ok = window._export_event_table_to_path(str(out_path))
        assert ok is True
        assert out_path.exists()
        exported = pd.read_csv(out_path)
        assert len(exported) == len(window.event_table_data)
    finally:
        window.close()
