from __future__ import annotations

from pathlib import Path
import time

import cv2
from PySide6.QtCore import QThread, Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from studymate.ui.window_effects import polish_windows_window


class VideoFrameWorker(QThread):
    frame_ready = Signal(QImage)

    def __init__(self, video_path: Path, target_size: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = Path(video_path)
        self._target_size = QSize(target_size)

    def run(self) -> None:
        capture = cv2.VideoCapture(str(self._video_path))
        if not capture.isOpened():
            return
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_interval = 1.0 / fps if fps > 1.0 else (1.0 / 30.0)
            target_width = max(1, self._target_size.width())
            target_height = max(1, self._target_size.height())
            next_frame_at = time.perf_counter()

            while not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue

                if frame.shape[1] != target_width or frame.shape[0] != target_height:
                    frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = QImage(
                    rgb.data,
                    rgb.shape[1],
                    rgb.shape[0],
                    rgb.shape[1] * rgb.shape[2],
                    QImage.Format.Format_RGB888,
                ).copy()
                self.frame_ready.emit(image)

                next_frame_at += frame_interval
                delay = next_frame_at - time.perf_counter()
                if delay > 0:
                    self.msleep(max(1, int(delay * 1000)))
                else:
                    next_frame_at = time.perf_counter()
        finally:
            capture.release()


class CroppedVideoFrame(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        if rect.isEmpty():
            return

        clip = QPainterPath()
        radius = min(32.0, rect.width() * 0.12, rect.height() * 0.12)
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.fillPath(clip, QColor("#000000"))

        if self._pixmap.isNull():
            return

        source_size = self._pixmap.size()
        if source_size.isEmpty():
            return

        scale = max(rect.width() / source_size.width(), rect.height() / source_size.height())
        scaled_width = source_size.width() * scale
        scaled_height = source_size.height() * scale
        target = QRect(
            int(round((rect.width() - scaled_width) / 2.0)),
            int(round((rect.height() - scaled_height) / 2.0)),
            int(round(scaled_width)),
            int(round(scaled_height)),
        )
        painter.drawPixmap(target, self._pixmap)


class StartupSplash(QWidget):
    def __init__(self, *, video_path: Path, app_icon: Path | None = None) -> None:
        del app_icon
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("StartupSplash")
        self.setStyleSheet(
            """
            QWidget#StartupSplash {
                background: transparent;
                border: none;
            }
            QWidget#StartupVideoShell {
                background: transparent;
                border: none;
            }
            """
        )

        self._video_path = Path(video_path)
        self._frame_worker: VideoFrameWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        self._shell = QWidget(self)
        self._shell.setObjectName("StartupVideoShell")
        shell_shadow = QGraphicsDropShadowEffect(self._shell)
        shell_shadow.setBlurRadius(50)
        shell_shadow.setOffset(0, 10)
        shell_shadow.setColor(QColor(15, 37, 57, 70))
        self._shell.setGraphicsEffect(shell_shadow)

        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self._video = CroppedVideoFrame(self._shell)
        shell_layout.addWidget(self._video, 1)
        root.addWidget(self._shell, 1)

        self._center_on_screen()
        self._apply_native_window_chrome()

    def _apply_native_window_chrome(self) -> None:
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        side = min(int(min(geometry.width(), geometry.height()) * 0.36), 560)
        side = max(360, side)
        side = min(side, max(360, min(geometry.width(), geometry.height()) - 120))
        self.resize(side, side)
        self.move(
            geometry.x() + int((geometry.width() - side) / 2),
            geometry.y() + int((geometry.height() - side) / 2),
        )

    def _start_video_worker(self) -> None:
        self._stop_video_worker()
        if not self._video_path.exists():
            return
        target_size = self._shell.size()
        if target_size.isEmpty():
            target_size = QSize(520, 520)
        worker = VideoFrameWorker(self._video_path, target_size, self)
        worker.frame_ready.connect(self._set_frame)
        worker.finished.connect(worker.deleteLater)
        self._frame_worker = worker
        worker.start()

    def _stop_video_worker(self) -> None:
        if self._frame_worker is None:
            return
        self._frame_worker.requestInterruption()
        self._frame_worker.wait(1500)
        self._frame_worker = None

    def _set_frame(self, image: QImage) -> None:
        self._video.setPixmap(QPixmap.fromImage(image))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_native_window_chrome()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_native_window_chrome()
        self._start_video_worker()

    def hideEvent(self, event) -> None:
        self._stop_video_worker()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._stop_video_worker()
        super().closeEvent(event)

    def update_progress(self, phase: str, status: str, value: int) -> None:
        del phase, status, value
        return
