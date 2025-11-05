from PyQt5.QtWidgets import QWidget
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

try:
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedPlotSettingsDialog as DialogT
except Exception:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog as DialogT


def test_event_labels_wires_once(qapp):
    fig = Figure(figsize=(4, 3))
    canvas = FigureCanvasQTAgg(fig)
    ax = fig.add_subplot(111)

    dlg = DialogT(parent=None, ax=ax, canvas=canvas)

    tab = dlg._make_event_labels_tab(None)
    assert isinstance(tab, QWidget)
    tab2 = dlg._make_event_labels_tab(None)
    assert isinstance(tab2, QWidget)

    # Ensure signals only wired once even after rebuilding the tab.
    row_signal = dlg.event_list.currentRowChanged
    assert dlg.event_list.receivers(row_signal) == 1

    style_signal = getattr(dlg.event_editor, "styleChanged", None)
    if style_signal is not None:
        assert dlg.event_editor.receivers(style_signal) == 1

    text_signal = getattr(dlg.event_editor, "labelTextChanged", None)
    if text_signal is not None:
        assert dlg.event_editor.receivers(text_signal) == 1

    # Trigger a couple of row changes to ensure the wiring stays healthy.
    if dlg.event_list.count() == 0:
        dlg.event_list.addItem("a")
        dlg.event_list.addItem("b")
    dlg.event_list.setCurrentRow(0)
    dlg.event_list.setCurrentRow(1)

    dlg.close()
