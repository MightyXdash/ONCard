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
        layout.addWidget(title)
        layout.addWidget(question, 1)
        layout.addLayout(footer)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.card)
