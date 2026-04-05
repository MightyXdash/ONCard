from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
)

from studymate.ui.animated import AnimatedToolButton, CardHoverChrome


class CardTile(QFrame):
    selected = Signal(dict)
    move_requested = Signal(dict)
    remove_requested = Signal(dict)

    def __init__(self, card: dict) -> None:
        super().__init__()
        self.card = card
        self.setObjectName("CardTile")
        self.setCursor(Qt.PointingHandCursor)
        self._min_tile_width = 300
        self._max_tile_width = 460
        self.setMinimumWidth(self._min_tile_width)
        self.setMaximumWidth(self._max_tile_width)
        self.setFixedHeight(238)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._hover_chrome = CardHoverChrome(self)

        self.title_display = QLabel(card.get("title", "Untitled"))
        self.title_display.setObjectName("CardTitleLabel")
        self.title_display.setWordWrap(True)
        self.title_display.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.question_display = QLabel(card.get("question", ""))
        self.question_display.setObjectName("CardQuestionLabel")
        self.question_display.setWordWrap(True)
        self.question_display.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.question_display.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        subject_label = QLabel(card.get("subject", "General"))
        subject_label.setObjectName("SmallMeta")

        options_button = AnimatedToolButton()
        options_button.setText("More")
        options_button.setPopupMode(AnimatedToolButton.ToolButtonPopupMode.InstantPopup)
        options_button.setObjectName("CardOptionsButton")
        options_menu = QMenu(options_button)
        options_menu.setObjectName("CardOptionsMenu")
        options_menu.setWindowFlag(Qt.NoDropShadowWindowHint, False)
        options_menu.setAttribute(Qt.WA_TranslucentBackground, False)
        move_action = options_menu.addAction("Move card")
        remove_action = options_menu.addAction("Remove")
        move_action.triggered.connect(lambda: self.move_requested.emit(self.card))
        remove_action.triggered.connect(lambda: self.remove_requested.emit(self.card))
        options_button.setMenu(options_menu)

        difficulty_badge = QLabel(f"Difficulty {card.get('natural_difficulty', 5)}/10")
        difficulty_badge.setObjectName("CardMetaPill")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title_display, 1)
        header.addWidget(options_button, 0, Qt.AlignTop)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addWidget(subject_label, 1)
        footer.addWidget(difficulty_badge, 0, Qt.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.question_display, 1)
        layout.addLayout(footer)
        self.set_tile_width(336)

    def set_tile_width(self, width: int) -> None:
        clamped = max(self._min_tile_width, min(self._max_tile_width, int(width)))
        self.setFixedWidth(clamped)
        if clamped <= 330:
            tile_height = 228
            title_height = 52
            question_height = 74
        elif clamped <= 390:
            tile_height = 242
            title_height = 60
            question_height = 88
        else:
            tile_height = 256
            title_height = 68
            question_height = 102
        self.setFixedHeight(tile_height)
        self.title_display.setMaximumHeight(title_height)
        self.question_display.setMaximumHeight(question_height)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.card)

    def enterEvent(self, event) -> None:
        self._hover_chrome.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_chrome.set_hovered(False)
        super().leaveEvent(event)
