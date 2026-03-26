from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from studymate.services.backup_service import BackupService
from studymate.services.data_store import DataStore
from studymate.services.model_registry import MODELS
from studymate.services.update_content import load_packaged_update_content
from studymate.services.ollama_service import OllamaService
from studymate.services.update_service import ReleaseInfo, UpdateService
from studymate.theme import app_stylesheet
from studymate.ui.icon_helper import IconHelper
from studymate.ui.main_window import MainWindow
from studymate.ui.update_dialog import EmbeddingOnboardingDialog, UpdateDialog, WhatsNewDialog
from studymate.ui.wizard import OnboardingWizard
from studymate.utils.paths import AppPaths
from studymate.version import APP_VERSION
from studymate.workers.install_worker import ModelInstallWorker
from studymate.workers.update_check_worker import UpdateCheckWorker
from studymate.workers.update_download_worker import UpdateDownloadWorker


def run_app() -> int:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
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
    window.show()

    QTimer.singleShot(500, lambda: _show_whats_new_if_needed(app, window, datastore, ollama, update_service, paths))
    QTimer.singleShot(1200, lambda: _check_for_updates(app, window, update_service))
    return app.exec()


def _check_for_updates(app: QApplication, window: MainWindow, update_service: UpdateService) -> None:
    worker = UpdateCheckWorker(update_service, APP_VERSION)
    app._oncard_update_check_worker = worker  # type: ignore[attr-defined]

    def on_available(release: ReleaseInfo) -> None:
        content = load_packaged_update_content(update_service.paths.assets, APP_VERSION)
        dialog = UpdateDialog(release=release, content=content)
        if dialog.exec():
            _download_update_and_install(app, window, update_service, release)

    worker.available.connect(on_available)
    worker.up_to_date.connect(lambda: None)
    worker.failed.connect(lambda _message: None)
    worker.start()


def _download_update_and_install(
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
    app._oncard_update_download_worker = worker  # type: ignore[attr-defined]

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
                "show_whats_new_for": release.version,
            }
        )
        update_service.launch_helper(launcher)
        window.begin_update_shutdown()
        QTimer.singleShot(0, app.quit)

    def on_failed(message: str) -> None:
        progress.close()
        QMessageBox.warning(window, "Update failed", message)

    worker.progress_value.connect(progress.setValue)
    worker.status.connect(progress.setLabelText)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.start()

def _show_whats_new_if_needed(
    app: QApplication,
    window: MainWindow,
    datastore: DataStore,
    ollama: OllamaService,
    update_service: UpdateService,
    paths: AppPaths,
) -> None:
    state = update_service.load_update_state()
    if state.get("show_whats_new_for") != APP_VERSION:
        return
    content = load_packaged_update_content(paths.assets, APP_VERSION)
    dialog = WhatsNewDialog(version=APP_VERSION, content=content)
    dialog.exec()
    _maybe_prompt_embedding_onboarding(app, window, datastore, ollama, content)
    update_service.clear_update_state()


def _maybe_prompt_embedding_onboarding(
    app: QApplication,
    window: MainWindow,
    datastore: DataStore,
    ollama: OllamaService,
    content,
) -> None:
    setup = datastore.load_setup()
    prompted_version = str(setup.get("embedding_gate_prompted_version", ""))
    if prompted_version == APP_VERSION:
        return
    try:
        installed = ollama.installed_tags()
    except Exception:
        return
    if MODELS["nomic_embed_text_v2_moe"].primary_tag in installed:
        return

    dialog = EmbeddingOnboardingDialog(content=content)
    setup["embedding_gate_prompted_version"] = APP_VERSION
    if dialog.exec():
        datastore.save_setup(setup)
        _install_embedding_model(app, window, datastore, ollama)
        return
    setup["embedding_gate_declined_version"] = APP_VERSION
    datastore.save_setup(setup)


def _install_embedding_model(app: QApplication, window: MainWindow, datastore: DataStore, ollama: OllamaService) -> None:
    progress = QProgressDialog("Installing embedding model...", None, 0, 0, window)
    progress.setWindowTitle("Adaptive study setup")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setCancelButton(None)
    progress.show()

    worker = ModelInstallWorker(["nomic_embed_text_v2_moe"], ollama)
    app._oncard_embedding_install_worker = worker  # type: ignore[attr-defined]

    def on_line(message: str) -> None:
        progress.setLabelText(message or "Installing embedding model...")

    def on_complete(status: dict) -> None:
        progress.close()
        updated = datastore.load_setup()
        installed_models = dict(updated.get("installed_models", {}))
        installed_models["nomic_embed_text_v2_moe"] = bool(status.get("nomic_embed_text_v2_moe"))
        updated["installed_models"] = installed_models
        datastore.save_setup(updated)
        if status.get("nomic_embed_text_v2_moe"):
            QMessageBox.information(window, "Adaptive study ready", "Embedding model installed successfully.")
        else:
            QMessageBox.warning(window, "Install failed", "Could not install nomic-embed-text-v2-moe right now.")

    worker.line.connect(on_line)
    worker.complete.connect(on_complete)
    worker.start()
