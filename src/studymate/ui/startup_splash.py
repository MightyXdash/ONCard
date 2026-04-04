from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from studymate.ui.window_effects import polish_windows_window


class SpinnerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, *, size: int = 380) -> None:
        super().__init__(parent)
        self._cycle_ms = 1650
        self._elapsed_ms = 0
        self._color = QColor(71, 195, 248)
        self.setFixedSize(size, size)
        self.setObjectName("StartupSpinner")

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed_ms = (self._elapsed_ms + self._timer.interval()) % self._cycle_ms
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        side = float(min(self.width(), self.height()))
        bar_width = side / 18.0
        bar_height = side / 5.9
        radius = bar_width / 2.0
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        base_rotations = (0.0, 90.0, -90.0, 180.0)

        def eased_motion(phase_value: float) -> tuple[float, float, float]:
            if phase_value <= 0.7:
                travel = phase_value / 0.7
            else:
                travel = (1.0 - phase_value) / 0.3
            travel = max(0.0, min(1.0, travel))
            eased = travel * travel * (3.0 - 2.0 * travel)
            return eased, bar_width * 4.8 * eased, bar_height * 1.25 * eased

        def draw_segment(dx: float, dy: float, local_angle: float, alpha: int, scale: float) -> None:
            glow = QColor(self._color)
            glow.setAlpha(max(16, int(alpha * 0.5)))
            painter.setBrush(glow)
            painter.drawRoundedRect(
                int((-bar_width * scale) / 2.0 - 2),
                int((-bar_height * scale) / 2.0 - 2),
                int(bar_width * scale + 4),
                int(bar_height * scale + 4),
                radius + 2.0,
                radius + 2.0,
            )

            fill = QColor(self._color)
            fill.setAlpha(alpha)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                int((-bar_width * scale) / 2.0),
                int((-bar_height * scale) / 2.0),
                int(bar_width * scale),
                int(bar_height * scale),
                radius,
                radius,
            )

        now = self._elapsed_ms / self._cycle_ms
        trail_offsets = (0.0, 0.05, 0.1, 0.15)

        for base in base_rotations:
            for trail_index, offset in enumerate(trail_offsets):
                phase = (now - offset) % 1.0
                eased, dx, dy = eased_motion(phase)
                local_angle = 90.0 * eased
                alpha = 255 - trail_index * 84
                scale = 1.0 - trail_index * 0.12

                painter.save()
                painter.translate(center_x, center_y)
                painter.rotate(base)
                painter.translate(dx, dy)
                painter.rotate(local_angle)
                draw_segment(dx, dy, local_angle, alpha, scale)
                painter.restore()

            # Secondary layer adds more motion pieces for a richer look.
            phase2 = (now + 0.32) % 1.0
            eased2, dx2, dy2 = eased_motion(phase2)
            painter.save()
            painter.translate(center_x, center_y)
            painter.rotate(base + 45.0)
            painter.translate(dx2 * 0.72, dy2 * 0.72)
            painter.rotate(90.0 * eased2)
            draw_segment(dx2, dy2, 90.0 * eased2, 156, 0.72)
            painter.restore()

            phase3 = (now + 0.56) % 1.0
            eased3, dx3, dy3 = eased_motion(phase3)
            painter.save()
            painter.translate(center_x, center_y)
            painter.rotate(base - 30.0)
            painter.translate(dx3 * 0.56, dy3 * 0.56)
            painter.rotate(-110.0 * eased3)
            draw_segment(dx3, dy3, -110.0 * eased3, 132, 0.58)
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
        root.setContentsMargins(0, 0, 0, 0)
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
        spinner_layout.addWidget(SpinnerWidget(spinner_wrap, size=380), 0, Qt.AlignmentFlag.AlignCenter)
        spinner_layout.addStretch(1)
        host_layout.addWidget(spinner_wrap, 1)

        root.addWidget(self._media_host, 1)

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
