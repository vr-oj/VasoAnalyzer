from vasoanalyzer.ui.snapshot_viewer import (
    SnapshotStackDataSource,
    SnapshotViewerController,
)


def test_snapshot_controller_routing(qt_app):
    controller = SnapshotViewerController()
    source = SnapshotStackDataSource(
        frames=["frame0", "frame1", "frame2"],
        frame_times=[0.0, 1.0, 2.0],
    )
    seen = []
    controller.frame_changed.connect(seen.append)

    controller.set_stack_source(source)
    controller.set_trace_time(0.1)
    controller._flush_pending()
    assert seen[-1] == "frame0"

    controller.set_event_time(1.9)
    controller._flush_pending()
    assert seen[-1] == "frame2"

    controller.set_trace_time(0.0)
    controller._flush_pending()
    assert seen[-1] == "frame2"
