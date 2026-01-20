from vasoanalyzer.ui.event_table import build_event_table_column_contract


def test_default_columns_normal_mode():
    columns = build_event_table_column_contract(
        review_mode=False,
        show_id=True,
        show_od=False,
        show_avg_p=True,
        show_set_p=False,
        has_id=True,
        has_od=True,
        has_avg_p=True,
        has_set_p=True,
    )
    assert columns == ["event", "time", "id", "avg_p"]


def test_review_mode_adds_review_column():
    columns = build_event_table_column_contract(
        review_mode=True,
        show_id=True,
        show_od=False,
        show_avg_p=True,
        show_set_p=False,
        has_id=True,
        has_od=True,
        has_avg_p=True,
        has_set_p=True,
    )
    assert columns == ["review", "event", "time", "id", "avg_p"]


def test_trace_toggles_drive_columns():
    columns = build_event_table_column_contract(
        review_mode=True,
        show_id=True,
        show_od=True,
        show_avg_p=True,
        show_set_p=False,
        has_id=True,
        has_od=True,
        has_avg_p=True,
        has_set_p=True,
    )
    assert columns == ["review", "event", "time", "id", "od", "avg_p"]


def test_stable_ordering():
    columns = build_event_table_column_contract(
        review_mode=True,
        show_id=True,
        show_od=True,
        show_avg_p=True,
        show_set_p=True,
        has_id=True,
        has_od=True,
        has_avg_p=True,
        has_set_p=True,
    )
    assert columns == ["review", "event", "time", "id", "od", "avg_p", "set_p"]
