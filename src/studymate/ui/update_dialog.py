from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from studymate.services.update_content import PackagedUpdateContent
from studymate.services.update_service import ReleaseInfo
from studymate.ui.banner_widget import BannerWidget


class UpdateDialog(QDialog):
    def __init__(self, *, release: ReleaseInfo, content: PackagedUpdateContent) -> None:
        super().__init__()
        self.setWindowTitle("Update available")
        self.setFixedSize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        title = QLabel(f"{release.version}  New update available!")
        title.setObjectName("PageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        banner = BannerWidget(
            banner_path=content.prompt_banner,
            placeholder_text="update_prompt_banner_16x9.png",
            height=188,
            radius=24,
        )
        layout.addWidget(banner, 0, Qt.AlignmentFlag.AlignHCenter)

        description = QLabel(content.prompt_short_description)
        description.setObjectName("SectionText")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)

        prompt = QLabel("Do you want to install now?")
        prompt.setObjectName("SectionTitle")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(prompt)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("No")
        install = QPushButton("Yes")
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        top_banner = BannerWidget(
            banner_path=content.whats_new_banner,
            placeholder_text="whats_new_top_banner_16x9.png",
            height=196,
            radius=26,
        )
        body.addWidget(top_banner, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel(content.whats_new_title or f"Welcome to ONCard {version}")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        body.addWidget(title)

        description = QLabel(content.whats_new_description)
        description.setObjectName("SectionText")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        body.addWidget(description)

        showcase = BannerWidget(
            banner_path=content.whats_new_showcase,
            placeholder_text="whats_new_showcase_16x9.png",
            height=228,
            radius=26,
        )
        body.addWidget(showcase, 0, Qt.AlignmentFlag.AlignHCenter)

        if content.whats_new_points:
            points_title = QLabel("What got added")
            points_title.setObjectName("SectionTitle")
            body.addWidget(points_title)

            for point in content.whats_new_points:
                label = QLabel(f"- {point}")
                label.setObjectName("SectionText")
                label.setWordWrap(True)
                body.addWidget(label)

        closing = BannerWidget(
            banner_path=content.whats_new_closing_banner,
            placeholder_text="whats_new_closing_banner_16x9.png",
            height=164,
            radius=24,
        )
        body.addWidget(closing, 0, Qt.AlignmentFlag.AlignHCenter)

        body.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Continue")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)


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
        later = QPushButton("No")
        install = QPushButton("Yes")
        install.setObjectName("PrimaryButton")
        later.clicked.connect(self.reject)
        install.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(install)
        buttons.addStretch(1)
        layout.addLayout(buttons)
