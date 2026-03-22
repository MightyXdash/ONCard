from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import requests

from studymate.services.update_service import ReleaseInfo


class UpdateDialog(QDialog):
    def __init__(self, *, current_version: str, release: ReleaseInfo) -> None:
        super().__init__()
        self.setWindowTitle("Update available")
        self.setFixedSize(560, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)
        title = QLabel("A newer version of ONCards is ready.")
        title.setObjectName("SectionTitle")
        text = QLabel(
            f"Current version: {current_version}\n"
            f"Latest version: {release.version}\n\n"
            "Do you want to download the installer now?"
        )
        text.setObjectName("SectionText")
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text)

        notes_title = QLabel("What changed")
        notes_title.setObjectName("SectionTitle")
        layout.addWidget(notes_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("UpdateNotesScroll")
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(12)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMinimumHeight(180)
        notes.setPlainText(release.notes_text)
        container_layout.addWidget(notes)

        for image_url in release.image_urls:
            pixmap = self._load_image(image_url)
            if pixmap is None:
                continue
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(pixmap.scaledToWidth(440, Qt.SmoothTransformation))
            label.setObjectName("UpdateNoteImage")
            container_layout.addWidget(label)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("Later")
        update = QPushButton("Update now")
        update.setObjectName("PrimaryButton")
        later.clicked.connect(self.reject)
        update.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(update)
        layout.addLayout(buttons)

    @staticmethod
    def _load_image(url: str) -> QPixmap | None:
        try:
            response = requests.get(url, timeout=8)
            response.raise_for_status()
        except requests.RequestException:
            return None
        pixmap = QPixmap()
        if not pixmap.loadFromData(response.content):
            return None
        return pixmap
