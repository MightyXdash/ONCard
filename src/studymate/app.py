from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import threading
import time

from PySide6.QtCore import QEventLoop, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QProgressDialog, QVBoxLayout

from studymate.services.account_archive_service import AccountArchiveService
from studymate.services.account_service import AccountService
from studymate.services.backup_service import BackupService
from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.model_registry import DEFAULT_TEXT_LLM_KEY, MODELS, QN_SUMMARIZER_AUTO_SELECTED_SETTING, QN_SUMMARIZER_CONTEXT_LENGTH, QN_SUMMARIZER_MODEL_KEY, has_any_supported_text_model
from studymate.services.update_content import load_packaged_update_content
from studymate.services.ollama_service import OllamaService
from studymate.services.update_service import ReleaseInfo, UpdateError, UpdateService
from studymate.theme import app_stylesheet, apply_app_theme
from studymate.ui.icon_helper import IconHelper
from studymate.ui.main_window import MainWindow
from studymate.ui.startup_splash import StartupSplash
from studymate.ui.update_dialog import EmbeddingOnboardingDialog, UpdateDialog, WhatsNewDialog, WhatsNewSummaryDialog
from studymate.ui.window_effects import polish_windows_window
from studymate.ui.wizard import OnboardingWizard
from studymate.utils.paths import AppPaths
from studymate.version import APP_VERSION
from studymate.workers.install_worker import ModelInstallWorker
from studymate.workers.startup_warmup_worker import StartupWarmupWorker
from studymate.workers.update_check_worker import UpdateCheckWorker
from studymate.workers.update_download_worker import UpdateDownloadWorker


