# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/


import pandas as pd
from PyQt5.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from vasoanalyzer.core.project import SampleN, save_project
from vasoanalyzer.ui.dialogs.excel_map_wizard import ExcelMapWizard


def _events_dataframe_from_rows(event_rows) -> pd.DataFrame:
    if not event_rows:
        raise ValueError("No event data available.")

    has_od = any(len(row) >= 5 for row in event_rows)
    has_frame = any(len(row) >= 4 for row in event_rows)

    records = []
    for row in event_rows:
        label = row[0] if len(row) >= 1 else ""
        time_val = row[1] if len(row) >= 2 else None
        id_val = row[2] if len(row) >= 3 else None
        od_val = None
        frame_val = None

        if has_od:
            if len(row) >= 5:
                od_val = row[3]
                frame_val = row[4] if has_frame else None
            elif len(row) >= 4:
                frame_val = row[3] if has_frame else None
        elif has_frame and len(row) >= 4:
            frame_val = row[3]

        record = {
            "Event": label,
            "Time (s)": time_val,
            "ID (µm)": id_val,
        }
        if has_od:
            record["OD (µm)"] = od_val
        if has_frame:
            record["Frame"] = frame_val
        records.append(record)

    df = pd.DataFrame(records)
    order = ["Event", "Time (s)", "ID (µm)"]
    if has_od:
        order.append("OD (µm)")
    if has_frame:
        order.append("Frame")
    df = df.reindex(columns=order)

    df["Event"] = df["Event"].astype(str)
    for col in ["Time (s)", "ID (µm)", "OD (µm)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Frame" in df.columns:
        df["Frame"] = pd.to_numeric(df["Frame"], errors="coerce")

    return df.reset_index(drop=True)


def save_data_as_n(self):
    if not self.current_project:
        QMessageBox.warning(self, "No Project", "Open or create a project first.")
        return
    if self.trace_data is None:
        QMessageBox.warning(self, "No Data", "No trace data loaded.")
        return

    if not self.current_project.experiments:
        QMessageBox.warning(self, "No Experiment", "Add an experiment to the project first.")
        return

    exp = self.current_experiment
    if exp is None:
        items = [e.name for e in self.current_project.experiments]
        choice, ok = QInputDialog.getItem(self, "Select Experiment", "Experiment:", items, 0, False)
        if not ok:
            return
        exp = next(e for e in self.current_project.experiments if e.name == choice)

    name, ok = QInputDialog.getText(self, "Sample Name", "Name:")
    if not ok or not name:
        return

    try:
        has_od = "Outer Diameter" in self.trace_data.columns
        columns = ["Event", "Time (s)", "ID (µm)"]
        if has_od:
            columns.append("OD (µm)")
        columns.append("Frame")
        events_df = pd.DataFrame(self.event_table_data, columns=columns)
        sample = SampleN(
            name=name,
            trace_data=self.trace_data.copy(),
            events_data=events_df,
        )
    except Exception as e:
        QMessageBox.critical(self, "Save Failed", str(e))
        return

    exp.samples.append(sample)
    self.refresh_project_tree()
    if self.current_project.path:
        save_project(self.current_project, self.current_project.path)


def open_excel_mapping_dialog(self, checked: bool = False):
    """Open Excel mapping dialog for exporting event data.

    Args:
        checked: Unused boolean from Qt signal (ignored)
    """
    if not self.event_table_data:
        QMessageBox.warning(self, "No Data", "No event data available to export.")
        return

    # Launch the newer wizard-based Excel mapping workflow.  The wizard
    # handles loading the Excel template and events CSV internally, so we
    # simply display it and return when the user closes the dialog.
    try:
        events_df = _events_dataframe_from_rows(self.event_table_data)
    except ValueError as exc:
        QMessageBox.warning(self, "Excel Mapping", str(exc))
        return

    wizard = ExcelMapWizard(self, events_df=events_df)
    wizard.exec_()
