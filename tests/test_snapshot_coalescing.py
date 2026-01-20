from vasoanalyzer.ui.snapshot_viewer import SnapshotViewerController


class DummySnapshotSource:
    def __init__(self, frame_count: int = 32) -> None:
        self._frames = list(range(frame_count))

    def index_for_time(self, t_seconds: float):
        try:
            idx = int(t_seconds)
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self._frames):
            return None
        return idx

    def get_frame_at_index(self, index: int):
        if index < 0 or index >= len(self._frames):
            return None
        return self._frames[index]

    def get_frame_at_time(self, t_seconds: float):
        idx = self.index_for_time(t_seconds)
        if idx is None:
            return None
        return self.get_frame_at_index(idx)


class DummyWidget:
    def __init__(self) -> None:
        self.seen: list[int] = []

    def set_frame(self, frame) -> None:
        self.seen.append(frame)


def test_snapshot_latest_wins(qt_app):
    controller = SnapshotViewerController()
    source = DummySnapshotSource()
    widget = DummyWidget()
    controller.frame_changed.connect(widget.set_frame)

    controller.set_stack_source(source)
    controller.set_trace_time(1)
    controller.set_trace_time(2)
    controller.set_trace_time(3)
    controller._flush_pending()

    assert widget.seen == [3]


def test_snapshot_redundant_skip(qt_app):
    controller = SnapshotViewerController()
    source = DummySnapshotSource()
    widget = DummyWidget()
    controller.frame_changed.connect(widget.set_frame)

    controller.set_stack_source(source)
    controller.set_trace_time(5)
    controller._flush_pending()
    controller.set_trace_time(5)
    controller._flush_pending()

    assert widget.seen == [5]


def test_snapshot_event_overrides_cursor(qt_app):
    controller = SnapshotViewerController()
    source = DummySnapshotSource()
    widget = DummyWidget()
    controller.frame_changed.connect(widget.set_frame)

    controller.set_stack_source(source)
    controller.set_event_time(10)
    controller.set_trace_time(3)
    controller._flush_pending()

    assert widget.seen[-1] == 10

    controller.set_event_time(None)
    controller.set_trace_time(3)
    controller._flush_pending()

    assert widget.seen[-1] == 3


def test_snapshot_flush_ignored_after_reset(qt_app):
    controller = SnapshotViewerController()
    source = DummySnapshotSource()
    widget = DummyWidget()
    controller.frame_changed.connect(widget.set_frame)

    controller.set_stack_source(source)
    generation = controller._generation
    controller.set_trace_time(4)
    controller.reset()
    controller._flush_pending(generation)

    assert widget.seen == []
