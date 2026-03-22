from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
)


class CardTile(QFrame):
    selected = Signal(dict)
    move_requested = Signal(dict)

    def __init__(self, card: dict) -> None:
        super().__init__()
        self.card = card
        self.setObjectName("CardTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)
        self.setFixedHeight(218)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        title = QTextEdit()
        title.setReadOnly(True)
        title.setPlainText(card.get("title", "Untitled"))
        title.setObjectName("CardTitleDisplay")
        title.setMaximumHeight(54)

        question = QTextEdit()
        question.setReadOnly(True)
        question.setPlainText(card.get("question", ""))
        question.setObjectName("CardQuestionDisplay")
        question.setMinimumHeight(72)
        question.setMaximumHeight(78)

        meta = QLabel(
            f"{card.get('subject', 'General')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        meta.setObjectName("SmallMeta")

        move_button = QPushButton("Move card")
        move_button.clicked.connect(lambda: self.move_requested.emit(self.card))

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(meta, 1)
        footer.addWidget(move_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(question, 1)
        layout.addLayout(footer)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.card)
