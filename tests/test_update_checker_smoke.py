from vasoanalyzer.ui.update_checker import UpdateChecker


def test_update_checker_constructs(qt_app) -> None:
    checker = UpdateChecker(qt_app)
    assert checker is not None
    assert not checker.is_running
