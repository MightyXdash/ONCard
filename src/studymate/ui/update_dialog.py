from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from studymate.services.update_content import PackagedUpdateContent
from studymate.services.update_service import ReleaseInfo
from studymate.ui.animated import AnimatedButton
from studymate.ui.audio import UiSoundBank
from studymate.ui.banner_widget import BannerWidget


class UpdateDialog(QDialog):
    def __init__(self, *, release: ReleaseInfo, prompt_banner: Path) -> None:
        super().__init__()
        self.setWindowTitle("Update available")
        self.setFixedSize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel("New Update!")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        banner = BannerWidget(
            banner_path=prompt_banner,
            placeholder_text="update_prompt_banner_16x9.png",
            height=188,
            radius=24,
        )
        layout.addWidget(banner, 0, Qt.AlignmentFlag.AlignHCenter)

        prompt = QLabel("Would you like us to install the app for you?")
        prompt.setObjectName("SectionTitle")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = AnimatedButton("No")
        install = AnimatedButton("Yes")
        install.setObjectName("PrimaryButton")
        later.clicked.connect(self.reject)
        install.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(install)
        buttons.addStretch(1)
        layout.addLayout(buttons)


class WhatsNewDialog(QDialog):
    def __init__(self, *, version: str, content: PackagedUpdateContent) -> None:
        super().__init__()
        self.setWindowTitle("What's new")
        self.resize(760, 860)
        self.sounds = UiSoundBank(content.banner1.parents[2] / "sfx")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        surface = QFrame()
        surface.setObjectName("Surface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(18, 18, 18, 18)
        surface_layout.setSpacing(16)
        layout.addWidget(surface, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(4, 2, 4, 8)
        body.setSpacing(18)

        title = QLabel(content.update_name or f"Welcome to ONCard {version}")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        body.addWidget(title)

        if content.subtitle.strip():
            subtitle = QLabel(content.subtitle)
            subtitle.setObjectName("UpdateSubtitle")
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle.setWordWrap(True)
            body.addWidget(subtitle)

        banner1 = BannerWidget(
            banner_path=content.banner1,
            placeholder_text="whats_new_top_banner_16x9.png",
            height=228,
            radius=26,
        )
        body.addWidget(banner1, 0, Qt.AlignmentFlag.AlignHCenter)

        text1 = QLabel(content.text1)
        text1.setObjectName("SectionText")
        text1.setWordWrap(True)
        text1.setAlignment(Qt.AlignmentFlag.AlignJustify | Qt.AlignmentFlag.AlignTop)
        body.addWidget(text1)

        if content.banner2 is not None:
            banner2 = BannerWidget(
                banner_path=content.banner2,
                placeholder_text="whats_new_showcase_16x9.png",
                height=228,
                radius=26,
            )
            body.addWidget(banner2, 0, Qt.AlignmentFlag.AlignHCenter)

        if content.text2.strip():
            text2 = QLabel(content.text2)
            text2.setObjectName("SectionText")
            text2.setWordWrap(True)
            text2.setAlignment(Qt.AlignmentFlag.AlignJustify | Qt.AlignmentFlag.AlignTop)
            body.addWidget(text2)

        body.addStretch(1)
        scroll.setWidget(host)
        surface_layout.addWidget(scroll, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = AnimatedButton("Continue")
        close_btn.setObjectName("PrimaryButton")
        close_btn.setFixedWidth(156)
        close_btn.setProperty("skipClickSfx", True)
        close_btn.clicked.connect(self._accept_with_click)
        close_row.addWidget(close_btn)
        close_row.addStretch(1)
        surface_layout.addLayout(close_row)

    def _accept_with_click(self) -> None:
        self.sounds.play("click")
        QTimer.singleShot(45, self.accept)


class EmbeddingOnboardingDialog(QDialog):
    def __init__(self, *, content: PackagedUpdateContent) -> None:
        super().__init__()
        self.setWindowTitle("Smarter study mode")
        self.setFixedSize(520, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        banner = BannerWidget(
            banner_path=content.prompt_banner,
            placeholder_text="update_prompt_banner_16x9.png",
            height=150,
            radius=22,
        )
        layout.addWidget(banner, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("Install the Nomic embedding model for NNA?")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        description = QLabel(
            "This optional model, nomic-embed-text-v2-moe, powers smarter topic grouping, weak-area detection, and reinforcement cards. "
            "It is only used for the new adaptive study flow."
        )
        description.setObjectName("SectionText")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = AnimatedButton("No")
        install = AnimatedButton("Yes")
        install.setObjectName("PrimaryButton")
        later.clicked.connect(self.reject)
        install.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(install)
        buttons.addStretch(1)
        layout.addLayout(buttons)
