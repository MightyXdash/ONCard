from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from studymate.services.update_service import ReleaseInfo


class UpdateDialog(QDialog):
    def __init__(self, *, current_version: str, release: ReleaseInfo) -> None:
        super().__init__()
        self.setWindowTitle("Update available")
        self.setFixedSize(420, 220)

        layout = QVBoxLayout(self)
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
        layout.addWidget(text, 1)

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
