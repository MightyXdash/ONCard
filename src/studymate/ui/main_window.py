from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService
from studymate.ui.create_tab import CreateTab
from studymate.ui.icon_helper import IconHelper
from studymate.ui.study_tab import StudyTab


class MainWindow(QMainWindow):
    def __init__(self, paths, datastore: DataStore, ollama: OllamaService, icons: IconHelper) -> None:
        super().__init__()
        self.paths = paths
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.pending_update_launcher: Path | None = None
        self.setWindowTitle("ONCard")
        self.resize(1600, 980)
        self._build_ui()

    def _build_ui(self) -> None:
        shell = QWidget()
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(18)

        nav = QHBoxLayout()
        self.settings_btn = QPushButton("")
        self.settings_btn.setObjectName("TopNavButton")
        self.settings_btn.setFixedWidth(52)
        self.settings_btn.setIcon(self.icons.icon("common", "settings_info", "S"))
        self.settings_btn.clicked.connect(self._open_settings)
        nav.addWidget(self.settings_btn, 0, Qt.AlignLeft)
        nav.addStretch(1)

        self.create_btn = QPushButton("Create")
        self.create_btn.setObjectName("TopNavButton")
        self.create_btn.setCheckable(True)
        self.create_btn.setChecked(True)
        self.create_btn.setIcon(self.icons.icon("create", "autofill_magic", "C"))

        self.cards_btn = QPushButton("Cards")
        self.cards_btn.setObjectName("TopNavButton")
        self.cards_btn.setCheckable(True)
        self.cards_btn.setIcon(self.icons.icon("study", "flashcard", "C"))

        self.create_btn.clicked.connect(lambda: self._switch_tab(0))
        self.cards_btn.clicked.connect(lambda: self._switch_tab(1))
        nav.addWidget(self.create_btn, 0, Qt.AlignRight)
        nav.addWidget(self.cards_btn, 0, Qt.AlignRight)
        layout.addLayout(nav)

        self.stack = QStackedWidget()
        self.create_tab = CreateTab(self.datastore, self.ollama, self.icons)
        self.study_tab = StudyTab(self.datastore, self.ollama, self.icons)
        self.create_tab.card_saved.connect(self.study_tab.reload_cards)
        self.stack.addWidget(self.create_tab)
        self.stack.addWidget(self.study_tab)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(shell)

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.create_btn.setChecked(index == 0)
        self.cards_btn.setChecked(index == 1)
        if index == 1:
            self.study_tab.reload_cards()

    def _open_settings(self) -> None:
        QMessageBox.information(self, "Settings", "Settings panel is coming next.")

    def queue_update_launcher(self, launcher_path: Path) -> None:
        self.pending_update_launcher = launcher_path
        self.close()

    def consume_pending_update_launcher(self) -> Path | None:
        launcher = self.pending_update_launcher
        self.pending_update_launcher = None
        return launcher

    def closeEvent(self, event) -> None:
        if self.create_tab.has_pending_work():
            answer = QMessageBox.question(
                self,
                "Force quit?",
                "ONCard is still processing queued work. Do you want to force quit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.pending_update_launcher = None
                event.ignore()
                return
        super().closeEvent(event)
