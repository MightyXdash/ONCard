from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from studymate.services.update_service import ReleaseInfo, UpdateError, UpdateService


class UpdateDownloadWorker(QThread):
    progress_value = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, service: UpdateService, release: ReleaseInfo) -> None:
        super().__init__()
        self.service = service
        self.release = release

    def run(self) -> None:
        try:
            path = self.service.download_installer(self.release, on_progress=self._emit_progress)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(str(path))

    def _emit_progress(self, percent: int, message: str) -> None:
        self.progress_value.emit(percent)
        self.status.emit(message)
