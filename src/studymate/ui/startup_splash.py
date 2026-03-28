from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:  # pragma: no cover
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QVideoWidget = None  # type: ignore[assignment]


class StartupSplash(QWidget):
    def __init__(self, *, video_path: Path, app_icon: Path | None = None) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("StartupSplash")
        self.setStyleSheet(
            """
            QWidget#StartupSplash {
                background: #ffffff;
                border: 1px solid rgba(111, 132, 154, 0.12);
            }
            QFrame#StartupMediaHost {
                background: #ffffff;
                border: none;
            }
            """
        )
        self.resize(320, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        self._media_host = QFrame(self)
        self._media_host.setObjectName("StartupMediaHost")
        host_layout = QVBoxLayout(self._media_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self._video_widget: QVideoWidget | QLabel
        if QMediaPlayer is not None and QVideoWidget is not None and video_path.exists():
            self._video_widget = QVideoWidget(self._media_host)
            self._video_widget.setStyleSheet("background: #ffffff; border: none;")
            if hasattr(self._video_widget, "setAspectRatioMode"):
                self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            host_layout.addWidget(self._video_widget, 1)
            self._player = QMediaPlayer(self)
            if QAudioOutput is not None:
                self._audio = QAudioOutput(self)
                self._audio.setMuted(True)
                self._player.setAudioOutput(self._audio)
            self._player.setVideoOutput(self._video_widget)
            self._player.setSource(QUrl.fromLocalFile(str(video_path.resolve())))
            self._player.mediaStatusChanged.connect(self._loop_video)
            self._player.play()
        else:
            fallback = QLabel("ONCard", self._media_host)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setStyleSheet(
                "font-size: 44px; font-weight: 800; color: #132435; letter-spacing: 0.04em; background: transparent;"
            )
            if app_icon is not None and app_icon.exists():
                fallback.setPixmap(QIcon(str(app_icon)).pixmap(164, 164))
            self._video_widget = fallback
            host_layout.addWidget(self._video_widget, 1)
            self._player = None

        root.addWidget(self._media_host, 1)

        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        width = min(self.width(), max(280, geometry.width() - 180))
        height = min(self.height(), max(280, geometry.height() - 180))
        self.resize(width, height)
        self.move(
            geometry.x() + int((geometry.width() - width) / 2),
            geometry.y() + int((geometry.height() - height) / 2),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        return

    def _loop_video(self, status) -> None:
        if self._player is None:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def update_progress(self, phase: str, status: str, value: int) -> None:
        return
