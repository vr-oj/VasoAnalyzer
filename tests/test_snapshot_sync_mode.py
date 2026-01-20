from vasoanalyzer.ui.snapshot_viewer import (
    SnapshotStackDataSource,
    SnapshotViewerController,
)


def test_snapshot_sync_mode_event_overrides_cursor(qt_app):
    controller = SnapshotViewerController()
    source = SnapshotStackDataSource(
        frames=["frame0", "frame1"],
        frame_times=[0.0, 1.0],
    )
    controller.set_stack_source(source)

    modes: list[str] = []
    controller.sync_mode_changed.connect(modes.append)

    controller.set_trace_time(0.2)
    assert modes[-1] == "cursor"

    controller.set_event_time(0.9)
    assert modes[-1] == "event"

    controller.set_event_time(None)
    assert modes[-1] == "cursor"


def test_snapshot_sync_mode_none_without_cursor(qt_app):
    controller = SnapshotViewerController()
    modes: list[str] = []
    controller.sync_mode_changed.connect(modes.append)

    controller.set_trace_time(0.5)
    assert modes[-1] == "cursor"

    controller.set_trace_time(None)
    assert modes[-1] == "none"
