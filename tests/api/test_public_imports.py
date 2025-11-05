def test_public_imports() -> None:
    import vasoanalyzer
    from vasoanalyzer.ui.plots.plot_host import PlotHost
    from vasoanalyzer.core.project import open_project, open_project_ctx
    from vasoanalyzer.services.project_service import SQLiteProjectRepository

    assert vasoanalyzer
    assert PlotHost
    assert open_project
    assert open_project_ctx
    assert SQLiteProjectRepository
