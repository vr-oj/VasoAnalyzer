"""Tests for epoch model and event conversion."""

import pytest

from vasoanalyzer.ui.publication import (
    Epoch,
    EpochManifest,
    bath_events_to_epochs,
    build_compact_legend,
    build_epoch_legend,
    drug_events_to_epochs,
    events_to_epochs,
    format_epoch_summary,
    pressure_setpoints_to_epochs,
)


class TestEpochModel:
    """Test Epoch dataclass and serialization."""

    def test_epoch_creation(self):
        """Test creating a basic epoch."""
        epoch = Epoch(
            id="test_1",
            channel="Drug",
            label="U-46619 25 nM",
            t_start=100.0,
            t_end=200.0,
            style="bar",
            color="#1f77b4",
            emphasis="strong",
        )

        assert epoch.id == "test_1"
        assert epoch.channel == "Drug"
        assert epoch.label == "U-46619 25 nM"
        assert epoch.t_start == 100.0
        assert epoch.t_end == 200.0
        assert epoch.style == "bar"
        assert epoch.color == "#1f77b4"
        assert epoch.emphasis == "strong"
        assert epoch.duration() == 100.0

    def test_epoch_validation(self):
        """Test epoch validation."""
        # Invalid: t_end < t_start
        with pytest.raises(ValueError, match="t_end.*t_start"):
            Epoch(
                id="bad",
                channel="Drug",
                label="Test",
                t_start=200.0,
                t_end=100.0,
                style="bar",
            )

    def test_epoch_overlaps(self):
        """Test epoch overlap detection."""
        epoch1 = Epoch(
            id="1",
            channel="Drug",
            label="A",
            t_start=100.0,
            t_end=200.0,
            style="bar",
        )
        epoch2 = Epoch(
            id="2",
            channel="Drug",
            label="B",
            t_start=150.0,
            t_end=250.0,
            style="bar",
        )
        epoch3 = Epoch(
            id="3",
            channel="Drug",
            label="C",
            t_start=300.0,
            t_end=400.0,
            style="bar",
        )

        assert epoch1.overlaps(epoch2)
        assert epoch2.overlaps(epoch1)
        assert not epoch1.overlaps(epoch3)
        assert not epoch3.overlaps(epoch1)

    def test_epoch_serialization(self):
        """Test epoch to_dict/from_dict round-trip."""
        original = Epoch(
            id="test",
            channel="Drug",
            label="Test Drug 100 nM",
            t_start=50.0,
            t_end=150.0,
            style="bar",
            color="#ff0000",
            emphasis="strong",
            row_index=1,
            meta={"drug_id": "test_drug", "concentration": 100},
        )

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Epoch.from_dict(data)

        assert restored.id == original.id
        assert restored.channel == original.channel
        assert restored.label == original.label
        assert restored.t_start == original.t_start
        assert restored.t_end == original.t_end
        assert restored.style == original.style
        assert restored.color == original.color
        assert restored.emphasis == original.emphasis
        assert restored.row_index == original.row_index
        assert restored.meta == original.meta


class TestEventConversion:
    """Test event to epoch conversion."""

    def test_events_to_epochs_basic(self):
        """Test basic event to epoch conversion."""
        event_times = [100.0, 200.0, 300.0]
        event_labels = ["Drug A", "Drug B", "Pressure 60"]
        event_label_meta = [
            {"category": "drug"},
            {"category": "drug"},
            {"category": "pressure"},
        ]

        epochs = events_to_epochs(
            event_times,
            event_labels,
            event_label_meta,
            default_duration=60.0,
        )

        assert len(epochs) == 3
        assert epochs[0].channel == "Drug"
        assert epochs[0].label == "Drug A"
        assert epochs[0].t_start == 100.0
        # Next event in same channel occurs at t=200 → infer end from that
        assert epochs[0].t_end == 200.0

        assert epochs[2].channel == "Pressure"
        assert epochs[2].style == "box"
        # No subsequent pressure event → default duration applied
        assert epochs[2].t_end == 360.0

    def test_events_to_epochs_uses_next_within_channel(self):
        """Durations should extend to the next event in the same channel."""
        event_times = [0.0, 120.0, 240.0]
        event_labels = ["Drug A on", "Drug A boost", "Drug B"]
        event_label_meta = [
            {"category": "drug"},
            {"category": "drug"},
            {"category": "drug"},
        ]

        epochs = events_to_epochs(
            event_times,
            event_labels,
            event_label_meta,
            default_duration=30.0,
        )

        assert len(epochs) == 3
        assert epochs[0].t_start == 0.0
        assert epochs[0].t_end == 120.0  # stretches to next drug event
        assert epochs[1].t_end == 240.0  # stretches to following drug event
        assert epochs[2].t_end == 270.0  # falls back to default duration

    def test_events_to_epochs_respects_metadata_duration(self):
        """Explicit duration/t_end metadata should override inferred values."""
        event_times = [10.0, 50.0]
        event_labels = ["Custom", "Custom"]
        event_label_meta = [
            {"category": "custom", "duration": 5},
            {"category": "custom", "t_end": 120.0},
        ]

        epochs = events_to_epochs(
            event_times,
            event_labels,
            event_label_meta,
            default_duration=30.0,
        )

        assert epochs[0].t_end == 15.0  # uses duration field
        assert epochs[1].t_end == 120.0  # uses explicit t_end value

    def test_pressure_setpoints_to_epochs(self):
        """Test pressure setpoint conversion."""
        setpoint_times = [0.0, 100.0, 200.0]
        setpoint_values = [20.0, 40.0, 60.0]

        epochs = pressure_setpoints_to_epochs(setpoint_times, setpoint_values)

        assert len(epochs) == 3
        assert all(e.channel == "Pressure" for e in epochs)
        assert all(e.style == "box" for e in epochs)

        assert epochs[0].label == "20 mmHg"
        assert epochs[0].t_start == 0.0
        assert epochs[0].t_end == 100.0

        assert epochs[1].label == "40 mmHg"
        assert epochs[1].t_start == 100.0
        assert epochs[1].t_end == 200.0

    def test_drug_events_to_epochs(self):
        """Test drug event conversion."""
        start_times = [100.0, 300.0]
        end_times = [200.0, 400.0]
        names = ["U-46619", "BaCl2"]
        concentrations = [25.0, 100.0]

        # Drugs
        drug_epochs = drug_events_to_epochs(
            start_times,
            end_times,
            names,
            concentrations,
            channel="Drug",
        )

        assert len(drug_epochs) == 2
        assert all(e.channel == "Drug" for e in drug_epochs)
        assert all(e.style == "bar" for e in drug_epochs)
        assert drug_epochs[0].label == "U-46619 25.0 nM"
        assert drug_epochs[1].label == "BaCl2 100.0 nM"

        # Blockers
        blocker_epochs = drug_events_to_epochs(
            start_times[:1],
            end_times[:1],
            names[:1],
            concentrations[:1],
            channel="Blocker",
        )

        assert len(blocker_epochs) == 1
        assert blocker_epochs[0].channel == "Blocker"

    def test_bath_events_to_epochs(self):
        """Test bath/perfusate event conversion."""
        start_times = [150.0]
        end_times = [250.0]
        labels = ["Ca2+-free PSS + EGTA 5 mM"]

        epochs = bath_events_to_epochs(start_times, end_times, labels)

        assert len(epochs) == 1
        assert epochs[0].channel == "Perfusate"
        assert epochs[0].style == "shade"
        assert epochs[0].label == "Ca2+-free PSS + EGTA 5 mM"