class RoundedTopBanner(QLabel):
    def __init__(self, banner_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap(str(banner_path)) if banner_path.exists() else QPixmap()
        self.setMinimumHeight(260)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def paintEvent(self, event) -> None:
        del event
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()
        path = QPainterPath()
        radius = 16.0
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius)
        path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        painter.setClipPath(path)
        target = rect.adjusted(0, 0, 0, 0)
        scaled = self._pixmap.scaled(
            int(target.width() * 1.28),
            int(target.height() * 1.28),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = target.center().x() - scaled.width() // 2
        y = target.top()
        painter.drawPixmap(x, y, scaled)


class QNSummarizerDownloadDialog(QDialog):
    def __init__(self, banner_path: Path, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowTitle("Faster And Better")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        transparent_palette = self.palette()
        transparent = QColor(0, 0, 0, 0)
        for role in (
            QPalette.ColorRole.Window,
            QPalette.ColorRole.Base,
            QPalette.ColorRole.AlternateBase,
            QPalette.ColorRole.Button,
        ):
            transparent_palette.setColor(role, transparent)
        self.setPalette(transparent_palette)
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setMaximumWidth(430)
        polish_windows_window(self, rounded=False, remove_border=True, native_shadow=False)
        self.setStyleSheet(
            """
            QDialog {
                background: transparent;
            }
            QLabel#SummarizerTitle {
                font-size: 20px;
                font-weight: 700;
                color: #1A1A1A;
            }
            QLabel#SummarizerText {
                font-size: 13px;
                line-height: 1.45;
                color: #4B5560;
            }
            QPushButton {
                min-height: 34px;
                border-radius: 8px;
                border: none;
                padding: 6px 12px;
                background: rgba(15, 37, 57, 0.08);
                color: #1A1A1A;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.14);
                border: none;
            }
            QPushButton#PrimaryButton {
                background: #111827;
                color: white;
            }
            QPushButton#PrimaryButton:hover {
                background: #273247;
                border: none;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(16)

        banner = RoundedTopBanner(banner_path)
        banner.setFixedSize(430, 260)
        layout.addWidget(banner)

        title = QLabel("Faster And Better")
        title.setObjectName("SummarizerTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setContentsMargins(22, 0, 22, 0)
        layout.addWidget(title)

        text = QLabel(
            "QyrouNnet-Summarizer is a lightweight summarization model developed as part of the ONCard ecosystem. "
            "It is optimized for processing structured content, including Wikipedia articles, while supporting features tailored specifically "
            "to its architecture. The model delivers high-speed summarization, reducing typical processing times from several seconds to "
            "near-instant performance."
        )
        text.setObjectName("SummarizerText")
        text.setWordWrap(True)
        text.setContentsMargins(24, 0, 24, 0)
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(24, 0, 24, 0)
        buttons.setSpacing(8)
        download_btn = QPushButton("Download Model")
        download_btn.setObjectName("PrimaryButton")
        learn_btn = QPushButton("Learn More")
        pass_btn = QPushButton("I Will Pass")
        buttons.addWidget(download_btn)
        buttons.addWidget(learn_btn)
        buttons.addWidget(pass_btn)
        layout.addLayout(buttons)

        download_btn.clicked.connect(self.accept)
        learn_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://ollama.com/QyrouNnet/summarizer")))
        pass_btn.clicked.connect(self.reject)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16.0, 16.0)
        painter.fillPath(path, QColor("#FAFAFB"))
        painter.setPen(QPen(QColor(215, 219, 226, 230), 1))
        painter.drawPath(path)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        polish_windows_window(self, rounded=False, remove_border=True, native_shadow=False)


class SessionController:
    def __init__(self, app: QApplication, base_paths: AppPaths, icons: IconHelper) -> None:
        self.app = app
        self.base_paths = base_paths
        self.icons = icons
        self.ollama = OllamaService()
        self.account_service = AccountService(base_paths)
        self.archive_service = AccountArchiveService()

        self.window: MainWindow | None = None
        self.paths: AppPaths | None = None
        self.datastore: DataStore | None = None
        self.preflight: ModelPreflightService | None = None
        self.update_service: UpdateService | None = None
        self.backup_service: BackupService | None = None
        self._switching = False
        self._startup_ready = False
        self._background_model_sync_threads: list[threading.Thread] = []

        self.app.aboutToQuit.connect(self._on_about_to_quit)

    def start(self) -> int:
        self.account_service.ensure_seed_account(name="Account 1")
        if not self._open_active_session(show_splash=True):
            return 0
        return self.app.exec()

    def list_accounts(self) -> list[dict]:
        return self.account_service.list_accounts()

    def active_account_id(self) -> str:
        return self.account_service.get_active_account_id()

    def rename_active_account(self, new_name: str) -> None:
        active_id = self.active_account_id()
        if not active_id:
            raise RuntimeError("No active account is available.")
        clean_name = str(new_name or "").strip()
        if not clean_name:
            raise ValueError("Name is required.")
        self.account_service.rename_account(active_id, clean_name)

    def switch_to_account(self, account_id: str) -> None:
        target = str(account_id or "").strip()
        if not target or target == self.active_account_id():
            return
        self.account_service.set_active_account(target)
        self._reload_session()

    def create_temp_export(self) -> Path:
        if self.paths is None:
            raise RuntimeError("No active session.")
        account = self.account_service.get_active_account()
        if account is None:
            raise RuntimeError("No active account is available.")
        return self.archive_service.create_temp_export(account=account, paths=self.paths)

    def active_transfer_profile_name(self) -> str:
        account = self.account_service.get_active_account()
        fallback_name = str(account.get("name", "")).strip() if account is not None else ""
        if self.datastore is None:
            return fallback_name or "ONCard Account"
        profile = self.datastore.load_profile()
        for key in ("profile_name", "name"):
            candidate = str(profile.get(key, "")).strip()
            if candidate:
                return candidate
        return fallback_name or "ONCard Account"

    def estimate_current_account_size(self) -> int:
        if self.paths is None:
            raise RuntimeError("No active session.")
        total = 0
        for item in self.paths.data.rglob("*"):
            if not item.is_file():
                continue
            try:
                total += item.stat().st_size
            except OSError:
                continue
        return total

    def create_transfer_export(self) -> Path:
        return self.create_temp_export()

    def import_archive_into_current(self, archive_path: Path) -> None:
        if self.paths is None:
            raise RuntimeError("No active session.")
        current_id = self.active_account_id()
        if not current_id:
            raise RuntimeError("No active account is available.")
        self._teardown_session()
        target_paths = self.account_service.account_paths(current_id)
        target_paths.ensure()
        try:
            self.archive_service.import_archive_into_account(archive_path=Path(archive_path), paths=target_paths, overwrite=True)
        except Exception:
            self._open_active_session(show_splash=False)
            raise
        if not self._open_active_session(show_splash=False):
            self.app.quit()

    def import_transfer_archive_with_feedback(self, archive_path: Path) -> None:
        self.import_archive_into_current(archive_path)
        QMessageBox.information(
            None,
            "Transfer account",
            "Account data was copied from the host and loaded on this device.",
        )

    def delete_current_account(self) -> str:
        current_id = self.active_account_id()
        if not current_id:
            raise RuntimeError("No active account is available.")
        self._teardown_session()
        next_id = self.account_service.delete_account(current_id)
        if not next_id:
            self.app.quit()
            return "quit"
        if not self._open_active_session(show_splash=False):
            self.app.quit()
            return "quit"
        return "switched"

    def create_new_account_via_profile(self, parent=None) -> bool:
        provisional_name = "New account"
        suffix = 2
        while self.account_service.name_exists(provisional_name):
            provisional_name = f"New account {suffix}"
            suffix += 1

        created = self.account_service.create_account(name=provisional_name, make_active=False)
        created_id = str(created.get("id", ""))
        created_paths = self.account_service.account_paths(created_id)
        created_paths.ensure()
        created_store: DataStore | None = DataStore(created_paths)
        try:
            wizard = OnboardingWizard(
                created_paths,
                created_store,
                self.ollama,
                self.icons,
                archive_service=self.archive_service,
            )
            if wizard.exec() == 0:
                self.account_service.delete_account(created_id)
                return False

            imported_archive = str(getattr(wizard, "import_archive_path", "") or "").strip()
            if imported_archive:
                if created_store is not None:
                    created_store.close()
                    created_store = None
                self.archive_service.import_archive_into_account(
                    archive_path=Path(imported_archive),
                    paths=created_paths,
                    overwrite=True,
                )
                created_store = DataStore(created_paths)

            if created_store is None:
                created_store = DataStore(created_paths)
            profile = created_store.load_profile()
            final_name = str(profile.get("name", "")).strip() or provisional_name
            if self.account_service.name_exists(final_name, exclude_account_id=created_id):
                raise RuntimeError("An account with the same name already exists.")
            if final_name != provisional_name:
                self.account_service.rename_account(created_id, final_name)
        except Exception:
            self.account_service.delete_account(created_id)
            raise
        finally:
            if created_store is not None:
                created_store.close()

        self.account_service.set_active_account(created_id)
        self._reload_session()
        return True

    def _reload_session(self) -> None:
        if self._switching:
            return
        self._switching = True
        try:
            self._teardown_session()
            if not self._open_active_session(show_splash=False):
                self.app.quit()
        finally:
            self._switching = False

    def _teardown_session(self) -> None:
        if self.window is not None:
            self.window.begin_update_shutdown()
            self.window.close()
            self.window.deleteLater()
            self.window = None
        if self.datastore is not None:
            self.datastore.close()
            self.datastore = None
        self.preflight = None
        self.backup_service = None
        self.update_service = None
        self.paths = None

    def _open_active_session(self, *, show_splash: bool) -> bool:
        active = self.account_service.get_active_account()
        if active is None:
            active = self.account_service.ensure_seed_account(name="Account 1")
        account_id = str(active.get("id", "")).strip()
        if not account_id:
            return False
        self.account_service.set_active_account(account_id)
        self.paths = self.account_service.account_paths(account_id)
        self.paths.ensure()

        self.datastore = DataStore(self.paths)
        self.ollama.configure_from_ai_settings(self.datastore.load_ai_settings())
        self.backup_service = BackupService(self.paths)
        self.preflight = ModelPreflightService(self.datastore, self.ollama)
        self.update_service = UpdateService(self.paths)
        self._sync_account_name_from_profile()
        setup = self.datastore.load_setup()
        self.app.setProperty("reducedMotion", bool(setup.get("performance", {}).get("reduced_motion", False)))

        app_icon = self.paths.icons / "app" / "app_logo.png"
        if show_splash:
            splash = StartupSplash(video_path=self.paths.startup_video, app_icon=app_icon if app_icon.exists() else None)
            splash.show()
            self.app.processEvents()
            _run_startup_warmup(self.app, splash, self.datastore, self.preflight)

        if not bool(setup.get("onboarding_complete", False)):
            wizard = OnboardingWizard(
                self.paths,
                self.datastore,
                self.ollama,
                self.icons,
                archive_service=self.archive_service,
            )
            result = wizard.exec()
            if result == 0:
                return False
            if wizard.import_archive_path:
                self.datastore.close()
                self.archive_service.import_archive_into_account(
                    archive_path=Path(wizard.import_archive_path),
                    paths=self.paths,
                    overwrite=True,
                )
                self.datastore = DataStore(self.paths)
                self.ollama.configure_from_ai_settings(self.datastore.load_ai_settings())
                self.preflight = ModelPreflightService(self.datastore, self.ollama)
            self._sync_account_name_from_profile()
            setup = self.datastore.load_setup()

        apply_app_theme(self.app, dict(setup.get("appearance", {})).get("theme", "light"))

        if not _ensure_default_text_model(self.app, self.datastore, self.ollama):
            return False

        self.window = MainWindow(
            self.paths,
            self.datastore,
            self.ollama,
            self.icons,
            self.preflight,
            session_controller=self,
        )
        self.window.show()
        self._maybe_prompt_qn_summarizer_download()
        self._schedule_background_model_sync()

        if self.window is not None and self.update_service is not None and self.datastore is not None and self.paths is not None:
            window = self.window
            update_service = self.update_service
            datastore = self.datastore
            paths = self.paths
            QTimer.singleShot(350, lambda: _notify_pending_silent_patch(window, update_service))
            QTimer.singleShot(
                500,
                lambda: _show_whats_new_if_needed(
                    self.app,
                    window,
                    datastore,
                    self.ollama,
                    update_service,
                    paths,
                ),
            )
            QTimer.singleShot(1200, lambda: _check_for_updates(self.app, window, update_service))
        self._startup_ready = True
        return True

    def _maybe_prompt_qn_summarizer_download(self) -> None:
        if self.window is None or self.datastore is None:
            return
        try:
            snap = self.preflight.snapshot(force=True) if self.preflight is not None else None
        except Exception:
            snap = None
        if snap is not None and snap.has_model(QN_SUMMARIZER_MODEL_KEY):
            ai_settings = self.datastore.load_ai_settings()
            if not bool(ai_settings.get(QN_SUMMARIZER_AUTO_SELECTED_SETTING, False)) and not str(ai_settings.get("wiki_breakdown_model_key", "")).strip():
                ai_settings["wiki_breakdown_model_key"] = QN_SUMMARIZER_MODEL_KEY
                ai_settings["wiki_breakdown_context_length"] = QN_SUMMARIZER_CONTEXT_LENGTH
                ai_settings[QN_SUMMARIZER_AUTO_SELECTED_SETTING] = True
                self.datastore.save_ai_settings(ai_settings)
            return
        dialog = QNSummarizerDownloadDialog(self.paths.banners / "summarizer_download.png", self.window)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self.window._open_settings(auto_install_model_key=QN_SUMMARIZER_MODEL_KEY)

    def _schedule_background_model_sync(self) -> None:
        if self.preflight is None:
            return

        def run_sync() -> None:
            preflight = self.preflight
            if preflight is None:
                return
            try:
                preflight.snapshot(force=True)
                preflight.invalidate()
            except Exception:
                return

        def launch_sync_thread() -> None:
            thread = threading.Thread(target=run_sync, daemon=True)
            self._background_model_sync_threads.append(thread)
            thread.start()
            self._background_model_sync_threads = [item for item in self._background_model_sync_threads if item.is_alive()]

        # Post-launch retries: catches cases where Ollama starts a bit later than the UI.
        QTimer.singleShot(1200, launch_sync_thread)
        QTimer.singleShot(4500, launch_sync_thread)

    def _sync_account_name_from_profile(self) -> None:
        if self.datastore is None:
            return
        active_id = self.active_account_id()
        if not active_id:
            return
        profile = self.datastore.load_profile()
        account = self.account_service.get_account(active_id)
        if account is None:
            return

        account_name = str(account.get("name", "")).strip()
        desired_user_name = str(profile.get("name", "")).strip()
        if not desired_user_name:
            desired_user_name = account_name or f"Account {active_id[:6]}"

        profile_name = str(profile.get("profile_name", "")).strip() or desired_user_name
        profile_changed = False
        if str(profile.get("name", "")).strip() != desired_user_name:
            profile["name"] = desired_user_name
            profile_changed = True
        if str(profile.get("profile_name", "")).strip() != profile_name:
            profile["profile_name"] = profile_name
            profile_changed = True

        final_account_name = desired_user_name
        if account_name != desired_user_name:
            try:
                self.account_service.rename_account(active_id, desired_user_name)
            except ValueError:
                base = desired_user_name or account_name or f"Account {active_id[:6]}"
                suffix = 2
                candidate = base
                while self.account_service.name_exists(candidate, exclude_account_id=active_id):
                    candidate = f"{base} {suffix}"
                    suffix += 1
                self.account_service.rename_account(active_id, candidate)
                final_account_name = candidate
                if profile.get("name", "") != final_account_name:
                    profile["name"] = final_account_name
                    profile_changed = True
                if not str(profile.get("profile_name", "")).strip():
                    profile["profile_name"] = final_account_name
                    profile_changed = True

        if profile_changed:
            self.datastore.save_profile(profile)

    def _on_about_to_quit(self) -> None:
        active_id = self.active_account_id()
        if active_id:
            try:
                self.account_service.touch_last_used(active_id)
            except Exception:
                pass
        if self.backup_service is not None:
            self.backup_service.create_exit_backup()
        if self.update_service is not None:
            _maybe_install_pending_silent_patch(self.update_service)
        if self.datastore is not None:
            self.datastore.close()


def run_app() -> int:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parents[2]
    base_paths = AppPaths.from_runtime(root)
    base_paths.ensure()

    app = QApplication(sys.argv)
    app.setEffectEnabled(Qt.UI_AnimateTooltip, False)

    fonts_dir = base_paths.assets / "fonts" / "NunitoSans"
    if fonts_dir.exists():
        preferred_fonts = [
            "NunitoSans-Regular.ttf",
            "NunitoSans-SemiBold.ttf",
            "NunitoSans-Bold.ttf",
            "NunitoSans-ExtraBold.ttf",
        ]
        selected_fonts = [fonts_dir / name for name in preferred_fonts if (fonts_dir / name).exists()]
        for font_path in selected_fonts or list(fonts_dir.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(font_path))
    literata_dir = base_paths.assets / "fonts" / "Literata"
    if literata_dir.exists():
        preferred_fonts = [
            "Literata-Regular.ttf",
            "Literata-Italic.ttf",
            "Literata-SemiBold.ttf",
            "Literata-SemiBoldItalic.ttf",
            "Literata-Bold.ttf",
            "Literata-BoldItalic.ttf",
        ]
        selected_fonts = [literata_dir / name for name in preferred_fonts if (literata_dir / name).exists()]
        for font_path in selected_fonts or list(literata_dir.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Nunito Sans", 10))
    app.setStyleSheet(app_stylesheet())

    icons = IconHelper(base_paths.icons)
    app_icon = base_paths.icons / "app" / "app_logo.png"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    controller = SessionController(app, base_paths, icons)
    return controller.start()


def _run_startup_warmup(
    app: QApplication,
    splash: StartupSplash,
    datastore: DataStore,
    preflight: ModelPreflightService,
) -> None:
    minimum_done = {"value": False}
    worker_done = {"value": False}
    finished_payload: dict[str, object] = {}

    worker = StartupWarmupWorker(datastore, preflight)
    app._oncard_startup_worker = worker  # type: ignore[attr-defined]
    splash.update_progress("Preparing your library", "Loading SQL cache and warmup tasks...", 3)

    def maybe_quit() -> None:
        return

    def on_progress(phase: str, status: str, value: int) -> None:
        splash.update_progress(phase, status, value)

    def on_finished(payload: object) -> None:
        finished_payload["snapshot"] = payload
        worker_done["value"] = True
        maybe_quit()

    def on_failed(message: str) -> None:
        finished_payload["error"] = message
        worker_done["value"] = True
        maybe_quit()

    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.start()
    minimum_end = time.monotonic() + 3.0
    while True:
        app.processEvents()
        if not minimum_done["value"] and time.monotonic() >= minimum_end:
            minimum_done["value"] = True
        if minimum_done["value"] and worker_done["value"]:
            break
        time.sleep(0.01)
    splash.close()
    app.processEvents()
    if finished_payload.get("error"):
        QMessageBox.warning(None, "Startup warmup", str(finished_payload["error"]))


def _check_for_updates(app: QApplication, window: MainWindow, update_service: UpdateService) -> None:
    worker = UpdateCheckWorker(update_service, APP_VERSION)
    app._oncard_update_check_worker = worker  # type: ignore[attr-defined]

    def on_available(release: ReleaseInfo) -> None:
        if release.update_kind == "patch":
            _prepare_silent_patch_update(app, window, update_service, release)
            return
        banner = _resolve_update_prompt_banner(update_service, release)
        dialog = UpdateDialog(release=release, prompt_banner=banner)
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
        try:
            installer_path = Path(path_str)
            launcher = update_service.create_post_exit_launcher(installer_path, os.getpid(), silent=False)
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
        except UpdateError as exc:
            QMessageBox.warning(window, "Update failed", str(exc))
            return
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


def _resolve_update_prompt_banner(update_service: UpdateService, release: ReleaseInfo) -> Path:
    remote_banner = update_service.download_release_prompt_image(release)
    if remote_banner is not None and remote_banner.exists():
        return remote_banner
    return load_packaged_update_content(update_service.paths.assets, APP_VERSION).prompt_banner


def _prepare_silent_patch_update(
    app: QApplication,
    window: MainWindow,
    update_service: UpdateService,
    release: ReleaseInfo,
) -> None:
    pending = update_service.load_ready_silent_patch(APP_VERSION)
    if pending and str(pending.get("latest_version", "")) == release.version:
        window.show_update_notice("Patch update ready. It will install after you close ONCard.", 7000)
        return
    if getattr(app, "_oncard_silent_patch_worker", None) is not None:
        return

    window.show_update_notice("Downloading patch update in the background...", 6000)
    worker = UpdateDownloadWorker(update_service, release)
    app._oncard_silent_patch_worker = worker  # type: ignore[attr-defined]

    def on_finished(path_str: str) -> None:
        app._oncard_silent_patch_worker = None  # type: ignore[attr-defined]
        installer_path = Path(path_str)
        update_service.save_update_state(
            {
                "current_version": APP_VERSION,
                "latest_version": release.version,
                "installer_path": str(installer_path),
                "pending_silent_install": True,
                "show_whats_new_for": release.version,
            }
        )
        window.show_update_notice("Patch update ready. It will install after you close ONCard.", 7000)

    def on_failed(_message: str) -> None:
        app._oncard_silent_patch_worker = None  # type: ignore[attr-defined]
        window.show_update_notice("Background update download failed. ONCard will try again later.", 7000)

    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.start()


def _notify_pending_silent_patch(window: MainWindow, update_service: UpdateService) -> None:
    pending = update_service.load_ready_silent_patch(APP_VERSION)
    if pending:
        window.show_update_notice("Patch update ready. It will install after you close ONCard.", 7000)


def _maybe_install_pending_silent_patch(update_service: UpdateService) -> None:
    pending = update_service.load_ready_silent_patch(APP_VERSION)
    if not pending:
        return
    installer_path = Path(str(pending.get("installer_path", "")))
    if not installer_path.exists():
        update_service.clear_update_state()
        return
    launcher = update_service.create_post_exit_launcher(installer_path, os.getpid(), silent=True)
    pending["launcher_path"] = str(launcher)
    update_service.save_update_state(pending)
    try:
        update_service.launch_helper(launcher)
    except UpdateError:
        update_service.clear_update_state()


def _ensure_default_text_model(app: QApplication, datastore: DataStore, ollama: OllamaService) -> bool:
    setup = datastore.load_setup()
    installed_models = dict(setup.get("installed_models", {}))
    try:
        installed_tags = ollama.installed_tags(use_cloud=False)
    except Exception:
        installed_tags = set()

    default_spec = MODELS[DEFAULT_TEXT_LLM_KEY]
    if has_any_supported_text_model(installed_models, installed_tags):
        return True

    prompt = QMessageBox(None)
    prompt.setWindowTitle(f"Install {default_spec.display_name}")
    prompt.setText(f"Install {default_spec.display_name} to open ONCard.")
    prompt.setInformativeText("No supported local AI model is installed yet.")
    exit_button = prompt.addButton("Exit app", QMessageBox.ButtonRole.RejectRole)
    install_button = prompt.addButton("Install", QMessageBox.ButtonRole.AcceptRole)
    prompt.setDefaultButton(install_button)
    prompt.exec()

    if prompt.clickedButton() == exit_button:
        return False

    if shutil.which("ollama") is None:
        QMessageBox.warning(
            None,
            "Ollama required",
            "Install Ollama first, then restart ONCard and choose Install again.",
        )
        return False

    progress = QProgressDialog(f"Installing {default_spec.display_name}...", None, 0, 0, None)
    progress.setWindowTitle("AI model setup")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setCancelButton(None)
    progress.show()

    worker = ModelInstallWorker([DEFAULT_TEXT_LLM_KEY], ollama)
    app._oncard_required_model_install_worker = worker  # type: ignore[attr-defined]
    loop = QEventLoop()
    result = {"ok": False}

    def on_line(message: str) -> None:
        progress.setLabelText(message or f"Installing {default_spec.display_name}...")

    def on_complete(status: dict) -> None:
        result["ok"] = bool(status.get(DEFAULT_TEXT_LLM_KEY))
        loop.quit()

    worker.line.connect(on_line)
    worker.complete.connect(on_complete)
    worker.start()
    loop.exec()
    progress.close()
    worker.wait(1000)
    app._oncard_required_model_install_worker = None  # type: ignore[attr-defined]

    setup = datastore.load_setup()
    installed_models = dict(setup.get("installed_models", {}))
    installed_models[DEFAULT_TEXT_LLM_KEY] = result["ok"]
    setup["installed_models"] = installed_models
    selected_models = list(setup.get("selected_models", []))
    if result["ok"] and DEFAULT_TEXT_LLM_KEY not in selected_models:
        selected_models.append(DEFAULT_TEXT_LLM_KEY)
    setup["selected_models"] = selected_models
    datastore.save_setup(setup)
    ai_settings = datastore.load_ai_settings()
    ai_settings["selected_text_llm_key"] = DEFAULT_TEXT_LLM_KEY
    ai_settings["selected_ocr_llm_key"] = DEFAULT_TEXT_LLM_KEY
    datastore.save_ai_settings(ai_settings)

    if not result["ok"]:
        QMessageBox.warning(
            None,
            "Install failed",
            f"ONCard could not install {default_spec.display_name}. The app needs that model before opening.",
        )
    return result["ok"]

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
    intro = WhatsNewSummaryDialog(version=APP_VERSION, content=content)
    intro.exec()
    if intro.dive_deeper_requested:
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
        installed = ollama.installed_tags(use_cloud=False)
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
