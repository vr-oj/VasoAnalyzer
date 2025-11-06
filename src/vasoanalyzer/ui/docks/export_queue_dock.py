"""Export queue dock for batch export management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["ExportQueueDock", "ExportJob", "ExportStatus"]


class ExportStatus(Enum):
    """Export job status."""

    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class ExportJob:
    """Export job specification."""

    name: str
    output_path: str
    format: str  # "TIFF", "SVG", "PNG", "PDF"
    dpi: int
    width_mm: float
    height_mm: float
    preset_name: str | None = None
    status: ExportStatus = ExportStatus.PENDING
    error_message: str | None = None


class ExportQueueDock(QDockWidget):
    """
    Dockable panel for batch export queue management.

    Features:
    - Add export jobs with format/DPI/size settings
    - Queue management (add, remove, clear)
    - Progress tracking
    - Export history
    """

    # Signal emitted when export is requested
    export_requested = pyqtSignal(list)  # list of ExportJob

    # Signal emitted when job is cancelled
    job_cancelled = pyqtSignal(str)  # job name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Export Queue", parent)
        self.setObjectName("ExportQueueDock")

        # Export queue
        self._jobs: list[ExportJob] = []

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ Public API

    def add_job(self, job: ExportJob) -> None:
        """Add export job to queue."""
        self._jobs.append(job)
        self._refresh_queue()

    def remove_job(self, job_name: str) -> None:
        """Remove job from queue."""
        self._jobs = [j for j in self._jobs if j.name != job_name]
        self._refresh_queue()

    def clear_completed(self) -> None:
        """Clear completed jobs from queue."""
        self._jobs = [j for j in self._jobs if j.status != ExportStatus.COMPLETED]
        self._refresh_queue()

    def update_job_status(
        self, job_name: str, status: ExportStatus, error: str | None = None
    ) -> None:
        """Update job status."""
        for job in self._jobs:
            if job.name == job_name:
                job.status = status
                if error:
                    job.error_message = error
                break
        self._refresh_queue()

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dock UI."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        header = QLabel("Export Queue")
        header.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(header)

        # Job configuration group
        config_group = QGroupBox("New Export Job")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(6)

        # Format selector
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["TIFF", "SVG", "PNG", "PDF"])
        format_layout.addWidget(self.format_combo, 1)
        config_layout.addLayout(format_layout)

        # DPI selector
        dpi_layout = QHBoxLayout()
        dpi_layout.addWidget(QLabel("DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setSingleStep(50)
        dpi_layout.addWidget(self.dpi_spin, 1)
        config_layout.addLayout(dpi_layout)

        # Width selector (mm)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Width (mm):"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(50, 500)
        self.width_spin.setValue(180)  # Single column default
        self.width_spin.setSingleStep(1)
        self.width_spin.setToolTip("Figure width in millimeters (89mm single, 183mm double column)")
        width_layout.addWidget(self.width_spin, 1)
        config_layout.addLayout(width_layout)

        # Height selector (mm)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Height (mm):"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(50, 500)
        self.height_spin.setValue(120)  # Default aspect ratio
        self.height_spin.setSingleStep(1)
        self.height_spin.setToolTip("Figure height in millimeters")
        height_layout.addWidget(self.height_spin, 1)
        config_layout.addLayout(height_layout)

        # Preset selector (future enhancement)
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("(Current Style)")
        preset_layout.addWidget(self.preset_combo, 1)
        config_layout.addLayout(preset_layout)

        # Add to queue button
        self.add_job_btn = QPushButton("Add to Queue")
        self.add_job_btn.clicked.connect(self._on_add_job)
        config_layout.addWidget(self.add_job_btn)

        layout.addWidget(config_group)

        # Queue list
        queue_label = QLabel("Queued Exports:")
        layout.addWidget(queue_label)

        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list, 1)

        # Queue actions
        queue_actions = QHBoxLayout()
        queue_actions.setSpacing(4)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Remove selected job")
        self.remove_btn.clicked.connect(self._on_remove_job)
        queue_actions.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("Clear Completed")
        self.clear_btn.setToolTip("Clear completed jobs")
        self.clear_btn.clicked.connect(self._on_clear_completed)
        queue_actions.addWidget(self.clear_btn)

        layout.addLayout(queue_actions)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Export all button
        self.export_all_btn = QPushButton("Export All")
        self.export_all_btn.setToolTip("Start batch export")
        self.export_all_btn.clicked.connect(self._on_export_all)
        layout.addWidget(self.export_all_btn)

        # Summary label
        self.summary_label = QLabel("0 jobs in queue")
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.summary_label)

        self.setWidget(container)

    def _apply_theme(self) -> None:
        """Apply current theme to dock."""
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text = CURRENT_THEME.get("text", "#000000")
        self.setStyleSheet(f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
            QListWidget {{
                background-color: {bg};
                color: {text};
            }}
        """)

    # ------------------------------------------------------------------ Queue Management

    def _refresh_queue(self) -> None:
        """Refresh queue list display."""
        self.queue_list.clear()

        for job in self._jobs:
            status_icon = {
                ExportStatus.PENDING: "⏸",
                ExportStatus.RUNNING: "▶",
                ExportStatus.COMPLETED: "✓",
                ExportStatus.FAILED: "✗",
                ExportStatus.CANCELLED: "⊗",
            }.get(job.status, "?")

            display_text = f"{status_icon} {job.name} ({job.format}, {job.dpi} DPI)"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, job.name)

            # Color code by status
            if job.status == ExportStatus.COMPLETED:
                item.setForeground(Qt.darkGreen)
            elif job.status == ExportStatus.FAILED:
                item.setForeground(Qt.red)
            elif job.status == ExportStatus.RUNNING:
                item.setForeground(Qt.blue)

            if job.error_message:
                item.setToolTip(f"Error: {job.error_message}")

            self.queue_list.addItem(item)

        # Update summary
        pending = sum(1 for j in self._jobs if j.status == ExportStatus.PENDING)
        completed = sum(1 for j in self._jobs if j.status == ExportStatus.COMPLETED)
        total = len(self._jobs)
        self.summary_label.setText(
            f"{total} job{'s' if total != 1 else ''} ({pending} pending, {completed} completed)"
        )

        # Update progress
        if total > 0:
            progress = int((completed / total) * 100)
            self.progress_bar.setValue(progress)
        else:
            self.progress_bar.setValue(0)

    # ------------------------------------------------------------------ Actions

    def _on_add_job(self) -> None:
        """Add new export job to queue."""
        # Get output path
        format_ext = self.format_combo.currentText().lower()
        file_filter = f"{self.format_combo.currentText()} Files (*.{format_ext})"

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Destination",
            f"figure.{format_ext}",
            file_filter,
        )

        if not output_path:
            return

        # Create job
        job = ExportJob(
            name=f"Export {len(self._jobs) + 1}",
            output_path=output_path,
            format=self.format_combo.currentText(),
            dpi=self.dpi_spin.value(),
            width_mm=float(self.width_spin.value()),
            height_mm=float(self.height_spin.value()),
            preset_name=None
            if self.preset_combo.currentIndex() == 0
            else self.preset_combo.currentText(),
        )

        self.add_job(job)
        QMessageBox.information(self, "Job Added", f"Export job added to queue:\n{output_path}")

    def _on_remove_job(self) -> None:
        """Remove selected job from queue."""
        items = self.queue_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No Selection", "Please select a job to remove.")
            return

        job_name = items[0].data(Qt.UserRole)
        self.remove_job(job_name)

    def _on_clear_completed(self) -> None:
        """Clear all completed jobs."""
        self.clear_completed()

    def _on_export_all(self) -> None:
        """Start batch export."""
        pending_jobs = [j for j in self._jobs if j.status == ExportStatus.PENDING]
        if not pending_jobs:
            QMessageBox.information(self, "No Jobs", "No pending jobs to export.")
            return

        self.export_requested.emit(pending_jobs)
