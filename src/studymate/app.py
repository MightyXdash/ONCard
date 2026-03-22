from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from studymate.services.backup_service import BackupService
from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService
from studymate.services.update_service import ReleaseInfo, UpdateService
from studymate.theme import app_stylesheet
from studymate.ui.icon_helper import IconHelper
from studymate.ui.main_window import MainWindow
from studymate.ui.update_dialog import UpdateDialog
from studymate.ui.wizard import OnboardingWizard
from studymate.utils.paths import AppPaths
from studymate.version import APP_VERSION
from studymate.workers.update_check_worker import UpdateCheckWorker
from studymate.workers.update_download_worker import UpdateDownloadWorker


def run_app() -> int:
    root = Path(__file__).resolve().parents[2]
    paths = AppPaths.from_runtime(root)
    paths.ensure()

    app = QApplication(sys.argv)

    fonts_dir = paths.assets / "fonts" / "NunitoSans"
    if fonts_dir.exists():
        for font_path in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Nunito Sans", 10))
    app.setStyleSheet(app_stylesheet())

    icons = IconHelper(paths.icons)
    app_icon = paths.icons / "app" / "app_logo.png"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))

    datastore = DataStore(paths)
    backup_service = BackupService(paths)
    ollama = OllamaService()
    update_service = UpdateService(paths)

    setup = datastore.load_setup()
    if not setup.get("onboarding_complete", False):
        wizard = OnboardingWizard(paths, datastore, ollama, icons)
        result = wizard.exec()
        if result == 0:
            return 0

    window = MainWindow(paths, datastore, ollama, icons)
    app.aboutToQuit.connect(backup_service.create_exit_backup)
    app.aboutToQuit.connect(lambda: _launch_pending_update(window, update_service))
    window.show()

    QTimer.singleShot(1200, lambda: _check_for_updates(app, window, update_service))
    return app.exec()


def _check_for_updates(app: QApplication, window: MainWindow, update_service: UpdateService) -> None:
    worker = UpdateCheckWorker(update_service, APP_VERSION)
    app._oncards_update_check_worker = worker  # type: ignore[attr-defined]

    def on_available(release: ReleaseInfo) -> None:
        dialog = UpdateDialog(current_version=APP_VERSION, release=release)
        if dialog.exec():
            _download_update(app, window, update_service, release)

    worker.available.connect(on_available)
    worker.up_to_date.connect(lambda: None)
    worker.failed.connect(lambda _message: None)
    worker.start()


def _download_update(
    app: QApplication,
    window: MainWindow,
    update_service: UpdateService,
    release: ReleaseInfo,
) -> None:
    progress = QProgressDialog("Downloading update...", None, 0, 100, window)
    progress.setWindowTitle("Downloading update")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setCancelButton(None)
    progress.setValue(0)
    progress.show()

    worker = UpdateDownloadWorker(update_service, release)
    app._oncards_update_download_worker = worker  # type: ignore[attr-defined]

    def on_finished(path_str: str) -> None:
        progress.close()
        installer_path = Path(path_str)
        launcher = update_service.create_post_exit_launcher(installer_path, os.getpid())
        update_service.save_update_state(
            {
                "current_version": APP_VERSION,
                "latest_version": release.version,
                "installer_path": str(installer_path),
                "launcher_path": str(launcher),
            }
        )
        answer = QMessageBox.question(
            window,
            "Install update",
            "The new installer is ready. Close ONCards and launch the installer now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            window.queue_update_launcher(launcher)

    def on_failed(message: str) -> None:
        progress.close()
        QMessageBox.warning(window, "Update failed", message)

    worker.progress_value.connect(progress.setValue)
    worker.status.connect(progress.setLabelText)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.start()


def _launch_pending_update(window: MainWindow, update_service: UpdateService) -> None:
    launcher = window.consume_pending_update_launcher()
    if launcher and launcher.exists():
        update_service.launch_helper(launcher)