class TestEpochManifest:
    """Test epoch manifest serialization."""

    def test_manifest_serialization(self):
        """Test manifest to_dict/from_dict round-trip."""
        epochs = [
            Epoch(
                id="1",
                channel="Drug",
                label="Test",
                t_start=0.0,
                t_end=100.0,
                style="bar",
            ),
            Epoch(
                id="2",
                channel="Pressure",
                label="60 mmHg",
                t_start=0.0,
                t_end=200.0,
                style="box",
            ),
        ]

        manifest = EpochManifest(
            epochs=epochs,
            epoch_theme="default_v1",
            row_order=["Pressure", "Drug", "Blocker"],
        )

        # Serialize
        data = manifest.to_dict()

        # Deserialize
        restored = EpochManifest.from_dict(data)

        assert len(restored.epochs) == len(manifest.epochs)
        assert restored.epoch_theme == manifest.epoch_theme
        assert restored.row_order == manifest.row_order


class TestCaptionBuilder:
    """Test caption/legend generation."""

    def test_build_epoch_legend_simple(self):
        """Test simple epoch legend generation."""
        epochs = [
            Epoch(
                id="1",
                channel="Drug",
                label="U-46619 25 nM",
                t_start=100.0,
                t_end=200.0,
                style="bar",
            ),
        ]

        legend = build_epoch_legend(epochs)

        assert "drug application" in legend.lower()
        assert "U-46619 25 nM" in legend

    def test_build_epoch_legend_complex(self):
        """Test complex epoch legend with multiple channels."""
        epochs = [
            Epoch(
                id="1",
                channel="Pressure",
                label="60 mmHg",
                t_start=0.0,
                t_end=100.0,
                style="box",
            ),
            Epoch(
                id="2",
                channel="Drug",
                label="U-46619 25 nM",
                t_start=100.0,
                t_end=200.0,
                style="bar",
            ),
            Epoch(
                id="3",
                channel="Perfusate",
                label="Ca2+-free PSS",
                t_start=150.0,
                t_end=250.0,
                style="shade",
            ),
        ]

        legend = build_epoch_legend(epochs)

        assert "pressure" in legend.lower()
        assert "drug" in legend.lower()
        assert "perfusate" in legend.lower() or "shaded" in legend.lower()

    def test_build_compact_legend(self):
        """Test compact legend generation."""
        epochs = [
            Epoch(
                id="1",
                channel="Drug",
                label="U-46619",
                t_start=0.0,
                t_end=100.0,
                style="bar",
            ),
            Epoch(
                id="2",
                channel="Blocker",
                label="BaCl2",
                t_start=100.0,
                t_end=200.0,
                style="bar",
            ),
        ]

        legend = build_compact_legend(epochs)

        assert "Bars" in legend
        assert "U-46619" in legend
        assert "BaCl2" in legend

    def test_format_epoch_summary(self):
        """Test epoch summary formatting."""
        epochs = [
            Epoch(
                id="1",
                channel="Pressure",
                label="20 mmHg",
                t_start=0.0,
                t_end=100.0,
                style="box",
            ),
            Epoch(
                id="2",
                channel="Pressure",
                label="40 mmHg",
                t_start=100.0,
                t_end=200.0,
                style="box",
            ),
            Epoch(
                id="3",
                channel="Drug",
                label="U-46619",
                t_start=150.0,
                t_end=250.0,
                style="bar",
            ),
        ]

        summary = format_epoch_summary(epochs)

        assert "3 epochs" in summary
        assert "2 pressure" in summary
        assert "1 drug" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
