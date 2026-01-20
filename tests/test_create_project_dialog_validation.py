from PyQt5.QtCore import QSettings

from vasoanalyzer.ui.dialogs.new_project_dialog import NewProjectDialog


def test_create_project_dialog_validation(qt_app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    dialog = NewProjectDialog(None, settings=settings)

    assert dialog.project_name_edit.text() == "Untitled Project"
    assert dialog.create_experiment_checkbox.isChecked()
    assert dialog.experiment_name_edit.text() == "Experiment 1"
    assert dialog.project_path_edit.text()
    assert dialog.create_button.isEnabled()

    dialog.project_name_edit.setText("")
    assert not dialog.create_button.isEnabled()

    dialog.project_name_edit.setText("Project A")
    dialog._set_location("")
    assert not dialog.create_button.isEnabled()

    dialog._set_location(str(tmp_path))
    assert dialog.create_button.isEnabled()

    dialog.create_experiment_checkbox.setChecked(False)
    assert not dialog.experiment_name_edit.isEnabled()
    assert dialog.create_button.isEnabled()

    dialog.create_experiment_checkbox.setChecked(True)
    dialog.experiment_name_edit.setText("")
    assert not dialog.create_button.isEnabled()
