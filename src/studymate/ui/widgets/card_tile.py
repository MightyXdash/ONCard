from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)


class CardTile(QFrame):
    selected = Signal(dict)
    move_requested = Signal(dict)
    remove_requested = Signal(dict)

    def __init__(self, card: dict) -> None:
        super().__init__()
        self.card = card
        self.setObjectName("CardTile")
        self.setCursor(Qt.PointingHandCursor)
        self._min_tile_width = 260
        self._max_tile_width = 420
        self.setMinimumWidth(self._min_tile_width)
        self.setMaximumWidth(self._max_tile_width)
        self.setFixedHeight(232)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.title_display = QTextEdit()
        self.title_display.setReadOnly(True)
        self.title_display.setPlainText(card.get("title", "Untitled"))
        self.title_display.setObjectName("CardTitleDisplay")
        self.title_display.setMaximumHeight(58)

        self.question_display = QTextEdit()
        self.question_display.setReadOnly(True)
        self.question_display.setPlainText(card.get("question", ""))
        self.question_display.setObjectName("CardQuestionDisplay")
        self.question_display.setMinimumHeight(86)
        self.question_display.setMaximumHeight(104)

        meta = QLabel(
            f"{card.get('subject', 'General')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        meta.setObjectName("SmallMeta")

        options_button = QToolButton()
        options_button.setText("Options")
        options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        options_button.setObjectName("CompactGhostButton")
        options_menu = QMenu(options_button)
        move_action = options_menu.addAction("Move card")
        remove_action = options_menu.addAction("Remove")
        move_action.triggered.connect(lambda: self.move_requested.emit(self.card))
        remove_action.triggered.connect(lambda: self.remove_requested.emit(self.card))
        options_button.setMenu(options_menu)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(meta, 1)
        footer.addWidget(options_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self.title_display)
        layout.addWidget(self.question_display, 1)
        layout.addLayout(footer)
        self.set_tile_width(320)

    def set_tile_width(self, width: int) -> None:
        clamped = max(self._min_tile_width, min(self._max_tile_width, int(width)))
        self.setFixedWidth(clamped)
        self.setFixedHeight(220 if clamped <= 290 else 236 if clamped <= 340 else 252 if clamped <= 390 else 268)
        self.title_display.setMaximumHeight(54 if clamped <= 290 else 62)
        self.question_display.setMinimumHeight(78 if clamped <= 290 else 94)
        self.question_display.setMaximumHeight(86 if clamped <= 290 else 112)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.card)
