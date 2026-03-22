from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget


class BannerWidget(QWidget):
    def __init__(self, *, banner_path: Path, placeholder_text: str, height: int = 220, radius: int = 28) -> None:
        super().__init__()
        self.banner_path = banner_path
        self.placeholder_text = placeholder_text
        self.banner_height = height
        self.radius = radius
        self.banner_width = int(height * (16 / 9))
        self.setFixedSize(self.banner_width, height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            clip = QPainterPath()
            clip.addRoundedRect(rect, self.radius, self.radius)
            painter.setClipPath(clip)

            pixmap = QPixmap(str(self.banner_path)) if self.banner_path.exists() else QPixmap()
            if not pixmap.isNull():
                scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = max(0, (scaled.width() - self.width()) // 2)
                y = max(0, (scaled.height() - self.height()) // 2)
                painter.drawPixmap(self.rect(), scaled, QRect(x, y, self.width(), self.height()))
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
