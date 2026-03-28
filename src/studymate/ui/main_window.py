from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMessageBox, QVBoxLayout, QWidget

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedStackedWidget
from studymate.ui.audio import ClickSoundFilter, UiSoundBank
from studymate.ui.create_tab import CreateTab
from studymate.ui.icon_helper import IconHelper
from studymate.ui.settings_dialog import SettingsDialog
from studymate.ui.study_tab import StudyTab


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        preflight: ModelPreflightService,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.preflight = preflight
        self.sounds = UiSoundBank(self.paths.assets / "sfx")
        self._click_sfx_filter = ClickSoundFilter(self.sounds, self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._click_sfx_filter)
        self._update_shutdown_requested = False
        self.setWindowTitle("ONCard")
        self._apply_initial_geometry()
        self._build_ui()

    def _apply_initial_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1600, 980)
            return
        available = screen.availableGeometry()
        width = min(1600, max(980, available.width() - 64))
        height = min(980, max(720, available.height() - 72))
        self.resize(width, height)

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("AppShell")
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(18)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(12)
        self.settings_btn = AnimatedButton("")
        self.settings_btn.setObjectName("SettingsNavButton")
        self.settings_btn.setFixedSize(34, 34)
        self.settings_btn.setIcon(self.icons.icon("common", "settings_info", "S"))
        self.settings_btn.clicked.connect(self._open_settings)
        nav.addWidget(self.settings_btn, 0, Qt.AlignLeft)
        nav.addStretch(1)

        self.create_btn = AnimatedButton("Create")
        self.create_btn.setObjectName("TopNavButton")
        self.create_btn.setCheckable(True)
        self.create_btn.setChecked(True)
        self.create_btn.setProperty("skipClickSfx", True)

        self.cards_btn = AnimatedButton("Cards")
        self.cards_btn.setObjectName("TopNavButton")
        self.cards_btn.setCheckable(True)
        self.cards_btn.setProperty("skipClickSfx", True)

        self.create_btn.clicked.connect(lambda: self._play_and_switch(0))
        self.cards_btn.clicked.connect(lambda: self._play_and_switch(1))
        nav.addWidget(self.create_btn, 0, Qt.AlignRight)
        nav.addWidget(self.cards_btn, 0, Qt.AlignRight)
        layout.addLayout(nav)

        self.stack = AnimatedStackedWidget()
        self.create_tab = CreateTab(self.datastore, self.ollama, self.icons, self.preflight)
        self.study_tab = StudyTab(self.datastore, self.ollama, self.icons, self.preflight)
        self.create_tab.card_saved.connect(self.study_tab.mark_cards_dirty)
        self.stack.addWidget(self.create_tab)
        self.stack.addWidget(self.study_tab)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(shell)
        self.statusBar().setSizeGripEnabled(False)
        self._sync_nav_icons()

    def _sync_nav_icons(self) -> None:
        self.create_btn.setIcon(
            self.icons.icon(
                "create",
                "autofill_magic_white" if self.create_btn.isChecked() else "autofill_magic",
                "C",
            )
        )
        self.cards_btn.setIcon(
            self.icons.icon(
                "study",
                "flashcard_white" if self.cards_btn.isChecked() else "flashcard",
                "C",
            )
        )

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.create_btn.setChecked(index == 0)
        self.cards_btn.setChecked(index == 1)
        self._sync_nav_icons()
        if index == 1:
            self.study_tab.activate_view()

    def _play_and_switch(self, index: int) -> None:
        if self.stack.currentIndex() != index:
            self.sounds.play("woosh")
        self._switch_tab(index)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.datastore, self.ollama, self.preflight, self)
        dialog.exec()

    def begin_update_shutdown(self) -> None:
        self._update_shutdown_requested = True

    def show_update_notice(self, message: str, timeout_ms: int = 6000) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def closeEvent(self, event) -> None:
        if not self._update_shutdown_requested and self.create_tab.has_pending_work():
            answer = QMessageBox.question(
                self,
                "Force quit?",
                "ONCard is still processing queued work. Do you want to force quit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)
