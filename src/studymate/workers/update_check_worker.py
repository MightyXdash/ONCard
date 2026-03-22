from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.services.update_service import ReleaseInfo, UpdateError, UpdateService


class UpdateCheckWorker(QThread):
    available = Signal(object)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, service: UpdateService, current_version: str) -> None:
        super().__init__()
        self.service = service
        self.current_version = current_version

    def run(self) -> None:
        try:
            release = self.service.get_latest_release(self.current_version)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        if release is None:
            self.up_to_date.emit()
            return
        self.available.emit(release)
