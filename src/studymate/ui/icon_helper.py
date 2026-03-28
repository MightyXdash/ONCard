from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle


class IconHelper:
    def __init__(self, icons_root: Path) -> None:
        self.icons_root = icons_root
        self._cache: dict[tuple[str, str, str], QIcon] = {}

    def icon(self, group: str, name: str, fallback_text: str = "?") -> QIcon:
        cache_key = (group, name, fallback_text[:1].upper())
        if cache_key in self._cache:
            return self._cache[cache_key]
        path = self.icons_root / group / f"{name}.png"
        if path.exists():
            icon = QIcon(str(path))
        else:
            icon = self._generated_icon(fallback_text[:1].upper())
        self._cache[cache_key] = icon
        return icon

    @staticmethod
    def std_icon(name: QStyle.StandardPixmap) -> QIcon:
        return QApplication.style().standardIcon(name)

    @staticmethod
    def _generated_icon(char: str) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#e1e8f2"))
        painter.setPen(QColor("#9da9bb"))
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        font = QFont("Segoe UI", 22, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#5e6b7d"))
        painter.drawText(pix.rect(), Qt.AlignCenter, char)
        painter.end()
        return QIcon(pix)
