from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from studymate.ui.window_effects import polish_windows_window


class SpinnerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, *, size: int = 250) -> None:
        super().__init__(parent)
        self._spokes = 10
        self._cycle_ms = 1000
        self._elapsed_ms = 0
        self._color = QColor("#000000")
        self.setFixedSize(size, size)
        self.setObjectName("StartupSpinner")

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed_ms = (self._elapsed_ms + self._timer.interval()) % self._cycle_ms
        self.update()

    @staticmethod
    def _pulse_scale(phase: float) -> float:
        # Approximate the keyframe "kick" near 50% with a smooth bump.
        distance = abs(phase - 0.5)
        if distance >= 0.18:
            return 1.0
        normalized = 1.0 - (distance / 0.18)
        return 1.0 + 0.5 * normalized * normalized

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)

        side = float(min(self.width(), self.height()))
        bar_width = side / 20.0
        bar_height = side / 4.8
        base_translation = side / 2.65
        radius = bar_width / 2.0
        now = self._elapsed_ms / self._cycle_ms
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0

        for index in range(self._spokes):
            rotation = float(index + 1) * 36.0
            delay = float(index + 1) * 0.1
            phase = (now - delay) % 1.0
            translation = base_translation * self._pulse_scale(phase)
            theta = math.radians(rotation - 90.0)
            centerline_x = center_x + math.cos(theta) * translation
            centerline_y = center_y + math.sin(theta) * translation

            painter.save()
            painter.translate(centerline_x, centerline_y)
            painter.rotate(rotation)
            painter.drawRoundedRect(
                int(-bar_width / 2.0),
                int(0),
                int(bar_width),
                int(bar_height),
                radius,
                radius,
            )
            painter.restore()


class StartupSplash(QWidget):
    def __init__(self, *, video_path: Path, app_icon: Path | None = None) -> None:
        del video_path, app_icon
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("StartupSplash")
        self.setStyleSheet(
            """
            QWidget#StartupSplash {
                background: transparent;
                border: none;
            }
            QFrame#StartupMediaHost {
                background: #ffffff;
                border: none;
                border-radius: 54px;
            }
            QWidget#StartupSpinnerWrap {
                background: transparent;
                border: none;
            }
            QWidget#StartupSpinner {
                background: transparent;
                border: none;
            }
            """
        )
        self.resize(520, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        self._media_host = QFrame(self)
        self._media_host.setObjectName("StartupMediaHost")
        host_layout = QVBoxLayout(self._media_host)
        host_layout.setContentsMargins(24, 24, 24, 24)
        host_layout.setSpacing(0)

        spinner_wrap = QWidget(self._media_host)
        spinner_wrap.setObjectName("StartupSpinnerWrap")
        spinner_layout = QVBoxLayout(spinner_wrap)
        spinner_layout.setContentsMargins(0, 0, 0, 0)
        spinner_layout.setSpacing(0)
        spinner_layout.addStretch(1)
        spinner_layout.addWidget(SpinnerWidget(spinner_wrap, size=250), 0, Qt.AlignmentFlag.AlignCenter)
        spinner_layout.addStretch(1)
        host_layout.addWidget(spinner_wrap, 1)

        root.addWidget(self._media_host, 1)

        self._center_on_screen()
        self._apply_native_window_chrome()

    def _apply_native_window_chrome(self) -> None:
        polish_windows_window(self, small_corners=False, remove_border=True)

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        side = min(int(min(geometry.width(), geometry.height()) * 0.36), 560)
        side = max(360, side)
        width = min(side, max(360, geometry.width() - 120))
        height = min(side, max(360, geometry.height() - 120))
        self.resize(width, height)
        self.move(
            geometry.x() + int((geometry.width() - width) / 2),
            geometry.y() + int((geometry.height() - height) / 2),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_native_window_chrome()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_native_window_chrome()

    def update_progress(self, phase: str, status: str, value: int) -> None:
        return
