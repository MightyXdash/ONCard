from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class BannerWidget(QWidget):
    def __init__(self, *, banner_path: Path, placeholder_text: str, height: int = 220, radius: int = 28) -> None:
        super().__init__()
        self.banner_path = banner_path
        self.placeholder_text = placeholder_text
        self.banner_height = height
        self.radius = radius
        self.banner_width = int(height * (16 / 9))
        self._image = self._load_image()
        self.setFixedSize(self.banner_width, height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _load_image(self) -> QImage:
        if not self.banner_path.exists():
            return QImage()
        reader = QImageReader(str(self.banner_path))
        reader.setAutoTransform(True)
        image = reader.read()
        return image if not image.isNull() else QImage()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            clip = QPainterPath()
            clip.addRoundedRect(rect, self.radius, self.radius)
            painter.setClipPath(clip)

            if not self._image.isNull():
                dpr = max(1.0, self.devicePixelRatioF())
                target_width = max(1, int(self.width() * dpr))
                target_height = max(1, int(self.height() * dpr))
                scaled = self._image.scaled(
                    target_width,
                    target_height,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                x = max(0, (scaled.width() - target_width) // 2)
                y = max(0, (scaled.height() - target_height) // 2)
                painter.drawImage(self.rect(), scaled, QRect(x, y, target_width, target_height))
            else:
                gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
                gradient.setColorAt(0.0, QColor("#f7f7f7"))
                gradient.setColorAt(0.5, QColor("#ededed"))
                gradient.setColorAt(1.0, QColor("#dddddd"))
                painter.fillPath(clip, gradient)

                painter.setPen(QColor("#5f5f5f"))
                painter.setFont(QFont("Segoe UI Variable Display", 16, QFont.DemiBold))
                painter.drawText(rect.adjusted(28, 0, -28, 0), Qt.AlignCenter, self.placeholder_text)

            painter.setClipping(False)
            painter.setPen(QPen(QColor("#d4d4d4"), 1))
            painter.drawRoundedRect(rect, self.radius, self.radius)
        finally:
            painter.end()
