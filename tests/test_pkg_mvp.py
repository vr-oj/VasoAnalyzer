from __future__ import annotations

from pathlib import Path

from hashlib import sha256

import pandas as pd

from vasoanalyzer.core.project import Experiment, Project, SampleN
from vasoanalyzer.pkg.models import ChannelSpec, DatasetMeta, Event, RefEntry, Sampling
from vasoanalyzer.pkg.package import VasoPackage
from vasoanalyzer.pkg.exporter import export_project_to_package


def test_roundtrip(tmp_path: Path) -> None:
    package_path = tmp_path / "study.vaso"
    VasoPackage.create(package_path, title="Test Study")
    pkg = VasoPackage.open(package_path)
    meta = DatasetMeta(
        name="Seg1",
        modality="diam+pres",
        sampling=Sampling(rate_hz=10.0),
        channels=[
            ChannelSpec(key="ID", unit="um"),
            ChannelSpec(key="PRES", unit="mmHg"),
        ],
    )
    pkg.add_dataset(meta)
    pkg.add_event(Event(id="ev1", dataset_id=meta.id, t=12.3, label="CCh 1uM"))

    pkg2 = VasoPackage.open(package_path)
    assert meta.id in pkg2.datasets
    assert any(event.label.startswith("CCh") for event in pkg2.events)
    verification = pkg2.verify()
    assert verification["ok"], verification
    assert meta.id in pkg2.catalog.datasets
    assert pkg2.catalog.datasets[meta.id].ref_count == 0
    assert pkg2.linkmap == {}


def test_pack_blob(tmp_path: Path) -> None:
    package_path = tmp_path / "study.vaso"
    VasoPackage.create(package_path)
    pkg = VasoPackage.open(package_path)
    dataset = DatasetMeta(
        name="Seg2",
        modality="diam",
        sampling=Sampling(rate_hz=30.0),
        channels=[ChannelSpec(key="ID", unit="um")],
    )
    pkg.add_dataset(dataset)

    blob_path = tmp_path / "a.tif"
    blob_path.write_bytes(b"TIFF\x00" + b"\x00" * 1024)
    ref = pkg.pack_file_into_blobs(
        dataset_id=dataset.id,
        fs_path=blob_path,
        role="tiff",
        mime="image/tiff",
    )
    assert ref.uri.startswith("vaso://blobs/")
    verification = pkg.verify()
    assert verification["ok"], verification


def test_relink_updates_linkmap(tmp_path: Path) -> None:
    package_path = tmp_path / "study.vaso"
    VasoPackage.create(package_path)
    pkg = VasoPackage.open(package_path)

    dataset = DatasetMeta(
        name="Seg3",
        modality="diam",
        sampling=Sampling(rate_hz=20.0),
        channels=[ChannelSpec(key="ID", unit="um")],
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    actual = data_dir / "trace.csv"
    content = b"time,diam\n0,120\n1,121\n"
    actual.write_bytes(content)
    digest = sha256(content).hexdigest()

    missing = tmp_path / "missing" / "trace.csv"
    ref = RefEntry(
        sha256=digest,
        size=len(content),
        mime="text/csv",
        role="trace",
        uri=missing.as_posix(),
    )

    pkg.add_dataset(dataset, refs=[ref])
    updates = pkg.relink(data_dir)
    assert missing.as_posix() in updates
    assert updates[missing.as_posix()] == actual.as_posix()

    reopened = VasoPackage.open(package_path)
    assert reopened.linkmap[missing.as_posix()] == actual.as_posix()
    resolved_refs = reopened.refs[dataset.id]
    assert any(r.uri == actual.as_posix() for r in resolved_refs)
    entry = reopened.catalog.datasets[dataset.id]
    assert entry.ref_count == 1


def test_export_project_to_package(tmp_path: Path) -> None:
    trace_df = pd.DataFrame({"Time": [0.0, 1.0], "ID": [120.0, 121.2]})
    events_df = pd.DataFrame({"Time": [0.5], "Label": ["CCh"], "Lane": ["drug"]})
    sample = SampleN(name="Seg4", trace_data=trace_df, events_data=events_df)
    experiment = Experiment(name="Exp1", samples=[sample])
    project = Project(name="Study", experiments=[experiment])

    dest = tmp_path / "sidecar.vaso"
    export_project_to_package(project, dest, base_dir=tmp_path, timezone="UTC")

    pkg = VasoPackage.open(dest)
    assert len(pkg.datasets) == 1
    dataset_id = next(iter(pkg.datasets))
    assert pkg.catalog.datasets[dataset_id].ref_count == 0
    assert len(pkg.events) == 1
