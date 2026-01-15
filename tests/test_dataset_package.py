import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from vasoanalyzer.core.project import Experiment, Project, SampleN, save_project, load_project
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.storage.dataset_package import (
    DatasetPackageError,
    DatasetPackageValidationError,
    export_dataset_package,
    import_dataset_package,
)


def _make_project(tmp_path: Path, name: str) -> Path:
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0, 2.0], "inner_diam": [10.0, 10.5, 10.2]})
    events_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "label": ["start", "stop"], "frame": [0, 1]})
    sample = SampleN(name="SampleA", trace_data=trace_df, events_data=events_df)
    project = Project(name=name, experiments=[Experiment(name="ExpA", samples=[sample])])
    vaso_path = tmp_path / f"{name}.vaso"
    save_project(project, vaso_path.as_posix())
    project.close()
    return vaso_path


def _make_empty_project(tmp_path: Path, name: str, experiments: list[Experiment] | None = None) -> Path:
    project = Project(name=name, experiments=experiments or [Experiment(name="Default", samples=[])])
    vaso_path = tmp_path / f"{name}.vaso"
    save_project(project, vaso_path.as_posix())
    project.close()
    return vaso_path


def _first_dataset_id(path: Path) -> int:
    store = sqlite_store.open_project(path)
    try:
        datasets = list(sqlite_store.iter_datasets(store))
        assert datasets
        return int(datasets[0]["id"])
    finally:
        store.close()


def _all_dataset_ids(path: Path) -> list[int]:
    store = sqlite_store.open_project(path)
    try:
        return [int(row["id"]) for row in sqlite_store.iter_datasets(store)]
    finally:
        store.close()


def _dataset_counts(path: Path, dataset_id: int) -> tuple[int, int]:
    store = sqlite_store.open_project(path)
    try:
        trace_df = sqlite_store.get_trace(store, dataset_id)
        events_df = sqlite_store.get_events(store, dataset_id)
        return len(trace_df.index), len(events_df.index)
    finally:
        store.close()


def test_dataset_round_trip(tmp_path: Path):
    src_project = _make_project(tmp_path, "ProjectA")
    dataset_id = _first_dataset_id(src_project)

    package_path = tmp_path / "sample.vasods"
    export_dataset_package(src_project, dataset_id, package_path)
    assert package_path.exists()

    dest_project = _make_empty_project(tmp_path, "ProjectB", experiments=[Experiment(name="ExpB", samples=[])])

    new_dataset_id = import_dataset_package(dest_project, package_path, target_experiment_name="ExpB")
    src_counts = _dataset_counts(src_project, dataset_id)
    dest_counts = _dataset_counts(dest_project, new_dataset_id)

    assert dest_counts == src_counts


def test_dataset_name_collision_suffix(tmp_path: Path):
    source_project = _make_project(tmp_path, "ProjectCollision")
    dataset_id = _first_dataset_id(source_project)
    package_path = tmp_path / "collision.vasods"
    export_dataset_package(source_project, dataset_id, package_path)

    dest_project = _make_empty_project(tmp_path, "ProjectCollisionDest", experiments=[Experiment(name="ExpA", samples=[])])

    first_import_id = import_dataset_package(dest_project, package_path, target_experiment_name="ExpA")
    second_import_id = import_dataset_package(dest_project, package_path, target_experiment_name="ExpA")

    store = sqlite_store.open_project(dest_project)
    try:
        names = {row["id"]: row["name"] for row in sqlite_store.iter_datasets(store)}
    finally:
        store.close()

    assert names[first_import_id] == "SampleA"
    assert names[second_import_id] == "SampleA (Copy)"


def test_package_checksum_validation(tmp_path: Path):
    project_path = _make_project(tmp_path, "ProjectTamper")
    dataset_id = _first_dataset_id(project_path)
    package_path = tmp_path / "tamper.vasods"
    export_dataset_package(project_path, dataset_id, package_path)

    # Tamper with trace.csv without updating manifest by rewriting the archive
    with zipfile.ZipFile(package_path, "r") as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    entries["data/trace.csv"] = b"t_seconds,inner_diam\n0.0,99.0\n"
    rebuilt = package_path.with_suffix(".tmp")
    with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    rebuilt.replace(package_path)

    dest_project = _make_empty_project(tmp_path, "ProjectDest", experiments=[Experiment(name="ExpB", samples=[])])

    with pytest.raises(DatasetPackageValidationError):
        import_dataset_package(dest_project, package_path, target_experiment_name="ExpB")


def _make_multi_project(tmp_path: Path, count: int = 3) -> Path:
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "inner_diam": [10.0, 10.5]})
    events_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "label": ["start", "stop"]})
    samples = [SampleN(name=f"S{i}", trace_data=trace_df, events_data=events_df) for i in range(count)]
    project = Project(
        name="Multi",
        experiments=[Experiment(name="Exp", samples=samples)],
    )
    path = tmp_path / "multi.vaso"
    save_project(project, path.as_posix())
    project.close()
    return path


def test_best_effort_import(tmp_path: Path):
    source = _make_multi_project(tmp_path, count=3)
    dest = _make_empty_project(tmp_path, "Dest", experiments=[Experiment(name="ExpDest", samples=[])])

    dataset_ids = _all_dataset_ids(source)
    packages = []
    for ds_id in dataset_ids:
        pkg_path = tmp_path / f"pkg_{ds_id}.vasods"
        export_dataset_package(source, ds_id, pkg_path)
        packages.append((ds_id, pkg_path))

    # Tamper one package to force a failure (rebuild to avoid duplicate warnings)
    bad_ds, bad_pkg = packages[1]
    with zipfile.ZipFile(bad_pkg, "r") as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    entries["data/trace.csv"] = b"t_seconds,inner_diam\n0.0,99.0\n"
    rebuilt = bad_pkg.with_suffix(".tmp")
    with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    rebuilt.replace(bad_pkg)

    imported = []
    failures = []
    for ds_id, pkg in packages:
        try:
            new_id = import_dataset_package(dest, pkg, target_experiment_name="ExpDest")
            imported.append(new_id)
        except Exception as exc:
            failures.append((ds_id, str(exc)))

    # Two should import successfully, one should fail
    assert len(imported) == 2
    assert len(failures) == 1

    # Destination project remains loadable
    loaded = load_project(dest.as_posix())
    assert loaded.experiments
    loaded.close()
