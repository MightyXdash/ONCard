from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
from pathlib import Path
import math
import random
import re
import time
import uuid

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, Property, QEvent, QPoint, QPointF, QParallelAnimationGroup, QPropertyAnimation, QRect, QRectF, QSignalBlocker, QThread, QTimer, Qt, QUrl, Signal, QSize, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat, QTextCursor, QTextDocument, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QLineEdit,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from studymate.constants import SUBJECT_TAXONOMY
from studymate.constants import SEMANTIC_SEARCH_MIN_SCORE, SEMANTIC_SEARCH_SCORE_MARGIN
from studymate.services.data_store import DataStore
from studymate.services.embedding_service import EmbeddingService
from studymate.services.model_registry import (
    MODELS,
    QN_SUMMARIZER_CONTEXT_LENGTH,
    QN_SUMMARIZER_MODEL_KEY,
    feature_model_setting_key,
    cloud_label_for_model_tag,
    text_llm_key_for_model_tag,
    non_embedding_llm_keys,
    resolve_active_text_llm_spec,
    resolve_active_text_model_tag,
    resolve_feature_text_llm_spec,
    resolve_feature_text_model_tag,
)
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.services.recommendation_service import (
    RecommendedCard,
    build_global_recommendations,
    recommendation_candidate_cards,
)
from studymate.services.study_intelligence import (
    StudySessionState,
    SessionCardEntry,
    build_session_state,
    card_cluster_key,
    enqueue_similar_cards,
    mark_card_completed,
    next_card_for_session,
    queue_reinforcement_cards,
    register_grade_result,
)
from studymate.theme import is_dark_theme
from studymate.utils.markdown import markdown_to_html
from studymate.ui.animated import (
    AnimatedButton,
    AnimatedLineEdit,
    AnimatedStackedWidget,
    AnimatedToolButton,
    fade_widget_visibility,
    polish_surface,
)
from studymate.ui.icon_helper import IconHelper
from studymate.ui.widgets.card_tile import CardTile
from studymate.workers.embedding_worker import EmbeddingWorker
from studymate.workers.followup_worker import FollowUpWorker
from studymate.workers.grade_worker import GradeWorker
from studymate.workers.reinforcement_worker import ReinforcementWorker
from studymate.workers.ai_search_worker import (
    AiSearchAnswerWorker,
    AiSearchPlannerWorker,
    ImageSearchTermsWorker,
    WikipediaBreakdownWorker,
    WikipediaImagesWorker,
)
from studymate.workers.mcq_worker import cached_mcq_payload, normalize_mcq_answers

CARD_SEARCH_LOADING_PENALTY_CACHE_KEY = "cards_search_loading_penalties"
CARD_SEARCH_LOADING_PENALTY_HOURS = 90
CARD_SEARCH_LOADING_LINES = (
    "I am flipping through cards like a caffeinated librarian.",
    "I am looking for the question that definitely knows what you meant.",
    "I am interrogating the deck one flashcard at a time.",
    "I am checking which card is about to act relevant.",
    "I am searching the pile for the academic main character.",
    "I am opening the card drawer with unnecessary confidence.",
    "I am doing a tiny little exam-season treasure hunt.",
    "I am tracking the card that has been dodging responsibility.",
    "I am asking the deck to stop being cryptic for a second.",
    "I am sniffing out the exact question with scholarly flair.",
    "I am searching for the card that thinks it is hard to find.",
    "I am sorting the useful cards from the dramatic ones.",
    "I am rummaging through questions like they owe me clarity.",
    "I am finding the one card that actually understood the assignment.",
    "I am checking which flashcard is about to save your grade.",
    "I am speed-dating the deck until the right card says hello.",
    "I am doing premium question archaeology.",
    "I am looking for the answer-shaped troublemaker.",
    "I am shaking the deck until the right concept falls out.",
    "I am searching like there is a quiz in five minutes.",
    "I am asking every card where it was on the night of the confusion.",
    "I am digging for the question that matches your vibe exactly.",
    "I am checking the cards for suspiciously relevant knowledge.",
    "I am browsing the deck with examiner-level suspicion.",
    "I am trying to catch the exact card before it pretends to be unrelated.",
    "I am flipping through academic receipts.",
    "I am following the scent of a probably-important keyword.",
    "I am searching for the card that was definitely in the lecture somewhere.",
    "I am doing a controlled panic through the question pile.",
    "I am locating the brain cell this deck outsourced.",
    "I am looking for the card that will make this feel obvious in hindsight.",
    "I am checking which question is ready to be weirdly specific.",
    "I am scanning the deck like a disappointed invigilator.",
    "I am fishing out the card with the least chaotic wording.",
    "I am searching for the one flashcard that paid attention in class.",
    "I am dusting off a question that might carry this whole search.",
    "I am letting the cards know I mean business.",
    "I am flipping through concepts like a judge on a talent show.",
    "I am searching for the card that secretly did the reading.",
    "I am poking around the deck for the academically juicy bit.",
    "I am doing a quiet manhunt for the right answer.",
    "I am checking which card has the audacity to be useful today.",
    "I am reading titles like they are witness statements.",
    "I am pulling one concept at a time out of the revision abyss.",
    "I am searching the deck for the overachiever question.",
    "I am looking for the card that can explain itself without drama.",
    "I am matching your search to the least unhelpful wording available.",
    "I am asking the flashcards to form a reasonable lineup.",
    "I am checking where the smart card is hiding.",
    "I am searching for the question with elite timing.",
    "I am dragging the relevant card into the light.",
    "I am looking for the card that absolutely heard you the first time.",
    "I am chasing a keyword through the study maze.",
    "I am checking which question is about to stop this nonsense.",
    "I am rummaging for the card with suspiciously clean phrasing.",
    "I am doing a little detective montage in the deck.",
    "I am asking the cards which one wants to be picked.",
    "I am narrowing this down before the flashcards get ideas.",
    "I am searching for the concept wearing the correct nametag.",
    "I am trying the obvious card first, then the weirdly named one.",
    "I am combing through the deck for the academically incriminating evidence.",
    "I am hunting for the question that made the syllabus nervous.",
    "I am checking which card contains the least amount of nonsense.",
    "I am looking for the exact topic before the deck starts freelancing.",
    "I am searching like the exam is outside revving its engine.",
    "I am opening every mental filing cabinet with dramatic efficiency.",
    "I am looking for the card that can explain this without waffle.",
    "I am checking which flashcard has your back right now.",
    "I am doing a respectful raid on the knowledge pile.",
    "I am flipping until the right question blinks first.",
    "I am searching for the card that understands the plot.",
    "I am checking the deck for signs of actual competence.",
    "I am pulling relevant facts out of organized chaos.",
    "I am scanning for the question that sounds exactly like what you meant.",
    "I am trying to find the card before the synonyms get silly.",
    "I am looking for the flashcard equivalent of oh there you are.",
    "I am checking which concept is pretending not to know you.",
    "I am doing a tactical stroll through your revision stack.",
    "I am finding the question that deserves a smug little nod.",
    "I am searching for the card that took better notes than the rest.",
    "I am checking which flashcard can speak normal human for a moment.",
    "I am flipping through the deck like it just challenged me.",
    "I am looking for the card with the strongest exam energy.",
    "I am searching for the one question that did not come here to waste time.",
    "I am checking which card is hiding behind clever wording again.",
    "I am about to find the academic needle in this very nerdy haystack.",
    "I am reading the deck like a gossip column for facts.",
    "I am searching for the card that is weirdly perfect for this.",
    "I am pulling the right question out of the revision trench.",
    "I am seeing which card is ready for its moment in the sunlight.",
)

class PromptTextEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class FollowUpPromptShell(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FollowUpPromptShell")
        self.setProperty("focusRing", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QFrame#FollowUpPromptShell {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(166, 181, 197, 0.36);
                border-radius: 22px;
            }
            QFrame#FollowUpPromptShell[focusRing="true"] {
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(166, 181, 197, 0.52);
            }
            """
        )


class FollowUpModelButton(QPushButton):
    clickedModel = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_name = "Gemma4 e2B"
        self.reasoning = "Instant"
        self._hovered = False
        self._pressed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(28)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("FollowUpModelButton")
        self.clicked.connect(lambda _checked=False: self.clickedModel.emit())
        self.setStyleSheet("QPushButton#FollowUpModelButton { background: transparent; border: none; }")

    def set_state(self, model_name: str, reasoning: str) -> None:
        self.model_name = model_name
        self.reasoning = "Think" if str(reasoning).lower() == "think" else "Instant"
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(f"{self.model_name} {self.reasoning}") + 18, 28)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        hover_rect = rect.adjusted(0, -1, 0, 1)
        if self._pressed:
            painter.setBrush(QColor(0, 0, 0, 14))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(hover_rect, 7, 7)
        elif self._hovered:
            painter.setBrush(QColor(0, 0, 0, 7))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(hover_rect, 7, 7)
        model_font = QFont("Nunito Sans", 8)
        model_font.setWeight(QFont.Weight.DemiBold)
        reason_font = QFont("Nunito Sans", 8)
        painter.setFont(model_font)
        painter.setPen(QColor("#515861"))
        left = 8
        baseline = int((self.height() + painter.fontMetrics().ascent() - painter.fontMetrics().descent()) / 2)
        painter.drawText(left, baseline, self.model_name)
        left += painter.fontMetrics().horizontalAdvance(self.model_name + " ")
        painter.setFont(reason_font)
        painter.setPen(QColor("#9AA1A9"))
        painter.drawText(left, baseline, self.reasoning)
        painter.end()


class FollowUpModelMenu(QWidget):
    selectionChanged = Signal(str, str)

    RANKED_MODEL_KEYS = ["gemma4_e2b", "gemma4_e4b", "qwen3_5_9b", "qwen3_5_4b", "qwen3_5_2b"]

    def __init__(self, owner: "StudyTab") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("FollowUpModelMenu")
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._panel_margin = 12
        self._open_group: QParallelAnimationGroup | None = None
        self._close_group: QParallelAnimationGroup | None = None
        self.setStyleSheet(
            """
            QLabel#FollowUpMenuSection {
                color: #8F96A0;
                font-size: 10px;
                font-weight: 700;
                padding: 4px 10px 1px 10px;
            }
            QPushButton#FollowUpMenuItem {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #2D333A;
                font-size: 13px;
                font-weight: 500;
                padding: 8px 14px;
                text-align: left;
            }
            QPushButton#FollowUpMenuItem:hover {
                background: rgba(18, 25, 32, 0.045);
            }
            QPushButton#FollowUpMenuItem[selected="true"] {
                background: rgba(18, 25, 32, 0.05);
            }
            """
        )
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(self._panel_margin + 6, self._panel_margin + 4, self._panel_margin + 6, self._panel_margin + 4)
        self.layout_root.setSpacing(3)
        self.hide()

    @staticmethod
    def display_name_for_key(key: str) -> str:
        spec = MODELS.get(key)
        if spec is None:
            return str(key or "Model")
        return spec.display_name.replace(":", " ").replace("e2b", "e2B").replace("e4b", "e4B").replace("2b", "2B").replace("4b", "4B").replace("9b", "9B")

    def _clear(self) -> None:
        while self.layout_root.count():
            item = self.layout_root.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_section(self, title: str) -> None:
        label = QLabel(title)
        label.setObjectName("FollowUpMenuSection")
        self.layout_root.addWidget(label)

    def _add_item(self, text: str, callback, selected: bool = False) -> None:
        button = QPushButton(text)
        button.setObjectName("FollowUpMenuItem")
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setProperty("selected", "true" if selected else "false")
        button.clicked.connect(callback)
        self.layout_root.addWidget(button)

    def _available_keys(self) -> list[str]:
        if bool(self.owner.datastore.load_ai_settings().get("ollama_cloud_enabled", False)):
            tag = str(self.owner.datastore.load_ai_settings().get("ollama_cloud_selected_model_tag", "")).strip()
            key = text_llm_key_for_model_tag(tag)
            return [key] if key else []
        setup_models = dict(self.owner.datastore.load_setup().get("installed_models", {}))
        keys = [key for key in non_embedding_llm_keys() if bool(setup_models.get(key, False)) or self.owner.preflight.has_model(key)]
        ranked = [key for key in self.RANKED_MODEL_KEYS if key in keys]
        return ranked + [key for key in keys if key not in ranked]

    def rebuild(self) -> None:
        self._clear()
        settings = self.owner.datastore.load_ai_settings()
        current_reasoning = self.owner._followup_reasoning_mode()
        current_key = self.owner._followup_model_key()
        self._add_section("Reasoning")
        for mode in ("Think", "Instant"):
            self._add_item(mode, lambda _checked=False, value=mode.lower(): self._choose_reasoning(value), selected=current_reasoning == mode.lower())
        self._add_section("Model")
        keys = self._available_keys()
        shown = keys[:4]
        for key in shown:
            self._add_item(self.display_name_for_key(key), lambda _checked=False, value=key: self._choose_model(value), selected=current_key == key)
        rest = keys[4:]
        if rest:
            self._add_item(f"More models ({len(rest)})", self._show_more_models)
        if bool(settings.get("ollama_cloud_enabled", False)):
            tag = str(settings.get("ollama_cloud_selected_model_tag", "")).strip()
            if tag:
                self._add_item(cloud_label_for_model_tag(tag).replace(" (Cloud)", ""), lambda: None, selected=True)
        content_width = 224
        self.setFixedWidth(content_width + (self._panel_margin * 2) + 4)
        self.adjustSize()

    def _choose_reasoning(self, value: str) -> None:
        self.selectionChanged.emit("", value)
        self.close_animated()

    def _choose_model(self, key: str) -> None:
        self.selectionChanged.emit(key, "")
        self.close_animated()

    def _show_more_models(self) -> None:
        self._clear()
        self._add_section("More models")
        current_key = self.owner._followup_model_key()
        for key in self._available_keys()[4:]:
            self._add_item(self.display_name_for_key(key), lambda _checked=False, value=key: self._choose_model(value), selected=current_key == key)
        self.adjustSize()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card_rect = self.rect().adjusted(self._panel_margin, self._panel_margin, -self._panel_margin, -self._panel_margin)
        painter.setBrush(QColor(255, 255, 255, 252))
        painter.setPen(QPen(QColor(220, 224, 230, 235), 1))
        painter.drawRoundedRect(card_rect, 14, 14)
        painter.end()

    def _stop_animations(self) -> None:
        if self._open_group is not None:
            self._open_group.stop()
            self._open_group = None
        if self._close_group is not None:
            self._close_group.stop()
            self._close_group = None

    def show_below(self, widget: QWidget) -> None:
        self._stop_animations()
        self.rebuild()
        parent_rect = self.owner.rect()
        local_bottom = widget.mapTo(self.owner, QPoint(0, widget.height() + 8))
        local_top = widget.mapTo(self.owner, QPoint(0, -8))
        width = self.sizeHint().width()
        height = max(80, self.sizeHint().height())
        anchor_x = local_bottom.x() - 36
        x = max(12, min(anchor_x, parent_rect.right() - width - 12))
        preferred_y = local_top.y() - height
        fallback_y = local_bottom.y()
        if preferred_y >= 12:
            y = preferred_y
        else:
            y = min(fallback_y, parent_rect.bottom() - height - 12)
        y = max(12, y)
        final_rect = QRect(x, y, width, height)
        start_rect = QRect(final_rect)
        start_rect.translate(0, 8)
        self.setGeometry(start_rect)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(160)
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(final_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        opacity_effect = QGraphicsOpacityEffect(self)
        opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(opacity_effect)
        opacity_animation = QPropertyAnimation(opacity_effect, b"opacity", self)
        opacity_animation.setDuration(150)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry_animation)
        group.addAnimation(opacity_animation)
        group.finished.connect(lambda: self.setGraphicsEffect(None))
        group.finished.connect(lambda: setattr(self, "_open_group", None))
        self._open_group = group
        group.start()

    def close_animated(self) -> None:
        if not self.isVisible():
            return
        self._stop_animations()
        start_rect = self.geometry()
        end_rect = QRect(start_rect)
        end_rect.translate(0, 8)
        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(130)
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        opacity_effect = QGraphicsOpacityEffect(self)
        opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(opacity_effect)
        opacity_animation = QPropertyAnimation(opacity_effect, b"opacity", self)
        opacity_animation.setDuration(120)
        opacity_animation.setStartValue(1.0)
        opacity_animation.setEndValue(0.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry_animation)
        group.addAnimation(opacity_animation)
        group.finished.connect(self.hide)
        group.finished.connect(lambda: self.setGraphicsEffect(None))
        group.finished.connect(lambda: setattr(self, "_close_group", None))
        self._close_group = group
        group.start()


class AiTagChip(QWidget):
    def __init__(self, text: str = "I am Luca, how can I help you?", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._reveal = 1.0
        self.hide()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(max(214, metrics.horizontalAdvance(self._text) + 18), 24)

    def getReveal(self) -> float:
        return self._reveal

    def setReveal(self, value: float) -> None:
        try:
            self._reveal = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._reveal = 1.0
        self.update()

    reveal = Property(float, getReveal, setReveal)

    def paintEvent(self, event) -> None:
        del event
        if self._reveal <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        if rect.width() <= 1 or rect.height() <= 1:
            return

        clip_width = rect.width() * self._reveal
        painter.save()
        painter.setClipRect(QRectF(rect.left(), rect.top(), clip_width, rect.height()))
        font = QFont(self.font())
        font.setItalic(True)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#64748B"))
        painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, self._text)
        painter.restore()


class FollowUpThinkingMarker(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._show_line = False
        self._angle = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(24, 34)

    def set_state(self, *, active: bool, show_line: bool, angle: float) -> None:
        self._active = bool(active)
        self._show_line = bool(show_line)
        self._angle = float(angle)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center_x = self.width() / 2.0
        if self._show_line:
            painter.setPen(QPen(QColor("#dfe5eb"), 1))
            painter.drawLine(QPointF(center_x, 22.0), QPointF(center_x, float(self.height())))
        if self._active:
            rect = QRectF(center_x - 7.5, 4.0, 15.0, 15.0)
            painter.setPen(QPen(QColor("#e2e7ed"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(rect)
            painter.setPen(QPen(QColor("#728190"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, int((-90.0 - self._angle) * 16), int(124 * 16))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#aeb8c3"))
            painter.drawEllipse(QRectF(center_x - 2.4, 9.6, 4.8, 4.8))


class FollowUpThinkingRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self._marker = FollowUpThinkingMarker(self)
        self._label = QLabel("", self)
        self._label.setObjectName("FollowUpThinkingStep")
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._marker, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._label, 1, Qt.AlignmentFlag.AlignTop)

    def set_step(self, text: str, *, active: bool, show_line: bool, angle: float) -> None:
        self._label.setText(str(text or "").strip())
        self._marker.set_state(active=active, show_line=show_line, angle=angle)

    def set_angle(self, angle: float, *, active: bool, show_line: bool) -> None:
        self._marker.set_state(active=active, show_line=show_line, angle=angle)


class FollowUpThinkingPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[FollowUpThinkingRow] = []
        self._steps: list[str] = []
        self._angle = 0.0
        self.setObjectName("FollowUpThinkingPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            """
            QFrame#FollowUpThinkingPanel {
                background: transparent;
                border: none;
            }
            QLabel#FollowUpThinkingTitle {
                color: #27394c;
                font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 400;
            }
            QLabel#FollowUpThinkingStep {
                color: #536273;
                font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 400;
                padding-top: 0;
            }
            """
        )
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(2, 8, 2, 8)
        self._root.setSpacing(8)
        title = QLabel("Thinking")
        title.setObjectName("FollowUpThinkingTitle")
        self._root.addWidget(title)
        self._steps_layout = QVBoxLayout()
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(0)
        self._root.addLayout(self._steps_layout)
        self._root.addStretch(1)

    def set_angle(self, angle: float) -> None:
        self._angle = float(angle)
        last_index = len(self._rows) - 1
        for index, row in enumerate(self._rows):
            row.set_angle(self._angle, active=index == last_index, show_line=index < last_index)

    def set_steps(self, steps: list[str]) -> None:
        visible_steps = [str(step).strip() for step in steps if str(step).strip()][-5:] or ["Preparing response"]
        if visible_steps == self._steps:
            return
        self._steps = visible_steps
        while len(self._rows) > len(visible_steps):
            row = self._rows.pop()
            self._steps_layout.removeWidget(row)
            row.deleteLater()
        while len(self._rows) < len(visible_steps):
            row = FollowUpThinkingRow(self)
            self._steps_layout.addWidget(row)
            self._rows.append(row)
        last_index = len(visible_steps) - 1
        for index, step in enumerate(visible_steps):
            self._rows[index].set_step(step, active=index == last_index, show_line=index < last_index, angle=self._angle)


class CardSearchLoadingWidget(QWidget):
    def __init__(self, texts: tuple[str, ...] | list[str] | str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if isinstance(texts, str):
            self._texts = [texts]
        else:
            self._texts = [str(text).strip() for text in texts if str(text).strip()]
        if not self._texts:
            self._texts = ["I am flipping through cards like a caffeinated librarian."]
        self._active_texts = self._texts[:1]
        self._last_texts: list[str] = []
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def start(self, texts: tuple[str, ...] | list[str] | None = None) -> None:
        selected = [str(text).strip() for text in list(texts or []) if str(text).strip()]
        if selected:
            self._active_texts = selected[:1]
        else:
            candidates = [text for text in self._texts if text not in self._last_texts]
            if not candidates:
                candidates = self._texts[:]
            self._active_texts = candidates[:1]
        self._last_texts = self._active_texts[:]
        self._phase = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._phase = 0.0
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.0065) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            text_rect = self.rect().adjusted(2, 0, -2, 0)
            text = self._active_texts[0] if self._active_texts else ""
            painter.setPen(QColor("#7f93a7"))
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)

            shimmer_width = max(112.0, text_rect.width() * 0.34)
            track = max(1.0, text_rect.width() + shimmer_width)
            x = text_rect.left() - shimmer_width + (track * self._phase)
            highlight = QRectF(float(x), float(text_rect.top()), float(shimmer_width), float(text_rect.height()))
            gradient = QLinearGradient(highlight.left(), highlight.center().y(), highlight.right(), highlight.center().y())
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(0.18, QColor(255, 255, 255, 26))
            gradient.setColorAt(0.5, QColor(255, 255, 255, 144))
            gradient.setColorAt(0.82, QColor(255, 255, 255, 26))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(highlight, gradient)
        finally:
            painter.end()


class AiQueryLineEdit(AnimatedLineEdit):
    aiModeChanged = Signal(bool)
    historyRequested = Signal()
    imageDropped = Signal(str)

    TRIGGER_TOKENS = {"/ai": "ai", "#ai": "ai", "/wiki": "wiki"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ai_mode = False
        self._ai_mode_kind = "ai"
        self._image_attached = False
        self._ghost_text = ""
        self._base_left_margin = self.textMargins().left()
        self._placeholder_before_ai_mode = ""
        self._ai_placeholder_text = "I am Luca, how can I help you?"
        self.setAcceptDrops(True)
        self._update_text_margins()

    def ai_mode_active(self) -> bool:
        return self._ai_mode

    def ai_mode_kind(self) -> str:
        return self._ai_mode_kind if self._ai_mode else ""

    def set_image_attached(self, attached: bool) -> None:
        self._image_attached = bool(attached)

    def ghost_text(self) -> str:
        return self._ghost_text

    def set_ghost_text(self, text: str) -> None:
        normalized = str(text or "")
        if self._ghost_text == normalized:
            return
        self._ghost_text = normalized
        self.update()

    def set_ai_mode(self, active: bool, mode_kind: str = "ai") -> None:
        normalized_kind = "wiki" if str(mode_kind or "").strip().lower() == "wiki" else "ai"
        if self._ai_mode == active and self._ai_mode_kind == normalized_kind:
            return
        self._ai_mode = active
        self._ai_mode_kind = normalized_kind if active else "ai"
        self.setProperty("aiMode", active)
        if active:
            self._placeholder_before_ai_mode = self.placeholderText()
            self._ai_placeholder_text = (
                "Search a Wikipedia topic to break down..." if self._ai_mode_kind == "wiki" else "I am Luca, how can I help you?"
            )
            self.setPlaceholderText("")
        else:
            self._ai_placeholder_text = "I am Luca, how can I help you?"
            if self._placeholder_before_ai_mode:
                self.setPlaceholderText(self._placeholder_before_ai_mode)
        self._update_text_margins()
        self.update()
        self.aiModeChanged.emit(active)

    def keyPressEvent(self, event) -> None:
        if self._ai_mode and event.key() == Qt.Key_Backspace and not self.text():
            self.set_ai_mode(False)
            event.accept()
            return
        if self._ai_mode and event.key() == Qt.Key_Up:
            self.historyRequested.emit()
            event.accept()
            return
        if not self._ai_mode and event.text():
            cursor = self.cursorPosition()
            selected = self.selectedText()
            if selected:
                start = min(self.cursorPosition(), self.selectionStart())
                end = start + len(selected)
                prospective = f"{self.text()[:start]}{event.text()}{self.text()[end:]}"
            else:
                prospective = f"{self.text()[:cursor]}{event.text()}{self.text()[cursor:]}"
            trigger_kind = self.TRIGGER_TOKENS.get(prospective.strip().lower(), "")
            if trigger_kind:
                with QSignalBlocker(self):
                    self.clear()
                self.set_ai_mode(True, trigger_kind)
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_text_margins()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._ai_mode:
            if self.text():
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            font = QFont(self.font())
            font.setItalic(True)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor("#64748B"))
            rect = self.contentsRect().adjusted(self._base_left_margin, 0, 0, 0)
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self._ai_placeholder_text)
            return

        text = self.text()
        ghost = self._ghost_text
        if (
            not text
            or not ghost
            or self.selectedText()
            or self.cursorPosition() != len(text)
            or not ghost.lower().startswith(text.lower())
            or len(ghost) <= len(text)
        ):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        painter.setFont(font)
        painter.setPen(QColor("#9AA6B2"))
        rect = self.contentsRect().adjusted(self._base_left_margin, 0, 0, 0)
        suffix = ghost[len(text):]
        leading_space_count = len(suffix) - len(suffix.lstrip())
        leading_spaces = suffix[:leading_space_count]
        suffix = suffix[leading_space_count:]
        if not suffix:
            return
        ghost_gap = 1
        x = rect.left() + painter.fontMetrics().horizontalAdvance(text + leading_spaces) + ghost_gap
        suffix_rect = QRect(x, rect.top(), max(0, rect.right() - x), rect.height())
        painter.drawText(suffix_rect, Qt.AlignVCenter | Qt.AlignLeft, suffix)

    @staticmethod
    def _first_image_path(event) -> str:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return ""
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            suffix = Path(path).suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                return path
        return ""

    def dragEnterEvent(self, event) -> None:
        if not self._image_attached and self._first_image_path(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if not self._image_attached and self._first_image_path(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        path = self._first_image_path(event)
        if path and not self._image_attached:
            self.imageDropped.emit(path)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _tag_rect(self):
        contents = self.contentsRect()
        tag_height = max(22, min(contents.height() - 4, 24))
        chip_width = max(56, self._tag_chip.sizeHint().width())
        y = contents.top() + max(0, (contents.height() - tag_height) // 2)
        return QRect(contents.left() + 2, y, chip_width, tag_height)

    def _update_text_margins(self) -> None:
        self.setTextMargins(self._base_left_margin, 0, 0, 0)


class AiResponseSkeleton(QWidget):
    DEFAULT_HEIGHT = 268
    WIKI_MIN_HEIGHT = 214
    WIKI_MAX_HEIGHT = 246

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._show_wiki_image_box = False
        self._reasoning_blocks: list[str] = []
        self._visible_reasoning_count = 0
        self._active_reasoning_index = -1
        self._reasoning_progress = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._advance)
        self._reasoning_anim = QVariantAnimation(self)
        self._reasoning_anim.setDuration(520)
        self._reasoning_anim.setStartValue(0.0)
        self._reasoning_anim.setEndValue(1.0)
        self._reasoning_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reasoning_anim.valueChanged.connect(self._set_reasoning_progress)
        self._reasoning_anim.finished.connect(self._queue_next_reasoning_block)
        self._reasoning_queue_timer = QTimer(self)
        self._reasoning_queue_timer.setSingleShot(True)
        self._reasoning_queue_timer.timeout.connect(self._reveal_next_reasoning_block)
        self.setMinimumHeight(self.DEFAULT_HEIGHT)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._reasoning_anim.stop()
        self._reasoning_queue_timer.stop()

    def clear_research_message(self) -> None:
        self._reasoning_anim.stop()
        self._reasoning_queue_timer.stop()
        self._reasoning_blocks = []
        self._visible_reasoning_count = 0
        self._active_reasoning_index = -1
        self._reasoning_progress = 0.0
        self.setMinimumHeight(self.preferred_height())
        self.update()

    def set_wiki_image_box_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if self._show_wiki_image_box == normalized:
            return
        self._show_wiki_image_box = normalized
        self.setMinimumHeight(self.preferred_height())
        self.update()

    def show_research_message(self, text: str) -> None:
        self.show_reasoning_messages([text])

    def show_reasoning_messages(self, messages: list[str]) -> None:
        cleaned = [" ".join(str(message or "").strip().split()) for message in messages]
        self._reasoning_blocks = [message for message in cleaned if message]
        self._visible_reasoning_count = 0
        self._active_reasoning_index = -1
        self._reasoning_progress = 0.0
        self._reasoning_anim.stop()
        self._reasoning_queue_timer.stop()
        if not self._reasoning_blocks:
            self.setMinimumHeight(self.preferred_height())
            self.update()
            return
        self._reveal_next_reasoning_block()

    def _set_reasoning_progress(self, value) -> None:
        try:
            self._reasoning_progress = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._reasoning_progress = 1.0
        self.update()

    def _reveal_next_reasoning_block(self) -> None:
        if self._visible_reasoning_count >= len(self._reasoning_blocks):
            return
        self._active_reasoning_index = self._visible_reasoning_count
        self._visible_reasoning_count += 1
        self._reasoning_progress = 0.0
        self._reasoning_anim.stop()
        self._reasoning_anim.setStartValue(0.0)
        self._reasoning_anim.setEndValue(1.0)
        self._reasoning_anim.start()
        self.setMinimumHeight(self.preferred_height())
        self.update()

    def _queue_next_reasoning_block(self) -> None:
        if self._visible_reasoning_count < len(self._reasoning_blocks):
            self._reasoning_queue_timer.start(120)

    def _advance(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def _wiki_visual_mode_active(self) -> bool:
        return self._show_wiki_image_box and self._visible_reasoning_count <= 0

    def preferred_height(self, width: int | None = None) -> int:
        if not self._wiki_visual_mode_active():
            return self.DEFAULT_HEIGHT
        base_width = width if width and width > 0 else max(self.width(), self.minimumWidth(), 320)
        inner_width = max(220.0, float(base_width - 40))
        thumb_width = max(124.0, min(164.0, inner_width * 0.26))
        thumb_height = max(152.0, min(192.0, thumb_width * 1.18))
        content_height = thumb_height + 32.0
        return int(max(self.WIKI_MIN_HEIGHT, min(self.WIKI_MAX_HEIGHT, content_height + 4.0)))

    def _draw_shimmer(self, painter: QPainter, rect: QRectF, *, radius: float, alpha: int, width_ratio: float) -> None:
        shimmer_width = max(52.0, rect.width() * width_ratio)
        track = max(1.0, rect.width() + shimmer_width)
        x = rect.left() - shimmer_width + (track * self._phase)
        highlight = QRectF(x, rect.top(), shimmer_width, rect.height())
        gradient = QLinearGradient(highlight.left(), 0, highlight.right(), 0)
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.5, QColor(255, 255, 255, alpha))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(highlight, gradient)
        painter.restore()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FAFAFB"))
        painter.drawRoundedRect(rect, 24.0, 24.0)

        content = rect.adjusted(18, 18, -18, -18)
        line_height = 14
        gap = 10
        message_bottom = content.top()
        if self._visible_reasoning_count > 0:
            message_font = QFont(self.font())
            message_font.setPointSize(10)
            message_font.setWeight(QFont.Weight.Medium)
            painter.setFont(message_font)
            text_flags = int(Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap)
            block_width = content.width() * 0.9
            y = float(content.top())
            for index, text in enumerate(self._reasoning_blocks[: self._visible_reasoning_count]):
                block_height = 42.0
                block_rect = QRectF(content.left(), y, block_width, block_height)
                text_rect = block_rect.adjusted(12.0, 0.0, -12.0, 0.0)
                block_progress = self._reasoning_progress if index == self._active_reasoning_index else 1.0
                clip_height = max(0.0, text_rect.height() * block_progress)
                if clip_height > 0.0:
                    painter.save()
                    painter.setClipRect(QRectF(text_rect.left(), text_rect.top(), text_rect.width(), clip_height))
                    painter.setPen(QColor("#21415F"))
                    painter.drawText(text_rect, text_flags, text)
                    shimmer_width = max(220.0, text_rect.width() * 0.72)
                    track = max(1.0, text_rect.width() + shimmer_width)
                    x = text_rect.left() - shimmer_width + (track * self._phase)
                    highlight = QRectF(x, text_rect.top() - 8.0, shimmer_width, text_rect.height() + 16.0)
                    shimmer = QLinearGradient(highlight.left(), 0, highlight.right(), 0)
                    shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
                    shimmer.setColorAt(0.14, QColor(234, 243, 255, 18))
                    shimmer.setColorAt(0.28, QColor(241, 247, 255, 48))
                    shimmer.setColorAt(0.42, QColor(248, 251, 255, 96))
                    shimmer.setColorAt(0.5, QColor(255, 255, 255, 178 if index == self._active_reasoning_index else 146))
                    shimmer.setColorAt(0.58, QColor(248, 251, 255, 96))
                    shimmer.setColorAt(0.72, QColor(241, 247, 255, 48))
                    shimmer.setColorAt(0.86, QColor(234, 243, 255, 18))
                    shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                    painter.fillRect(highlight, shimmer)
                    painter.restore()
                y = block_rect.bottom() + 8.0
            message_bottom = int(y) + 4

        widths = [0.74, 0.92, 0.87, 0.95, 0.68, 0.90, 0.84, 0.57, 0.93, 0.88, 0.79, 0.64]
        thumb_rect = QRectF()
        if self._wiki_visual_mode_active():
            widths = [0.82, 0.68, 0.76, 0.61, 0.93, 0.86]
            thumb_width = max(124.0, min(164.0, content.width() * 0.26))
            thumb_height = max(152.0, min(192.0, thumb_width * 1.18))
            thumb_top = content.top() + 4.0
            thumb_rect = QRectF(content.left(), thumb_top, thumb_width, thumb_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(226, 234, 242))
            painter.drawRoundedRect(thumb_rect, 22.0, 22.0)
            self._draw_shimmer(painter, thumb_rect, radius=22.0, alpha=146, width_ratio=0.42)
            message_bottom = int(thumb_top)

        for index, ratio in enumerate(widths):
            top = int(message_bottom + index * (line_height + gap))
            if top + line_height > content.bottom():
                break
            available_width = content.width()
            left = content.left()
            if not thumb_rect.isNull():
                if top < thumb_rect.bottom() - 2.0:
                    left = thumb_rect.right() + 22.0
                else:
                    left = content.left() + 2.0
                available_width = max(80.0, content.right() - left)
            bar = QRectF(left, top, available_width * ratio, line_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(231, 236, 242))
            painter.drawRoundedRect(bar, 8.0, 8.0)
            self._draw_shimmer(painter, bar, radius=8.0, alpha=150, width_ratio=0.26)


class CardSearchSkeletonTile(QFrame):
    cycleCompleted = Signal()

    def __init__(self, tile_width: int, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.18
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._advance)
        self.setObjectName("CardSearchSkeletonTile")
        self.setFixedWidth(tile_width)
        self.setMinimumHeight(218)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        previous = self._phase
        self._phase = (self._phase + 0.022) % 1.0
        if self._phase < previous:
            self.cycleCompleted.emit()
        self.update()

    def _draw_bar(self, painter: QPainter, rect: QRectF, color: QColor, radius: float) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, radius, radius)

        shimmer_width = max(62.0, rect.width() * 0.42)
        track = max(1.0, rect.width() + shimmer_width)
        x = rect.left() - shimmer_width + (track * self._phase)
        highlight = QRectF(x, rect.top(), shimmer_width, rect.height())
        gradient = QLinearGradient(highlight.left(), highlight.center().y(), highlight.right(), highlight.center().y())
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.18, QColor(255, 255, 255, 28))
        gradient.setColorAt(0.36, QColor(255, 255, 255, 82))
        gradient.setColorAt(0.5, QColor(255, 255, 255, 132))
        gradient.setColorAt(0.64, QColor(255, 255, 255, 82))
        gradient.setColorAt(0.82, QColor(255, 255, 255, 28))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.save()
        painter.setClipPath(self._rounded_rect_path(rect, radius))
        painter.fillRect(highlight.adjusted(0.0, -1.0, 0.0, 1.0), gradient)
        painter.restore()

    @staticmethod
    def _rounded_rect_path(rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(168, 182, 197, 96), 1))
        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawRoundedRect(outer, 24.0, 24.0)

        content = outer.adjusted(18.0, 18.0, -18.0, -18.0)
        widths = [0.56, 0.88, 0.76, 0.92, 0.66]
        heights = [17.0, 13.0, 13.0, 13.0, 13.0]
        y = content.top()
        for index, ratio in enumerate(widths):
            bar = QRectF(content.left(), y, content.width() * ratio, heights[index])
            color = QColor(213, 224, 235, 250) if index == 0 else QColor(226, 234, 242, 250)
            self._draw_bar(painter, bar, color, 8.0 if index == 0 else 6.0)
            y += heights[index] + (18.0 if index == 0 else 13.0)

        pill_y = content.bottom() - 24.0
        for index, width in enumerate((78.0, 64.0)):
            pill = QRectF(content.left() + (index * 88.0), pill_y, width, 20.0)
            self._draw_bar(painter, pill, QColor(236, 242, 248, 250), 10.0)


class AiAttachmentChip(QFrame):
    removed = Signal()

    def __init__(self, icons: IconHelper, parent=None) -> None:
        super().__init__(parent)
        self._path = ""
        self.setObjectName("AiAttachmentChip")
        self.setFixedHeight(34)
        self.setStyleSheet(
            """
            QFrame#AiAttachmentChip {
                background: rgba(242, 246, 251, 0.96);
                border: 1px solid rgba(215, 219, 226, 0.96);
                border-radius: 12px;
            }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 4, 6, 4)
        layout.setSpacing(6)

        self.preview = QLabel(self)
        self.preview.setFixedSize(24, 24)
        self.preview.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.preview, 0, Qt.AlignVCenter)

        self.remove_btn = AnimatedToolButton()
        self.remove_btn.setIcon(icons.icon("common", "close", "X"))
        self.remove_btn.setIconSize(QSize(12, 12))
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setAutoRaise(True)
        self.remove_btn.setFixedSize(18, 18)
        self.remove_btn.clicked.connect(self.removed.emit)
        layout.addWidget(self.remove_btn, 0, Qt.AlignVCenter)
        self.hide()

    def path(self) -> str:
        return self._path

    def set_image(self, path: str) -> bool:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        thumb = pixmap.scaled(24, 24, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.preview.setPixmap(thumb)
        self.preview.setToolTip(Path(path).name)
        self._path = path
        self.show()
        return True

    def clear_image(self) -> None:
        self._path = ""
        self.preview.clear()
        self.preview.setToolTip("")
        self.hide()


class ImageSearchStatus(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._text = "I am finding cards which best match the image..."
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._advance)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2.0, 3.0, -2.0, -3.0)
        if rect.width() <= 1 or rect.height() <= 1:
            return

        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#64748B"))
        text_rect = rect.adjusted(8.0, 0.0, -8.0, 0.0)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)

        shimmer_width = max(120.0, text_rect.width() * 0.36)
        track = max(1.0, text_rect.width() + shimmer_width)
        x = text_rect.left() - shimmer_width + (track * self._phase)
        highlight = QRectF(x, text_rect.top(), shimmer_width, text_rect.height())
        gradient = QLinearGradient(highlight.left(), 0, highlight.right(), 0)
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.18, QColor(238, 246, 255, 36))
        gradient.setColorAt(0.5, QColor(255, 255, 255, 180))
        gradient.setColorAt(0.82, QColor(238, 246, 255, 36))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.fillRect(highlight, gradient)


class AiRevealOverlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._pixmap = QPixmap()
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def getProgress(self) -> float:
        return self._progress

    def setProgress(self, value: float) -> None:
        try:
            self._progress = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._progress = 1.0
        self.update()

    progress = Property(float, getProgress, setProgress)

    def paintEvent(self, event) -> None:
        del event
        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if rect.width() <= 2 or rect.height() <= 2:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 24.0, 24.0)
        painter.fillPath(path, QColor("#FAFAFB"))

        content = rect.adjusted(1, 1, -1, -1)
        reveal_bottom = content.top() + (content.height() * self._progress)
        if reveal_bottom <= content.top():
            return

        painter.save()
        painter.setClipPath(path)
        painter.setClipRect(QRectF(content.left(), content.top(), content.width(), reveal_bottom - content.top()))
        painter.drawPixmap(QRectF(content), self._pixmap, QRectF(0, 0, self._pixmap.width(), self._pixmap.height()))
        painter.restore()

        if reveal_bottom < content.bottom():
            feather = min(58.0, content.height() * 0.2)
            band_top = max(content.top(), reveal_bottom - feather)
            gradient = QLinearGradient(content.left(), band_top, content.left(), reveal_bottom)
            gradient.setColorAt(0.0, QColor(250, 250, 251, 0))
            gradient.setColorAt(1.0, QColor(250, 250, 251, 255))
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(content.left(), band_top, content.width(), reveal_bottom - band_top), gradient)
            painter.restore()


class WikiShortSummaryWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._visible_count = 0
        self._char_started_times: list[float] = []
        self._paint_now = 0.0
        self._fade_seconds = 0.34
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        font = QFont("Segoe UI", 11)
        font.setWeight(QFont.Weight.Normal)
        self.setFont(font)

    def _text_color(self) -> QColor:
        return QColor("#E7EDF4") if is_dark_theme() else QColor("#1A1A1A")

    def clear(self) -> None:
        self._text = ""
        self._visible_count = 0
        self._char_started_times = []
        self._paint_now = 0.0
        self.updateGeometry()
        self.update()

    def set_full_text(self, text: str) -> None:
        self._text = str(text or "")
        self._visible_count = 0
        self._char_started_times = []
        self._paint_now = 0.0
        self.updateGeometry()
        self.update()

    def show_full_text(self, text: str) -> None:
        self._text = str(text or "")
        self._visible_count = len(self._text)
        self._char_started_times = []
        self._paint_now = 0.0
        self.updateGeometry()
        self.update()

    def set_stream_config(self, *, fade_seconds: float) -> None:
        self._fade_seconds = max(0.05, float(fade_seconds or 0.34))

    def set_stream_frame(self, *, visible_count: int, char_started_times: list[float], now: float) -> None:
        self._visible_count = max(0, min(len(self._text), int(visible_count)))
        self._char_started_times = list(char_started_times[: self._visible_count])
        self._paint_now = float(now or 0.0)
        self.update()

    def height_for_width(self, width: int) -> int:
        if not self._text.strip():
            return 0
        _, height = self._build_layout(self._text, max(1, int(width)), include_animation=False)
        return height

    def sizeHint(self) -> QSize:
        width = max(240, self.width() or 240)
        return QSize(width, self.height_for_width(width))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        del event
        if not self._text.strip():
            return
        visible_text = self._text[: self._visible_count]
        if not visible_text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layout, _ = self._build_layout(visible_text, max(1, self.width()), include_animation=bool(self._char_started_times))
        layout.draw(painter, QPointF(0.0, 0.0))

    def _build_layout(self, text: str, width: int, *, include_animation: bool) -> tuple[QTextLayout, int]:
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        if include_animation and self._char_started_times:
            formats: list[QTextLayout.FormatRange] = []
            for index, _char in enumerate(text):
                started_at = self._char_started_times[index] if index < len(self._char_started_times) else self._paint_now
                progress = min(1.0, max(0.0, (self._paint_now - started_at) / self._fade_seconds))
                opacity = max(0.16, progress)
                fmt = QTextCharFormat()
                base_color = self._text_color()
                fmt.setForeground(QColor(base_color.red(), base_color.green(), base_color.blue(), int(opacity * 255)))
                span = QTextLayout.FormatRange()
                span.start = index
                span.length = 1
                span.format = fmt
                formats.append(span)
            layout.setFormats(formats)
        elif text:
            fmt = QTextCharFormat()
            fmt.setForeground(self._text_color())
            span = QTextLayout.FormatRange()
            span.start = 0
            span.length = len(text)
            span.format = fmt
            layout.setFormats([span])
        layout.beginLayout()
        height = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(float(width))
            line.setPosition(QPointF(0.0, height))
            height += line.height()
        layout.endLayout()
        return layout, int(math.ceil(height))


class AiOverlayTabChip(QFrame):
    clicked = Signal()

    def __init__(self, icon: QIcon, text: str, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self.setObjectName("AiOverlayTabChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 8, 4)
        layout.setSpacing(5)
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(15, 15)
        self.icon_label.setPixmap(icon.pixmap(QSize(15, 15)))
        self.text_label = QLabel(text, self)
        self.text_label.setObjectName("AiOverlayTabChipText")
        self.text_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _apply_style(self) -> None:
        background = "rgba(15, 37, 57, 0.10)" if self._active else "rgba(255, 255, 255, 0.72)"
        text_color = "#E7EDF4" if is_dark_theme() else "#1A1A1A"
        self.setStyleSheet(
            f"""
            QFrame#AiOverlayTabChip {{
                background: {background};
                border: none;
                border-radius: 7px;
            }}
            QLabel#AiOverlayTabChipText {{
                background: transparent;
                color: {text_color};
                font-size: 11px;
            }}
            """
        )


class WikiEntryMorphProxy(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._progress = 0.0
        self._start_pixmap = QPixmap()
        self._end_pixmap = QPixmap()

    def set_pixmaps(self, start_pixmap: QPixmap, end_pixmap: QPixmap) -> None:
        self._start_pixmap = start_pixmap
        self._end_pixmap = end_pixmap
        self.update()

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        target = self.rect()
        if not self._start_pixmap.isNull() and self._progress < 0.98:
            painter.setOpacity(1.0 - min(1.0, self._progress * 1.45))
            painter.drawPixmap(target, self._start_pixmap)
        if not self._end_pixmap.isNull():
            painter.setOpacity(min(1.0, 0.12 + self._progress * 0.88))
            painter.drawPixmap(target, self._end_pixmap)
        painter.end()


class OverlayCloseProxy(QWidget):
    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._pixmap = pixmap
        self._progress = 0.0

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def paintEvent(self, _event) -> None:
        if self._pixmap.isNull():
            return
        eased = self._progress
        scale = 1.0 - (0.018 * eased)
        opacity = max(0.0, 1.0 - eased)
        width = self.width() * scale
        height = self.height() * scale
        target = QRectF((self.width() - width) / 2.0, 2.0 * eased, width, height)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(opacity)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        painter.end()


class AiResponseOverlay(QWidget):
    closed = Signal()
    wikiSearchRequested = Signal(str)
    WIKI_THUMB_WIDTH = 220
    WIKI_THUMB_MAX_HEIGHT = 292
    WIKI_THUMB_RADIUS = 13
    WIKI_THUMB_RIGHT_GAP = 32
    WIKI_THUMB_BOTTOM_GAP = 18
    WIKI_THUMB_SUPERSAMPLE = 3

    def __init__(self, icons: IconHelper, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self.setObjectName("AiResponseOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()
        self._animation_group: QParallelAnimationGroup | None = None
        self._last_markdown = ""
        self._syncing_size = False
        self._streaming_started = False
        self._closing = False
        self._display_markdown = ""
        self._target_markdown = ""
        self._anchor_y: int | None = None
        self._copy_flash_active = False
        self._manual_pos: QPoint | None = None
        self._drag_active = False
        self._drag_offset = QPoint()
        self._close_animation: QAbstractAnimation | None = None
        self._close_proxy: OverlayCloseProxy | None = None
        self._reveal_animation: QAbstractAnimation | None = None
        self._display_chunk_count = 0
        self._stream_mode = "words"
        self._stream_units_per_second = 30.0
        self._stream_unit_credit = 0.0
        self._last_stream_time = 0.0
        self._last_render_commit = 0.0
        self._target_chunks: list[str] = []
        self._render_cost_ema_ms = 7.0
        self._last_fade_start = 0.0
        self._active_char_fades: list[tuple[QVariantAnimation, int, int]] = []
        self._reveal_duration_ms = 620
        self._tab_mode = ""
        self._active_tab = "wiki"
        self._tab_markdown: dict[str, str] = {}
        self._tab_content_format: dict[str, str] = {}
        self._tab_copy_payload: dict[str, str] = {}
        self._tab_loading: dict[str, bool] = {}
        self._wiki_short_summary_text = ""
        self._wiki_short_summary_stream_enabled = False
        self._wiki_short_summary_chars_per_second = 150.0
        self._wiki_short_summary_fade_seconds = 0.34
        self._wiki_short_summary_stream_target = ""
        self._wiki_short_summary_visible_count = 0
        self._wiki_short_summary_stream_started_at = 0.0
        self._wiki_short_summary_stream_started_times: list[float] = []
        self._wiki_short_summary_expansion_animation: QVariantAnimation | None = None
        self._wiki_short_summary_presented = False
        self._wiki_summary_region_current_height = 0
        self._wiki_summary_region_target_height = 0
        self._size_anchor_bottom: int | None = None
        self._wiki_entry_active = False
        self._wiki_entry_morph_animation: QAbstractAnimation | None = None
        self._wiki_entry_morphing = False
        self._wiki_entry_morph_proxy: WikiEntryMorphProxy | None = None
        self._wiki_entry_morph_proxy_animation: QAbstractAnimation | None = None
        self._wiki_entry_content_fade: QAbstractAnimation | None = None
        self._wiki_entry_content_effects: list[tuple[QWidget, QGraphicsOpacityEffect]] = []
        self._suppress_next_animate_in = False
        self._wiki_entry_app_filter_installed = False
        self._wiki_entry_ignore_until_mouse_release = False
        self._wiki_entry_restore_state: dict[str, object] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 56, 56, 56)
        root.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("AiResponseSurface")
        self._apply_surface_style(entry_mode=False)
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(52)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(21, 28, 37, 66))
        self.surface.setGraphicsEffect(shadow)
        root.addWidget(self.surface)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(18, 8, 18, 20)
        layout.setSpacing(8)

        self.summary_region = QWidget(self.surface)
        self.summary_region.hide()
        self.summary_region.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.summary_region_layout = QVBoxLayout(self.summary_region)
        self.summary_region_layout.setContentsMargins(0, 14, 20, 6)
        self.summary_region_layout.setSpacing(0)
        self.summary_text = WikiShortSummaryWidget(self.summary_region)
        self.summary_region_layout.addWidget(self.summary_text)
        layout.addWidget(self.summary_region)

        self.header_frame = QFrame(self.surface)
        self.header_frame.setObjectName("AiOverlayHeader")
        self.header_frame.setCursor(Qt.OpenHandCursor)
        self.header_frame.setStyleSheet("background: transparent;")
        self.header_frame.setFixedHeight(0)
        header = QHBoxLayout(self.header_frame)
        header.setContentsMargins(0, 0, 76, 0)
        header.setSpacing(8)
        self.wiki_tab_btn = AiOverlayTabChip(icons.icon("common", "wiki", "W"), "Wikipedia", self.header_frame)
        self.wiki_tab_btn.setFixedWidth(92)
        self.wiki_tab_btn.clicked.connect(lambda: self._select_response_tab("wiki"))
        header.addWidget(self.wiki_tab_btn)

        self.ai_tab_btn = AiOverlayTabChip(icons.icon("common", "clean", "A"), "Summary", self.header_frame)
        self.ai_tab_btn.setFixedWidth(84)
        self.ai_tab_btn.clicked.connect(lambda: self._select_response_tab("ai"))
        header.addWidget(self.ai_tab_btn)

        self.images_tab_btn = AiOverlayTabChip(icons.icon("common", "images", "I"), "Images", self.header_frame)
        self.images_tab_btn.setFixedWidth(80)
        self.images_tab_btn.clicked.connect(lambda: self._select_response_tab("images"))
        header.addWidget(self.images_tab_btn)

        self.wiki_search_input = AnimatedLineEdit(self.header_frame)
        self.wiki_search_input.setFixedHeight(24)
        self.wiki_search_input.setMinimumWidth(180)
        self.wiki_search_input.setMaximumWidth(360)
        self.wiki_search_input.setPlaceholderText("Search another topic...")
        self.wiki_search_input.returnPressed.connect(self._submit_wiki_search_from_header)
        self.wiki_search_action = self.wiki_search_input.addAction(
            icons.icon("common", "wiki_search", "S"),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.wiki_search_action.triggered.connect(self._submit_wiki_search_from_header)
        self.wiki_search_input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(255, 255, 255, 0.88);
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 0 9px 0 6px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(215, 219, 226, 0.96);
            }
            """
        )
        header.addWidget(self.wiki_search_input, 1)

        self.copy_btn = AnimatedToolButton()
        self.copy_btn.setObjectName("AiOverlayCopyButton")
        self.copy_btn.setIcon(icons.icon("common", "copy", "C"))
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setAutoRaise(True)
        self.copy_btn.setFixedSize(28, 28)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("")
        self.copy_btn.setProperty("skipClickSfx", True)
        self.copy_btn.hide()
        self.copy_btn.clicked.connect(self._copy_response)
        self.copy_btn.setStyleSheet(
            "background: transparent; border: none; padding: 4px;"
        )
        self.copy_btn.set_motion_scale_range(0.0)
        self.copy_btn.set_motion_hover_grow(0, 0)
        self.copy_btn.set_motion_lift(0.0)
        self.copy_btn.set_motion_press_scale(0.0)
        header.addWidget(self.copy_btn)

        self.close_btn = AnimatedToolButton()
        self.close_btn.setObjectName("AiOverlayCloseButton")
        self.close_btn.setIcon(icons.icon("common", "cross_three", "X"))
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.setAutoRaise(True)
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("")
        self.close_btn.setProperty("skipClickSfx", True)
        self.close_btn.clicked.connect(self.close_overlay)
        self.close_btn.setStyleSheet(
            "background: transparent; border: none; padding: 4px;"
        )
        self.close_btn.set_motion_scale_range(0.0)
        self.close_btn.set_motion_hover_grow(0, 0)
        self.close_btn.set_motion_lift(0.0)
        self.close_btn.set_motion_press_scale(0.0)
        header.addWidget(self.close_btn)
        layout.addWidget(self.header_frame)
        header.removeWidget(self.copy_btn)
        header.removeWidget(self.close_btn)
        self.copy_btn.setParent(self.surface)
        self.close_btn.setParent(self.surface)
        self.header_frame.hide()
        self.wiki_tab_btn.hide()
        self.ai_tab_btn.hide()
        self.images_tab_btn.hide()
        self.wiki_search_input.hide()

        self.wiki_entry_shell = QFrame(self.surface)
        self.wiki_entry_shell.setObjectName("WikiEntrySearchShell")
        self.wiki_entry_shell.setStyleSheet(
            """
            QFrame#WikiEntrySearchShell {
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(215, 219, 226, 0.96);
                border-radius: 28px;
            }
            """
        )
        entry_layout = QHBoxLayout(self.wiki_entry_shell)
        entry_layout.setContentsMargins(16, 0, 8, 0)
        entry_layout.setSpacing(8)
        self.wiki_entry_shell.installEventFilter(self)
        self.wiki_entry_submit_btn = AnimatedToolButton(self.wiki_entry_shell)
        self.wiki_entry_submit_btn.setIcon(icons.icon("common", "wiki_search", "S"))
        self.wiki_entry_submit_btn.setIconSize(QSize(17, 17))
        self.wiki_entry_submit_btn.setAutoRaise(True)
        self.wiki_entry_submit_btn.setFixedSize(30, 30)
        self.wiki_entry_submit_btn.setCursor(Qt.PointingHandCursor)
        self.wiki_entry_submit_btn.setProperty("skipClickSfx", True)
        self.wiki_entry_submit_btn.setStyleSheet("background: transparent; border: none; padding: 5px;")
        self.wiki_entry_submit_btn.clicked.connect(self._submit_wiki_search_entry)
        self.wiki_entry_submit_btn.installEventFilter(self)
        entry_layout.addWidget(self.wiki_entry_submit_btn, 0, Qt.AlignVCenter)
        self.wiki_entry_input = AnimatedLineEdit(self.wiki_entry_shell)
        self.wiki_entry_input.setFixedHeight(44)
        self.wiki_entry_input.setPlaceholderText("Search wikipedia")
        self.wiki_entry_input.returnPressed.connect(self._submit_wiki_search_entry)
        self.wiki_entry_input.installEventFilter(self)
        self.wiki_entry_input.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                padding: 0 4px 0 0;
                font-size: 18px;
            }
            """
        )
        entry_layout.addWidget(self.wiki_entry_input, 1)
        self.wiki_entry_close_btn = AnimatedToolButton(self.wiki_entry_shell)
        self.wiki_entry_close_btn.setIcon(icons.icon("common", "cross_three", "X"))
        self.wiki_entry_close_btn.setIconSize(QSize(15, 15))
        self.wiki_entry_close_btn.setAutoRaise(True)
        self.wiki_entry_close_btn.setFixedSize(32, 32)
        self.wiki_entry_close_btn.setCursor(Qt.PointingHandCursor)
        self.wiki_entry_close_btn.setProperty("skipClickSfx", True)
        self.wiki_entry_close_btn.setStyleSheet("background: transparent; border: none; padding: 6px;")
        self.wiki_entry_close_btn.clicked.connect(self.close_overlay)
        self.wiki_entry_close_btn.installEventFilter(self)
        self.wiki_entry_close_effect = QGraphicsOpacityEffect(self.wiki_entry_close_btn)
        self.wiki_entry_close_effect.setOpacity(0.0)
        self.wiki_entry_close_btn.setGraphicsEffect(self.wiki_entry_close_effect)
        self.wiki_entry_close_btn.setEnabled(False)
        entry_layout.addWidget(self.wiki_entry_close_btn, 0, Qt.AlignVCenter)
        self.wiki_entry_shell.hide()

        self.drag_zone = QWidget(self.surface)
        self.drag_zone.setCursor(Qt.OpenHandCursor)
        self.drag_zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.drag_zone.setStyleSheet("background: transparent;")
        self.drag_zone.installEventFilter(self)
        self.drag_zone.hide()

        self.body = QTextBrowser(self.surface)
        self.body.setObjectName("AiResponseBody")
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)
        self.body.anchorClicked.connect(self._open_response_link)
        self.body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.body.verticalScrollBar().setStyleSheet(
            """
            QScrollBar:vertical {
                width: 8px;
                margin: 2px 0 2px 0;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(158, 168, 184, 0.42);
                border-radius: 1px;
                margin: 0 3px;
                min-height: 28px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(158, 168, 184, 0.54);
                border-radius: 4px;
                margin: 0;
                min-height: 28px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
            }
            """
        )
        self.body.document().setDocumentMargin(0)
        self._apply_response_font(use_literata=True)
        document_layout = self.body.document().documentLayout()
        if document_layout is not None:
            document_layout.documentSizeChanged.connect(self._on_body_document_size_changed)
        self.body_container = QWidget(self.surface)
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.body)

        self.skeleton = AiResponseSkeleton(self.surface)
        self.response_host = QWidget(self.surface)
        self.response_stack = QStackedLayout(self.response_host)
        self.response_stack.setContentsMargins(0, 0, 0, 0)
        self.response_stack.setStackingMode(QStackedLayout.StackOne)
        self.response_stack.addWidget(self.skeleton)
        self.response_stack.addWidget(self.body_container)
        self.response_stack.setCurrentWidget(self.skeleton)
        self.reveal_overlay = AiRevealOverlay(self.response_host)
        layout.addWidget(self.response_host, 1)

        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(16)
        self._stream_timer.timeout.connect(self._flush_stream_tick)

        self._wiki_summary_stream_timer = QTimer(self)
        self._wiki_summary_stream_timer.setInterval(16)
        self._wiki_summary_stream_timer.timeout.connect(self._flush_wiki_summary_stream_tick)

        self._size_debounce = QTimer(self)
        self._size_debounce.setSingleShot(True)
        self._size_debounce.timeout.connect(lambda: self._sync_size(animated=True))

        self._size_animation = QPropertyAnimation(self, b"geometry", self)
        self._size_animation.setDuration(145)
        self._size_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _apply_surface_style(self, *, entry_mode: bool) -> None:
        root_layout = self.layout()
        if entry_mode:
            if root_layout is not None:
                root_layout.setContentsMargins(56, 56, 56, 34)
            self.surface.setStyleSheet(
                """
                QFrame#AiResponseSurface {
                    background: transparent;
                    border: none;
                    border-radius: 0px;
                }
                """
            )
            return
        if root_layout is not None:
            root_layout.setContentsMargins(56, 56, 56, 56)
        self.surface.setStyleSheet(
            """
            QFrame#AiResponseSurface {
                background: #FAFAFB;
                border: 1px solid rgba(215, 219, 226, 0.88);
                border-radius: 18px;
            }
            """
        )

    def _apply_response_font(self, *, use_literata: bool, justify_text: bool = False) -> None:
        self._response_uses_literata = use_literata
        text_align = "justify" if justify_text else "left"
        if use_literata:
            family = '"Literata", "Georgia", "Times New Roman", serif'
            qfont_family = "Literata"
            body_size = 15
            body_line_height = 1.78
            h1_size = 24
            h1_top_margin = 0
            h2_size = 12
            h3_size = 13
            text_color = "#566064"
            subtext_color = "#737C80"
            title_color = "#008970"
            muted_color = "#958E82"
            rule_color = "#E8E1D7"
            section_color = "#357B78"
            lead_color = "#B66A2C"
            callout_bg = "#FCF8F1"
            callout_border = "#D7A45C"
            code_bg = "#F2EEE7"
            code_border = "#E7DED2"
            link_color = "#2E716E"
        else:
            family = '"Segoe UI", "Segoe UI Variable Display", sans-serif'
            qfont_family = "Segoe UI"
            body_size = 15
            body_line_height = 1.68
            h1_size = 23
            h1_top_margin = -5
            h2_size = 15
            h3_size = 14
            text_color = "#1A1A1A"
            subtext_color = "#4B5560"
            title_color = "#1A1A1A"
            muted_color = "#657180"
            rule_color = "rgba(214, 220, 230, 0.9)"
            section_color = "#1A1A1A"
            lead_color = "#B66A2C"
            callout_bg = "rgba(239, 242, 247, 0.92)"
            callout_border = "rgba(214, 220, 230, 0.9)"
            code_bg = "rgba(239, 242, 247, 0.92)"
            code_border = "rgba(214, 220, 230, 0.9)"
            link_color = "#0B3A75"
        if is_dark_theme():
            text_color = "#e7edf4"
            subtext_color = "#aeb9c6"
            title_color = "#f7fafc"
            muted_color = "#9aa8b7"
            rule_color = "rgba(122, 142, 164, 0.34)"
            section_color = "#d7e8ff" if not use_literata else "#9ad6c8"
            lead_color = "#e6b96e"
            callout_bg = "rgba(31, 42, 54, 0.92)"
            callout_border = "rgba(121, 183, 255, 0.62)"
            code_bg = "rgba(17, 24, 32, 0.95)"
            code_border = "rgba(122, 142, 164, 0.34)"
            link_color = "#79b7ff"
        self.body.setStyleSheet(
            f"background: transparent; border: none; color: {text_color}; font-family: {family}; font-weight: 400;"
        )
        self.body.document().setDefaultStyleSheet(
            f"""
            body {{
                color: {text_color};
                font-family: {family};
                font-size: {body_size}px;
                font-weight: 400;
                line-height: {body_line_height};
                text-align: {text_align};
            }}
            h1 {{
                font-family: {family};
                font-size: {h1_size}px;
                font-weight: 600;
                margin: {h1_top_margin}px 0 6px 0;
                color: {title_color};
            }}
            h2 {{
                font-family: {family};
                font-size: {h2_size}px;
                font-weight: 600;
                margin: 28px 0 12px 0;
                color: {section_color};
            }}
            h3 {{
                font-size: {h3_size}px;
                font-weight: 600;
                margin: 22px 0 9px 0;
                color: {section_color};
            }}
            p, li {{
                margin: 0 0 13px 0;
                color: {text_color};
                text-align: {text_align};
            }}
            p.meta {{
                color: {muted_color};
                font-size: 13px;
                margin: 0 0 24px 0;
            }}
            ul, ol {{
                margin: 0 0 12px 18px;
            }}
            table.bullet-list {{
                margin: 6px 0 18px 0;
                border: none;
            }}
            td.bullet-cell {{
                width: 22px;
                color: #76B993;
                font-size: 19px;
                padding: 4px 12px 11px 0;
            }}
            td.bullet-text {{
                color: {text_color};
                font-size: {body_size}px;
                padding: 4px 0 11px 0;
            }}
            td.bullet-subtext {{
                color: {subtext_color};
            }}
            td.bullet-text strong {{
                color: inherit;
                font-weight: 600;
            }}
            td.bullet-text strong.bullet-heading {{
                color: {lead_color};
                font-weight: 600;
            }}
            hr {{
                color: {rule_color};
                background-color: {rule_color};
                height: 1px;
                border: none;
                margin: 24px 0 32px 0;
            }}
            blockquote {{
                background-color: {callout_bg};
                border-left: 2px solid {callout_border};
                margin: 14px 0 24px 0;
                padding: 15px 19px;
            }}
            blockquote p {{
                margin: 0;
            }}
            pre {{
                background: {code_bg};
                border: 1px solid {code_border};
                border-radius: 10px;
                padding: 12px;
                margin: 8px 0 12px 0;
            }}
            code {{
                background: {code_bg};
                border-radius: 6px;
                padding: 2px 5px;
            }}
            strong {{
                color: inherit;
                font-weight: 600;
            }}
            strong.bullet-heading {{
                color: {lead_color};
                font-weight: 600;
            }}
            em {{
                font-style: italic;
            }}
            a {{
                color: {link_color};
                text-decoration: none;
            }}
            """
        )
        base_font = QFont(qfont_family, self.font().pointSize())
        base_font.setWeight(QFont.Weight.Normal)
        self.body.setFont(base_font)

    def begin_stream(self) -> None:
        was_visible = self.isVisible()
        if self._close_animation is not None:
            self._close_animation.stop()
            self._close_animation = None
        self._clear_close_proxy()
        if self._reveal_animation is not None:
            self._reveal_animation.stop()
            self._reveal_animation = None
        self._wiki_entry_restore_state = None
        self._apply_surface_style(entry_mode=False)
        self._clear_wiki_result_content_opacity()
        self._wiki_entry_active = False
        self._reveal_duration_ms = 620
        self._tab_mode = ""
        self._active_tab = "wiki"
        self._tab_markdown = {}
        self._tab_content_format = {}
        self._tab_copy_payload = {}
        self._tab_loading = {}
        self._wiki_short_summary_text = ""
        self._last_markdown = ""
        self._display_markdown = ""
        self._target_markdown = ""
        self._target_chunks = []
        self._streaming_started = False
        self._closing = False
        self._display_chunk_count = 0
        self._stream_unit_credit = 0.0
        self._last_stream_time = 0.0
        self._last_render_commit = 0.0
        self._last_fade_start = 0.0
        self._stream_timer.stop()
        self._wiki_summary_stream_timer.stop()
        self._stop_char_fades()
        self._stop_wiki_short_summary_stream(reset_notice=True)
        self._wiki_short_summary_presented = False
        self._size_anchor_bottom = None
        self._apply_response_font(use_literata=True)
        self.body.setAlignment(Qt.AlignLeft)
        self.body.clear()
        self.skeleton.clear_research_message()
        self.skeleton.set_wiki_image_box_visible(False)
        self.skeleton.start()
        self.response_host.show()
        self.response_stack.setCurrentWidget(self.skeleton)
        self.reveal_overlay.hide()
        self.copy_btn.hide()
        self.close_btn.show()
        self.header_frame.setFixedHeight(0)
        self.header_frame.hide()
        self.wiki_tab_btn.hide()
        self.ai_tab_btn.hide()
        self.images_tab_btn.hide()
        self.wiki_search_input.hide()
        self.wiki_entry_shell.hide()
        self.wiki_entry_input.setEnabled(True)
        parent = self.parentWidget()
        self._manual_pos = None
        self._anchor_y = max(72, int(parent.height() * 0.16)) if parent is not None else 72
        self._streaming_started = True
        self._sync_size(force_minimum=False, animated=False)
        self.show()
        self.drag_zone.show()
        self.raise_()
        self._layout_overlay_elements()
        if self._suppress_next_animate_in:
            self._suppress_next_animate_in = False
        elif not was_visible:
            self._animate_in()

    @staticmethod
    def _tab_button_style(active: bool) -> str:
        if active:
            return (
                "background: rgba(15, 37, 57, 0.10); border: none; border-radius: 7px; "
                "padding: 3px 7px; text-align: left; font-size: 11px;"
            )
        return (
            "background: rgba(255, 255, 255, 0.72); border: none; border-radius: 7px; "
            "padding: 3px 7px; text-align: left; font-size: 11px;"
        )

    def enable_wikipedia_tabs(self) -> None:
        self._tab_mode = "wiki"
        self._active_tab = "wiki"
        self._tab_markdown = {"wiki": "", "ai": "", "images": ""}
        self._tab_content_format = {"wiki": "markdown", "ai": "markdown", "images": "html"}
        self._tab_copy_payload = {"wiki": "", "ai": "", "images": ""}
        self._tab_loading = {"wiki": True, "ai": True, "images": True}
        self._apply_response_font(use_literata=False)
        self.header_frame.setFixedHeight(38)
        self.header_frame.show()
        self.copy_btn.show()
        self.wiki_tab_btn.show()
        self.ai_tab_btn.show()
        self.images_tab_btn.show()
        self.wiki_search_input.clear()
        self.wiki_search_input.show()
        self._refresh_tab_styles()
        self.response_stack.setCurrentWidget(self.skeleton)
        self.skeleton.clear_research_message()
        self.skeleton.set_wiki_image_box_visible(True)
        self.skeleton.start()
        self._layout_overlay_elements()
        self._sync_size(animated=False)

    def configure_wiki_short_summary_behavior(self, *, stream_in: bool, chars_per_second: float = 150.0, fade_seconds: float = 0.34) -> None:
        self._wiki_short_summary_stream_enabled = bool(stream_in)
        self._wiki_short_summary_chars_per_second = max(1.0, float(chars_per_second or 50.0))
        self._wiki_short_summary_fade_seconds = max(0.05, float(fade_seconds or 0.34))
        self.summary_text.set_stream_config(fade_seconds=self._wiki_short_summary_fade_seconds)

    def set_wiki_search_query(self, text: str) -> None:
        self.wiki_search_input.setText(" ".join(str(text or "").strip().split()))

    def _submit_wiki_search_from_header(self) -> None:
        query = " ".join(self.wiki_search_input.text().strip().split())
        if not query:
            return
        self.wiki_search_input.clear()
        self.wikiSearchRequested.emit(query)

    def show_wikipedia_search_entry(self) -> None:
        self._capture_wiki_entry_restore_state()
        self._reset_wiki_entry_state(restore_surface=False)
        if self._animation_group is not None:
            self._animation_group.stop()
            self._animation_group = None
        self._apply_surface_style(entry_mode=True)
        self._wiki_entry_active = True
        self._closing = False
        buttons = QApplication.mouseButtons()
        self._wiki_entry_ignore_until_mouse_release = bool(buttons & Qt.MouseButton.LeftButton)
        self._tab_mode = "wiki-entry"
        self._active_tab = "wiki"
        self._tab_markdown = {}
        self._tab_content_format = {}
        self._tab_copy_payload = {}
        self._tab_loading = {}
        self._last_markdown = ""
        self._display_markdown = ""
        self._target_markdown = ""
        self._target_chunks = []
        self._stream_timer.stop()
        self._wiki_summary_stream_timer.stop()
        self._stop_char_fades()
        self._stop_wiki_short_summary_stream(reset_notice=True)
        self.summary_region.hide()
        self.header_frame.hide()
        self.response_host.hide()
        self.reveal_overlay.hide()
        self.copy_btn.hide()
        self.close_btn.hide()
        self.drag_zone.hide()
        self.wiki_entry_input.clear()
        self.wiki_entry_input.setEnabled(True)
        self.wiki_entry_close_effect.setOpacity(0.0)
        self.wiki_entry_close_btn.setEnabled(False)
        self.wiki_entry_shell.show()
        self._install_wiki_entry_app_filter()
        self._sync_size(animated=False)
        self.show()
        self.raise_()
        self._layout_overlay_elements()
        if self._suppress_next_animate_in:
            self._suppress_next_animate_in = False
        else:
            self._animate_in()
        QTimer.singleShot(0, self.wiki_entry_input.setFocus)

    def is_wikipedia_search_entry_open(self) -> bool:
        close_running = False
        if self._close_animation is not None:
            close_running = self._close_animation.state() == QAbstractAnimation.State.Running
        return bool(
            self.isVisible()
            and self._wiki_entry_active
            and self.wiki_entry_shell.isVisible()
            and not self._closing
            and not close_running
        )

    def close_wikipedia_search_entry(self) -> None:
        if not self.is_wikipedia_search_entry_open():
            return
        self.close_overlay()

    def _submit_wiki_search_entry(self) -> None:
        query = " ".join(self.wiki_entry_input.text().strip().split())
        if not query:
            self.wiki_entry_input.setFocus()
            return
        start_global = QRect(self.wiki_entry_shell.mapToGlobal(QPoint(0, 0)), self.wiki_entry_shell.size())
        self.wiki_entry_input.setEnabled(False)
        self._remove_wiki_entry_app_filter()
        self._animate_wiki_entry_to_result_menu(start_global, query)

    def _install_wiki_entry_app_filter(self) -> None:
        if self._wiki_entry_app_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._wiki_entry_app_filter_installed = True

    def _remove_wiki_entry_app_filter(self) -> None:
        if not self._wiki_entry_app_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._wiki_entry_app_filter_installed = False
        self._wiki_entry_ignore_until_mouse_release = False

    def _reset_wiki_entry_state(self, *, restore_surface: bool = True) -> None:
        self._remove_wiki_entry_app_filter()
        self._closing = False
        if self._close_animation is not None:
            self._close_animation.stop()
            self._close_animation = None
        self._clear_close_proxy()
        if self._reveal_animation is not None:
            self._reveal_animation.stop()
            self._reveal_animation = None
            self.reveal_overlay.hide()
        if self._wiki_entry_morph_animation is not None:
            self._wiki_entry_morph_animation.stop()
            self._wiki_entry_morph_animation = None
        self._wiki_entry_morphing = False
        self._clear_wiki_entry_morph_proxy()
        self._clear_wiki_result_content_opacity()
        self._wiki_entry_active = False
        self._wiki_entry_ignore_until_mouse_release = False
        self.wiki_entry_shell.hide()
        self.wiki_entry_input.setEnabled(True)
        self.wiki_entry_close_effect.setOpacity(0.0)
        self.wiki_entry_close_btn.setEnabled(False)
        if restore_surface:
            self._apply_surface_style(entry_mode=False)

    def _capture_wiki_entry_restore_state(self) -> None:
        if not self.isVisible() or self._wiki_entry_active or self._tab_mode != "wiki":
            self._wiki_entry_restore_state = None
            return
        self._wiki_entry_restore_state = {
            "active_tab": self._active_tab,
            "tab_markdown": dict(self._tab_markdown),
            "tab_content_format": dict(self._tab_content_format),
            "tab_copy_payload": dict(self._tab_copy_payload),
            "tab_loading": dict(self._tab_loading),
            "wiki_short_summary_text": self._wiki_short_summary_text,
        }

    def _restore_wiki_entry_result_state(self) -> bool:
        state = self._wiki_entry_restore_state
        if not isinstance(state, dict):
            return False
        self._wiki_entry_restore_state = None
        self._remove_wiki_entry_app_filter()
        self._clear_wiki_result_content_opacity()
        self._closing = False
        self._wiki_entry_active = False
        self._wiki_entry_ignore_until_mouse_release = False
        if self._close_animation is not None:
            self._close_animation.stop()
            self._close_animation = None
        self._clear_close_proxy()
        if self._reveal_animation is not None:
            self._reveal_animation.stop()
            self._reveal_animation = None
        if self._wiki_entry_morph_animation is not None:
            self._wiki_entry_morph_animation.stop()
            self._wiki_entry_morph_animation = None
        self._wiki_entry_morphing = False
        self._clear_wiki_entry_morph_proxy()
        self._apply_surface_style(entry_mode=False)
        self.wiki_entry_shell.hide()
        self.wiki_entry_input.setEnabled(True)
        self.wiki_entry_close_effect.setOpacity(0.0)
        self.wiki_entry_close_btn.setEnabled(False)
        self.response_host.show()
        self.reveal_overlay.hide()
        self.close_btn.show()
        self.drag_zone.show()
        self.header_frame.setFixedHeight(38)
        self.header_frame.show()
        self.copy_btn.show()
        self.wiki_tab_btn.show()
        self.ai_tab_btn.show()
        self.images_tab_btn.show()
        self.wiki_search_input.show()
        self._tab_mode = "wiki"
        self._active_tab = str(state.get("active_tab", "wiki") or "wiki")
        self._tab_markdown = dict(state.get("tab_markdown", {}))
        self._tab_content_format = dict(state.get("tab_content_format", {}))
        self._tab_copy_payload = dict(state.get("tab_copy_payload", {}))
        self._tab_loading = dict(state.get("tab_loading", {}))
        self._wiki_short_summary_text = str(state.get("wiki_short_summary_text", "") or "")
        self._stop_wiki_short_summary_stream(reset_notice=True)
        if self._wiki_short_summary_text:
            self.summary_text.show_full_text(self._wiki_short_summary_text)
            self._ensure_summary_region_visible()
            self._wiki_short_summary_presented = True
        else:
            self._wiki_short_summary_presented = False
        self._refresh_tab_styles()
        if self._tab_loading.get(self._active_tab, False):
            self._show_tab_skeleton()
        else:
            self._show_tab_content(self._active_tab, animate_transition=False)
        self._sync_size(animated=False)
        self.raise_()
        self._layout_overlay_elements()
        return True

    def _widget_is_wiki_entry_child(self, widget: object) -> bool:
        if not isinstance(widget, QWidget):
            return False
        current: QWidget | None = widget
        while current is not None:
            if current is self.wiki_entry_shell:
                return True
            current = current.parentWidget()
        return False

    def _sync_wiki_entry_close_visibility(self) -> None:
        if not self._wiki_entry_active or not self.wiki_entry_shell.isVisible():
            self.wiki_entry_close_effect.setOpacity(0.0)
            self.wiki_entry_close_btn.setEnabled(False)
            return
        local_pos = self.wiki_entry_shell.mapFromGlobal(QCursor.pos())
        visible = self.wiki_entry_shell.rect().contains(local_pos)
        self.wiki_entry_close_effect.setOpacity(1.0 if visible else 0.0)
        self.wiki_entry_close_btn.setEnabled(visible)

    def _animate_wiki_entry_to_result_menu(self, start_global: QRect, query: str) -> None:
        query = " ".join(str(query or "").strip().split())
        if not query:
            self.wiki_entry_input.setEnabled(True)
            self.wiki_entry_shell.show()
            self.wiki_entry_input.setFocus()
            return
        self._wiki_entry_restore_state = None
        start_pixmap = self.grab()
        app = QApplication.instance()
        if app is not None and bool(app.property("reducedMotion")):
            self._apply_surface_style(entry_mode=False)
            self._suppress_next_animate_in = True
            self.begin_stream()
            self.wiki_entry_input.setEnabled(True)
            self.wikiSearchRequested.emit(query)
            self._clear_wiki_result_content_opacity()
            return
        if self._wiki_entry_morph_animation is not None:
            self._wiki_entry_morph_animation.stop()
            self._wiki_entry_morph_animation = None
        parent = self.parentWidget()
        if parent is None:
            self.wiki_entry_input.setEnabled(True)
            self.wiki_entry_shell.show()
            self.wiki_entry_input.setFocus()
            return

        root_margins = self.layout().contentsMargins()
        start_top_left = start_global.topLeft() - QPoint(root_margins.left(), root_margins.top())
        start_size = QSize(
            start_global.width() + root_margins.left() + root_margins.right(),
            start_global.height() + root_margins.top() + root_margins.bottom(),
        )
        start_rect = QRect(parent.mapFromGlobal(start_top_left), start_size)

        self._manual_pos = None
        self._anchor_y = max(72, int(parent.height() * 0.16))
        self._size_debounce.stop()
        self._size_animation.stop()
        self._apply_surface_style(entry_mode=False)
        self._suppress_next_animate_in = True
        self.begin_stream()
        self.enable_wikipedia_tabs()
        end_rect = QRect(self.geometry())
        end_pixmap = self.grab()
        self._wiki_entry_morphing = True
        self._wiki_entry_active = False
        self.wiki_entry_shell.hide()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.hide()

        finished = {"done": False}

        def _finish() -> None:
            if finished["done"]:
                return
            finished["done"] = True
            self._manual_pos = None
            self._anchor_y = max(72, int(parent.height() * 0.16))
            self._wiki_entry_morphing = False
            self._clear_wiki_entry_morph_proxy()
            self.setGeometry(end_rect)
            self.show()
            self.raise_()
            self._sync_size(animated=False)
            self.wiki_entry_input.setEnabled(True)
            self._wiki_entry_morph_animation = None
            self.wikiSearchRequested.emit(query)
            self.wiki_search_input.clear()
            self._clear_wiki_result_content_opacity()

        animation = self._start_wiki_entry_morph_proxy(start_rect, end_rect, start_pixmap, end_pixmap, _finish)
        self._wiki_entry_morph_animation = animation
        QTimer.singleShot(
            900,
            lambda current=animation: (
                _finish()
                if self._wiki_entry_morph_animation is current and not finished["done"]
                else None
            ),
        )

    def _start_wiki_entry_morph_proxy(
        self,
        start_rect: QRect,
        end_rect: QRect,
        start_pixmap: QPixmap,
        end_pixmap: QPixmap,
        finished_callback,
    ) -> QAbstractAnimation:
        self._clear_wiki_entry_morph_proxy()
        parent = self.parentWidget()
        if parent is None:
            finished_callback()
            return QParallelAnimationGroup(self)
        proxy = WikiEntryMorphProxy(parent)
        proxy.set_pixmaps(start_pixmap, end_pixmap)
        proxy.setGeometry(start_rect)
        proxy.show()
        proxy.raise_()

        geometry_animation = QPropertyAnimation(proxy, b"geometry", proxy)
        geometry_animation.setDuration(560)
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutExpo)

        progress_animation = QPropertyAnimation(proxy, b"progress", proxy)
        progress_animation.setDuration(560)
        progress_animation.setStartValue(0.0)
        progress_animation.setEndValue(1.0)
        progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(proxy)
        group.addAnimation(geometry_animation)
        group.addAnimation(progress_animation)

        def _finish() -> None:
            finished_callback()

        group.finished.connect(_finish)
        self._wiki_entry_morph_proxy = proxy
        self._wiki_entry_morph_proxy_animation = group
        group.start()
        return group

    def _clear_wiki_entry_morph_proxy(self) -> None:
        if self._wiki_entry_morph_proxy_animation is not None:
            self._wiki_entry_morph_proxy_animation.stop()
            self._wiki_entry_morph_proxy_animation = None
        if self._wiki_entry_morph_proxy is not None:
            self._wiki_entry_morph_proxy.hide()
            self._wiki_entry_morph_proxy.deleteLater()
            self._wiki_entry_morph_proxy = None

    def _prepare_wiki_result_content_opacity(self, opacity: float) -> None:
        self._clear_wiki_result_content_opacity()
        for widget in (self.header_frame, self.response_host, self.copy_btn, self.close_btn):
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(max(0.0, min(1.0, float(opacity))))
            widget.setGraphicsEffect(effect)
            self._wiki_entry_content_effects.append((widget, effect))

    def _clear_wiki_result_content_opacity(self) -> None:
        if self._wiki_entry_content_fade is not None:
            self._wiki_entry_content_fade.stop()
            self._wiki_entry_content_fade = None
        for widget, effect in self._wiki_entry_content_effects:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        self._wiki_entry_content_effects = []

    def _fade_in_wiki_result_content(self) -> None:
        if not self._wiki_entry_content_effects:
            return
        group = QParallelAnimationGroup(self)
        for _widget, effect in self._wiki_entry_content_effects:
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setDuration(220)
            animation.setStartValue(effect.opacity())
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(animation)

        def _finish() -> None:
            self._wiki_entry_content_fade = None
            self._clear_wiki_result_content_opacity()

        group.finished.connect(_finish)
        self._wiki_entry_content_fade = group
        group.start()

    def set_wikipedia_markdown(self, markdown_text: str) -> None:
        if self._tab_mode != "wiki":
            return
        self._tab_markdown["wiki"] = markdown_text
        self._tab_copy_payload["wiki"] = markdown_text
        self._tab_loading["wiki"] = False
        if self._active_tab == "wiki":
            self._show_tab_content("wiki")

    def set_wikipedia_ai_markdown(self, markdown_text: str) -> None:
        if self._tab_mode != "wiki":
            return
        self._tab_markdown["ai"] = markdown_text
        self._tab_copy_payload["ai"] = markdown_text
        self._tab_loading["ai"] = False
        if self._active_tab == "ai":
            self._show_tab_content("ai")

    def set_wikipedia_images_html(self, html_text: str, *, copy_text: str = "") -> None:
        if self._tab_mode != "wiki":
            return
        self._tab_markdown["images"] = html_text
        self._tab_copy_payload["images"] = copy_text
        self._tab_loading["images"] = False
        if self._active_tab == "images":
            self._show_tab_content("images", animate_transition=False)

    def _select_response_tab(self, tab_name: str) -> None:
        if self._tab_mode != "wiki":
            return
        if tab_name == "ai":
            normalized = "ai"
        elif tab_name == "images":
            normalized = "images"
        else:
            normalized = "wiki"
        if self._active_tab == normalized:
            return
        self._active_tab = normalized
        if self._wiki_short_summary_text:
            self.show_wiki_short_summary(self._wiki_short_summary_text)
        self._refresh_tab_styles()
        if self._tab_loading.get(normalized, False):
            self._show_tab_skeleton()
            return
        self._show_tab_content(normalized)

    def _refresh_tab_styles(self) -> None:
        self.wiki_tab_btn.set_active(self._active_tab == "wiki")
        self.ai_tab_btn.set_active(self._active_tab == "ai")
        self.images_tab_btn.set_active(self._active_tab == "images")

    def _show_tab_skeleton(self) -> None:
        self._stream_timer.stop()
        self._stop_char_fades()
        self._apply_response_font(use_literata=self._active_tab == "ai")
        self.body.clear()
        self.copy_btn.hide()
        self.response_stack.setCurrentWidget(self.skeleton)
        self.skeleton.clear_research_message()
        self.skeleton.set_wiki_image_box_visible(self._active_tab == "wiki")
        self.skeleton.start()
        self.reveal_overlay.hide()
        self._layout_overlay_elements()
        self._sync_size(animated=False)

    def _show_tab_content(self, tab_name: str, *, animate_transition: bool = True) -> None:
        content = self._tab_markdown.get(tab_name, "")
        content_format = self._tab_content_format.get(tab_name, "markdown")
        self._apply_response_font(use_literata=tab_name == "ai", justify_text=tab_name == "wiki")
        self.body.setAlignment(Qt.AlignJustify if tab_name == "wiki" else Qt.AlignLeft)
        if animate_transition and self.response_stack.currentWidget() is self.body_container:
            self.response_stack.setCurrentWidget(self.skeleton)
            self.skeleton.clear_research_message()
            self.skeleton.set_wiki_image_box_visible(tab_name == "wiki")
            self.skeleton.start()
        if content_format == "html":
            self.set_html_content(content, copy_text=self._tab_copy_payload.get(tab_name, ""))
            return
        self.set_markdown(content)

    def show_research_message(self, message: str) -> None:
        self.show_reasoning_messages([message])

    def show_reasoning_messages(self, messages: list[str]) -> None:
        self._stream_timer.stop()
        self._stop_char_fades()
        self.body.setAlignment(Qt.AlignLeft)
        self.body.clear()
        self.copy_btn.hide()
        self.response_stack.setCurrentWidget(self.skeleton)
        self.skeleton.set_wiki_image_box_visible(False)
        self.skeleton.start()
        self.skeleton.show_reasoning_messages(messages)
        self.reveal_overlay.hide()
        self._layout_overlay_elements()
        self._sync_size(animated=False)

    def set_markdown(self, markdown_text: str) -> None:
        cleaned = self._normalize_markdown(markdown_text)
        if self._tab_mode == "wiki" and self._active_tab == "wiki":
            cleaned = self._prepare_local_markdown_images(cleaned, self.body.document())
        self._last_markdown = cleaned
        self._target_markdown = cleaned
        self._display_markdown = cleaned
        editorial = bool(getattr(self, "_response_uses_literata", False))
        self.body.setHtml(markdown_to_html(self._display_markdown, editorial=editorial))
        if editorial:
            self._apply_editorial_document_colors()
        self._force_scroll_metrics(reset_to_top=True)
        bar = self.body.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)
        self.skeleton.clear_research_message()
        self.skeleton.stop()
        animate_reveal = self.response_stack.currentWidget() is self.skeleton
        self.response_stack.setCurrentWidget(self.body_container)
        self.copy_btn.show()
        self._layout_overlay_elements()
        self._size_debounce.stop()
        self._sync_size(animated=False)
        if animate_reveal:
            self._start_reveal_animation()
            QTimer.singleShot(0, lambda: self._sync_size(animated=False))
            return
        self.reveal_overlay.hide()
        QTimer.singleShot(0, self._refresh_body_metrics_from_viewport)
        QTimer.singleShot(24, self._refresh_body_metrics_from_viewport)
        self._size_debounce.start(22)

    def set_html_content(self, html_text: str, *, copy_text: str = "") -> None:
        rendered_html = str(html_text or "").strip()
        self._last_markdown = str(copy_text or "").strip()
        self._target_markdown = self._last_markdown
        self._display_markdown = self._last_markdown
        self.body.setHtml(rendered_html)
        self._force_scroll_metrics(reset_to_top=True)
        bar = self.body.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)
        self.skeleton.clear_research_message()
        self.skeleton.stop()
        animate_reveal = self.response_stack.currentWidget() is self.skeleton
        self.response_stack.setCurrentWidget(self.body_container)
        self.copy_btn.show()
        self._layout_overlay_elements()
        self._size_debounce.stop()
        self._sync_size(animated=False)
        if animate_reveal:
            self._start_reveal_animation()
            QTimer.singleShot(0, lambda: self._sync_size(animated=False))
            return
        self.reveal_overlay.hide()
        QTimer.singleShot(0, self._refresh_body_metrics_from_viewport)
        QTimer.singleShot(24, self._refresh_body_metrics_from_viewport)
        self._size_debounce.start(22)

    def show_wiki_short_summary(self, summary: str) -> None:
        cleaned = " ".join(str(summary or "").strip().split())
        if cleaned:
            self._wiki_short_summary_text = cleaned
        if self._tab_mode != "wiki" or not cleaned:
            return
        if cleaned == self._wiki_summary_stream_target and (
            self._wiki_summary_stream_timer.isActive()
            or (
                self._wiki_short_summary_expansion_animation is not None
                and self._wiki_short_summary_expansion_animation.state() == QAbstractAnimation.State.Running
            )
        ):
            return
        if self._wiki_short_summary_stream_enabled and not self._wiki_short_summary_presented:
            self._stop_wiki_short_summary_stream(reset_notice=False)
            self._start_wiki_short_summary_sequence(cleaned)
            return
        self.summary_text.show_full_text(cleaned)
        self._ensure_summary_region_visible()
        self._wiki_short_summary_presented = True
        self._sync_size(animated=False)

    def _start_wiki_short_summary_sequence(self, summary: str) -> None:
        self._wiki_summary_stream_target = summary
        self._wiki_short_summary_visible_count = 0
        self._wiki_short_summary_stream_started_times = []
        self.summary_text.set_full_text(summary)
        self.summary_text.set_stream_frame(visible_count=0, char_started_times=[], now=0.0)
        self._wiki_short_summary_presented = False
        if self.isVisible():
            self._size_anchor_bottom = self.geometry().bottom()
        self._animate_wiki_summary_overlay_expansion()

    def _animate_wiki_summary_overlay_expansion(self) -> None:
        if not self._wiki_summary_stream_target:
            return
        if not self.isVisible():
            self._ensure_summary_region_visible()
            self._begin_wiki_short_summary_stream()
            return
        app = QApplication.instance()
        if app is not None and bool(app.property("reducedMotion")):
            self._ensure_summary_region_visible()
            self._sync_size(animated=False)
            self._begin_wiki_short_summary_stream()
            return
        self._wiki_summary_region_target_height = self._desired_summary_region_height()
        if self._wiki_summary_region_target_height <= 0:
            self._begin_wiki_short_summary_stream()
            return
        animation = QVariantAnimation(self)
        animation.setDuration(560)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutExpo)

        def _advance(value) -> None:
            progress = max(0.0, min(1.0, float(value)))
            self._set_summary_region_height(int(round(self._wiki_summary_region_target_height * progress)))
            self._sync_size(animated=False)

        def _finish() -> None:
            self._set_summary_region_height(self._wiki_summary_region_target_height)
            self._sync_size(animated=False)
            self._wiki_short_summary_expansion_animation = None
            self._begin_wiki_short_summary_stream()

        animation.valueChanged.connect(_advance)
        animation.finished.connect(_finish)
        animation.start()
        self._wiki_short_summary_expansion_animation = animation

    def _begin_wiki_short_summary_stream(self) -> None:
        self._wiki_short_summary_stream_started_at = time.perf_counter()
        self._wiki_short_summary_visible_count = 0
        self._wiki_short_summary_stream_started_times = []
        self._wiki_summary_stream_timer.start()

    def _flush_wiki_summary_stream_tick(self) -> None:
        target = self._wiki_summary_stream_target
        if not target:
            self._wiki_summary_stream_timer.stop()
            return
        now = time.perf_counter()
        elapsed = max(0.0, now - self._wiki_short_summary_stream_started_at)
        visible = min(len(target), int(elapsed * self._wiki_short_summary_chars_per_second))
        while len(self._wiki_short_summary_stream_started_times) < visible:
            index = len(self._wiki_short_summary_stream_started_times)
            self._wiki_short_summary_stream_started_times.append(
                self._wiki_short_summary_stream_started_at + (index / self._wiki_short_summary_chars_per_second)
            )
        self._wiki_short_summary_visible_count = visible
        self.summary_text.set_stream_frame(
            visible_count=visible,
            char_started_times=self._wiki_short_summary_stream_started_times,
            now=now,
        )
        if visible >= len(target):
            final_char_ready_at = self._wiki_short_summary_stream_started_at + (
                max(0, len(target) - 1) / self._wiki_short_summary_chars_per_second
            )
            if now >= final_char_ready_at + self._wiki_short_summary_fade_seconds:
                self._wiki_summary_stream_timer.stop()
                self._wiki_short_summary_presented = True
                self.summary_text.show_full_text(target)

    def _stop_wiki_short_summary_stream(self, *, reset_notice: bool) -> None:
        self._wiki_summary_stream_timer.stop()
        if self._wiki_short_summary_expansion_animation is not None:
            self._wiki_short_summary_expansion_animation.stop()
            self._wiki_short_summary_expansion_animation = None
        self._wiki_summary_stream_target = ""
        self._wiki_short_summary_visible_count = 0
        self._wiki_short_summary_stream_started_at = 0.0
        self._wiki_short_summary_stream_started_times = []
        self._wiki_summary_region_target_height = 0
        self._size_anchor_bottom = None
        if reset_notice:
            self._set_summary_region_height(0)
            self.summary_text.clear()

    def _ensure_summary_region_visible(self) -> None:
        target_height = self._desired_summary_region_height()
        self._wiki_summary_region_target_height = target_height
        if target_height > 0 and self.isVisible() and self._size_anchor_bottom is None:
            self._size_anchor_bottom = self.geometry().bottom()
        self._set_summary_region_height(target_height)

    def _set_summary_region_height(self, height: int) -> None:
        normalized = max(0, int(height or 0))
        self._wiki_summary_region_current_height = normalized
        self.summary_region.setVisible(normalized > 0)
        self.summary_region.setMinimumHeight(normalized)
        self.summary_region.setMaximumHeight(normalized)

    def _desired_summary_region_height(self) -> int:
        if not self._wiki_short_summary_text.strip():
            return 0
        width = max(240, self._target_width() - 112)
        margins = self.summary_region_layout.contentsMargins()
        text_width = max(120, width - margins.left() - margins.right())
        text_height = self.summary_text.height_for_width(text_width)
        if text_height <= 0:
            return 0
        return margins.top() + margins.bottom() + text_height

    @staticmethod
    def _prepare_local_markdown_images(markdown_text: str, document: QTextDocument) -> str:
        image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
        registered_count = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal registered_count
            raw_url = match.group(2).strip()
            url = QUrl(raw_url)
            if url.scheme().lower() == "file":
                local_path = url.toLocalFile()
            elif not url.scheme():
                local_path = raw_url
            else:
                return ""
            path = Path(local_path)
            if not path.exists() or not path.is_file():
                return ""
            image = AiResponseOverlay._prepare_wiki_thumbnail_image(QImage(str(path)))
            if image.isNull():
                return ""
            resource_url = QUrl(f"oncard-wiki-thumb:{registered_count}")
            registered_count += 1
            document.addResource(QTextDocument.ResourceType.ImageResource, resource_url, image)
            return f"![{match.group(1)}]({resource_url.toString()})"

        cleaned = image_pattern.sub(replace, str(markdown_text or ""))
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    @staticmethod
    def _prepare_wiki_thumbnail_image(image: QImage) -> QImage:
        if image.isNull():
            return QImage()
        scale = AiResponseOverlay.WIKI_THUMB_SUPERSAMPLE
        target_width = AiResponseOverlay.WIKI_THUMB_WIDTH * scale
        target_max_height = AiResponseOverlay.WIKI_THUMB_MAX_HEIGHT * scale
        scaled = image.scaled(
            target_width,
            target_max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QImage(
            scaled.width() + (AiResponseOverlay.WIKI_THUMB_RIGHT_GAP * scale),
            scaled.height() + (AiResponseOverlay.WIKI_THUMB_BOTTOM_GAP * scale),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        rect = QRectF(0.5, 0.5, max(1.0, scaled.width() - 1.0), max(1.0, scaled.height() - 1.0))
        radius = AiResponseOverlay.WIKI_THUMB_RADIUS * scale
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        painter.drawImage(0, 0, scaled)
        painter.end()
        canvas.setDevicePixelRatio(float(scale))
        return canvas

    @staticmethod
    def _wiki_images_html(article: dict, *, loading: bool = False) -> tuple[str, str]:
        title = " ".join(str(article.get("title", "Wikipedia")).strip().split()) or "Wikipedia"
        images = article.get("images", [])
        if not isinstance(images, list):
            images = []

        valid_images: list[dict] = []
        for image in images:
            if not isinstance(image, dict):
                continue
            image_path = str(image.get("path", "")).strip()
            if not image_path or not Path(image_path).exists():
                continue
            valid_images.append(image)

        if not valid_images:
            if loading:
                loading_html = (
                    '<div style="padding: 12px 4px 0 4px;">'
                    '<p style="margin: 0; font-size: 15px; color: #657180;">Loading Wikimedia images...</p>'
                    "</div>"
                )
                return loading_html, "Loading Wikimedia images..."
            empty_html = (
                '<div style="padding: 12px 4px 0 4px;">'
                '<p style="margin: 0; font-size: 15px; color: #657180;">No images for this seach :(</p>'
                "</div>"
            )
            return empty_html, "No images for this seach :("

        cards: list[str] = []
        copy_lines = [f"Wikimedia images for {title}"]
        for index, image in enumerate(valid_images):
            image_path = str(image.get("path", "")).strip()
            source_url = str(image.get("description_url", "") or image.get("source_url", "")).strip()
            label = " ".join(str(image.get("title", "Wikipedia image")).strip().split()) or "Wikipedia image"
            local_url = QUrl.fromLocalFile(image_path).toString()
            open_url = html.escape(source_url or local_url, quote=True)
            image_url = html.escape(local_url, quote=True)
            label_html = html.escape(label)
            cards.append(
                (
                    '<td style="width:50%; vertical-align:top; padding: 0 10px 16px 0;">'
                    f'<a href="{open_url}" style="text-decoration:none;">'
                    f'<img src="{image_url}" alt="{label_html}" '
                    'style="display:block; width:100%; max-width:320px; border-radius:10px;" />'
                    "</a>"
                    f'<div style="margin-top:7px; font-size:12px; line-height:1.35; color:#657180;">{label_html}</div>'
                    "</td>"
                )
            )
            copy_lines.append(f"{index + 1}. {label}")
            if source_url:
                copy_lines.append(source_url)

        rows: list[str] = []
        for start in range(0, len(cards), 2):
            row_cards = cards[start : start + 2]
            if len(row_cards) == 1:
                row_cards.append('<td style="width:50%; vertical-align:top; padding: 0 10px 16px 0;"></td>')
            rows.append("<tr>" + "".join(row_cards) + "</tr>")

        gallery_html = (
            '<div style="padding: 2px 4px 0 4px;">'
            f'<div style="margin: 0 0 12px 0; font-size: 13px; color: #657180;">Wikimedia images for {html.escape(title)}</div>'
            '<table style="width:100%; border:none; border-collapse:separate; border-spacing:0;">'
            + "".join(rows)
            + "</table>"
            + (
                '<div style="margin-top: 4px; font-size: 12px; color: #8b95a3;">Loading more images...</div>'
                if loading
                else ""
            )
            + "</div>"
        )
        return gallery_html, "\n".join(copy_lines).strip()

    def _open_response_link(self, url) -> None:
        link = url.toString().strip()
        if not link:
            return
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", link):
            link = f"https://{link}"
        QDesktopServices.openUrl(QUrl(link))

    def _apply_editorial_document_colors(self) -> None:
        heading_format = QTextCharFormat()
        heading_format.setForeground(QColor("#357B78"))
        block = self.body.document().firstBlock()
        while block.isValid():
            if block.blockFormat().headingLevel() in {1, 2, 3}:
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.mergeCharFormat(heading_format)
            block = block.next()

    def _on_body_document_size_changed(self, _size) -> None:
        if self.response_stack.currentWidget() is not self.body_container:
            return
        if not self.isVisible():
            return
        self._size_debounce.start(22)

    def set_stream_settings(self, mode: str, tps: float, fade_seconds: float) -> None:
        return

    def refresh_layout(self) -> None:
        if self.isVisible():
            self._sync_size(animated=False)
            self._layout_overlay_elements()
            self._refresh_body_metrics_from_viewport()

    def eventFilter(self, watched, event) -> bool:
        wiki_entry_shell = getattr(self, "wiki_entry_shell", None)
        wiki_entry_submit_btn = getattr(self, "wiki_entry_submit_btn", None)
        wiki_entry_input = getattr(self, "wiki_entry_input", None)
        wiki_entry_close_btn = getattr(self, "wiki_entry_close_btn", None)
        if getattr(self, "_wiki_entry_active", False):
            if event.type() == QEvent.MouseButtonRelease:
                self._wiki_entry_ignore_until_mouse_release = False
            if watched in (wiki_entry_shell, wiki_entry_submit_btn, wiki_entry_input, wiki_entry_close_btn) and event.type() in (
                QEvent.Enter,
                QEvent.Leave,
            ):
                QTimer.singleShot(0, self._sync_wiki_entry_close_visibility)
            if event.type() == QEvent.MouseButtonPress and not self._widget_is_wiki_entry_child(watched):
                if self._wiki_entry_ignore_until_mouse_release:
                    return False
                self.close_overlay()
                return True
        drag_zone = getattr(self, "drag_zone", None)
        if drag_zone is not None and watched is drag_zone:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.drag_zone.setCursor(Qt.ClosedHandCursor)
                return True
            if event.type() == QEvent.MouseMove and self._drag_active:
                self._manual_pos = event.globalPosition().toPoint() - self._drag_offset
                self.move(self._manual_pos)
                return True
            if event.type() == QEvent.MouseButtonRelease and self._drag_active:
                self._drag_active = False
                self._manual_pos = self.pos()
                self.drag_zone.setCursor(Qt.OpenHandCursor)
                return True
        return super().eventFilter(watched, event)

    def has_markdown(self) -> bool:
        return bool(self._last_markdown.strip())

    def _start_reveal_animation(self) -> None:
        self.reveal_overlay.setGeometry(self.response_host.rect())
        self.reveal_overlay.raise_()
        self.reveal_overlay.setPixmap(self.body_container.grab())
        self.reveal_overlay.setProgress(0.0)
        self.reveal_overlay.show()

        animation = QPropertyAnimation(self.reveal_overlay, b"progress", self)
        animation.setDuration(int(getattr(self, "_reveal_duration_ms", 620) or 620))
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _finish() -> None:
            self.reveal_overlay.hide()
            self._reveal_animation = None
            self._size_debounce.start(22)

        animation.finished.connect(_finish)
        animation.start()
        self._reveal_animation = animation

    def set_reveal_duration(self, duration_ms: int) -> None:
        self._reveal_duration_ms = max(1, int(duration_ms or 620))

    def _should_follow_bottom(self) -> bool:
        scroll = self.body.verticalScrollBar()
        return scroll.maximum() <= 0 or scroll.value() >= max(0, scroll.maximum() - 24)

    def _animate_in(self) -> None:
        end_pos = self._target_pos()
        start_pos = QPoint(end_pos.x(), end_pos.y() + 14)
        self.move(start_pos)
        if self._animation_group is not None:
            self._animation_group.stop()
        motion = 1 if QApplication.instance() is not None and bool(QApplication.instance().property("reducedMotion")) else 200

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(motion)
        slide.setStartValue(start_pos)
        slide.setEndValue(end_pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(slide)
        self._animation_group.start()

    def close_overlay(self) -> None:
        if self._closing or not self.isVisible():
            return
        if self._wiki_entry_active and self._restore_wiki_entry_result_state():
            return
        self._closing = True
        self._remove_wiki_entry_app_filter()
        self._stream_timer.stop()
        self._stop_wiki_short_summary_stream(reset_notice=True)
        self._stop_char_fades()
        self._clear_wiki_result_content_opacity()
        self._wiki_entry_morphing = False
        self._clear_wiki_entry_morph_proxy()
        self._wiki_entry_active = False
        self._wiki_entry_ignore_until_mouse_release = False
        self.wiki_entry_shell.hide()
        self.wiki_entry_close_effect.setOpacity(0.0)
        self.wiki_entry_close_btn.setEnabled(False)
        self.skeleton.clear_research_message()
        self.skeleton.stop()
        self.reveal_overlay.hide()
        animation = self._start_close_proxy_animation()

        def _finish() -> None:
            self.hide()
            self._clear_close_proxy()
            self.drag_zone.hide()
            self._drag_active = False
            self.drag_zone.setCursor(Qt.OpenHandCursor)
            self._closing = False
            self._close_animation = None
            self._apply_surface_style(entry_mode=False)
            self.closed.emit()

        animation.finished.connect(_finish)
        animation.start()
        self._animation_group = None
        self._close_animation = animation

    def _start_close_proxy_animation(self) -> QAbstractAnimation:
        self._clear_close_proxy()
        app = QApplication.instance()
        if app is not None and bool(app.property("reducedMotion")):
            animation = QVariantAnimation(self)
            animation.setDuration(1)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            return animation
        parent = self.parentWidget()
        if parent is None:
            animation = QVariantAnimation(self)
            animation.setDuration(120)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            return animation
        proxy = OverlayCloseProxy(self.grab(), parent)
        proxy.setGeometry(self.geometry().adjusted(-2, -2, 2, 8))
        proxy.show()
        proxy.raise_()
        self.hide()

        progress_animation = QPropertyAnimation(proxy, b"progress", proxy)
        progress_animation.setDuration(190)
        progress_animation.setStartValue(0.0)
        progress_animation.setEndValue(1.0)
        progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        geometry_animation = QPropertyAnimation(proxy, b"geometry", proxy)
        geometry_animation.setDuration(190)
        start_rect = proxy.geometry()
        end_rect = QRect(start_rect)
        end_rect.translate(0, 16)
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(proxy)
        group.addAnimation(progress_animation)
        group.addAnimation(geometry_animation)
        self._close_proxy = proxy
        return group

    def _clear_close_proxy(self) -> None:
        if self._close_proxy is not None:
            self._close_proxy.hide()
            self._close_proxy.deleteLater()
            self._close_proxy = None

    def _copy_response(self) -> None:
        if not self._last_markdown.strip():
            return
        QApplication.clipboard().setText(self._last_markdown)
        self._copy_flash_active = True
        self.copy_btn.setIcon(self._icons.icon("common", "check", "C"))
        QTimer.singleShot(2000, self._reset_copy_button_style)

    def _reset_copy_button_style(self) -> None:
        self._copy_flash_active = False
        self.copy_btn.setIcon(self._icons.icon("common", "copy", "C"))

    def _layout_overlay_elements(self) -> None:
        surface_rect = self.surface.rect()
        right = surface_rect.right() - 18
        summary_offset = self._wiki_summary_region_current_height
        if self._wiki_entry_active:
            entry_width = min(690, max(260, surface_rect.width() - 24))
            entry_height = 56
            self.wiki_entry_shell.setGeometry(
                max(12, (surface_rect.width() - entry_width) // 2),
                max(10, (surface_rect.height() - entry_height) // 2),
                entry_width,
                entry_height,
            )
            self.wiki_entry_shell.raise_()
            return
        if self._tab_mode == "wiki" and self.header_frame.isVisible():
            top = self.header_frame.y() + max(0, (self.header_frame.height() - self.close_btn.height()) // 2)
        else:
            top = 14 + summary_offset
        self.close_btn.move(right - self.close_btn.width() + 1, top)
        self.copy_btn.move(self.close_btn.x() - self.copy_btn.width() - 8, top)
        drag_left = 14
        drag_top = 10 + summary_offset
        drag_height = 34
        if self._tab_mode == "wiki" and self.header_frame.isVisible():
            if self.wiki_search_input.isVisible():
                drag_left = max(
                    14,
                    self.header_frame.x() + self.wiki_search_input.x() + self.wiki_search_input.width() + 12,
                )
            else:
                rightmost_tab = self.images_tab_btn if self.images_tab_btn.isVisible() else self.ai_tab_btn
                drag_left = max(14, self.header_frame.x() + rightmost_tab.x() + rightmost_tab.width() + 12)
        drag_right = max(drag_left + 1, self.copy_btn.x() - 10)
        self.drag_zone.setGeometry(drag_left, drag_top, max(1, drag_right - drag_left), drag_height)
        self.drag_zone.raise_()
        if self._tab_mode == "wiki":
            self.header_frame.raise_()
        self.copy_btn.raise_()
        self.close_btn.raise_()

    @staticmethod
    def _normalize_markdown(markdown_text: str) -> str:
        if not markdown_text:
            return ""

        normalized = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
        protected_images: dict[str, str] = {}

        def protect_image(match: re.Match[str]) -> str:
            token = f"@@ONCARDWIKIIMAGE{chr(65 + len(protected_images))}@@"
            protected_images[token] = match.group(0)
            return token

        normalized = re.sub(r"!\[[^\]\n]*\]\([^)\n]+\)", protect_image, normalized)
        trailing_newline = normalized.endswith("\n")
        bullet_chars = r"\-\*\+\u2022\u25CF\u25AA\u25E6\u2043\u2219"
        section_label_modes = {
            "key points",
            "quick explanation",
            "quick breakdown",
            "takeaway",
            "key takeaway",
            "key take away",
            "summary",
            "short answer",
            "next steps",
        }
        canonical_section = {
            "key takeaway": "takeaway",
            "key take away": "takeaway",
        }
        section_headings = {
            "key points": "Key Points",
            "quick explanation": "Quick Explanation",
            "quick breakdown": "Quick Breakdown",
            "takeaway": "Takeaway",
            "summary": "Summary",
            "short answer": "Short Answer",
            "next steps": "Next Steps",
        }
        section_pattern = "|".join(re.escape(label) for label in sorted(section_label_modes, key=len, reverse=True))
        url_pattern = re.compile(r"(?:https?://|www\.)\S+")

        def rewrite_emphasized_section_label(value: str) -> str:
            line = value
            patterns = (
                rf"^(?P<indent>\s*)(?P<em>\*\*|__)\s*(?P<label>{section_pattern})\s*:\s*(?P=em)\s*(?P<content>.*)$",
                rf"^(?P<indent>\s*)(?P<em>\*\*|__)\s*(?P<label>{section_pattern})\s*(?P=em)\s*:\s*(?P<content>.*)$",
                rf"^(?P<indent>\s*)(?P<em>\*\*|__)\s*(?P<label>{section_pattern})\s*:\s*(?P<content>.*)$",
                rf"^(?P<indent>\s*)(?P<em>\*\*|__)\s*(?P<label>{section_pattern})\s*(?P=em)\s*$",
                rf"^(?P<indent>\s*)(?P<em>\*\*|__)\s*(?P<label>{section_pattern})\s*$",
            )
            for pattern in patterns:
                match = re.match(pattern, line, flags=re.IGNORECASE)
                if not match:
                    continue
                indent = match.group("indent") or ""
                label = match.group("label") or ""
                content = " ".join(str(match.groupdict().get("content", "") or "").split())
                if content:
                    return f"{indent}{label}: {content}"
                return f"{indent}{label}"
            return line

        def close_unbalanced_leading_emphasis(value: str) -> str:
            stripped_value = value.lstrip()
            if stripped_value.startswith("**") and (len(re.findall(r"(?<!\\)\*\*", value)) % 2 == 1):
                label_colon = value.find(":")
                if label_colon > -1:
                    closed = f"{value[:label_colon + 1]}**{value[label_colon + 1:]}"
                    return re.sub(r"(\*\*[^*\n]{1,120}:\*\*)(?=\S)", r"\1 ", closed)
                return f"{value}**"
            if stripped_value.startswith("__") and (len(re.findall(r"(?<!\\)__", value)) % 2 == 1):
                return f"{value}__"
            return value

        # Repair common broken encodings for bullets before regex normalization.
        normalized = normalized.replace("\u00e2\u20ac\u00a2", "\u2022")
        normalized = normalized.replace("\u00e2\u2014\u008f", "\u25CF")
        normalized = normalized.replace("\u00e2\u2013\u00aa", "\u25AA")
        normalized = normalized.replace("\u00e2\u2014\u00a6", "\u25E6")
        emoji_bullet_pattern = r"(?:✅|❌|✔️|✔|✖️|✖|☑️|☑|🟢|🔴|🟡|🔵|•)"

        # Split glued structural markers into their own lines.
        normalized = re.sub(r"#[ \t]+#", "##", normalized)
        normalized = re.sub(r"(?<=[^\s#])(?=(?:#{1,6})\s*[A-Za-z])", "\n", normalized)
        normalized = re.sub(
            rf"(?i)(?<=[^\n])(?=(?:{section_pattern})\s*[:\-])",
            "\n",
            normalized,
        )
        normalized = re.sub(
            rf"(?i)(?<=[.!?])\s*(?=(?:#{{1,6}}\s*)?(?:{section_pattern})\b)",
            "\n\n",
            normalized,
        )
        normalized = re.sub(rf"(?<=[.!?])\s*(?=[{bullet_chars}]\s+\S)", "\n", normalized)
        normalized = re.sub(rf"(?<!^)(?<!\n)\s+(?={emoji_bullet_pattern}\s+\S)", "\n- ", normalized)
        normalized = re.sub(r"(?<=[.!?])\s*(?=\d{1,3}[.)-]\s+\S)", "\n", normalized)
        normalized = re.sub(r"(?<=\S)\s+(?=\d{1,3}[.)](?=\S))", "\n", normalized)

        # Convert setext headings to ATX headings.
        setext_converted: list[str] = []
        source_lines = normalized.split("\n")
        idx = 0
        while idx < len(source_lines):
            current = source_lines[idx]
            if idx + 1 < len(source_lines):
                underline = source_lines[idx + 1].strip()
                if current.strip() and re.fullmatch(r"=+", underline):
                    setext_converted.append(f"# {current.strip()}")
                    idx += 2
                    continue
                if current.strip() and re.fullmatch(r"-{3,}", underline) and not re.match(r"^\s*[-*+]\s", current):
                    setext_converted.append(f"## {current.strip()}")
                    idx += 2
                    continue
            setext_converted.append(current)
            idx += 1

        healed: list[str] = []
        in_fence = False
        section_mode = ""

        for raw_line in setext_converted:
            if re.fullmatch(r"(?:\*{3,}|-{3,}|_{3,})", raw_line.strip()):
                healed.append("---")
                section_mode = ""
                continue
            expanded = raw_line
            expanded = re.sub(rf"^\s*[{bullet_chars}]\s+", "- ", expanded)
            expanded = re.sub(r"(?<=[^\s#])(?=(?:#{1,6})\s*)", "\n", expanded)
            expanded = re.sub(
                rf"(?i)(?<=[^\n])(?=(?:{section_pattern})\s*[:\-])",
                "\n",
                expanded,
            )
            expanded = re.sub(
                rf"(?i)(?<=[.!?])\s*(?=(?:#{{1,6}}\s*)?(?:{section_pattern})\b)",
                "\n",
                expanded,
            )
            expanded = re.sub(rf"(?<=[.!?])\s*(?:[{bullet_chars}]|\d{{1,3}}[.)-])\s+(?=\S)", "\n- ", expanded)
            expanded = re.sub(rf"(?<!^)(?<!\n)\s+(?={emoji_bullet_pattern}\s+\S)", "\n- ", expanded)

            for part in expanded.split("\n"):
                line = part
                stripped = line.strip()

                if stripped.startswith(("```", "~~~")):
                    in_fence = not in_fence
                    healed.append(line)
                    continue
                if in_fence:
                    healed.append(line)
                    continue
                if re.fullmatch(r"(?:\*{3,}|-{3,}|_{3,})", stripped):
                    healed.append("---")
                    section_mode = ""
                    continue

                line = re.sub(rf"^\s*[{bullet_chars}]\s+", "- ", line)
                line = re.sub(r"^(#{1,6})(?=\S)", r"\1 ", line)
                line = re.sub(r"^#\s+#\s*", "## ", line)
                line = re.sub(r"^([\-+])(?=\S)", r"\1 ", line)
                line = re.sub(r"^\*(?!\*)(?=\S)", "* ", line)
                line = re.sub(r"^(\d+)[)\-](?=\S)", r"\1. ", line)
                line = re.sub(r"^(\d+)[)\-]\s+", r"\1. ", line)
                line = re.sub(r"^(>)(?=\S)", r"\1 ", line)
                line = re.sub(r"^\[([xX ])\]\s+(?=\S)", r"- [\1] ", line)
                line = re.sub(r"(\*\*[^*\n]{1,120}:\*\*)(?=\S)", r"\1 ", line)
                line = re.sub(r"([:;,!?])(?=[A-Za-z])", r"\1 ", line)
                line = rewrite_emphasized_section_label(line)
                def _unglue_token(token: str) -> str:
                    if not token or token.isspace():
                        return token
                    trimmed = token.rstrip(").,;!?")
                    if (
                        trimmed.startswith(("http://", "https://", "www."))
                        or url_pattern.fullmatch(trimmed)
                        or re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#]\S*)?", trimmed)
                    ):
                        return token
                    updated = token
                    updated = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", updated)
                    updated = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", updated)
                    updated = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", updated)
                    updated = re.sub(
                        r"^(of|in|on|at|by|for|from|with|to|into|onto|upon|over|under|during|through|between|before|after|around|across)(the|a|an)([A-Za-z0-9-].*)$",
                        r"\1 \2 \3",
                        updated,
                    )
                    updated = re.sub(
                        r"^(was|were|is|are|be|been|being|has|have|had|does|did|do)(the|a|an)([A-Za-z0-9-].*)$",
                        r"\1 \2 \3",
                        updated,
                    )
                    updated = re.sub(
                        r"^(of|in|on|at|by|for|from|with|to)(the|a|an)$",
                        r"\1 \2",
                        updated,
                    )
                    updated = re.sub(
                        r"^(was|were|is|are|be|been|being|has|have|had|does|did|do)(the|a|an)$",
                        r"\1 \2",
                        updated,
                    )
                    updated = re.sub(
                        r"\b([a-z]{4,})(for|with|from|into|over|under|after|before|between|through|and|or|to|the)\b",
                        r"\1 \2",
                        updated,
                    )
                    updated = re.sub(
                        r"\b([a-z]{4,}(?:s|ed|ing))a\b",
                        r"\1 a",
                        updated,
                    )
                    updated = re.sub(
                        r"\bfor(?=im[a-z]{3,}\b)",
                        "for ",
                        updated,
                    )
                    updated = re.sub(
                        r"\bor(?=self(?:-[a-z]{2,})?\b)",
                        "or ",
                        updated,
                    )
                    updated = re.sub(
                        r"\bto(?=be[a-z]{3,}\b)",
                        "to ",
                        updated,
                    )
                    updated = re.sub(
                        r"\bthe(?=[bcdfghjklmnpqrstvwxyz][a-z]{7,}\b)",
                        "the ",
                        updated,
                    )
                    updated = re.sub(
                        r"^the(new|old|same|next|first|last|other|american|united|electoral|continental|federal|national|presidency|government)([A-Za-z0-9-].*)?$",
                        r"the \1\2",
                        updated,
                    )
                    updated = re.sub(
                        r"^(was|were|is|are|be|been|being|has|have|had|can|could|should|would|will|shall|may|might|must|does|did|do)([a-z]{7,})$",
                        r"\1 \2",
                        updated,
                    )
                    updated = re.sub(r"([A-Za-z][’']s)(?=[A-Za-z]{3,}\b)", r"\1 ", updated)
                    updated = re.sub(r"(?<=[a-z]{3}ly)(?=[a-z]{3,})", " ", updated)
                    return updated

                line = "".join(_unglue_token(token) for token in re.split(r"(\s+)", line))
                line = close_unbalanced_leading_emphasis(line)
                stripped = line.strip()
                lowered = stripped.lower()

                if re.fullmatch(r"(?:\*{3,}|-{3,}|_{3,})", stripped):
                    healed.append("---")
                    section_mode = ""
                    continue

                if lowered in section_label_modes:
                    canonical = canonical_section.get(lowered, lowered)
                    heading = section_headings.get(canonical, " ".join(word.capitalize() for word in canonical.split()))
                    healed.append(f"## {heading}")
                    section_mode = canonical
                    continue

                match = re.match(
                    rf"(?i)^(?:#{{1,6}}\s*)?({section_pattern})\s*[:\-]?\s*(.+)?$",
                    stripped,
                )
                if match and stripped:
                    label = match.group(1).lower()
                    canonical = canonical_section.get(label, label)
                    content = (match.group(2) or "").strip()
                    heading = section_headings.get(canonical, " ".join(word.capitalize() for word in canonical.split()))
                    healed.append(f"## {heading}")
                    if content:
                        if canonical in {"key points", "takeaway", "next steps"}:
                            healed.append(f"- {content}")
                        else:
                            healed.append(content)
                    section_mode = canonical
                    continue

                if stripped.startswith("## "):
                    label = stripped[3:].strip().lower()
                    canonical = canonical_section.get(label, label)
                    section_mode = canonical if canonical in section_label_modes else ""
                elif stripped.startswith("#"):
                    section_mode = ""

                if stripped == "":
                    healed.append("")
                    continue

                inline_items = re.split(
                    rf"(?:^|(?<=[.!?]))\s*(?:[{bullet_chars}]|\d{{1,3}}[.)-])\s+(?=\S)",
                    stripped,
                )
                inline_items = [segment.strip() for segment in inline_items if segment.strip()]
                if (
                    section_mode in {"key points", "takeaway", "next steps"}
                    and len(inline_items) > 1
                    and not stripped.startswith((">", "#", "```"))
                ):
                    for segment in inline_items:
                        healed.append(f"- {segment}")
                    continue

                is_list_item = bool(re.match(r"^(?:[-*+]\s|\d+\.\s)", stripped))
                if section_mode in {"key points", "takeaway", "next steps"} and not is_list_item and not stripped.startswith((">", "#")):
                    if ":" in stripped or stripped.startswith(("**", "[x]", "[X]", "[ ]")) or section_mode == "takeaway":
                        line = f"- {stripped}"
                elif re.match(rf"^(?:Pros|Cons|Pro|Con|Final Thought|Takeaway)\s*:\s*{emoji_bullet_pattern}\s+", stripped, flags=re.IGNORECASE):
                    line = f"- {stripped}"
                elif re.match(rf"^{emoji_bullet_pattern}\s+\S", stripped):
                    line = f"- {stripped}"
                healed.append(line)

        cleaned = [line for line in healed if not re.fullmatch(r"#{1,6}", line.strip())]
        collapsed: list[str] = []
        blank_count = 0
        for line in cleaned:
            stripped_line = line.strip()
            if re.fullmatch(r"-\s*(?:\*\*|__)?\s*", stripped_line):
                continue
            if stripped_line in {"**", "__", "- **", "- __"}:
                continue
            if line.strip() == "":
                blank_count += 1
                if blank_count > 2:
                    continue
            else:
                blank_count = 0
            collapsed.append(line)

        renumbered: list[str] = []
        ordered_index = 1
        for line in collapsed:
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "---":
                ordered_index = 1
                renumbered.append(line)
                continue
            match = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
            if match:
                renumbered.append(f"{match.group(1)}{ordered_index}. {match.group(2)}")
                ordered_index += 1
                continue
            renumbered.append(line)

        nested_spaced: list[str] = []
        parent_allows_subpoints = False
        for line in renumbered:
            stripped = line.strip()
            if not stripped:
                nested_spaced.append(line)
                continue
            if stripped.startswith("#") or stripped == "---":
                parent_allows_subpoints = False
                nested_spaced.append(line)
                continue
            bullet_match = re.match(r"^(\s*)-\s+(.+)$", line)
            if bullet_match:
                indent, content = bullet_match.groups()
                content_starts_topic = bool(re.match(r"^(?:\*\*|__)[^*_]{1,90}(?:\*\*|__)\s*[:\-]?", content))
                topic_text = re.sub(r"^(?:\*\*|__)([^*_]{1,120})(?:\*\*|__).*$", r"\1", content).strip()
                if parent_allows_subpoints and not indent and not content_starts_topic:
                    nested_spaced.append(f"  - {content}")
                    continue
                nested_spaced.append(line)
                parent_allows_subpoints = content.rstrip().endswith(":") or topic_text.endswith(":")
                continue
            parent_allows_subpoints = False
            nested_spaced.append(line)

        section_spaced: list[str] = []
        for line in nested_spaced:
            stripped = line.strip()
            if stripped.startswith("#") and section_spaced and section_spaced[-1].strip():
                section_spaced.append("")
            section_spaced.append(line)

        result = "\n".join(section_spaced)
        for token, image_markdown in protected_images.items():
            result = result.replace(token, image_markdown)
        if trailing_newline and not result.endswith("\n"):
            result += "\n"
        return result

    def _split_stream_chunks(self, markdown_text: str) -> list[str]:
        if self._stream_mode == "characters":
            return list(markdown_text)
        if self._stream_mode == "lines":
            return markdown_text.splitlines(keepends=True)
        return re.findall(r"\S+\s*", markdown_text)

    def _compose_stream_markdown(self, chunks: list[str], count: int) -> str:
        text = "".join(chunks[:count])
        return text

    def _render_commit_interval(self) -> float:
        if self._stream_mode == "characters":
            base_interval = 1.0 / 30.0
        elif self._stream_units_per_second >= 85.0:
            base_interval = 1.0 / 30.0
        elif self._stream_units_per_second >= 45.0:
            base_interval = 1.0 / 34.0
        else:
            base_interval = 1.0 / 40.0
        budget_interval = max(1.0 / 60.0, min(0.11, (self._render_cost_ema_ms * 1.65) / 1000.0))
        return max(base_interval, budget_interval)

    def _fade_restart_interval(self) -> float:
        if self._stream_units_per_second >= 90.0:
            return 0.18
        if self._stream_units_per_second >= 60.0:
            return 0.15
        if self._stream_units_per_second >= 30.0:
            return 0.12
        return 0.1

    @staticmethod
    def _compute_changed_span(previous: str, current: str) -> tuple[int, int] | None:
        if previous == current:
            return None
        max_prefix = min(len(previous), len(current))
        prefix = 0
        while prefix < max_prefix and previous[prefix] == current[prefix]:
            prefix += 1
        prev_suffix = len(previous)
        curr_suffix = len(current)
        while prev_suffix > prefix and curr_suffix > prefix and previous[prev_suffix - 1] == current[curr_suffix - 1]:
            prev_suffix -= 1
            curr_suffix -= 1
        if curr_suffix <= prefix:
            return None
        return prefix, curr_suffix

    def _flush_stream_tick(self) -> None:
        self._stream_timer.stop()

    def complete_stream(self) -> None:
        if self._target_markdown or self._last_markdown:
            self.set_markdown(self._target_markdown or self._last_markdown)

    def ensure_stream_progress(self) -> None:
        if self._target_markdown or self._last_markdown:
            self.set_markdown(self._target_markdown or self._last_markdown)

    def _set_fade_span_alpha(self, start: int, end: int, alpha: int) -> None:
        document = self.body.document()
        max_pos = max(0, document.characterCount() - 1)
        if start < 0:
            start = 0
        if start > max_pos:
            return
        end = min(end, max_pos)
        if end <= start:
            return
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(26, 26, 26, max(0, min(255, alpha))))
        cursor.mergeCharFormat(fmt)

    def _stop_char_fades(self) -> None:
        for animation, _start, _end in self._active_char_fades:
            animation.stop()
        self._active_char_fades.clear()

    def _animate_new_text_fade(self, start: int, end: int) -> None:
        if end <= start:
            return
        app = QApplication.instance()
        if app is not None and bool(app.property("reducedMotion")):
            return
        animation = QVariantAnimation(self)
        animation.setDuration(400)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(120)
        animation.setEndValue(255)
        animation.valueChanged.connect(
            lambda value, span_start=start, span_end=end: self._set_fade_span_alpha(span_start, span_end, int(value))
        )

        def _finalize(span_start: int = start, span_end: int = end, current_animation: QVariantAnimation = animation) -> None:
            self._set_fade_span_alpha(span_start, span_end, 255)
            self._active_char_fades[:] = [
                (fade_animation, fade_start, fade_end)
                for fade_animation, fade_start, fade_end in self._active_char_fades
                if fade_animation is not current_animation
            ]
            current_animation.deleteLater()

        animation.finished.connect(_finalize)
        self._active_char_fades.append((animation, start, end))
        self._set_fade_span_alpha(start, end, 120)
        animation.start()

    def _sync_size(self, force_minimum: bool = False, animated: bool = True) -> None:
        if self._syncing_size:
            return
        if getattr(self, "_wiki_entry_morphing", False):
            return
        parent = self.parentWidget()
        if parent is None:
            return
        if self._wiki_entry_active:
            width = min(760, max(420, parent.width() - 120))
            height = 162
            self.setFixedWidth(width)
            target_rect = QRect(QPoint(max(16, (parent.width() - width) // 2), max(72, int(parent.height() * 0.22))), QSize(width, height))
            if self.isVisible() and self.height() > height:
                target_rect.moveTop(self.y())
            self._size_animation.stop()
            self.setGeometry(target_rect)
            self._layout_overlay_elements()
            self.raise_()
            return
        self._syncing_size = True
        try:
            width = self._target_width()
            if width <= 0:
                return
            self.setFixedWidth(width)
            root_margins = self.layout().contentsMargins()
            surface_margins = self.surface.layout().contentsMargins()
            viewport_width = max(
                240,
                width - root_margins.left() - root_margins.right() - surface_margins.left() - surface_margins.right(),
            )
            self.body.setMinimumWidth(viewport_width)
            if self._wiki_short_summary_text.strip():
                desired_summary_height = self._desired_summary_region_height()
                self._wiki_summary_region_target_height = desired_summary_height
                if (
                    self._wiki_summary_region_current_height > 0
                    and self._wiki_short_summary_expansion_animation is None
                    and desired_summary_height != self._wiki_summary_region_current_height
                ):
                    self._set_summary_region_height(desired_summary_height)
            document_layout = self.body.document().documentLayout()
            if document_layout is not None:
                doc_height = int(document_layout.documentSize().height())
            else:
                doc_height = int(self.body.document().size().height())
            skeleton_height = self.skeleton.preferred_height(viewport_width)
            compact_height = 90
            minimum_height = compact_height
            max_height = max(minimum_height, int(parent.height() * 0.7))
            collapsed_height = max(minimum_height, int(max_height * 0.5))
            header_height = 36
            summary_height = self._wiki_summary_region_current_height
            summary_layout_height = summary_height + ((self.surface.layout().spacing() + 2) if summary_height > 0 else 0)
            if self.response_stack.currentWidget() is self.skeleton:
                body_height = skeleton_height + header_height + surface_margins.top() + surface_margins.bottom() + 24
            else:
                body_height = doc_height + header_height + surface_margins.top() + surface_margins.bottom() + 24
            total_height = compact_height if force_minimum or not self._streaming_started else max(compact_height, body_height + root_margins.top() + root_margins.bottom())
            expanded_height = min(max_height, total_height)
            if force_minimum:
                final_height = minimum_height
            else:
                # The summary region is extra top space. It must not steal height
                # from the existing tab/content section.
                final_height = max(collapsed_height, expanded_height) + summary_layout_height
            available_body_height = max(
                96,
                final_height
                - root_margins.top()
                - root_margins.bottom()
                - surface_margins.top()
                - surface_margins.bottom()
                - header_height
                - summary_layout_height
                - 24,
            )
            # Constrain the shared response host viewport instead of the text browser
            # itself to avoid clipped-content/scroll-range mismatches.
            self.response_host.setMinimumHeight(available_body_height)
            self.response_host.setMaximumHeight(available_body_height)
            self.body.setMinimumHeight(0)
            self.body.setMaximumHeight(16777215)
            if self.response_stack.currentWidget() is self.skeleton:
                self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            else:
                # Let QTextBrowser decide overflow from actual rendered layout.
                # Estimated doc height can be stale and incorrectly hide scroll.
                self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            target_rect = QRect(self._target_pos(), QSize(width, final_height))
            if self._size_anchor_bottom is not None:
                target_rect.moveBottom(self._size_anchor_bottom)
            if not self.isVisible() or force_minimum or not animated:
                self._size_animation.stop()
                self.setGeometry(target_rect)
            else:
                current_rect = self.geometry()
                if current_rect == target_rect:
                    return
                if self._size_animation.state() == QAbstractAnimation.State.Running:
                    end_rect = self._size_animation.endValue()
                    if isinstance(end_rect, QRect) and end_rect == target_rect:
                        return
                self._size_animation.stop()
                self._size_animation.setStartValue(current_rect)
                self._size_animation.setEndValue(target_rect)
                self._size_animation.start()
            self._layout_overlay_elements()
            self.raise_()
        finally:
            self._syncing_size = False

    def _refresh_body_metrics_from_viewport(self) -> None:
        if self.response_stack.currentWidget() is not self.body_container:
            return
        viewport = self.body.viewport().width()
        if viewport <= 0:
            return
        self._force_scroll_metrics(reset_to_top=False)

    def _force_scroll_metrics(self, *, reset_to_top: bool) -> None:
        if self.response_stack.currentWidget() is not self.body_container:
            return
        viewport_width = self.body.viewport().width()
        viewport_height = self.body.viewport().height()
        if viewport_width <= 0 or viewport_height <= 0:
            return
        document = self.body.document()
        document.setTextWidth(max(1, viewport_width))
        document.adjustSize()
        doc_layout = document.documentLayout()
        if doc_layout is not None:
            doc_height = int(math.ceil(doc_layout.documentSize().height()))
        else:
            doc_height = int(math.ceil(document.size().height()))
        bar = self.body.verticalScrollBar()
        if bar is None:
            return
        previous_value = 0 if reset_to_top else bar.value()
        max_value = max(0, doc_height - viewport_height)
        bar.setRange(0, max_value)
        bar.setPageStep(max(1, viewport_height))
        bar.setSingleStep(24)
        bar.setValue(max(0, min(previous_value, max_value)))

    def _target_width(self) -> int:
        parent = self.parentWidget()
        if parent is None:
            return 0
        available = max(360, parent.width() - 80)
        return min(872, available)

    def _target_pos(self) -> QPoint:
        parent = self.parentWidget()
        if parent is None:
            return QPoint(0, 0)
        if self._manual_pos is not None:
            return self._manual_pos
        x = max(16, (parent.width() - self.width()) // 2)
        y = self._anchor_y if self._anchor_y is not None else max(72, int(parent.height() * 0.16))
        return QPoint(x, y)


class StartStudyDialog(QDialog):
    def __init__(self, path_label: str, count: int) -> None:
        super().__init__()
        self.setWindowTitle("Start study")
        self.setFixedSize(420, 220)

        layout = QVBoxLayout(self)
        title = QLabel("Start studying from this section?")
        title.setObjectName("SectionTitle")
        text = QLabel(f"Path: {path_label}\nCards available: {count}")
        text.setObjectName("SectionText")
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = AnimatedButton("Cancel")
        start = AnimatedButton("Start")
        start.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        start.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(start)
        layout.addLayout(actions)


class MoveCardDialog(QDialog):
    def __init__(self, card: dict, datastore: DataStore) -> None:
        super().__init__()
        self.card = card
        self.datastore = datastore
        self.selected_path = {
            "subject": card.get("subject", "Mathematics"),
            "category": card.get("category", "All"),
            "subtopic": card.get("subtopic", "All"),
        }

        self.setWindowTitle("Move card")
        self.setFixedSize(520, 620)

        layout = QVBoxLayout(self)
        title = QLabel("Choose the new subject path for this card.")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Subject path"])
        self.tree.itemClicked.connect(self._select_path)
        layout.addWidget(self.tree, 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        cancel = AnimatedButton("Cancel")
        move = AnimatedButton("Move")
        move.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        move.clicked.connect(self._move)
        action_row.addWidget(cancel)
        action_row.addWidget(move)
        layout.addLayout(action_row)

        self._build_tree()

    def _build_tree(self) -> None:
        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([subject])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            self.tree.addTopLevelItem(subject_item)

            all_item = QTreeWidgetItem([f"{subject} / All"])
            all_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            subject_item.addChild(all_item)

            for category in details.get("core", []):
                category_item = QTreeWidgetItem([f"{subject} / {category}"])
                category_item.setData(0, Qt.UserRole, {"subject": subject, "category": category, "subtopic": "All"})
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    sub_item = QTreeWidgetItem([f"{subject} / {category} / {subtopic}"])
                    sub_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(sub_item)
        self.tree.collapseAll()

    def _select_path(self, item: QTreeWidgetItem) -> None:
        self.selected_path = item.data(0, Qt.UserRole)

    def _move(self) -> None:
        result = self.datastore.move_card(
            self.card["id"],
            self.card.get("subject", "Mathematics"),
            self.selected_path["subject"],
            self.selected_path,
        )
        if result is None:
            QMessageBox.warning(self, "Move failed", "Could not move that card.")
            return
        self.accept()


class ReinforcementProgressDialog(QDialog):
    def __init__(self, icons: IconHelper) -> None:
        super().__init__()
        self.setWindowTitle("Preparing reinforcement")
        self.setFixedSize(460, 300)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("Preparing reinforcement cards")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("ONCard is building a short targeted practice block for the weak topic.")
        subtitle.setObjectName("SectionText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.status_label = QLabel("Waiting to start...")
        self.status_label.setObjectName("SmallMeta")
        layout.addWidget(self.status_label)

        self._done_icon = icons.icon("common", "complete_green_circle", "O").pixmap(18, 18)
        self._pending_icon = icons.icon("common", "pending_red_circle", ".").pixmap(18, 18)

        for key, label_text in [
            ("creating", "Creating questions"),
            ("filling", "Filling cards"),
            ("embedding", "Embedding temporary cards"),
            ("adding", "Adding to session"),
        ]:
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(self._pending_icon)
            text_label = QLabel(label_text)
            text_label.setObjectName("SectionText")
            row.addWidget(icon_label)
            row.addWidget(text_label, 1)
            layout.addLayout(row)
            self.rows[key] = (icon_label, text_label)

    def update_step(self, key: str, message: str, done: bool) -> None:
        self.status_label.setText(message)
        row = self.rows.get(key)
        if row is None:
            return
        icon_label, _text_label = row
        icon_label.setPixmap(self._done_icon if done else self._pending_icon)


class SessionPrepDialog(QDialog):
    def __init__(self, icons: IconHelper) -> None:
        super().__init__()
        self.setWindowTitle("Preparing study session")
        self.setFixedSize(460, 308)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("Preparing your study session")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("ONCard is getting the next study block ready.")
        subtitle.setObjectName("SectionText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.status_label = QLabel("Waiting to start...")
        self.status_label.setObjectName("SmallMeta")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self._done_icon = icons.icon("common", "complete_green_circle", "O").pixmap(18, 18)
        self._pending_icon = icons.icon("common", "pending_red_circle", ".").pixmap(18, 18)

        for key, label_text in [
            ("seed", "Preparing seed cards"),
            ("topics", "Building topic links"),
            ("launch", "Starting study"),
        ]:
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(self._pending_icon)
            text_label = QLabel(label_text)
            text_label.setObjectName("SectionText")
            row.addWidget(icon_label)
            row.addWidget(text_label, 1)
            layout.addLayout(row)
            self.rows[key] = (icon_label, text_label)

    def update_step(self, key: str, message: str, done: bool) -> None:
        self.status_label.setText(message)
        row = self.rows.get(key)
        if row is None:
            return
        icon_label, _text_label = row
        icon_label.setPixmap(self._done_icon if done else self._pending_icon)

    def set_progress(self, value: int) -> None:
        self.progress_bar.setValue(max(0, min(100, int(value))))


class SessionPrepWorker(QThread):
    progress = Signal(str, str, str, int, int, bool)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        session_id: str,
        cards: list[dict],
        seed_cards: list[dict],
        embedding_service: EmbeddingService,
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.cards = list(cards)
        self.seed_cards = list(seed_cards)
        self.embedding_service = embedding_service

    def run(self) -> None:
        try:
            total_seed = max(1, len(self.seed_cards))
            if not self.seed_cards:
                self.progress.emit(self.session_id, "seed", "Seed cards already had embeddings.", 1, 1, True)
            else:
                self.progress.emit(self.session_id, "seed", "Checking seed card embeddings...", 0, total_seed, False)
                for index, card in enumerate(self.seed_cards, start=1):
                    if self.isInterruptionRequested():
                        return
                    label = str(card.get("title") or card.get("question") or "Card").strip() or "Card"
                    self.progress.emit(
                        self.session_id,
                        "seed",
                    f"Embedding seed cards... ({index}/{total_seed}) {label}",
                    index,
                    total_seed,
                    False,
                )
                self.embedding_service.ensure_card_embedding(card)
                self.progress.emit(self.session_id, "seed", "Seed cards are ready.", total_seed, total_seed, True)

            if self.isInterruptionRequested():
                return
            self.progress.emit(self.session_id, "topics", "Building topic links from the seed set...", 0, 1, False)
            cluster_map = self.embedding_service.topic_clusters(self.cards)
            if self.isInterruptionRequested():
                return
            self.progress.emit(self.session_id, "topics", "Topic links are ready.", 1, 1, True)
            self.progress.emit(self.session_id, "launch", "Study session ready.", 1, 1, True)
            self.finished.emit(self.session_id, cluster_map)
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class TopicClusterWorker(QThread):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, *, session_id: str, cards: list[dict], embedding_service: EmbeddingService) -> None:
        super().__init__()
        self.session_id = session_id
        self.cards = list(cards)
        self.embedding_service = embedding_service

    def run(self) -> None:
        try:
            cluster_map = self.embedding_service.topic_clusters(self.cards)
            if self.isInterruptionRequested():
                return
            self.finished.emit(self.session_id, cluster_map)
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class CardSearchWorker(QThread):
    finished = Signal(int, str, object)

    def __init__(
        self,
        *,
        request_id: int,
        query: str,
        cards: list[dict],
        embedding_service: EmbeddingService,
        limit: int,
        allow_semantic: bool,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.query = query
        self.cards = cards
        self.embedding_service = embedding_service
        self.limit = limit
        self.allow_semantic = allow_semantic

    def run(self) -> None:
        query = self.query.strip()
        if not query:
            self.finished.emit(self.request_id, query, [])
            return
        scored = StudyTab._build_card_search_results(
            query,
            self.cards,
            self.embedding_service,
            limit=self.limit,
            allow_semantic=self.allow_semantic,
        )
        self.finished.emit(self.request_id, query, scored)


class ImageCardSearchWorker(QThread):
    finished = Signal(int, str, object)

    def __init__(
        self,
        *,
        request_id: int,
        queries: list[str],
        cards: list[dict],
        embedding_service: EmbeddingService,
        limit: int,
        allow_semantic: bool,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.queries = [" ".join(str(query or "").strip().split()) for query in queries if str(query or "").strip()]
        self.cards = list(cards)
        self.embedding_service = embedding_service
        self.limit = limit
        self.allow_semantic = allow_semantic

    def run(self) -> None:
        if not self.queries:
            self.finished.emit(self.request_id, "", [])
            return
        merged: dict[str, dict] = {}
        rank = 0
        for query in self.queries:
            scored = StudyTab._build_card_search_results(
                query,
                self.cards,
                self.embedding_service,
                limit=self.limit,
                allow_semantic=self.allow_semantic,
            )
            for item in scored:
                if not isinstance(item, dict) or not isinstance(item.get("card"), dict):
                    continue
                card = item["card"]
                card_id = str(card.get("id", "")).strip() or str(id(card))
                score = float(item.get("score", 0.0) or 0.0)
                source = str(item.get("source", "")).strip()
                current = merged.get(card_id)
                if current is None or score > float(current.get("score", 0.0) or 0.0):
                    merged[card_id] = {"card": card, "score": score, "source": source or "image", "_rank": rank}
                rank += 1

        keyword_query = " ".join(self.queries)
        for card in StudyTab._fallback_text_search(keyword_query, self.cards)[: self.limit]:
            card_id = str(card.get("id", "")).strip() or str(id(card))
            if card_id not in merged:
                merged[card_id] = {"card": card, "score": 0.0, "source": "image-keyword", "_rank": rank}
                rank += 1

        results = list(merged.values())
        results.sort(key=lambda item: (float(item.get("score", 0.0) or 0.0), -int(item.get("_rank", 0))), reverse=True)
        for item in results:
            item.pop("_rank", None)
        self.finished.emit(self.request_id, keyword_query, results[: self.limit])


class StudyTab(QWidget):
    CARD_RENDER_BATCH_SIZE = 24
    CARD_INITIAL_STREAM_BATCH = 8
    CARD_STREAM_BATCH_SIZE = 8
    CARD_SUGGESTION_DEBOUNCE_MS = 80
    CARD_SUGGESTION_IDLE_COLLAPSE_MS = 6000
    CARD_GHOST_FULL_ACCEPT_MS = 750
    CARD_GHOST_AUTO_SEARCH_MS = 850
    CARD_SEARCH_SKELETON_MIN_CYCLES = 2
    CARDS_TOOLBAR_CONTROL_HEIGHT = 40
    CARDS_TOOLBAR_SHELL_HEIGHT = 50
    CARDS_TOOLBAR_ACTION_WIDTH = 88
    AI_TRIGGER_TOKENS = {"/ai": "ai", "#ai": "ai", "/wiki": "wiki"}

    @staticmethod
    def _card_expected_answer(card: dict, datastore=None, model_tag: str = "") -> str:
        answer = str(card.get("answer", "")).strip()
        if answer:
            return answer
        try:
            mcq_answers = normalize_mcq_answers(card.get("mcq_answers", []))
        except ValueError:
            mcq_answers = []
        if mcq_answers:
            return mcq_answers[0]
        if datastore is not None and model_tag:
            try:
                cached = cached_mcq_payload(datastore, card, model_tag)
            except Exception:
                cached = None
            if isinstance(cached, dict):
                return str(cached.get("correct_answer", "")).strip()
        return ""

    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        preflight: ModelPreflightService | None = None,
    ) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.preflight = preflight or ModelPreflightService(datastore, ollama)
        self.current_subject = "All Subjects"
        self.current_category = "All"
        self.current_subtopic = "All"
        self.cards: list[dict] = []
        self.current_card: dict | None = None
        self.embedding_service = EmbeddingService(datastore, ollama)
        self.study_state: StudySessionState | None = None
        self.session_id = ""
        self.session_queue: list[dict] = []
        self.session_cards: list[dict] = []
        self.session_scores: list[float] = []
        self.session_temp_batches: dict[str, dict] = {}
        self.current_attempt_logged = False
        self.session_history: list[dict] = []
        self.current_history_index = -1
        self.revealed_hints = 0
        self.hint_cooldown = 0
        self.sidebar_expanded = True
        self.grade_worker: GradeWorker | None = None
        self.queued_grade_worker: GradeWorker | None = None
        self.followup_worker: FollowUpWorker | None = None
        self.embedding_worker: EmbeddingWorker | None = None
        self.reinforcement_worker: ReinforcementWorker | None = None
        self.reinforcement_embedding_worker: EmbeddingWorker | None = None
        self.session_prep_worker: SessionPrepWorker | None = None
        self.topic_cluster_worker: TopicClusterWorker | None = None
        self.card_search_worker: CardSearchWorker | None = None
        self.image_card_search_worker: ImageCardSearchWorker | None = None
        self.ai_query_planner_worker: AiSearchPlannerWorker | None = None
        self.ai_query_answer_worker: AiSearchAnswerWorker | None = None
        self.ai_query_tool_worker: CardSearchWorker | None = None
        self.wiki_breakdown_worker: WikipediaBreakdownWorker | None = None
        self.wiki_images_worker: WikipediaImagesWorker | None = None
        self.image_search_terms_worker: ImageSearchTermsWorker | None = None
        self._ai_query_workers: set[QThread] = set()
        self._pending_ai_query_plans: dict[int, dict] = {}
        self._wiki_gallery_images: list[dict] = []
        self._wiki_gallery_title = ""
        self._wiki_gallery_loading = False
        self.ai_query_image_path = ""
        self.session_prep_dialog: SessionPrepDialog | None = None
        self.reinforcement_dialog: ReinforcementProgressDialog | None = None
        self.ai_response_overlay: AiResponseOverlay | None = None
        self.ai_query_history: list[str] = []
        self.ai_query_history_index = 0
        self.pending_reinforcement_cards: list[dict] = []
        self.pending_reinforcement_cluster_key = ""
        self.session_prep_remaining_cards: list[dict] = []
        self.pending_cluster_refresh = False
        self.last_grade_report: dict | None = None
        self.session_end_requested = False
        self.card_search_query = ""
        self.card_search_suggestions: list[dict] = []
        self.card_search_full_results: list[dict] = []
        self.card_search_result_limit = 8
        self.card_render_limit = self.CARD_RENDER_BATCH_SIZE
        self.card_search_last_scores: list[float] = []
        self.card_search_has_executed = False
        self.card_search_loading = False
        self.card_search_skeleton_cycles = 0
        self.pending_card_search_results: tuple[int, str, list] | None = None
        self.card_search_request_id = 0
        self.card_search_dropdown_collapsed_by_idle = False
        self.card_search_ghost_text = ""
        self.card_search_last_tab_at = 0.0
        self.card_search_term_cache: list[tuple[str, str, str, str, str]] = []
        self.ai_query_request_id = 0
        self.card_search_no_close_match = False
        self.global_recommendations: list[RecommendedCard] = []
        self._recommendation_signature: tuple[int, int] | None = None
        self._card_search_animations: list[QParallelAnimationGroup] = []
        self._card_search_workers: list[CardSearchWorker] = []
        self.queued_grade_indexes: list[int] = []
        self.active_queue_entry_index = -1
        self.cards_dirty = True
        self.cards_loaded_once = False
        self._card_stream_generation = 0
        self._card_stream_cards: list[dict] = []
        self._card_stream_columns = 1
        self._card_stream_tile_width = 336
        self._card_stream_next_index = 0
        self._card_stream_animate = False
        self._last_render_layout_signature: tuple[int, int] | None = None
        self._post_reload_generation = 0

        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._tick_hint_cooldown)
        self.card_search_timer = QTimer(self)
        self.card_search_timer.setSingleShot(True)
        self.card_search_timer.timeout.connect(self._request_card_suggestions)
        self.card_search_idle_collapse_timer = QTimer(self)
        self.card_search_idle_collapse_timer.setSingleShot(True)
        self.card_search_idle_collapse_timer.timeout.connect(self._collapse_card_suggestions_after_idle)
        self.card_layout_timer = QTimer(self)
        self.card_layout_timer.setSingleShot(True)
        self.card_layout_timer.timeout.connect(self._rerender_cards_for_layout_change)
        self.card_stream_timer = QTimer(self)
        self.card_stream_timer.setSingleShot(True)
        self.card_stream_timer.timeout.connect(self._render_next_card_batch)
        self._followup_thinking_text = "Thinking"
        self._followup_thinking_steps: list[str] = []
        self._followup_thinking_angle = 0.0
        self._followup_thinking_last_tick = 0.0
        self._followup_autoscroll_enabled = True
        self._followup_programmatic_scroll = False
        self._followup_last_rendered_plain = ""
        self._followup_char_fades: list[tuple[QVariantAnimation, int, int]] = []
        self._followup_thinking_timer = QTimer(self)
        self._followup_thinking_timer.setInterval(16)
        self._followup_thinking_timer.timeout.connect(self._render_followup_thinking_status)

        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.followup_model_menu = FollowUpModelMenu(self)
        self.followup_model_menu.selectionChanged.connect(self._on_followup_selection_changed)
        self.ai_response_overlay = AiResponseOverlay(self.icons, self)
        self.ai_response_overlay.closed.connect(self._close_ai_overlay)
        self.ai_response_overlay.wikiSearchRequested.connect(self._submit_wiki_query)
        self.reload_cards()

    def _play_sound(self, name: str) -> None:
        parent = self.window()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play(name)

    def _active_text_llm_spec(self):
        return resolve_active_text_llm_spec(self.datastore.load_ai_settings())

    def _active_text_model_tag(self) -> str:
        return resolve_active_text_model_tag(self.datastore.load_ai_settings())

    def _feature_text_llm_spec(self, feature_key: str):
        return resolve_feature_text_llm_spec(self.datastore.load_ai_settings(), feature_key)

    def _feature_text_model_tag(self, feature_key: str) -> str:
        return resolve_feature_text_model_tag(self.datastore.load_ai_settings(), feature_key)

    def _neural_acceleration_enabled(self) -> bool:
        return bool(self.datastore.load_ai_settings().get("neural_acceleration", True))

    def _model_tag_for_key(self, model_key: str) -> str:
        ai_settings = self.datastore.load_ai_settings()
        if bool(ai_settings.get("ollama_cloud_enabled", False)):
            cloud_tag = str(ai_settings.get("ollama_cloud_selected_model_tag", "")).strip()
            if cloud_tag:
                return cloud_tag
        spec = MODELS.get(model_key)
        return spec.primary_tag if spec is not None else self._active_text_model_tag()

    def _feature_model_tag_for_key(self, model_key: str, feature_key: str) -> str:
        ai_settings = self.datastore.load_ai_settings()
        if str(ai_settings.get(feature_model_setting_key(feature_key), "")).strip() == str(model_key or "").strip():
            spec = MODELS.get(model_key)
            return spec.primary_tag if spec is not None else self._feature_text_model_tag(feature_key)
        return self._model_tag_for_key(model_key)

    def _followup_reasoning_mode(self) -> str:
        value = str(self.datastore.load_ai_settings().get("followup_reasoning_mode", "instant")).strip().lower()
        return "think" if value == "think" else "instant"

    def _followup_model_key(self) -> str:
        settings = self.datastore.load_ai_settings()
        explicit = str(settings.get("followup_model_key", "")).strip()
        if explicit in non_embedding_llm_keys():
            return explicit
        return self._feature_text_llm_spec("followup_context_length").key

    def _followup_model_display_name(self) -> str:
        settings = self.datastore.load_ai_settings()
        if bool(settings.get("ollama_cloud_enabled", False)):
            tag = str(settings.get("ollama_cloud_selected_model_tag", "")).strip()
            if tag:
                return cloud_label_for_model_tag(tag).replace(" (Cloud)", "")
        return FollowUpModelMenu.display_name_for_key(self._followup_model_key())

    def _sync_followup_model_button(self) -> None:
        button = getattr(self, "followup_model_btn", None)
        if isinstance(button, FollowUpModelButton):
            button.set_state(self._followup_model_display_name(), "Think" if self._followup_reasoning_mode() == "think" else "Instant")

    def _on_followup_selection_changed(self, model_key: str, reasoning: str) -> None:
        settings = self.datastore.load_ai_settings()
        if model_key:
            settings["followup_model_key"] = model_key
        if reasoning:
            settings["followup_reasoning_mode"] = "think" if reasoning == "think" else "instant"
        self.datastore.save_ai_settings(settings)
        self._sync_followup_model_button()

    def _toggle_followup_model_menu(self) -> None:
        menu = getattr(self, "followup_model_menu", None)
        button = getattr(self, "followup_model_btn", None)
        if not isinstance(menu, FollowUpModelMenu) or not isinstance(button, QWidget):
            return
        if menu.isVisible():
            menu.close_animated()
            return
        menu.show_below(button)

    def _close_followup_model_menu_if_outside(self, global_pos: QPoint) -> None:
        menu = getattr(self, "followup_model_menu", None)
        button = getattr(self, "followup_model_btn", None)
        if not isinstance(menu, FollowUpModelMenu) or not menu.isVisible():
            return
        if menu.geometry().contains(self.mapFromGlobal(global_pos)):
            return
        if isinstance(button, QWidget) and button.rect().contains(button.mapFromGlobal(global_pos)):
            return
        menu.close_animated()

    def _build_followup_controls(self, right_layout: QVBoxLayout, *, hidden: bool = True) -> None:
        self.followup_title = QLabel("Follow up on this card")
        self.followup_title.setObjectName("SectionTitle")
        self.followup_title.hide()
        self.followup_shell = FollowUpPromptShell()
        self.followup_shell_layout = QVBoxLayout(self.followup_shell)
        self.followup_shell_layout.setContentsMargins(16, 14, 12, 10)
        self.followup_shell_layout.setSpacing(8)
        self.followup_input = PromptTextEdit()
        self.followup_input.setPlaceholderText("Ask about your question")
        self.followup_input.setMinimumHeight(92)
        self.followup_input.setFrameShape(QFrame.Shape.NoFrame)
        self.followup_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.followup_input.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.followup_input.setStyleSheet(
            """
            QTextEdit {
                background: transparent;
                border: none;
                border-radius: 0px;
                padding: 2px 2px 0 2px;
                font-size: 15px;
                color: #274155;
            }
            QTextEdit:focus {
                border: none;
                background: transparent;
            }
            """
        )
        self.followup_input.submitted.connect(self._run_followup)
        self.followup_input.installEventFilter(self)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.followup_model_btn = FollowUpModelButton()
        self.followup_model_btn.clickedModel.connect(self._toggle_followup_model_menu)
        self.followup_model_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.followup_btn = AnimatedToolButton()
        self.followup_btn.setIcon(self.icons.icon("common", "send", "S"))
        self.followup_btn.setIconSize(QSize(18, 18))
        self.followup_btn.setFixedSize(34, 34)
        self.followup_btn.setCursor(Qt.PointingHandCursor)
        self.followup_btn.setToolTip("Send")
        self.followup_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.followup_btn.setStyleSheet(
            """
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 9px;
                padding: 7px;
            }
            QToolButton:hover {
                background: rgba(166, 182, 198, 0.1);
            }
            """
        )
        self.followup_btn.clicked.connect(lambda _checked=False: self._run_followup())
        footer.addWidget(self.followup_model_btn, 0, Qt.AlignmentFlag.AlignLeft)
        footer.addStretch(1)
        footer.addWidget(self.followup_btn, 0)
        self.followup_footer = QWidget()
        self.followup_footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.followup_footer.setStyleSheet("background: transparent; border: none;")
        self.followup_footer.setLayout(footer)
        self.followup_shell_layout.addWidget(self.followup_input, 1)
        self.followup_shell_layout.addWidget(self.followup_footer)
        if hidden:
            self.followup_shell.hide()
        self._sync_followup_model_button()
        right_layout.addWidget(self.followup_shell)

    def open_wikipedia_search_entry(self) -> None:
        preserve_current_wiki_results = bool(
            self.ai_response_overlay is not None
            and self.ai_response_overlay.isVisible()
            and getattr(self.ai_response_overlay, "_tab_mode", "") == "wiki"
            and not getattr(self.ai_response_overlay, "_wiki_entry_active", False)
        )
        if not preserve_current_wiki_results:
            self._stop_active_ai_workers()
            self.ai_query_request_id += 1
            self._pending_ai_query_plans.clear()
        self._clear_ai_image()
        with QSignalBlocker(self.card_search_input):
            self.card_search_input.clear()
        self.card_search_input.set_ai_mode(False)
        if self.ai_response_overlay is not None:
            self.ai_response_overlay.show_wikipedia_search_entry()

    def _smallest_available_image_model_key(self) -> str:
        ai_settings = self.datastore.load_ai_settings()
        if bool(ai_settings.get("ollama_cloud_enabled", False)):
            return self._active_text_llm_spec().key
        setup = self.datastore.load_setup()
        installed_models = dict(setup.get("installed_models", {}))
        candidates = []
        for key in non_embedding_llm_keys():
            spec = MODELS.get(key)
            if spec is None:
                continue
            if bool(installed_models.get(key, False)) or self.preflight.has_model(key):
                candidates.append(spec)
        if not candidates and self.preflight.has_model(self._active_text_llm_spec().key):
            return self._active_text_llm_spec().key
        if not candidates:
            return ""
        return min(candidates, key=lambda spec: spec.size_gb).key

    def _apply_mcq_payload_to_card_answer(self, entry: dict, payload: dict) -> str:
        card = entry.get("card")
        if not isinstance(card, dict):
            return ""
        correct_answer = str(payload.get("correct_answer", "")).strip()
        if not correct_answer:
            return ""
        if str(card.get("answer", "")).strip() == correct_answer:
            return correct_answer

        updated = dict(card)
        updated["answer"] = correct_answer
        if payload.get("answers"):
            updated["mcq_answers"] = list(payload.get("answers", []))
        saved = self.datastore.save_card(updated)
        entry["card"] = saved
        self.current_card = saved
        session_entry = entry.get("session_entry")
        if isinstance(session_entry, SessionCardEntry):
            session_entry.card = saved
        if self.study_state:
            card_id = str(saved.get("id", ""))
            self.study_state.card_lookup[card_id] = saved
            self.study_state.cards = [saved if str(item.get("id", "")) == card_id else item for item in self.study_state.cards]
        self.cards = [saved if str(item.get("id", "")) == str(saved.get("id", "")) else item for item in self.cards]
        return correct_answer

    def _surface(self, sidebar: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SidebarSurface" if sidebar else "Surface")
        polish_surface(frame, sidebar=sidebar)
        return frame

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.sidebar = self._surface(sidebar=True)
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMaximumWidth(280)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(16, 18, 16, 18)
        side_layout.setSpacing(12)

        side_head = QHBoxLayout()
        title = QLabel("Subjects")
        title.setObjectName("SectionTitle")
        self.collapse_btn = AnimatedToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setText("<")
        self.collapse_btn.setProperty("skipClickSfx", True)
        self.collapse_btn.setVisible(False)
        side_head.addWidget(title)
        side_head.addStretch(1)
        side_head.addWidget(self.collapse_btn)
        side_layout.addLayout(side_head)

        self.subject_tree = QTreeWidget()
        self.subject_tree.setHeaderHidden(True)
        self.subject_tree.setRootIsDecorated(False)
        self.subject_tree.setIndentation(0)
        self.subject_tree.setUniformRowHeights(True)
        self.subject_tree.itemClicked.connect(self._subject_clicked)
        side_layout.addWidget(self.subject_tree, 1)
        root.addWidget(self.sidebar)

        content = QVBoxLayout()
        content.setSpacing(14)

        self.mode_stack = AnimatedStackedWidget()
        self.cards_view = self._build_cards_view()
        self.study_view = self._build_study_view()
        self.mode_stack.addWidget(self.cards_view)
        self.mode_stack.addWidget(self.study_view)
        content.addWidget(self.mode_stack, 1)

        root.addLayout(content, 1)

    def _build_cards_view(self) -> QWidget:
        container = QWidget()
        self.cards_view_overlay = container
        self.cards_search_bar = None
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        search_bar = QWidget()
        self.cards_search_bar = search_bar
        search_bar.setObjectName("CardsSearchRow")
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)

        self.card_search_shell = QFrame()
        self.card_search_shell.setObjectName("SearchInputShell")
        polish_surface(self.card_search_shell)
        self.card_search_shell.setFixedHeight(self.CARDS_TOOLBAR_SHELL_HEIGHT)
        search_shell_layout = QHBoxLayout(self.card_search_shell)
        search_shell_layout.setContentsMargins(16, 5, 8, 5)
        search_shell_layout.setSpacing(8)

        self.card_search_stack = QStackedWidget()
        self.card_search_stack.setStyleSheet("background: transparent; border: none;")
        self.card_search_input = AiQueryLineEdit()
        self.card_search_input.setObjectName("SearchInputField")
        self.card_search_input.setPlaceholderText("Something like...")
        self.card_search_input.textChanged.connect(self._queue_card_search)
        self.card_search_input.returnPressed.connect(self._execute_card_search)
        self.card_search_input.aiModeChanged.connect(self._on_card_search_ai_mode_changed)
        self.card_search_input.historyRequested.connect(self._restore_previous_ai_query)
        self.card_search_input.imageDropped.connect(self._attach_ai_image)
        self.card_search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.card_search_input.installEventFilter(self)
        self.card_search_stack.addWidget(self.card_search_input)
        self.card_search_loading_widget = CardSearchLoadingWidget(CARD_SEARCH_LOADING_LINES)
        self.card_search_stack.addWidget(self.card_search_loading_widget)
        self.card_ai_attachment_chip = AiAttachmentChip(self.icons, self.card_search_shell)
        self.card_ai_attachment_chip.removed.connect(self._clear_ai_image)
        self.card_image_search_status = ImageSearchStatus(self.card_search_shell)
        self.card_ai_attach_btn = AnimatedToolButton()
        self.card_ai_attach_btn.setObjectName("SearchInputButton")
        self.card_ai_attach_btn.setIcon(self.icons.icon("common", "cam", "C"))
        self.card_ai_attach_btn.setIconSize(QSize(18, 18))
        self.card_ai_attach_btn.setCursor(Qt.PointingHandCursor)
        self.card_ai_attach_btn.setAutoRaise(True)
        self.card_ai_attach_btn.setFixedSize(30, 30)
        self.card_ai_attach_btn.setToolTip("Attach image")
        self.card_ai_attach_btn.clicked.connect(self._pick_ai_image)
        self.card_search_btn = AnimatedToolButton()
        self.card_search_btn.setObjectName("SearchInputButton")
        self.card_search_btn.setIcon(self._current_search_icon())
        self.card_search_btn.setIconSize(QSize(18, 18))
        self.card_search_btn.setCursor(Qt.PointingHandCursor)
        self.card_search_btn.setAutoRaise(True)
        self.card_search_btn.setFixedSize(30, 30)
        self.card_search_btn.setToolTip("Search")
        self.card_search_btn.setProperty("skipClickSfx", True)
        self.card_search_btn.clicked.connect(self._on_card_search_button_clicked)
        search_shell_layout.addWidget(self.card_search_btn, 0, Qt.AlignVCenter)
        search_shell_layout.addWidget(self.card_search_stack, 1)
        search_shell_layout.addWidget(self.card_ai_attachment_chip, 0, Qt.AlignVCenter)
        search_shell_layout.addWidget(self.card_image_search_status, 1, Qt.AlignVCenter)
        search_shell_layout.addWidget(self.card_ai_attach_btn, 0, Qt.AlignVCenter)
        search_layout.addWidget(self.card_search_shell, 1)

        actions_shell = QFrame()
        actions_shell.setObjectName("CardsSearchActions")
        polish_surface(actions_shell)
        actions_shell.setFixedHeight(self.CARDS_TOOLBAR_SHELL_HEIGHT)
        actions_shell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        actions_layout = QHBoxLayout(actions_shell)
        actions_layout.setContentsMargins(5, 5, 5, 5)
        actions_layout.setSpacing(6)

        self.start_cards_btn = AnimatedButton("Start")
        self.start_cards_btn.setFixedHeight(self.CARDS_TOOLBAR_CONTROL_HEIGHT)
        self.start_cards_btn.setFixedWidth(self.CARDS_TOOLBAR_ACTION_WIDTH)
        self.start_cards_btn.setProperty("skipClickSfx", True)
        self.start_cards_btn.clicked.connect(self._open_start_dialog)
        actions_layout.addWidget(self.start_cards_btn)
        self.refresh_cards_btn = AnimatedButton("Refresh")
        self.refresh_cards_btn.setFixedHeight(self.CARDS_TOOLBAR_CONTROL_HEIGHT)
        self.refresh_cards_btn.setFixedWidth(self.CARDS_TOOLBAR_ACTION_WIDTH)
        self.refresh_cards_btn.clicked.connect(lambda: self.reload_cards(force=True))
        actions_layout.addWidget(self.refresh_cards_btn)
        search_layout.addWidget(actions_shell, 0)
        layout.addWidget(search_bar)

        self.card_search_dropdown = QFrame()
        self.card_search_dropdown.setObjectName("SearchSuggestionDropdown")
        polish_surface(self.card_search_dropdown)
        dropdown_shadow = QGraphicsDropShadowEffect(self.card_search_dropdown)
        dropdown_shadow.setBlurRadius(48)
        dropdown_shadow.setOffset(0, 10)
        dropdown_shadow.setColor(QColor(15, 37, 57, 92))
        self.card_search_dropdown.setGraphicsEffect(dropdown_shadow)
        self.card_search_dropdown.setParent(container)
        self.card_search_dropdown.setVisible(False)
        dropdown_layout = QVBoxLayout(self.card_search_dropdown)
        dropdown_layout.setContentsMargins(10, 10, 10, 10)
        dropdown_layout.setSpacing(6)
        self.card_search_label = QLabel("Did you mean something like:")
        self.card_search_label.setObjectName("SmallMeta")
        dropdown_layout.addWidget(self.card_search_label)
        self.card_search_list = QListWidget()
        self.card_search_list.setObjectName("SearchSuggestionList")
        self.card_search_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_search_list.itemClicked.connect(self._card_search_suggestion_clicked)
        self.card_search_list.itemActivated.connect(self._card_search_suggestion_clicked)
        dropdown_layout.addWidget(self.card_search_list)

        self.cards_surface = self._surface()
        cards_layout = QVBoxLayout(self.cards_surface)
        cards_layout.setContentsMargins(18, 18, 18, 18)
        cards_layout.setSpacing(12)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.viewport().installEventFilter(self)
        self.card_host = QWidget()
        self.card_host.setObjectName("CardsCanvas")
        self.card_host_layout = QVBoxLayout(self.card_host)
        self.card_host_layout.setContentsMargins(0, 0, 0, 0)
        self.card_host_layout.setSpacing(0)
        self.recommendation_block = self._surface()
        self.recommendation_block.setObjectName("RecommendationBlock")
        recommendation_layout = QVBoxLayout(self.recommendation_block)
        recommendation_layout.setContentsMargins(18, 18, 18, 18)
        recommendation_layout.setSpacing(12)
        self.recommendation_title = QLabel("Our recommendation")
        self.recommendation_title.setObjectName("RecommendationTitle")
        recommendation_layout.addWidget(self.recommendation_title)
        self.recommendation_meta = QLabel(
            "According your past interactions, you will benefit from learning these first"
        )
        self.recommendation_meta.setObjectName("RecommendationMeta")
        self.recommendation_meta.setWordWrap(True)
        recommendation_layout.addWidget(self.recommendation_meta)
        self.recommendation_host = QWidget()
        self.recommendation_grid = QGridLayout(self.recommendation_host)
        self.recommendation_grid.setContentsMargins(0, 0, 0, 0)
        self.recommendation_grid.setHorizontalSpacing(16)
        self.recommendation_grid.setVerticalSpacing(16)
        self.recommendation_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        recommendation_layout.addWidget(self.recommendation_host)
        self.recommendation_block.hide()
        self.card_host_layout.addWidget(self.recommendation_block)
        self.card_grid_host = QWidget()
        self.card_grid_host.setObjectName("CardsCanvas")
        self.card_grid = QGridLayout(self.card_grid_host)
        self.card_grid.setContentsMargins(0, 14, 0, 0)
        self.card_grid.setHorizontalSpacing(20)
        self.card_grid.setVerticalSpacing(18)
        self.card_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.card_host_layout.addWidget(self.card_grid_host)
        self.card_scroll.setWidget(self.card_host)
        cards_layout.addWidget(self.card_scroll)
        self.card_empty_state = QWidget()
        self.card_empty_state.setObjectName("CardEmptyState")
        self.card_empty_state.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        empty_layout = QVBoxLayout(self.card_empty_state)
        empty_layout.setContentsMargins(56, 40, 56, 40)
        empty_layout.setSpacing(18)
        empty_layout.setAlignment(Qt.AlignCenter)
        self.card_empty_image = QLabel()
        self.card_empty_image.setAlignment(Qt.AlignCenter)
        self.card_empty_title = QLabel("Try another search")
        self.card_empty_title.setObjectName("PageTitle")
        self.card_empty_title.setAlignment(Qt.AlignCenter)
        self.card_empty_note = QLabel("Use a more direct topic, keyword, or idea from the card.")
        self.card_empty_note.setObjectName("SectionText")
        self.card_empty_note.setAlignment(Qt.AlignCenter)
        self.card_empty_note.setWordWrap(True)
        self.card_empty_note.setMaximumWidth(520)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.card_empty_image)
        empty_layout.addWidget(self.card_empty_title)
        empty_layout.addWidget(self.card_empty_note)
        empty_layout.addStretch(1)
        self.card_empty_state.hide()
        cards_layout.addWidget(self.card_empty_state)
        self.card_search_more_btn = AnimatedButton("See more")
        self.card_search_more_btn.setProperty("skipClickSfx", True)
        self.card_search_more_btn.clicked.connect(self._show_more_cards)
        self.card_search_more_btn.hide()
        cards_layout.addWidget(self.card_search_more_btn, 0, Qt.AlignHCenter)
        layout.addWidget(self.cards_surface, 1)
        self.cards_view_overlay.installEventFilter(self)
        return container

    def _build_search_icon(self) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#111111"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(4, 4, 11, 11)
        painter.drawLine(14, 14, 20, 20)
        painter.end()
        return QIcon(pixmap)

    def _current_search_icon(self) -> QIcon:
        if self.card_search_input.ai_mode_active():
            if self.card_search_input.ai_mode_kind() == "wiki":
                return self.icons.icon("common", "wiki_search", "W")
            return self.icons.icon("common", "ai_search", "A")
        return self._build_search_icon()

    def _build_close_icon(self) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#111111"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(7, 7, 17, 17)
        painter.drawLine(17, 7, 7, 17)
        painter.end()
        return QIcon(pixmap)

    def _build_study_view(self) -> QWidget:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left_surface = self._surface()
        left_layout = QVBoxLayout(left_surface)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        actions = QHBoxLayout()
        self.start_btn = AnimatedButton("Start")
        self.start_btn.setProperty("skipClickSfx", True)
        self.start_btn.clicked.connect(self._handle_study_primary_action)
        self.refresh_study_btn = AnimatedButton("Refresh")
        self.refresh_study_btn.clicked.connect(lambda: self.reload_cards(force=True))
        actions.addStretch(1)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.refresh_study_btn)
        left_layout.addLayout(actions)

        self.session_title = QLabel("Pick a card to start")
        self.session_title.setObjectName("PageTitle")
        self.session_meta = QLabel("")
        self.session_meta.setObjectName("SmallMeta")
        self.session_question = QLabel("Press Start for the current section.")
        self.session_question.setObjectName("SectionText")
        self.session_question.setWordWrap(True)
        self.session_question.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.answer_input = QTextEdit()
        self.answer_input.setPlaceholderText("Write your answer here...")
        self.answer_input.setMinimumHeight(180)

        hint_row = QHBoxLayout()
        self.hint_btn = AnimatedButton("Show hint")
        self.hint_btn.clicked.connect(self._show_hint)
        self.hint_status = QLabel("Hints stay hidden until you press Show hint.")
        self.hint_status.setObjectName("SmallMeta")
        hint_row.addWidget(self.hint_btn)
        hint_row.addWidget(self.hint_status, 1)

        self.hints_text = QTextEdit()
        self.hints_text.setReadOnly(True)
        self.hints_text.setFixedHeight(96)
        self.hints_text.setPlaceholderText("Hints will appear one by one.")

        button_row = QHBoxLayout()
        self.prev_card_btn = AnimatedButton("Back")
        self.prev_card_btn.clicked.connect(self._previous_card)
        self.idk_btn = AnimatedButton("I don't know")
        self.idk_btn.clicked.connect(self._ask_i_dont_know)
        self.grade_btn = AnimatedButton("Grade")
        self.grade_btn.clicked.connect(self._grade)
        self.next_btn = AnimatedButton("Next")
        self.next_btn.clicked.connect(self._next_card)
        button_row.addWidget(self.prev_card_btn)
        button_row.addWidget(self.idk_btn)
        button_row.addWidget(self.grade_btn)
        button_row.addWidget(self.next_btn)

        left_layout.addWidget(self.session_title)
        left_layout.addWidget(self.session_meta)
        left_layout.addWidget(self.session_question)
        left_layout.addWidget(self.answer_input, 1)
        left_layout.addLayout(hint_row)
        left_layout.addWidget(self.hints_text)
        left_layout.addLayout(button_row)

        right_surface = self._surface()
        right_surface.setMinimumWidth(360)
        right_surface.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_surface)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        self.grade_summary = QLabel("AI grader")
        self.grade_summary.setObjectName("PageTitle")
        self.grade_feedback = QTextBrowser()
        self.grade_feedback.setMinimumHeight(280)
        self._init_followup_feedback_browser(self.grade_feedback)
        self.followup_thinking_panel = FollowUpThinkingPanel()
        self.followup_response_host = QWidget()
        self.followup_response_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.followup_response_host.setAutoFillBackground(False)
        self.followup_response_host.setStyleSheet("background: transparent; border: none;")
        self.followup_response_stack = QStackedLayout(self.followup_response_host)
        self.followup_response_stack.setContentsMargins(0, 0, 0, 0)
        self.followup_response_stack.setStackingMode(QStackedLayout.StackOne)
        self.followup_response_stack.addWidget(self.grade_feedback)
        self.followup_response_stack.addWidget(self.followup_thinking_panel)
        self.followup_response_stack.setCurrentWidget(self.grade_feedback)

        right_layout.addWidget(self.grade_summary)
        right_layout.addWidget(self.followup_response_host, 1)
        self._build_followup_controls(right_layout, hidden=True)

        root.addWidget(left_surface, 2)
        root.addWidget(right_surface, 1)
        return container

    def _switch_mode(self, index: int) -> None:
        if self.mode_stack.currentIndex() != index:
            self._play_sound("woosh")
        self.mode_stack.setCurrentIndex(index)
        self._update_study_primary_action()

    def _has_active_session(self) -> bool:
        return self.current_card is not None or bool(self.session_history)

    def _update_study_primary_action(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        self.start_btn.setText("Cards" if self._has_active_session() else "Start")

    def _handle_study_primary_action(self) -> None:
        if self._has_active_session():
            self._switch_mode(0)
            return
        self._open_start_dialog()

    def _current_history_entry(self) -> dict | None:
        if 0 <= self.current_history_index < len(self.session_history):
            return self.session_history[self.current_history_index]
        return None

    def _history_entry(self, index: int) -> dict | None:
        if 0 <= index < len(self.session_history):
            return self.session_history[index]
        return None

    def _has_pending_background_grading(self) -> bool:
        return self.queued_grade_worker is not None or bool(self.queued_grade_indexes)

    def _sync_current_entry_snapshot(self) -> None:
        entry = self._current_history_entry()
        if entry is None:
            return
        entry["answer_text"] = self.answer_input.toPlainText()
        entry["hints_used"] = self.revealed_hints

    def _format_review_markdown(self, report: dict) -> str:
        score = float(report.get("marks_out_of_10", 0) or 0)
        state = str(report.get("state", "wrong")).title()
        hide_score = bool(report.get("hide_score"))
        parts: list[str] = []
        preview = str(report.get("preview_markdown", "")).strip()
        if preview:
            parts.append(preview)
        if hide_score:
            parts.append(f"### Result: {state}")
        else:
            parts.append(f"### Final score: {score:.1f}/10 | {state}")
        good = str(report.get("what_went_good", "")).strip()
        bad = str(report.get("what_went_bad", "")).strip()
        improve = str(report.get("what_to_improve", "")).strip()
        if good:
            parts.append(f"- Good: {good}")
        if bad:
            parts.append(f"- Bad: {bad}")
        if improve:
            parts.append(f"- Improve: {improve}")
        if score >= 9:
            parts.append("- Coach: Great work. You got the core meaning right, and that matters most.")
        elif score <= 5:
            parts.append("- Coach: Keep going. Use the follow up feature to ask more questions and work through it step by step.")
        return "\n\n".join(part for part in parts if part)

    def _set_hint_button_state(self, *, allow_editing: bool) -> None:
        if not self.current_card or not allow_editing:
            self.hint_btn.setEnabled(False)
            return
        hints = self.current_card.get("hints", [])
        has_more = self.revealed_hints < len(hints)
        self.hint_btn.setEnabled(has_more and self.hint_cooldown <= 0)

    def _update_study_controls(self) -> None:
        entry = self._current_history_entry()
        is_latest = self.current_history_index == len(self.session_history) - 1
        pending_current = entry is not None and entry.get("status") in {"queued", "grading"}
        editable = bool(entry) and is_latest and not pending_current and self.grade_worker is None
        self.prev_card_btn.setEnabled(self.current_history_index > 0)
        self.answer_input.setEnabled(editable)
        self.idk_btn.setEnabled(editable)
        self.next_btn.setEnabled(self.current_card is not None and self.grade_worker is None)
        self.grade_btn.setEnabled(editable and not self._has_pending_background_grading())
        self._set_hint_button_state(allow_editing=editable)
        self._update_study_primary_action()

    def _show_history_entry(self, index: int) -> None:
        entry = self._history_entry(index)
        if entry is None:
            return
        self.current_history_index = index
        self.current_card = entry["card"]
        self.last_grade_report = entry.get("grade_report")
        self.current_attempt_logged = bool(entry.get("attempt_logged", False))
        self.revealed_hints = int(entry.get("hints_used", 0))
        self.hint_cooldown = 0
        self.cooldown_timer.stop()

        card = entry["card"]
        title = card.get("title", "Untitled")
        if card.get("temporary"):
            title = f"{title} [TEMP]"
        self.session_title.setText(title)
        self.session_meta.setText(
            f"{card.get('subject', 'General')}  |  {card.get('category', 'All')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        self.session_question.setText(card.get("question", ""))
        self.answer_input.setPlainText(str(entry.get("answer_text", "")))
        visible_hints = card.get("hints", [])[: self.revealed_hints]
        self.hints_text.setPlainText("\n".join(f"{idx + 1}. {hint}" for idx, hint in enumerate(visible_hints)))
        if self.revealed_hints <= 0:
            self.hint_status.setText("Hints stay hidden until you press Show hint.")
        elif self.revealed_hints >= len(card.get("hints", [])):
            self.hint_status.setText("All hints revealed.")
        else:
            self.hint_status.setText("Previously revealed hints are shown here.")

        status = str(entry.get("status", "fresh"))
        if status == "done" and entry.get("grade_report"):
            report = entry["grade_report"]
            score = float(report.get("marks_out_of_10", 0) or 0)
            state = str(report.get("state", "wrong")).title()
            if report.get("hide_score"):
                self.grade_summary.setText(f"Result: {state}")
            else:
                self.grade_summary.setText(f"Final score: {score:.1f}/10  |  {state}")
            self.grade_feedback.setMarkdown(str(entry.get("review_markdown", "")))
            self._set_followup_visible(True)
        elif status in {"queued", "grading"}:
            label = "Queued for grading..." if status == "queued" else "Grading in background..."
            self.grade_summary.setText(label)
            self.grade_feedback.setMarkdown("### Review pending\nYour answer was saved and is waiting for grading.")
            self._set_followup_visible(False)
        elif status == "error":
            self.grade_summary.setText("Grading failed.")
            self.grade_feedback.setMarkdown(str(entry.get("review_markdown", "### Grading failed")))
            self._set_followup_visible(False)
        elif status == "skipped":
            self.grade_summary.setText("Skipped")
            self.grade_feedback.setMarkdown("### Skipped\nThis card was skipped without grading.")
            self._set_followup_visible(False)
        else:
            self.grade_summary.setText("AI grader")
            self.grade_feedback.clear()
            self._set_followup_visible(False)
        self._update_study_controls()

    def _previous_card(self) -> None:
        self._sync_current_entry_snapshot()
        if self.current_history_index <= 0:
            return
        self._show_history_entry(self.current_history_index - 1)

    def _toggle_sidebar(self) -> None:
        self.sidebar_expanded = True
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMaximumWidth(280)
        self.subject_tree.setVisible(True)
        self.collapse_btn.setText("<")

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.MouseButtonPress:
            self._close_followup_model_menu_if_outside(event.globalPosition().toPoint())
        if hasattr(self, "card_scroll") and watched is self.card_scroll.viewport() and event.type() == QEvent.Resize:
            self.card_layout_timer.start(60)
        elif (
            hasattr(self, "cards_view_overlay")
            and watched is self.cards_view_overlay
            and event.type() in (QEvent.Resize, QEvent.Show)
        ):
            QTimer.singleShot(0, self._reposition_card_search_dropdown)
        elif watched is self.card_search_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab and self._accept_card_search_ghost_completion():
                return True
        elif watched is self.card_search_input and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.card_search_shell.setProperty("focusRing", event.type() == QEvent.FocusIn)
            self.card_search_shell.style().unpolish(self.card_search_shell)
            self.card_search_shell.style().polish(self.card_search_shell)
            self.card_search_shell.update()
            if event.type() == QEvent.FocusIn and self.card_search_list.count() > 0:
                QTimer.singleShot(0, self._reposition_card_search_dropdown)
                if self.card_search_dropdown_collapsed_by_idle and len(self.card_search_input.text().strip()) >= 2:
                    self._set_card_search_dropdown_visible(True)
                    self._restart_card_suggestion_idle_collapse()
            elif event.type() == QEvent.FocusOut:
                self._set_card_search_dropdown_visible(False)
        elif hasattr(self, "followup_input") and watched is self.followup_input and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.followup_shell.setProperty("focusRing", event.type() == QEvent.FocusIn)
            self.followup_shell.style().unpolish(self.followup_shell)
            self.followup_shell.style().polish(self.followup_shell)
            self.followup_shell.update()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.ai_response_overlay is not None and self.ai_response_overlay.isVisible():
            QTimer.singleShot(0, self.ai_response_overlay.refresh_layout)

    def _rerender_cards_for_layout_change(self) -> None:
        if not self.cards_loaded_once:
            return
        metrics = self._compute_card_grid_metrics()
        if metrics is None:
            return
        layout_signature = (metrics[0], metrics[1])
        if layout_signature == self._last_render_layout_signature:
            return
        self._render_cards()

    def _set_card_search_dropdown_visible(self, visible: bool) -> None:
        if visible:
            self._reposition_card_search_dropdown()
            self.card_search_dropdown.raise_()
            self.card_search_dropdown_collapsed_by_idle = False
            if self.card_search_dropdown.isVisible():
                self.card_search_dropdown.setMaximumHeight(16777215)
                self.card_search_dropdown.updateGeometry()
                self.card_search_dropdown.update()
                return
        elif not self.card_search_dropdown.isVisible():
            return
        fade_widget_visibility(self.card_search_dropdown, visible)

    def _hide_card_search_dropdown_now(self) -> None:
        if not hasattr(self, "card_search_dropdown"):
            return
        animation = getattr(self.card_search_dropdown, "_height_animation", None)
        if animation is not None:
            animation.stop()
        self.card_search_dropdown._height_target_visible = False  # type: ignore[attr-defined]
        self.card_search_dropdown.hide()
        self.card_search_dropdown.setMaximumHeight(16777215)
        self.card_search_dropdown.updateGeometry()

    def _restart_card_suggestion_idle_collapse(self) -> None:
        if (
            self.card_search_input.hasFocus()
            and not self.card_search_input.ai_mode_active()
            and self.card_search_list.count() > 0
            and len(self.card_search_input.text().strip()) >= 2
        ):
            self.card_search_idle_collapse_timer.start(self.CARD_SUGGESTION_IDLE_COLLAPSE_MS)
            return
        self.card_search_idle_collapse_timer.stop()

    def _collapse_card_suggestions_after_idle(self) -> None:
        if not self.card_search_input.hasFocus() or self.card_search_input.ai_mode_active():
            return
        if self.card_search_list.count() <= 0:
            return
        self.card_search_dropdown_collapsed_by_idle = True
        self._set_card_search_dropdown_visible(False)
        self.card_search_input.clearFocus()

    def _reposition_card_search_dropdown(self) -> None:
        if not hasattr(self, "cards_view_overlay") or self.cards_view_overlay is None:
            return
        search_bar = getattr(self, "cards_search_bar", None)
        shell = getattr(self, "card_search_shell", None)
        dropdown = getattr(self, "card_search_dropdown", None)
        if search_bar is None or shell is None or dropdown is None:
            return

        top_left = search_bar.mapTo(self.cards_view_overlay, QPoint(shell.x(), shell.y() + shell.height() + 8))
        width = max(shell.width(), 320)
        max_width = max(320, self.cards_view_overlay.width() - top_left.x() - 4)
        dropdown_width = min(width, max_width)
        if dropdown_width <= 0:
            return

        dropdown.adjustSize()
        dropdown_height = max(dropdown.sizeHint().height(), dropdown.minimumSizeHint().height())
        dropdown.setGeometry(top_left.x(), top_left.y(), dropdown_width, dropdown_height)

    def activate_view(self) -> None:
        if not self.cards_loaded_once or self.cards_dirty:
            self.reload_cards(force=True)
            return
        if self.mode_stack.currentIndex() == 0 and self.card_grid.count() == 0 and self.cards:
            self._render_cards()

    def mark_cards_dirty(self) -> None:
        self.cards_dirty = True
        if self.isVisible():
            QTimer.singleShot(0, lambda: self.reload_cards(force=True))

    def reload_cards(self, force: bool = False) -> None:
        if self.cards_loaded_once and not (force or self.cards_dirty):
            return
        self.cards = self.datastore.list_all_cards()
        self._rebuild_card_search_term_cache()
        self.cards_loaded_once = True
        self.cards_dirty = False
        self.card_search_loading = False
        self.pending_card_search_results = None
        self._finish_card_search_loading()
        self._set_card_search_dropdown_visible(False)
        self._reset_card_render_limit()
        self._refresh_subjects(self.datastore.card_counts_by_subject())
        self._render_cards()
        self._post_reload_generation += 1
        generation = self._post_reload_generation
        QTimer.singleShot(120, lambda gen=generation: self._run_post_reload_tasks(gen))

    def _run_post_reload_tasks(self, generation: int) -> None:
        if generation != self._post_reload_generation or self.cards_dirty:
            return
        if self.preflight.semantic_search_available():
            self._embed_remaining_cards_in_background(self.cards)
        self._refresh_global_recommendations()
        if self.mode_stack.currentIndex() == 0:
            self._render_recommendations()

    @staticmethod
    def _card_counts_from_cards(cards: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {subject: 0 for subject in SUBJECT_TAXONOMY}
        for card in cards:
            subject = str(card.get("subject", "")).strip()
            if subject in counts:
                counts[subject] += 1
        return counts

    def _refresh_subjects(self, counts: dict[str, int] | None = None) -> None:
        counts = counts or self._card_counts_from_cards(self.cards)
        self.subject_tree.clear()

        all_item = QTreeWidgetItem(["All Subjects"])
        all_item.setData(0, Qt.UserRole, {"subject": "All Subjects", "category": "All", "subtopic": "All"})
        self.subject_tree.addTopLevelItem(all_item)

        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([f"{subject} ({counts.get(subject, 0)})"])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            if counts.get(subject, 0) == 0:
                subject_item.setForeground(0, QColor("#8f8f8f"))
            self.subject_tree.addTopLevelItem(subject_item)
            for category in details.get("core", []):
                category_item = QTreeWidgetItem([category])
                category_item.setData(
                    0,
                    Qt.UserRole,
                    {"subject": subject, "category": category, "subtopic": "All"},
                )
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    subtopic_item = QTreeWidgetItem([subtopic])
                    subtopic_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(subtopic_item)
        self.subject_tree.collapseAll()
        selected = self._find_subject_tree_item(
            self.current_subject,
            self.current_category,
            self.current_subtopic,
        )
        self.subject_tree.setCurrentItem(selected or all_item)

    def _find_subject_tree_item(self, subject: str, category: str, subtopic: str) -> QTreeWidgetItem | None:
        for top_index in range(self.subject_tree.topLevelItemCount()):
            item = self.subject_tree.topLevelItem(top_index)
            match = self._match_subject_tree_item(item, subject, category, subtopic)
            if match is not None:
                return match
        return None

    def _match_subject_tree_item(
        self,
        item: QTreeWidgetItem | None,
        subject: str,
        category: str,
        subtopic: str,
    ) -> QTreeWidgetItem | None:
        if item is None:
            return None
        payload = item.data(0, Qt.UserRole) or {}
        if (
            payload.get("subject", "All Subjects") == subject
            and payload.get("category", "All") == category
            and payload.get("subtopic", "All") == subtopic
        ):
            return item
        for child_index in range(item.childCount()):
            match = self._match_subject_tree_item(item.child(child_index), subject, category, subtopic)
            if match is not None:
                return match
        return None

    def _current_path_label(self) -> str:
        parts = []
        if self.current_subject != "All Subjects":
            parts.append(self.current_subject)
        if self.current_category != "All":
            parts.append(self.current_category)
        if self.current_subtopic != "All":
            parts.append(self.current_subtopic)
        return " / ".join(parts) if parts else "All Subjects"

    def _subject_clicked(self, item: QTreeWidgetItem) -> None:
        self._play_sound("click")
        payload = item.data(0, Qt.UserRole) or {"subject": "All Subjects", "category": "All", "subtopic": "All"}
        self.current_subject = payload["subject"]
        self.current_category = payload["category"]
        self.current_subtopic = payload.get("subtopic", "All")
        self.card_search_idle_collapse_timer.stop()
        self._set_card_search_dropdown_visible(False)
        self._sync_card_search_ghost_text()
        self._reset_card_render_limit()
        self._render_cards()

    def _clear_grid(self) -> None:
        while self.card_grid.count():
            child = self.card_grid.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    def _filtered_cards(self) -> list[dict]:
        if self.current_subject == "All Subjects" and self.current_category == "All" and self.current_subtopic == "All":
            return self.cards
        filtered = list(self.cards)
        if self.current_subject != "All Subjects":
            filtered = [card for card in filtered if card.get("subject") == self.current_subject]
        if self.current_category != "All":
            filtered = [card for card in filtered if card.get("category") == self.current_category]
        if self.current_subtopic != "All":
            filtered = [card for card in filtered if card.get("subtopic") == self.current_subtopic]
        return filtered

    def _rebuild_card_search_term_cache(self) -> None:
        cache: list[tuple[str, str, str, str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for card in self.cards:
            raw_terms = card.get("search_terms", [])
            if not isinstance(raw_terms, list):
                continue
            subject = str(card.get("subject", ""))
            category = str(card.get("category", ""))
            subtopic = str(card.get("subtopic", ""))
            for term in raw_terms:
                display = " ".join(str(term or "").strip().split())
                if len(display) < 2:
                    continue
                key = (display.lower(), subject, category, subtopic)
                if key in seen:
                    continue
                seen.add(key)
                cache.append((display.lower(), display, subject, category, subtopic))
        cache.sort(key=lambda item: (len(item[1]), item[1].lower()))
        self.card_search_term_cache = cache

    def _card_search_term_in_scope(self, subject: str, category: str, subtopic: str) -> bool:
        if self.current_subject != "All Subjects" and subject != self.current_subject:
            return False
        if self.current_category != "All" and category != self.current_category:
            return False
        if self.current_subtopic != "All" and subtopic != self.current_subtopic:
            return False
        return True

    def _queue_card_search(self, text: str) -> None:
        normalized = text.strip()
        trigger_kind = self.AI_TRIGGER_TOKENS.get(normalized.lower(), "")
        if not self.card_search_input.ai_mode_active() and trigger_kind:
            with QSignalBlocker(self.card_search_input):
                self.card_search_input.clear()
            self.card_search_input.set_ai_mode(True, trigger_kind)
            self._sync_card_search_action_button()
            self._sync_card_search_ghost_text()
            return
        if self.card_search_input.ai_mode_active():
            self.card_search_timer.stop()
            self.card_search_idle_collapse_timer.stop()
            self._set_card_search_dropdown_visible(False)
            self._sync_card_search_action_button()
            self._sync_card_search_ghost_text()
            return
        self.card_search_request_id += 1
        was_loading = self.card_search_loading
        if not normalized or normalized != self.card_search_query:
            self.card_search_has_executed = False
            self.card_search_loading = False
            self.pending_card_search_results = None
        self._sync_card_search_action_button()
        self._sync_card_search_ghost_text()
        if not text.strip():
            self.card_search_timer.stop()
            self.card_search_idle_collapse_timer.stop()
            self._set_card_search_dropdown_visible(False)
            self.card_search_suggestions = []
            self.card_search_full_results = []
            self.card_search_last_scores = []
            self.card_search_no_close_match = False
            self.card_search_loading = False
            self.pending_card_search_results = None
            self._reset_card_render_limit()
            self.card_search_more_btn.hide()
            self._render_cards()
            return
        if len(text.strip()) < 2 or not self.card_search_input.hasFocus():
            if was_loading:
                self._render_cards()
            return
        self.card_search_dropdown_collapsed_by_idle = False
        self._restart_card_suggestion_idle_collapse()
        if was_loading:
            self._render_cards()
        self.card_search_timer.start(self.CARD_SUGGESTION_DEBOUNCE_MS)

    def _request_card_suggestions(self) -> None:
        if self.card_search_input.ai_mode_active():
            return
        query = self.card_search_input.text().strip()
        if len(query) < 2 or not self.card_search_input.hasFocus():
            return
        cards = self._filtered_cards()
        if not cards:
            self._set_card_search_dropdown_visible(False)
            self._sync_card_search_ghost_text()
            return
        filters = self._search_scope_filters()
        candidates = self.datastore.search_cards_fts(query, limit=16, **filters)
        suggestions = self._fast_card_suggestions(query, candidates or cards, limit=5)
        if self._should_hide_card_suggestions(query, suggestions):
            self._set_card_search_dropdown_visible(False)
            self._sync_card_search_ghost_text()
            return
        self._on_card_suggestions_ready(self.card_search_request_id, query, suggestions)

    def _on_card_suggestions_ready(self, request_id: int, query: str, scored: object) -> None:
        if request_id != self.card_search_request_id:
            return
        if query != self.card_search_input.text().strip():
            return
        scored_items = scored if isinstance(scored, list) else []
        self.card_search_suggestions = [item.get("card", {}) for item in scored_items if isinstance(item, dict)]
        self.card_search_list.clear()
        if not scored_items:
            self._set_card_search_dropdown_visible(False)
            self._sync_card_search_ghost_text()
            return
        for index, item in enumerate(scored_items[:5]):
            if not isinstance(item, dict):
                continue
            self._append_card_search_suggestion(request_id, query, item)
        self._sync_card_search_ghost_text(scored_items)
        self._set_card_search_dropdown_visible(self.card_search_list.count() > 0)
        self._restart_card_suggestion_idle_collapse()

    def _append_card_search_suggestion(self, request_id: int, query: str, item: dict) -> None:
        if request_id != self.card_search_request_id or query != self.card_search_input.text().strip():
            return
        card = item.get("card", {})
        title = str(card.get("title", "Untitled")).strip() or "Untitled"
        short_title = title if len(title) <= 200 else f"{title[:197]}..."
        row = QListWidgetItem(short_title)
        row.setData(Qt.ItemDataRole.ToolTipRole, "")
        row.setData(Qt.UserRole, card)
        row.setSizeHint(QSize(0, 40))
        self.card_search_list.addItem(row)
        self._sync_card_search_list_height()
        self._reposition_card_search_dropdown()

    def _sync_card_search_ghost_text(self, scored_items: object | None = None) -> None:
        if not hasattr(self, "card_search_input"):
            return
        ghost = ""
        if not self.card_search_input.ai_mode_active():
            query = self.card_search_input.text()
            if query.strip():
                ghost = self._card_search_terms_ghost(query, scored_items)
        self.card_search_ghost_text = ghost
        self.card_search_input.set_ghost_text(ghost)

    def _card_search_terms_ghost(self, query: str, scored_items: object | None = None) -> str:
        del scored_items
        raw_query = str(query or "")
        if not raw_query.strip():
            return ""
        raw_query_lower = raw_query.lower()
        for candidate_lower, candidate, subject, category, subtopic in self.card_search_term_cache:
            if not self._card_search_term_in_scope(subject, category, subtopic):
                continue
            if len(candidate) <= len(raw_query):
                continue
            if candidate_lower.startswith(raw_query_lower):
                return f"{raw_query}{candidate[len(raw_query):]}"
        return ""

    def _accept_card_search_ghost_completion(self) -> bool:
        if self.card_search_input.ai_mode_active():
            return False
        text = self.card_search_input.text()
        ghost = self.card_search_input.ghost_text()
        if (
            not text
            or not ghost
            or not ghost.lower().startswith(text.lower())
            or len(ghost) <= len(text)
            or self.card_search_input.cursorPosition() != len(text)
        ):
            return False

        now = time.monotonic()
        tab_delta = now - self.card_search_last_tab_at
        fast_repeat = 0 < tab_delta <= (self.CARD_GHOST_FULL_ACCEPT_MS / 1000)
        auto_search = 0 < tab_delta <= (self.CARD_GHOST_AUTO_SEARCH_MS / 1000)
        self.card_search_last_tab_at = now
        if fast_repeat or auto_search:
            accepted = ghost
        else:
            accepted = self._card_search_next_ghost_word(text, ghost)

        with QSignalBlocker(self.card_search_input):
            self.card_search_input.setText(accepted)
            self.card_search_input.setCursorPosition(len(accepted))
        self._sync_card_search_ghost_text()
        self.card_search_timer.start(self.CARD_SUGGESTION_DEBOUNCE_MS)
        self._restart_card_suggestion_idle_collapse()
        if auto_search:
            QTimer.singleShot(0, self._execute_card_search)
        return True

    @staticmethod
    def _card_search_next_ghost_word(text: str, ghost: str) -> str:
        if len(ghost) <= len(text):
            return text
        index = len(text)
        while index < len(ghost) and ghost[index].isspace():
            index += 1
        while index < len(ghost) and not ghost[index].isspace():
            index += 1
        return ghost[:index]

    def _card_search_suggestion_clicked(self, item: QListWidgetItem) -> None:
        self.card_search_timer.stop()
        self.card_search_idle_collapse_timer.stop()
        self._set_card_search_dropdown_visible(False)
        card = item.data(Qt.UserRole) or {}
        title = str(card.get("title", "")).strip()
        if title:
            self.card_search_input.setText(title)
        self._play_sound("click")
        self._execute_card_search()

    def _sync_card_search_list_height(self) -> None:
        count = min(5, self.card_search_list.count())
        if count <= 0:
            self.card_search_list.setMinimumHeight(0)
            self.card_search_list.setMaximumHeight(16777215)
            return
        total_height = sum(max(self.card_search_list.sizeHintForRow(index), 40) for index in range(count))
        total_height += self.card_search_list.frameWidth() * 2
        self.card_search_list.setMinimumHeight(total_height)
        self.card_search_list.setMaximumHeight(total_height)

    def _search_scope_filters(self) -> dict[str, str | None]:
        return {
            "subject": None if self.current_subject == "All Subjects" else self.current_subject,
            "category": None if self.current_category == "All" else self.current_category,
            "subtopic": None if self.current_subtopic == "All" else self.current_subtopic,
        }

    def _on_card_search_ai_mode_changed(self, active: bool) -> None:
        self.card_search_timer.stop()
        self._set_card_search_dropdown_visible(False)
        self._sync_image_search_bar_state()
        if active:
            self.ai_query_history_index = len(self.ai_query_history)
            self.card_search_input.setFocus()

    def _pick_ai_image(self) -> None:
        if self.ai_query_image_path.strip():
            return
        self._play_sound("click")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if path:
            self._attach_ai_image(path)

    def _attach_ai_image(self, path: str) -> None:
        if self.ai_query_image_path.strip():
            QMessageBox.information(self, "Image search", "Remove the current image before adding another one.")
            return
        normalized = str(path or "").strip()
        if not normalized:
            return
        if not self.card_ai_attachment_chip.set_image(normalized):
            QMessageBox.warning(self, "Image search", "That image could not be loaded.")
            return
        self.ai_query_image_path = normalized
        self._sync_image_search_bar_state()
        self.card_search_input.setFocus()
        if not self.card_search_input.ai_mode_active():
            self._execute_card_search()

    def _clear_ai_image(self) -> None:
        self.ai_query_image_path = ""
        self.card_ai_attachment_chip.clear_image()
        self._sync_image_search_bar_state()

    def _sync_image_search_bar_state(self) -> None:
        attached = bool(self.ai_query_image_path.strip())
        image_search_mode = attached and not self.card_search_input.ai_mode_active()
        self.card_search_input.set_image_attached(attached)
        self.card_search_btn.setVisible(True)
        self.card_search_stack.setVisible(not image_search_mode)
        self.card_ai_attach_btn.setVisible(not attached)
        self.card_image_search_status.setVisible(image_search_mode)
        self._sync_card_search_action_button()

    def _sync_card_search_action_button(self) -> None:
        show_close = bool(self.ai_query_image_path.strip()) or (
            self.card_search_has_executed and not self.card_search_input.ai_mode_active()
        )
        self.card_search_btn.setIcon(self._build_close_icon() if show_close else self._current_search_icon())
        self.card_search_btn.setToolTip("Back" if show_close else "Search")

    def _on_card_search_button_clicked(self) -> None:
        if self.ai_query_image_path.strip() or (self.card_search_has_executed and not self.card_search_input.ai_mode_active()):
            self._clear_card_search()
            return
        self._execute_card_search()

    def _clear_card_search(self) -> None:
        self._play_sound("click")
        self.card_search_timer.stop()
        self.card_search_idle_collapse_timer.stop()
        self._set_card_search_dropdown_visible(False)
        self.card_search_request_id += 1
        self.card_search_query = ""
        self.card_search_has_executed = False
        self.card_search_loading = False
        self.pending_card_search_results = None
        self.card_search_full_results = []
        self.card_search_last_scores = []
        self.card_search_no_close_match = False
        self.card_search_more_btn.hide()
        self._reset_card_render_limit()
        self._clear_ai_image()
        self._finish_card_search_loading()
        with QSignalBlocker(self.card_search_input):
            self.card_search_input.clear()
        self.card_search_input.set_ai_mode(False)
        self._sync_card_search_ghost_text()
        self._sync_card_search_action_button()
        self._render_cards()

    def _restore_previous_ai_query(self) -> None:
        if not self.card_search_input.ai_mode_active() or not self.ai_query_history:
            return
        self.ai_query_history_index = max(0, self.ai_query_history_index - 1)
        query = self.ai_query_history[self.ai_query_history_index]
        with QSignalBlocker(self.card_search_input):
            self.card_search_input.setText(query)
        self.card_search_input.setCursorPosition(len(query))

    def _should_hide_card_suggestions(self, query: str, suggestions: list[dict]) -> bool:
        query_lower = query.lower().strip()
        if not query_lower:
            return True
        if self.card_search_has_executed and query_lower == self.card_search_query.lower().strip():
            return True
        titles = [str(item.get("card", {}).get("title", "")).strip().lower() for item in suggestions if isinstance(item, dict)]
        if any(title == query_lower for title in titles):
            return True
        if titles:
            top_title = titles[0]
            if len(query_lower) >= 5 and top_title.startswith(query_lower) and len(top_title) <= max(len(query_lower) + 6, int(len(query_lower) * 1.35)):
                return True
        return False

    def _execute_card_search(self) -> None:
        self._play_sound("click")
        query = self.card_search_input.text().strip()
        image_path = self.ai_query_image_path.strip()
        self.card_search_timer.stop()
        self.card_search_idle_collapse_timer.stop()
        self._hide_card_search_dropdown_now()
        if self.card_search_input.ai_mode_active():
            self.card_search_loading = False
            self.pending_card_search_results = None
            self._finish_card_search_loading()
            if self.card_search_input.ai_mode_kind() == "wiki":
                self._submit_wiki_query(query)
            else:
                self._submit_ai_query(query)
            return
        if image_path:
            self.card_search_loading = False
            self.pending_card_search_results = None
            self._finish_card_search_loading()
            self._execute_image_card_search(image_path, fallback_text=query)
            return
        if not query:
            self.card_search_query = ""
            self.card_search_has_executed = False
            self.card_search_loading = False
            self.pending_card_search_results = None
            self.card_search_full_results = []
            self.card_search_last_scores = []
            self.card_search_no_close_match = False
            self.card_search_more_btn.hide()
            self._finish_card_search_loading()
            self._sync_card_search_action_button()
            self._render_cards()
            return

        self.card_search_query = query
        self.card_search_has_executed = True
        self.card_search_loading = True
        self.card_search_skeleton_cycles = 0
        self.pending_card_search_results = None
        self._begin_card_search_loading()
        self._sync_card_search_action_button()
        self.card_search_result_limit = 8
        self.card_search_request_id += 1
        request_id = self.card_search_request_id
        self.card_search_full_results = []
        self.card_search_last_scores = []
        self.card_search_no_close_match = False
        self._render_cards()
        QTimer.singleShot(16, lambda req=request_id, text=query: self._start_text_card_search(req, text))

    def _start_text_card_search(self, request_id: int, query: str) -> None:
        if request_id != self.card_search_request_id:
            return
        if self.card_search_input.ai_mode_active() or query != self.card_search_input.text().strip():
            return
        cards = self._filtered_cards()
        semantic_enabled = self._neural_acceleration_enabled()
        worker = CardSearchWorker(
            request_id=request_id,
            query=query,
            cards=cards,
            embedding_service=self.embedding_service,
            limit=max(8, len(cards)),
            allow_semantic=semantic_enabled,
        )
        self.card_search_worker = worker
        self._card_search_workers.append(worker)
        worker.finished.connect(self._on_card_search_finished)
        worker.finished.connect(lambda _req, _query, _scored, current=worker: self._cleanup_card_search_worker(current))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _execute_image_card_search(self, image_path: str, *, fallback_text: str = "") -> None:
        ai_settings = self.datastore.load_ai_settings()
        explicit_model_key = str(ai_settings.get(feature_model_setting_key("ask_ai_image_context_length"), "")).strip()
        model_key = explicit_model_key or self._smallest_available_image_model_key()
        if not model_key:
            QMessageBox.information(self, "Image search", "Install a supported AI text model before using image search.")
            return
        if not self.preflight.require_model(model_key, parent=self, feature_name="Image search"):
            return
        cards = self._filtered_cards()
        if not cards:
            return
        self.card_search_request_id += 1
        request_id = self.card_search_request_id
        self.card_search_query = "Image search"
        self.card_search_has_executed = True
        self._sync_card_search_action_button()
        self.card_search_result_limit = 8
        self.card_search_full_results = []
        self.card_search_last_scores = []
        self.card_search_no_close_match = False
        term_count = max(2, min(6, int(ai_settings.get("image_search_term_count", 4) or 4)))
        context_length = int(ai_settings.get("ask_ai_image_context_length", 8192) or 8192)
        worker = ImageSearchTermsWorker(
            request_id=request_id,
            ollama=self.ollama,
            model=self._feature_model_tag_for_key(model_key, "ask_ai_image_context_length"),
            image_path=image_path,
            term_count=term_count,
            context_length=context_length,
        )
        self.image_search_terms_worker = worker
        worker.finished.connect(
            lambda _request_id, terms, original=fallback_text: self._on_image_search_terms_ready(_request_id, original, terms)
        )
        worker.failed.connect(self._on_image_search_terms_failed)
        worker.finished.connect(lambda _request_id, _terms, current=worker: self._cleanup_image_search_worker(current))
        worker.failed.connect(lambda _request_id, _message, current=worker: self._cleanup_image_search_worker(current))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_image_search_terms_ready(self, request_id: int, fallback_text: str, terms: object) -> None:
        if request_id != self.card_search_request_id:
            return
        search_terms = [str(term).strip() for term in terms if str(term).strip()] if isinstance(terms, list) else []
        queries = [fallback_text.strip(), *search_terms]
        queries = [" ".join(query.split()) for query in queries if " ".join(query.split())]
        if not queries:
            self._on_image_search_terms_failed(request_id, "Image search returned no searchable terms.")
            return
        cards = self._filtered_cards()
        semantic_enabled = self._neural_acceleration_enabled() and self.preflight.semantic_search_available()
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if semantic_enabled and missing:
            self._embed_remaining_cards_in_background(missing)
        worker = ImageCardSearchWorker(
            request_id=request_id,
            queries=queries,
            cards=cards,
            embedding_service=self.embedding_service,
            limit=max(8, len(cards)),
            allow_semantic=semantic_enabled,
        )
        self.image_card_search_worker = worker
        worker.finished.connect(self._on_image_card_search_finished)
        worker.finished.connect(lambda _req, _query, _scored, current=worker: self._cleanup_image_card_search_worker(current))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_image_card_search_finished(self, request_id: int, query: str, scored: object) -> None:
        if request_id != self.card_search_request_id:
            return
        del query
        scored_items = scored if isinstance(scored, list) else []
        self.card_search_full_results = [item["card"] for item in scored_items if isinstance(item, dict) and isinstance(item.get("card"), dict)]
        self.card_search_last_scores = [float(item.get("score", 0.0)) for item in scored_items if isinstance(item, dict)]
        self.card_search_no_close_match = not bool(scored_items)
        self._sync_card_search_action_button()
        self._render_cards(animate_search_results=True)
        self._clear_ai_image()
        self._sync_card_search_action_button()

    def _on_image_search_terms_failed(self, request_id: int, message: str) -> None:
        if request_id != self.card_search_request_id:
            return
        self.card_search_has_executed = False
        self._sync_card_search_action_button()
        QMessageBox.warning(self, "Image search", message)

    def _cleanup_image_search_worker(self, worker: ImageSearchTermsWorker) -> None:
        if self.image_search_terms_worker is worker:
            self.image_search_terms_worker = None

    def _cleanup_image_card_search_worker(self, worker: ImageCardSearchWorker) -> None:
        if self.image_card_search_worker is worker:
            self.image_card_search_worker = None

    def _on_card_search_finished(self, request_id: int, query: str, scored: object) -> None:
        if request_id != self.card_search_request_id:
            return
        if self.card_search_input.ai_mode_active():
            return
        if query != self.card_search_input.text().strip():
            return
        scored_items = scored if isinstance(scored, list) else []
        if (
            self.card_search_loading
            and scored_items
            and self.card_search_skeleton_cycles < self.CARD_SEARCH_SKELETON_MIN_CYCLES
        ):
            self.pending_card_search_results = (request_id, query, list(scored_items))
            return
        self._apply_card_search_results(scored_items)

    def _apply_pending_card_search_results(self, request_id: int) -> None:
        pending = self.pending_card_search_results
        if pending is None:
            return
        pending_request_id, query, scored_items = pending
        if pending_request_id != request_id or request_id != self.card_search_request_id:
            return
        if self.card_search_input.ai_mode_active() or query != self.card_search_input.text().strip():
            return
        self.pending_card_search_results = None
        self._apply_card_search_results(scored_items)

    def _apply_card_search_results(self, scored_items: list) -> None:
        self.card_search_full_results = [item["card"] for item in scored_items if isinstance(item, dict) and isinstance(item.get("card"), dict)]
        self.card_search_last_scores = [float(item.get("score", 0.0)) for item in scored_items if isinstance(item, dict)]
        self.card_search_no_close_match = not bool(scored_items)
        self.card_search_loading = False
        self._finish_card_search_loading()
        self._render_cards(animate_search_results=True)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _begin_card_search_loading(self) -> None:
        if not hasattr(self, "card_search_loading_widget"):
            return
        self.card_search_loading_widget.start(self._select_card_search_loading_lines())
        self.card_search_stack.setCurrentWidget(self.card_search_loading_widget)

    def _finish_card_search_loading(self) -> None:
        if not hasattr(self, "card_search_loading_widget"):
            return
        self.card_search_loading_widget.stop()
        self.card_search_stack.setCurrentWidget(self.card_search_input)

    def _load_card_search_loading_penalties(self) -> dict[str, dict[str, object]]:
        payload = self.datastore.load_cache_entry(CARD_SEARCH_LOADING_PENALTY_CACHE_KEY) or {}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return {}
        cleaned: dict[str, dict[str, object]] = {}
        now = self._utc_now()
        changed = False
        for line, entry in entries.items():
            text = str(line or "").strip()
            if text not in CARD_SEARCH_LOADING_LINES or not isinstance(entry, dict):
                changed = True
                continue
            expires_raw = str(entry.get("expires_at", "")).strip()
            try:
                expires_at = datetime.fromisoformat(expires_raw)
            except ValueError:
                changed = True
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                changed = True
                continue
            penalty = max(0, int(entry.get("penalty", 0) or 0))
            cleaned[text] = {
                "penalty": penalty,
                "applied_at": str(entry.get("applied_at", "")).strip(),
                "expires_at": expires_at.isoformat(),
            }
        if changed:
            self._save_card_search_loading_penalties(cleaned)
        return cleaned

    def _save_card_search_loading_penalties(self, entries: dict[str, dict[str, object]]) -> None:
        self.datastore.put_cache_entry(
            CARD_SEARCH_LOADING_PENALTY_CACHE_KEY,
            {
                "entries": entries,
                "updated_at": self.datastore.now_iso(),
            },
        )

    def _select_card_search_loading_lines(self) -> list[str]:
        penalties = self._load_card_search_loading_penalties()
        candidates = list(CARD_SEARCH_LOADING_LINES)
        previous = list(getattr(self.card_search_loading_widget, "_last_texts", []))
        if previous:
            alternates = [line for line in candidates if line not in previous]
            if alternates:
                candidates = alternates

        weighted: list[tuple[str, float]] = []
        for line in candidates:
            entry = penalties.get(line, {})
            penalty = max(0, int(entry.get("penalty", 0) or 0))
            weight = 1.0 / (1.0 + (0.85 * penalty))
            weighted.append((line, max(0.08, weight)))

        total = sum(weight for _line, weight in weighted)
        if total <= 0.0:
            choice = random.choice(candidates or list(CARD_SEARCH_LOADING_LINES))
        else:
            pick = random.uniform(0.0, total)
            choice = weighted[-1][0]
            running = 0.0
            for line, weight in weighted:
                running += weight
                if pick <= running:
                    choice = line
                    break

        now = self._utc_now()
        expires_at = now + timedelta(hours=CARD_SEARCH_LOADING_PENALTY_HOURS)
        current_penalty = max(0, int(penalties.get(choice, {}).get("penalty", 0) or 0))
        penalties[choice] = {
            "penalty": current_penalty + 1,
            "applied_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        self._save_card_search_loading_penalties(penalties)
        return [choice]

    def _show_more_cards(self) -> None:
        self._play_sound("click")
        if self.card_search_has_executed:
            self.card_search_result_limit += 8
        else:
            self.card_render_limit += self.CARD_RENDER_BATCH_SIZE
        self._render_cards()

    def _reset_card_render_limit(self) -> None:
        self.card_render_limit = self.CARD_RENDER_BATCH_SIZE

    def _cleanup_card_search_worker(self, worker: CardSearchWorker) -> None:
        if worker in self._card_search_workers:
            self._card_search_workers.remove(worker)
        if self.card_search_worker is worker:
            self.card_search_worker = None

    def _stop_active_ai_workers(self) -> None:
        for worker in (
            self.ai_query_planner_worker,
            self.ai_query_answer_worker,
            self.wiki_breakdown_worker,
            self.wiki_images_worker,
        ):
            if worker is not None and worker.isRunning():
                worker.stop()

    def _build_ai_card_context(self, scored_items: list[dict], *, limit: int = 6) -> list[dict]:
        attempts = self.datastore.load_attempts()
        attempts_by_card: dict[str, list[dict]] = {}
        for attempt in attempts:
            card_id = str(attempt.get("card_id", "")).strip()
            if not card_id:
                continue
            attempts_by_card.setdefault(card_id, []).append(attempt)

        payload: list[dict] = []
        for item in scored_items[:limit]:
            if not isinstance(item, dict):
                continue
            card = item.get("card")
            if not isinstance(card, dict):
                continue
            card_id = str(card.get("id", "")).strip()
            history = list(attempts_by_card.get(card_id, []))
            graded = [attempt for attempt in history if attempt.get("marks_out_of_10") is not None]
            latest = graded[-1] if graded else (history[-1] if history else None)
            average_marks = None
            if graded:
                average_marks = round(
                    sum(float(attempt.get("marks_out_of_10", 0.0) or 0.0) for attempt in graded) / len(graded),
                    2,
                )
            latest_feedback = None
            if isinstance(latest, dict):
                latest_feedback = {
                    "marks_out_of_10": latest.get("marks_out_of_10"),
                    "how_good": latest.get("how_good"),
                    "what_went_good": latest.get("what_went_good"),
                    "what_went_bad": latest.get("what_went_bad"),
                    "what_to_improve": latest.get("what_to_improve"),
                    "state": latest.get("state"),
                    "timestamp": latest.get("timestamp"),
                }
            payload.append(
                {
                    "card_id": card_id,
                    "title": str(card.get("title", "")).strip(),
                    "question": str(card.get("question", "")).strip(),
                    "answer": str(card.get("answer", "")).strip(),
                    "subject": str(card.get("subject", "")).strip(),
                    "difficulty": card.get("natural_difficulty"),
                    "match_source": str(item.get("source", "")).strip(),
                    "match_score": round(float(item.get("score", 0.0) or 0.0), 4),
                    "performance": {
                        "attempt_count": len(history),
                        "graded_attempt_count": len(graded),
                        "latest_marks_out_of_10": latest.get("marks_out_of_10") if isinstance(latest, dict) else None,
                        "latest_how_good": latest.get("how_good") if isinstance(latest, dict) else None,
                        "average_marks_out_of_10": average_marks,
                        "latest_feedback": latest_feedback,
                    },
                }
            )
        return payload

    def _start_ai_answer_worker(
        self,
        request_id: int,
        *,
        query: str,
        retrieved_cards: list[dict],
        retrieval_query: str,
        image_paths: list[str] | None = None,
        image_analysis: dict | None = None,
    ) -> None:
        ai_settings = self.datastore.load_ai_settings()
        profile_context = self.datastore.load_profile()
        model_spec = self._feature_text_llm_spec("ask_ai_answer_context_length")
        worker = AiSearchAnswerWorker(
            request_id=request_id,
            ollama=self.ollama,
            model=self._feature_text_model_tag("ask_ai_answer_context_length"),
            prompt=query,
            context_length=int(ai_settings.get("ask_ai_answer_context_length", ai_settings.get("discuss_context_length", 9216)) or 9216),
            profile_context=profile_context,
            retrieved_cards=retrieved_cards,
            retrieval_query=retrieval_query,
            tone=str(ai_settings.get("ask_ai_tone", ai_settings.get("assistant_tone", ""))).strip().lower(),
            emoji_level=max(1, min(4, int(ai_settings.get("ask_ai_emoji_level", 2) or 2))),
            image_paths=list(image_paths or []),
            image_analysis=dict(image_analysis or {}),
        )
        self.ai_query_answer_worker = worker
        self._ai_query_workers.add(worker)
        worker.failed.connect(self._on_ai_query_failed)
        worker.finished.connect(self._on_ai_query_finished)
        worker.failed.connect(lambda _request_id, _message, current=worker: self._cleanup_ai_answer_worker(current))
        worker.finished.connect(lambda _request_id, _markdown, current=worker: self._cleanup_ai_answer_worker(current))
        worker.start()

    def _submit_ai_query(self, query: str) -> None:
        image_path = self.ai_query_image_path.strip()
        if image_path and not query:
            QMessageBox.information(self, "Ask AI", "Add some text with the image so Ask AI knows what you want.")
            return
        if not query:
            return
        model_spec = self._feature_text_llm_spec("ask_ai_planner_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Ask AI"):
            return
        if not self.ai_query_history or self.ai_query_history[-1] != query:
            self.ai_query_history.append(query)
        self.ai_query_history_index = len(self.ai_query_history)
        self._stop_active_ai_workers()
        self.ai_query_request_id += 1
        request_id = self.ai_query_request_id
        self._pending_ai_query_plans.clear()
        with QSignalBlocker(self.card_search_input):
            self.card_search_input.clear()
        self._clear_ai_image()
        self.card_search_input.set_ai_mode(False)
        ai_settings = self.datastore.load_ai_settings()
        profile_context = self.datastore.load_profile()
        if self.ai_response_overlay is not None:
            self.ai_response_overlay.begin_stream()
        worker = AiSearchPlannerWorker(
            request_id=request_id,
            ollama=self.ollama,
            model=self._feature_text_model_tag("ask_ai_planner_context_length"),
            prompt=query,
            context_length=int(ai_settings.get("ask_ai_planner_context_length", ai_settings.get("discuss_context_length", 4400)) or 4400),
            profile_context=profile_context,
            image_paths=[image_path] if image_path else [],
            use_native_tools=bool(model_spec.supports_native_tools),
        )
        self.ai_query_planner_worker = worker
        self._ai_query_workers.add(worker)
        worker.failed.connect(self._on_ai_query_failed)
        worker.planned.connect(
            lambda _request_id, plan, original=query, images=[image_path] if image_path else []: self._on_ai_query_planned(
                _request_id, original, plan, images
            )
        )
        worker.failed.connect(lambda _request_id, _message, current=worker: self._cleanup_ai_planner_worker(current))
        worker.planned.connect(lambda _request_id, _plan, current=worker: self._cleanup_ai_planner_worker(current))
        worker.start()

    def _submit_wiki_query(self, query: str) -> None:
        if self.ai_query_image_path.strip():
            QMessageBox.information(self, "Wikipedia", "Wikipedia breakdown works from text topics, so remove the image first.")
            return
        if not query:
            return
        model_spec = self._feature_text_llm_spec("wiki_breakdown_context_length")
        model_tag = self._feature_text_model_tag("wiki_breakdown_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Wikipedia breakdown"):
            return
        if not self.ai_query_history or self.ai_query_history[-1] != query:
            self.ai_query_history.append(query)
        self.ai_query_history_index = len(self.ai_query_history)
        self._stop_active_ai_workers()
        self.ai_query_request_id += 1
        request_id = self.ai_query_request_id
        self._pending_ai_query_plans.clear()
        with QSignalBlocker(self.card_search_input):
            self.card_search_input.clear()
        self._clear_ai_image()
        self.card_search_input.set_ai_mode(False)

        if self.ai_response_overlay is not None:
            self.ai_response_overlay.begin_stream()
            self.ai_response_overlay.enable_wikipedia_tabs()
            self.ai_response_overlay.configure_wiki_short_summary_behavior(
                stream_in=self._wiki_short_summary_stream_model_enabled(model_spec.key, model_tag),
                chars_per_second=150.0,
                fade_seconds=0.34,
            )

        ai_settings = self.datastore.load_ai_settings()
        context_length = int(ai_settings.get("wiki_breakdown_context_length", 6000) or 6000)
        if model_spec.key == QN_SUMMARIZER_MODEL_KEY:
            context_length = QN_SUMMARIZER_CONTEXT_LENGTH
        profile_context = self.datastore.load_profile()
        self._wiki_gallery_images = []
        self._wiki_gallery_title = ""
        self._wiki_gallery_loading = True
        worker = WikipediaBreakdownWorker(
            request_id=request_id,
            ollama=self.ollama,
            model=model_tag,
            query=query,
            context_length=context_length,
            profile_context=profile_context,
            tone=str(ai_settings.get("ask_ai_tone", ai_settings.get("assistant_tone", ""))).strip().lower(),
            emoji_level=max(1, min(4, int(ai_settings.get("ask_ai_emoji_level", 2) or 2))),
        )
        self.wiki_breakdown_worker = worker
        self._ai_query_workers.add(worker)
        worker.failed.connect(self._on_ai_query_failed)
        worker.breakdown_started.connect(self._on_wiki_breakdown_started)
        worker.finished.connect(self._on_wiki_breakdown_finished)
        worker.failed.connect(lambda _request_id, _message, current=worker: self._cleanup_wiki_breakdown_worker(current))
        worker.finished.connect(lambda _request_id, _markdown, _short, current=worker: self._cleanup_wiki_breakdown_worker(current))
        worker.start()

    def _on_wiki_breakdown_started(self, request_id: int, article: object) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        if isinstance(article, dict):
            self._wiki_gallery_title = " ".join(str(article.get("title", "")).strip().split())
            self.ai_response_overlay.set_wikipedia_markdown(self._wiki_article_markdown(article))
            images_html, images_copy = AiResponseOverlay._wiki_images_html(
                {"title": self._wiki_gallery_title, "images": self._wiki_gallery_images},
                loading=True,
            )
            self.ai_response_overlay.set_wikipedia_images_html(images_html, copy_text=images_copy)
            worker = WikipediaImagesWorker(request_id=request_id, article_title=self._wiki_gallery_title)
            self.wiki_images_worker = worker
            self._ai_query_workers.add(worker)
            worker.image_loaded.connect(self._on_wiki_image_loaded)
            worker.finished.connect(self._on_wiki_images_finished)
            worker.failed.connect(self._on_wiki_images_failed)
            worker.finished.connect(lambda _request_id, current=worker: self._cleanup_wiki_images_worker(current))
            worker.failed.connect(lambda _request_id, _message, current=worker: self._cleanup_wiki_images_worker(current))
            worker.start()

    def _on_wiki_breakdown_finished(self, request_id: int, markdown_text: str, short_summary: str = "") -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        cleaned = (markdown_text or "").strip() or "### No answer\n- The model returned an empty response."
        self.ai_response_overlay.set_wikipedia_ai_markdown(cleaned)
        if short_summary:
            self.ai_response_overlay.show_wiki_short_summary(short_summary)

    def _on_wiki_image_loaded(self, request_id: int, image: object) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None or not isinstance(image, dict):
            return
        self._wiki_gallery_images.append(dict(image))
        images_html, images_copy = AiResponseOverlay._wiki_images_html(
            {"title": self._wiki_gallery_title, "images": self._wiki_gallery_images},
            loading=True,
        )
        self.ai_response_overlay.set_wikipedia_images_html(images_html, copy_text=images_copy)

    def _on_wiki_images_finished(self, request_id: int) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        self._wiki_gallery_loading = False
        images_html, images_copy = AiResponseOverlay._wiki_images_html(
            {"title": self._wiki_gallery_title, "images": self._wiki_gallery_images},
            loading=False,
        )
        self.ai_response_overlay.set_wikipedia_images_html(images_html, copy_text=images_copy)

    def _on_wiki_images_failed(self, request_id: int, _message: str) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        self._wiki_gallery_loading = False
        images_html, images_copy = AiResponseOverlay._wiki_images_html(
            {"title": self._wiki_gallery_title, "images": self._wiki_gallery_images},
            loading=False,
        )
        self.ai_response_overlay.set_wikipedia_images_html(images_html, copy_text=images_copy)

    @staticmethod
    def _wiki_article_markdown(article: dict) -> str:
        title = " ".join(str(article.get("title", "Wikipedia")).strip().split()) or "Wikipedia"
        url = str(article.get("url", "")).strip()
        extract = str(article.get("extract", "")).strip()
        thumbnail_path = str(article.get("thumbnail_path", "")).strip()
        parts = []
        if thumbnail_path and Path(thumbnail_path).exists():
            parts.extend([f"![{title}]({QUrl.fromLocalFile(thumbnail_path).toString()})", ""])
        parts.extend([f"# {title}", ""])
        parts.append(extract or "Wikipedia returned no readable article text.")
        if url:
            parts.extend(["", f"[view all in wikipedia]({url})"])
        return "\n".join(parts).strip()

    def _on_ai_query_planned(self, request_id: int, original_query: str, plan: dict, image_paths: list[str] | None = None) -> None:
        if request_id != self.ai_query_request_id:
            return
        needs_show_cards = bool(plan.get("needs_show_cards", False))
        search_query = " ".join(str(plan.get("search_query", "")).strip().split())
        research_message = " ".join(str(plan.get("research_message", "")).strip().split())
        reasoning_steps = [
            " ".join(str(message or "").strip().split())
            for message in plan.get("reasoning_steps", [])
            if str(message or "").strip()
        ][:2]
        overlay_messages = reasoning_steps + ([research_message] if needs_show_cards and research_message else [])
        if self.ai_response_overlay is not None and overlay_messages:
            self.ai_response_overlay.show_reasoning_messages(overlay_messages)
        if not needs_show_cards or str(plan.get("tool_name", "")).strip() != "ShowCards":
            self._start_ai_answer_worker(
                request_id,
                query=original_query,
                retrieved_cards=[],
                retrieval_query="",
                image_paths=image_paths,
                image_analysis=dict(plan.get("image_analysis", {}) or {}),
            )
            return
        self._pending_ai_query_plans[request_id] = {
            "original_query": original_query,
            "search_query": search_query or original_query,
            "research_message": research_message,
            "image_paths": list(image_paths or []),
            "image_analysis": dict(plan.get("image_analysis", {}) or {}),
        }
        worker = CardSearchWorker(
            request_id=request_id,
            query=search_query or original_query,
            cards=self.cards,
            embedding_service=self.embedding_service,
            limit=6,
            allow_semantic=self._neural_acceleration_enabled() and self.preflight.semantic_search_available(),
        )
        self.ai_query_tool_worker = worker
        worker.finished.connect(self._on_ai_show_cards_finished)
        worker.finished.connect(lambda _request_id, _query, _results, current=worker: self._cleanup_ai_tool_worker(current))
        worker.start()

    def _on_ai_show_cards_finished(self, request_id: int, query: str, scored_items: object) -> None:
        if request_id != self.ai_query_request_id:
            return
        plan = self._pending_ai_query_plans.pop(request_id, None)
        if not isinstance(plan, dict):
            return
        results = scored_items if isinstance(scored_items, list) else []
        retrieved_cards = self._build_ai_card_context(results, limit=6)
        self._start_ai_answer_worker(
            request_id,
            query=str(plan.get("original_query", "")).strip(),
            retrieved_cards=retrieved_cards,
            retrieval_query=" ".join(str(query or plan.get("search_query", "")).strip().split()),
            image_paths=list(plan.get("image_paths", []) or []),
            image_analysis=dict(plan.get("image_analysis", {}) or {}),
        )

    def _on_ai_query_failed(self, request_id: int, message: str) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        self._pending_ai_query_plans.pop(request_id, None)
        if getattr(self.ai_response_overlay, "_tab_mode", "") == "wiki" and not self.ai_response_overlay._tab_loading.get("wiki", True):
            self.ai_response_overlay.set_wikipedia_ai_markdown(f"### Unable to break down text\n- {message}")
            return
        self.ai_response_overlay.set_markdown(f"### Unable to answer\n- {message}")

    def _on_ai_query_finished(self, request_id: int, markdown_text: str) -> None:
        if request_id != self.ai_query_request_id or self.ai_response_overlay is None:
            return
        cleaned = (markdown_text or "").strip()
        if not cleaned:
            cleaned = "### No answer\n- The model returned an empty response."
        self.ai_response_overlay.set_markdown(cleaned)

    def _cleanup_ai_planner_worker(self, worker: AiSearchPlannerWorker) -> None:
        self._ai_query_workers.discard(worker)
        if self.ai_query_planner_worker is not worker:
            worker.deleteLater()
            return
        self.ai_query_planner_worker = None
        worker.deleteLater()

    def _cleanup_ai_answer_worker(self, worker: AiSearchAnswerWorker) -> None:
        self._ai_query_workers.discard(worker)
        if self.ai_query_answer_worker is not worker:
            worker.deleteLater()
            return
        self.ai_query_answer_worker = None
        worker.deleteLater()

    def _cleanup_ai_tool_worker(self, worker: CardSearchWorker) -> None:
        if self.ai_query_tool_worker is worker:
            self.ai_query_tool_worker = None
        worker.deleteLater()

    def _cleanup_wiki_breakdown_worker(self, worker: WikipediaBreakdownWorker) -> None:
        self._ai_query_workers.discard(worker)
        if self.wiki_breakdown_worker is not worker:
            worker.deleteLater()
            return
        self.wiki_breakdown_worker = None
        worker.deleteLater()

    def _cleanup_wiki_images_worker(self, worker: WikipediaImagesWorker) -> None:
        self._ai_query_workers.discard(worker)
        if self.wiki_images_worker is not worker:
            worker.deleteLater()
            return
        self.wiki_images_worker = None
        worker.deleteLater()

    @staticmethod
    def _wiki_short_summary_stream_model_enabled(model_key: str, model_tag: str) -> bool:
        normalized_key = str(model_key or "").strip().lower()
        normalized_tag = str(model_tag or "").strip().lower()
        return normalized_key == QN_SUMMARIZER_MODEL_KEY or "summarizer" in normalized_key or "summarizer" in normalized_tag

    def _close_ai_overlay(self) -> None:
        self.ai_query_request_id += 1
        self._pending_ai_query_plans.clear()
        self._stop_active_ai_workers()

    @staticmethod
    def _fallback_text_search(query: str, cards: list[dict]) -> list[dict]:
        normalized_query, terms = StudyTab._search_terms(query)
        if not normalized_query:
            return []

        scored: list[tuple[tuple[float, int, int, int], dict]] = []
        for card in cards:
            lexical_score, matched = StudyTab._lexical_search_score(normalized_query, terms, card)
            if not matched:
                continue
            title = str(card.get("title", "")).strip()
            question = str(card.get("question", "")).strip()
            scored.append(((lexical_score, -len(title), -len(question), -len(normalized_query)), card))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [card for _score, card in scored]

    @staticmethod
    def _search_terms(query: str) -> tuple[str, list[str]]:
        raw_terms = re.findall(r"[a-z0-9]+", query.lower())
        normalized_query = " ".join(raw_terms).strip()
        if not normalized_query:
            return "", []
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "define",
            "describe",
            "did",
            "do",
            "does",
            "explain",
            "for",
            "from",
            "how",
            "in",
            "into",
            "is",
            "it",
            "of",
            "on",
            "or",
            "the",
            "to",
            "was",
            "were",
            "what",
            "when",
            "where",
            "which",
            "why",
            "with",
        }
        filtered_terms = [term for term in raw_terms if len(term) > 2 and term not in stop_words]
        if filtered_terms:
            return normalized_query, filtered_terms
        return normalized_query, raw_terms

    @staticmethod
    def _lexical_search_score(normalized_query: str, terms: list[str], card: dict) -> tuple[float, bool]:
        title = " ".join(re.findall(r"[a-z0-9]+", str(card.get("title", "")).lower()))
        question = " ".join(re.findall(r"[a-z0-9]+", str(card.get("question", "")).lower()))
        answer = " ".join(re.findall(r"[a-z0-9]+", str(card.get("answer", "")).lower()))
        search_terms = card.get("search_terms", [])
        if not isinstance(search_terms, list):
            search_terms = []
        search_terms_text = " ".join(re.findall(r"[a-z0-9]+", " ".join(str(term) for term in search_terms).lower()))
        title_exact = 1 if normalized_query and title == normalized_query else 0
        title_phrase = 1 if normalized_query and normalized_query in title else 0
        content_phrase = 1 if normalized_query and (normalized_query in question or normalized_query in answer or normalized_query in search_terms_text) else 0
        title_hits = sum(1 for term in terms if term in title)
        content_hits = sum(1 for term in terms if term in question or term in answer or term in search_terms_text)
        full_title_term_match = 1 if terms and all(term in title for term in terms) else 0
        full_content_term_match = 1 if terms and all(term in question or term in answer or term in search_terms_text for term in terms) else 0
        matched = bool(
            title_exact
            or title_phrase
            or content_phrase
            or full_title_term_match
            or full_content_term_match
            or title_hits
            or content_hits
        )
        if not matched:
            return 0.0, False
        term_count = max(1, len(terms))
        score = (
            (1.2 * title_exact)
            + (0.95 * full_title_term_match)
            + (0.7 * title_phrase)
            + (0.45 * full_content_term_match)
            + (0.4 * content_phrase)
            + (0.32 * (title_hits / term_count))
            + (0.18 * (content_hits / term_count))
        )
        return score, True

    @classmethod
    def _build_card_search_results(
        cls,
        query: str,
        cards: list[dict],
        embedding_service: EmbeddingService,
        *,
        limit: int,
        allow_semantic: bool = True,
    ) -> list[dict]:
        query = query.strip()
        if not query:
            return []

        normalized_query, terms = cls._search_terms(query)
        semantic_results: list[dict] = []
        try:
            if not allow_semantic:
                raise RuntimeError("semantic-disabled")
            semantic = embedding_service.search_cards_by_text(query, cards, max_results=max(limit, len(cards)))
            best_score = float(semantic[0].score) if semantic else 0.0
            if best_score >= SEMANTIC_SEARCH_MIN_SCORE:
                score_floor = max(SEMANTIC_SEARCH_MIN_SCORE, best_score - SEMANTIC_SEARCH_SCORE_MARGIN)
                ranked: list[tuple[tuple[float, float], dict]] = []
                for item in semantic:
                    score = float(item.score)
                    if score < score_floor:
                        continue
                    lexical_score, _matched = cls._lexical_search_score(normalized_query, terms, item.card)
                    ranked.append(((score + (lexical_score * 0.15), score), item.card))
                ranked.sort(key=lambda item: item[0], reverse=True)
                semantic_results = [
                    {"card": card, "score": sort_key[1], "source": "semantic"}
                    for sort_key, card in ranked[:limit]
                ]
        except Exception:
            semantic_results = []

        if semantic_results:
            return semantic_results

        fallback = cls._fallback_text_search(query, cards)[:limit]
        return [{"card": card, "score": 0.0, "source": "fallback"} for card in fallback]

    @staticmethod
    def _fast_card_suggestions(query: str, cards: list[dict], limit: int = 5) -> list[dict]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []

        scored: list[tuple[tuple[int, int, int, int], dict]] = []
        for card in cards:
            title = str(card.get("title", "")).strip()
            title_lower = title.lower()
            question_lower = str(card.get("question", "")).lower()
            answer_lower = str(card.get("answer", "")).lower()
            search_terms_lower = " ".join(
                str(term).lower() for term in card.get("search_terms", []) if str(term).strip()
            )
            prefix_hits = sum(1 for term in terms if title_lower.startswith(term))
            title_hits = sum(1 for term in terms if term in title_lower)
            content_hits = sum(
                1
                for term in terms
                if term in question_lower or term in answer_lower or term in search_terms_lower
            )
            if prefix_hits == 0 and title_hits == 0 and content_hits == 0:
                continue
            scored.append(((prefix_hits, title_hits, content_hits, -len(title_lower)), card))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"card": card, "score": 0.0, "source": "fast"} for _score, card in scored[:limit]]

    def _is_global_all_view(self) -> bool:
        return (
            self.current_subject == "All Subjects"
            and self.current_category == "All"
            and self.current_subtopic == "All"
        )

    def _refresh_global_recommendations(self) -> None:
        attempts = self.datastore.load_attempts()
        signature = (len(self.cards), len(attempts))
        if signature == self._recommendation_signature:
            return
        self._recommendation_signature = signature
        if len(self.cards) <= 60 or not self.preflight.semantic_search_available():
            self.global_recommendations = []
            return
        self.global_recommendations = build_global_recommendations(
            self.cards,
            attempts,
            self.embedding_service,
            limit=10,
        )
        candidate_cards = recommendation_candidate_cards(self.cards, attempts)
        missing = [card for card in candidate_cards if not self.embedding_service.is_card_cached(card)]
        if missing:
            self._embed_remaining_cards_in_background(missing)

    def _render_recommendations(self) -> None:
        self._clear_layout(self.recommendation_grid)
        should_show = (
            not self.card_search_has_executed
            and self._is_global_all_view()
            and len(self.cards) > 60
            and bool(self.global_recommendations)
        )
        if not should_show:
            self.recommendation_block.hide()
            return

        visible_items = self.global_recommendations[:3]
        available_width = max(self._stable_card_content_width() - 44, 320)
        spacing = self.recommendation_grid.horizontalSpacing() or 16
        min_width = 300
        max_width = 380
        columns = max(1, min(3, len(visible_items), available_width // min_width))
        tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        while tile_width < min_width and columns > 1:
            columns -= 1
            tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        tile_width = max(min_width, min(max_width, tile_width))

        for idx, item in enumerate(visible_items):
            tile = CardTile(item.card)
            tile.set_tile_width(tile_width)
            tile.setToolTip(f"Related strong match similarity: {item.reason_similarity:.2f}")
            tile.selected.connect(self._card_selected)
            tile.move_requested.connect(self._move_card)
            tile.remove_requested.connect(self._remove_card)
            row = idx // columns
            col = idx % columns
            self.recommendation_grid.addWidget(tile, row, col)
        self.recommendation_block.show()

    def _stable_card_content_width(self) -> int:
        if not hasattr(self, "card_scroll"):
            return 300
        scroll = self.card_scroll
        scrollbar_width = max(
            scroll.verticalScrollBar().sizeHint().width(),
            scroll.style().pixelMetric(scroll.style().PixelMetric.PM_ScrollBarExtent),
        )
        available_width = scroll.width() - (scroll.frameWidth() * 2) - scrollbar_width
        viewport_margins = scroll.viewportMargins()
        available_width -= viewport_margins.left() + viewport_margins.right()
        return max(available_width, 300)

    def _compute_card_grid_metrics(self) -> tuple[int, int] | None:
        if not hasattr(self, "card_scroll"):
            return None
        available_width = max(self._stable_card_content_width() - 8, 300)
        min_width = 320
        max_width = 460
        spacing = self.card_grid.horizontalSpacing() or 18
        columns = max(1, min(4, available_width // min_width))
        tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        while tile_width < min_width and columns > 1:
            columns -= 1
            tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        tile_width = max(min_width, min(max_width, tile_width))
        return columns, tile_width

    def _add_card_tile(self, card: dict, index: int, *, columns: int, tile_width: int, animate: bool) -> None:
        tile = CardTile(card)
        tile.set_tile_width(tile_width)
        tile.selected.connect(self._card_selected)
        tile.move_requested.connect(self._move_card)
        tile.remove_requested.connect(self._remove_card)
        row = index // columns
        col = index % columns
        self.card_grid.addWidget(tile, row, col)
        if animate:
            self._animate_card_tile(tile, index)

    def _build_card_search_skeleton_tile(self, tile_width: int) -> QFrame:
        return CardSearchSkeletonTile(tile_width)

    def _on_card_search_skeleton_cycle_completed(self) -> None:
        if not self.card_search_loading:
            return
        self.card_search_skeleton_cycles += 1
        if self.card_search_skeleton_cycles >= self.CARD_SEARCH_SKELETON_MIN_CYCLES:
            self._apply_pending_card_search_results(self.card_search_request_id)

    def _show_card_search_skeleton(self) -> None:
        self.card_scroll.show()
        self.card_empty_state.hide()
        self.card_search_more_btn.hide()
        self.card_scroll.verticalScrollBar().setValue(0)
        metrics = self._compute_card_grid_metrics()
        if metrics is None:
            return
        columns, tile_width = metrics
        self._last_render_layout_signature = (columns, tile_width)
        skeleton_count = max(columns * 2, 4)
        for index in range(skeleton_count):
            row = index // columns
            col = index % columns
            tile = self._build_card_search_skeleton_tile(tile_width)
            if index == 0 and isinstance(tile, CardSearchSkeletonTile):
                tile.cycleCompleted.connect(self._on_card_search_skeleton_cycle_completed)
            self.card_grid.addWidget(tile, row, col)

    def _render_next_card_batch(self) -> None:
        if not self._card_stream_cards:
            return
        generation = self._card_stream_generation
        start = self._card_stream_next_index
        end = min(start + self.CARD_STREAM_BATCH_SIZE, len(self._card_stream_cards))
        for index in range(start, end):
            self._add_card_tile(
                self._card_stream_cards[index],
                index,
                columns=self._card_stream_columns,
                tile_width=self._card_stream_tile_width,
                animate=self._card_stream_animate,
            )
        self._card_stream_next_index = end
        if generation != self._card_stream_generation:
            return
        if self._card_stream_next_index < len(self._card_stream_cards):
            self.card_stream_timer.start(0)

    def _render_cards(self, animate_search_results: bool = False) -> None:
        self.card_stream_timer.stop()
        self._card_stream_generation += 1
        self._clear_grid()
        self.card_scroll.show()
        self.card_empty_state.hide()
        self.card_search_more_btn.hide()
        if self.card_search_loading:
            self._show_card_search_skeleton()
            return
        self._render_recommendations()
        if self.card_search_has_executed:
            all_cards = list(self.card_search_full_results)
            cards = all_cards[: self.card_search_result_limit]
        else:
            all_cards = self._filtered_cards()
            cards = all_cards[: self.card_render_limit]

        if not cards:
            if self.card_search_has_executed:
                self._show_card_empty_state()
                return
            empty_text = "No cards in this section yet."
            empty = QLabel(empty_text)
            empty.setObjectName("SectionText")
            empty.setAlignment(Qt.AlignCenter)
            self.card_grid.addWidget(empty, 0, 0, 1, 4)
            return

        metrics = self._compute_card_grid_metrics()
        if metrics is None:
            return
        columns, tile_width = metrics
        self._last_render_layout_signature = (columns, tile_width)

        self._card_search_animations = []
        self._card_stream_cards = list(cards)
        self._card_stream_columns = columns
        self._card_stream_tile_width = tile_width
        self._card_stream_next_index = 0
        self._card_stream_animate = animate_search_results
        initial_batch = min(len(self._card_stream_cards), self.CARD_INITIAL_STREAM_BATCH)
        for idx in range(initial_batch):
            self._add_card_tile(
                self._card_stream_cards[idx],
                idx,
                columns=columns,
                tile_width=tile_width,
                animate=animate_search_results,
            )
        self._card_stream_next_index = initial_batch
        if self._card_stream_next_index < len(self._card_stream_cards):
            self.card_stream_timer.start(0)
        if len(all_cards) > len(cards):
            if self.card_search_has_executed:
                self.card_search_more_btn.setText(f"See more results ({len(cards)}/{len(all_cards)})")
            else:
                self.card_search_more_btn.setText(f"Load more cards ({len(cards)}/{len(all_cards)})")
            self.card_search_more_btn.show()

    def _show_card_empty_state(self) -> None:
        image_path = self.datastore.paths.banners / "cards_search_empty_1x1.png"
        self.card_scroll.hide()
        self.card_empty_state.setMinimumHeight(0)
        self.card_empty_state.setMaximumHeight(16777215)
        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            self.card_empty_image.setPixmap(pixmap.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.card_empty_image.show()
        else:
            self.card_empty_image.hide()
        self.card_empty_title.setText("Try another search")
        self.card_empty_note.setText("Use a more direct topic, keyword, or idea from the card.")
        self.card_empty_state.show()

    def _animate_card_tile(self, tile: QWidget, index: int) -> None:
        opacity = QGraphicsOpacityEffect(tile)
        opacity.setOpacity(0.0)
        tile.setGraphicsEffect(opacity)

        opacity_anim = QVariantAnimation(tile)
        opacity_anim.setDuration(170)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        opacity_anim.valueChanged.connect(lambda value, effect=opacity: effect.setOpacity(float(value)))

        group = QParallelAnimationGroup(tile)
        group.addAnimation(opacity_anim)
        group.finished.connect(lambda current=tile, effect=opacity: current.setGraphicsEffect(None) if current.graphicsEffect() is effect else None)
        self._card_search_animations.append(group)
        QTimer.singleShot(index * 24, group.start)

    def _move_card(self, card: dict) -> None:
        self._play_sound("click")
        dialog = MoveCardDialog(card, self.datastore)
        if dialog.exec():
            self.reload_cards(force=True)

    def _remove_card(self, card: dict) -> None:
        self._play_sound("click")
        answer = QMessageBox.question(
            self,
            "Remove card",
            "Remove this card permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.datastore.delete_card(
            str(card.get("id", "")),
            str(card.get("subject", "Mathematics")),
        )
        if not deleted:
            QMessageBox.warning(self, "Remove failed", "Could not remove that card.")
            return
        self._remove_card_from_session(card)
        self.reload_cards(force=True)

    def _card_selected(self, card: dict) -> None:
        self._play_sound("click")
        answer = QMessageBox.question(
            self,
            "Start from here",
            "Do you want to start from here?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._begin_session_pool(self._filtered_cards(), first_card=card)

    def _open_start_dialog(self) -> None:
        self._play_sound("click")
        pool = self._filtered_cards()
        if not pool:
            return
        dialog = StartStudyDialog(self._current_path_label(), len(pool))
        if dialog.exec():
            self._play_sound("click")
            self._begin_session_pool(pool)

    def _begin_session_pool(self, pool: list[dict], first_card: dict | None = None) -> None:
        if not pool:
            return
        self._cancel_session_prep()
        cards = list(pool)
        random.shuffle(cards)
        if first_card is not None:
            cards = [card for card in cards if card.get("id") != first_card.get("id")]
            cards.insert(0, first_card)
        self.session_id = str(uuid.uuid4())
        self.study_state = None
        self.session_queue = list(cards)
        self.session_cards = list(cards)
        self.session_scores = []
        self.session_temp_batches = {}
        self.session_history = []
        self.current_history_index = -1
        self.queued_grade_indexes = []
        self.active_queue_entry_index = -1
        self.session_end_requested = False
        self.session_prep_remaining_cards = []
        self._switch_mode(1)
        seed_cards: list[dict] = []
        should_prepare_async = False
        if len(cards) > 5:
            self.study_state = build_session_state(cards, self._current_path_label())
            if not self.preflight.semantic_search_available():
                self.study_state.nna_enabled = False
            should_prepare_async = bool(self.study_state.nna_enabled)
            seed_cards = [self.study_state.card_lookup[card_id] for card_id in self.study_state.seed_ids if card_id in self.study_state.card_lookup]
            if first_card is not None:
                first_id = str(first_card.get("id", ""))
                self.study_state.seed_ids = [card_id for card_id in self.study_state.seed_ids if card_id != first_id]
                self.study_state.seed_ids.insert(0, first_id)
                seed_cards = [card for card in seed_cards if str(card.get("id", "")) != str(first_card.get("id", ""))]
                seed_cards.insert(0, first_card)
            remaining = [card for card in cards if not self.embedding_service.is_card_cached(card)]
            self.session_prep_remaining_cards = [
                card for card in remaining if str(card.get("id", "")) not in {str(seed.get("id", "")) for seed in seed_cards}
            ]
        self._advance_session()
        if should_prepare_async:
            self._start_session_prep(cards, seed_cards)

    def _advance_session(self) -> None:
        self._sync_current_entry_snapshot()
        if self.current_history_index < len(self.session_history) - 1:
            self._show_history_entry(self.current_history_index + 1)
            return
        if self.study_state and self.study_state.nna_enabled:
            card = next_card_for_session(self.study_state, self.embedding_service)
            if card is None:
                if self._has_pending_background_grading():
                    self.session_end_requested = True
                    self.grade_summary.setText("Finishing session...")
                    self.grade_feedback.setMarkdown("### Finalizing\nWaiting for queued grading to finish.")
                    self._set_followup_visible(False)
                    self._update_study_controls()
                    return
                self._finish_session()
                return
            self._start_session(card)
            return
        if not self.session_queue:
            if self._has_pending_background_grading():
                self.session_end_requested = True
                self.grade_summary.setText("Finishing session...")
                self.grade_feedback.setMarkdown("### Finalizing\nWaiting for queued grading to finish.")
                self._set_followup_visible(False)
                self._update_study_controls()
                return
            self._finish_session()
            return
        self._start_session(self.session_queue.pop(0))

    def _start_session(self, card: dict) -> None:
        session_entry = SessionCardEntry(card=card) if self.study_state and self.study_state.nna_enabled else None
        if session_entry is not None:
            self.study_state.shown_entries.append(session_entry)
        entry = {
            "card": card,
            "answer_text": "",
            "hints_used": 0,
            "grade_report": None,
            "review_markdown": "",
            "status": "fresh",
            "attempt_logged": False,
            "session_entry": session_entry,
        }
        self.session_history.append(entry)
        self._show_history_entry(len(self.session_history) - 1)

    def _cancel_session_prep(self) -> None:
        if self.session_prep_worker and self.session_prep_worker.isRunning():
            self.session_prep_worker.requestInterruption()
        self.session_prep_worker = None
        if self.topic_cluster_worker and self.topic_cluster_worker.isRunning():
            self.topic_cluster_worker.requestInterruption()
        self.topic_cluster_worker = None
        self.pending_cluster_refresh = False
        self.session_prep_remaining_cards = []
        if self.session_prep_dialog is not None:
            self.session_prep_dialog.close()
            self.session_prep_dialog.deleteLater()
            self.session_prep_dialog = None

    def _ensure_session_prep_dialog(self) -> SessionPrepDialog:
        if self.session_prep_dialog is None:
            self.session_prep_dialog = SessionPrepDialog(self.icons)
        return self.session_prep_dialog

    def _start_session_prep(self, cards: list[dict], seed_cards: list[dict]) -> None:
        dialog = self._ensure_session_prep_dialog()
        dialog.set_progress(5)
        dialog.update_step("seed", "Preparing your first cards in the background...", False)
        dialog.update_step("topics", "Waiting for seed cards...", False)
        dialog.update_step("launch", "First question is ready. Finishing the smart queue in background...", True)
        dialog.show()
        QApplication.processEvents()

        worker = SessionPrepWorker(
            session_id=self.session_id,
            cards=cards,
            seed_cards=seed_cards,
            embedding_service=self.embedding_service,
        )
        self.session_prep_worker = worker
        worker.progress.connect(self._on_session_prep_progress)
        worker.finished.connect(self._on_session_prep_finished)
        worker.failed.connect(self._on_session_prep_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _session_prep_progress_value(self, key: str, current: int, total: int) -> int:
        safe_total = max(1, total)
        safe_current = max(0, min(current, safe_total))
        if key == "seed":
            return 5 + int((safe_current / safe_total) * 65)
        if key == "topics":
            return 70 + int((safe_current / safe_total) * 25)
        if key == "launch":
            return 95 + int((safe_current / safe_total) * 5)
        return 0

    def _on_session_prep_progress(
        self,
        session_id: str,
        key: str,
        message: str,
        current: int,
        total: int,
        done: bool,
    ) -> None:
        if session_id != self.session_id:
            return
        dialog = self._ensure_session_prep_dialog()
        dialog.update_step(key, message, done)
        dialog.set_progress(self._session_prep_progress_value(key, current, total))

    def _on_session_prep_finished(self, session_id: str, cluster_map: object) -> None:
        if session_id != self.session_id:
            return
        self.session_prep_worker = None
        if self.study_state and isinstance(cluster_map, dict):
            self.study_state.cluster_map = {str(key): str(value) for key, value in cluster_map.items()}
        dialog = self._ensure_session_prep_dialog()
        dialog.update_step("launch", "Study session ready.", True)
        dialog.set_progress(100)
        QTimer.singleShot(500, self._close_session_prep_dialog)
        if self.session_prep_remaining_cards:
            remaining = list(self.session_prep_remaining_cards)
            self.session_prep_remaining_cards = []
            self._embed_remaining_cards_in_background(remaining)

    def _on_session_prep_failed(self, session_id: str, message: str) -> None:
        if session_id != self.session_id:
            return
        self.session_prep_worker = None
        self._close_session_prep_dialog()
        QMessageBox.warning(self, "Session prep failed", message)

    def _close_session_prep_dialog(self) -> None:
        if self.session_prep_dialog is None:
            return
        self.session_prep_dialog.close()
        self.session_prep_dialog.deleteLater()
        self.session_prep_dialog = None

    def _schedule_topic_cluster_refresh(self) -> None:
        if not self.study_state or not self.study_state.nna_enabled:
            return
        if self.topic_cluster_worker and self.topic_cluster_worker.isRunning():
            self.pending_cluster_refresh = True
            return
        self.pending_cluster_refresh = False
        worker = TopicClusterWorker(
            session_id=self.session_id,
            cards=list(self.study_state.cards),
            embedding_service=self.embedding_service,
        )
        self.topic_cluster_worker = worker
        worker.finished.connect(self._on_topic_cluster_refresh_finished)
        worker.failed.connect(self._on_topic_cluster_refresh_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_topic_cluster_refresh_finished(self, session_id: str, cluster_map: object) -> None:
        if session_id == self.session_id and self.study_state and isinstance(cluster_map, dict):
            self.study_state.cluster_map = {str(key): str(value) for key, value in cluster_map.items()}
        self.topic_cluster_worker = None
        if self.pending_cluster_refresh and session_id == self.session_id:
            self.pending_cluster_refresh = False
            self._schedule_topic_cluster_refresh()

    def _on_topic_cluster_refresh_failed(self, session_id: str, _message: str) -> None:
        self.topic_cluster_worker = None
        if self.pending_cluster_refresh and session_id == self.session_id:
            self.pending_cluster_refresh = False
            self._schedule_topic_cluster_refresh()

    def _ensure_seed_embeddings(self, cards: list[dict], dialog: SessionPrepDialog | None = None) -> bool:
        if not self.preflight.semantic_search_available():
            if dialog is not None:
                dialog.update_step("seed", "Semantic warmup skipped because the embedding model is not installed.", True)
            return True
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            if dialog is not None:
                dialog.update_step("seed", "Seed cards already had embeddings.", True)
                QApplication.processEvents()
            return True

        total = len(missing)
        try:
            for index, card in enumerate(missing, start=1):
                label = str(card.get("title") or card.get("question") or "Card").strip() or "Card"
                if dialog is not None:
                    dialog.update_step("seed", f"Embedding seed cards... ({index}/{total}) {label}", False)
                    QApplication.processEvents()
                self.embedding_service.ensure_card_embedding(card)
        except Exception as exc:
            QMessageBox.warning(self, "Embedding unavailable", str(exc))
            return False
        return True

    def _embed_remaining_cards_in_background(self, cards: list[dict]) -> None:
        if not self.preflight.semantic_search_available():
            return
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            self._schedule_topic_cluster_refresh()
            return
        if self.embedding_worker and self.embedding_worker.isRunning():
            return
        self.embedding_worker = EmbeddingWorker(cards=missing, embedding_service=self.embedding_service)
        self.embedding_worker.finished.connect(self._on_background_embeddings_finished)
        self.embedding_worker.failed.connect(lambda _message: self._on_background_embeddings_finished([]))
        self.embedding_worker.start()

    def _on_background_embeddings_finished(self, _cards: list[dict]) -> None:
        self.embedding_worker = None
        self._schedule_topic_cluster_refresh()
        self._refresh_global_recommendations()
        if _cards and self.card_search_input.text().strip():
            self._execute_card_search()
            return
        self._render_cards()

    def _set_followup_visible(self, visible: bool) -> None:
        self.followup_title.hide()
        self.followup_shell.setVisible(visible)
        self._sync_followup_model_button()

    def _build_followup_context(self) -> str:
        if not self.current_card:
            return ""
        parts = [
            f"Question: {self.current_card.get('question', '')}",
            f"Expected answer: {self.current_card.get('answer', '')}",
            f"Hints: {', '.join(self.current_card.get('hints', []))}",
        ]
        if self.last_grade_report:
            parts.extend(
                [
                    f"Score: {self.last_grade_report.get('marks_out_of_10', '')}",
                    f"What went good: {self.last_grade_report.get('what_went_good', '')}",
                    f"What went bad: {self.last_grade_report.get('what_went_bad', '')}",
                    f"What to improve: {self.last_grade_report.get('what_to_improve', '')}",
                ]
            )
        return "\n".join(parts) + "\n"

    def _ask_i_dont_know(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        self._set_followup_visible(True)
        self.followup_title.setText("Follow up on this card")
        self.followup_input.setPlainText("Thoroughly explain this to me step by step")
        self.grade_summary.setText("Study help")
        self.grade_feedback.setMarkdown("### Study help\nWorking on a step-by-step explanation...")
        self._run_followup(auto_prompt="Thoroughly explain this to me step by step")

    def _show_hint(self) -> None:
        if not self.current_card:
            return
        hints = self.current_card.get("hints", [])
        if self.hint_cooldown > 0:
            return
        if self.revealed_hints >= len(hints):
            self.hint_status.setText("No more hints for this card.")
            self.hint_btn.setEnabled(False)
            return
        self.revealed_hints += 1
        visible = hints[: self.revealed_hints]
        self.hints_text.setPlainText("\n".join(f"{idx + 1}. {hint}" for idx, hint in enumerate(visible)))
        if self.revealed_hints < len(hints):
            self.hint_cooldown = 30
            self.hint_btn.setEnabled(False)
            self.hint_status.setText("Next hint in 30s.")
            self.cooldown_timer.start(1000)
        else:
            self.hint_status.setText("All hints revealed.")
            self.hint_btn.setEnabled(False)

    def _tick_hint_cooldown(self) -> None:
        if self.hint_cooldown <= 0:
            self.cooldown_timer.stop()
            self.hint_btn.setEnabled(True)
            self.hint_status.setText("You can reveal the next hint now.")
            return
        self.hint_cooldown -= 1
        self.hint_status.setText(f"Next hint in {self.hint_cooldown}s.")

    def _save_attempt_for_entry(self, entry: dict, graded: bool, grade_payload: dict | None = None) -> None:
        card = entry.get("card")
        if not isinstance(card, dict):
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "card_id": card.get("id"),
            "subject": card.get("subject"),
            "category": card.get("category"),
            "subtopic": card.get("subtopic"),
            "question": card.get("question"),
            "answer_text": str(entry.get("answer_text", "")).strip(),
            "hints_used": int(entry.get("hints_used", 0)),
            "graded": graded,
            "temporary": bool(card.get("temporary", False)),
        }
        if self.study_state:
            payload["topic_cluster_key"] = card_cluster_key(self.study_state, card)
        if grade_payload:
            payload.update(grade_payload)
        if payload.get("temporary"):
            self._record_temp_attempt(card, payload)
            return
        self.datastore.save_attempt(payload)

    def _save_attempt(self, graded: bool, grade_payload: dict | None = None) -> None:
        entry = self._current_history_entry()
        if entry is None:
            return
        self._sync_current_entry_snapshot()
        self._save_attempt_for_entry(entry, graded, grade_payload)

    def _record_temp_attempt(self, card: dict, payload: dict) -> None:
        batch_id = str(card.get("temp_batch_id", "")).strip()
        if not batch_id:
            self.datastore.save_attempt(payload)
            return
        batch = self.session_temp_batches.setdefault(
            batch_id,
            {
                "expected_count": 4,
                "attempts": [],
                "card_ids": set(),
            },
        )
        card_id = str(payload.get("card_id", "")).strip()
        batch["card_ids"].add(card_id)
        batch["attempts"] = [item for item in batch["attempts"] if str(item.get("card_id", "")).strip() != card_id]
        batch["attempts"].append(payload)
        if len(batch["attempts"]) >= int(batch.get("expected_count", 4)):
            self._finalize_temp_batch(batch_id)

    def _finalize_temp_batch(self, batch_id: str) -> None:
        batch = self.session_temp_batches.get(batch_id)
        if not batch:
            return
        attempts = list(batch.get("attempts", []))
        weak_attempts = [item for item in attempts if item.get("marks_out_of_10") is not None and float(item.get("marks_out_of_10") or 0) <= 5.0]
        if len(weak_attempts) >= 2:
            self.datastore.save_attempts(attempts)
        elif len(weak_attempts) == 1:
            self.datastore.save_attempt(weak_attempts[0])
        del self.session_temp_batches[batch_id]

    @staticmethod
    def _should_grade_answer_on_next(answer_text: str) -> bool:
        text = answer_text.strip()
        if not text:
            return False
        return not GradeWorker._is_inappropriate_or_garbage(text)

    def _set_grading_busy_state(self, busy: bool) -> None:
        self.answer_input.setEnabled(not busy)
        self.idk_btn.setEnabled(not busy)
        self.next_btn.setEnabled(not busy)

    def _queue_grade_entry(self, entry_index: int) -> None:
        entry = self._history_entry(entry_index)
        if entry is None:
            return
        if entry.get("status") in {"queued", "grading", "done"}:
            return
        entry["status"] = "queued"
        if entry_index not in self.queued_grade_indexes:
            self.queued_grade_indexes.append(entry_index)
        if self.current_history_index == entry_index:
            self._show_history_entry(entry_index)
        self._process_grade_queue()

    def _process_grade_queue(self) -> None:
        if self.queued_grade_worker is not None:
            return
        while self.queued_grade_indexes:
            entry_index = self.queued_grade_indexes.pop(0)
            entry = self._history_entry(entry_index)
            if entry is None:
                continue
            if str(entry.get("status", "")) not in {"queued", "grading"}:
                continue
            card = entry.get("card")
            if not isinstance(card, dict):
                continue
            entry["status"] = "grading"
            self.active_queue_entry_index = entry_index
            model_spec = self._feature_text_llm_spec("grading_context_length")
            worker = GradeWorker(
                question=card.get("question", ""),
                expected_answer=self._card_expected_answer(card, self.datastore, self._feature_text_model_tag("grading_context_length")),
                user_answer=str(entry.get("answer_text", "")).strip(),
                difficulty=int(card.get("natural_difficulty", 5)),
                ollama=self.ollama,
                model=self._feature_text_model_tag("grading_context_length"),
                profile_context=self.datastore.load_profile(),
                context_length=int(self.datastore.load_ai_settings().get("grading_context_length", 8192) or 8192),
                stream_preview=False,
            )
            self.queued_grade_worker = worker
            worker.status.connect(lambda _message: self._refresh_pending_entry(entry_index))
            worker.finished.connect(lambda report, idx=entry_index: self._on_queued_grade_done(idx, report))
            worker.failed.connect(lambda message, idx=entry_index: self._on_queued_grade_failed(idx, message))
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            worker.start()
            if self.current_history_index == entry_index:
                self._show_history_entry(entry_index)
            self._update_study_controls()
            return
        self.active_queue_entry_index = -1
        if self.session_end_requested:
            self.session_end_requested = False
            self._finish_session()
            return
        self._update_study_controls()

    def _refresh_pending_entry(self, entry_index: int) -> None:
        entry = self._history_entry(entry_index)
        if entry is None:
            return
        if entry.get("status") == "queued":
            entry["status"] = "grading"
        if self.current_history_index == entry_index:
            self._show_history_entry(entry_index)
        else:
            self._update_study_controls()

    def _start_grade_request(self) -> bool:
        entry = self._current_history_entry()
        if entry is None or not self.current_card:
            return False
        model_spec = self._feature_text_llm_spec("grading_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Grading"):
            return False
        self._sync_current_entry_snapshot()
        user_answer = str(entry.get("answer_text", "")).strip()
        if not user_answer:
            return False
        if self.grade_worker and self.grade_worker.isRunning():
            return False
        if self._has_pending_background_grading():
            return False

        entry["status"] = "grading"
        self._set_grading_busy_state(True)
        self._set_followup_visible(False)
        self.grade_feedback.clear()
        self.grade_summary.setText("Grading...")

        worker = GradeWorker(
            question=self.current_card.get("question", ""),
            expected_answer=self._card_expected_answer(self.current_card, self.datastore, self._feature_text_model_tag("grading_context_length")),
            user_answer=user_answer,
            difficulty=int(self.current_card.get("natural_difficulty", 5)),
            ollama=self.ollama,
            model=self._feature_text_model_tag("grading_context_length"),
            profile_context=self.datastore.load_profile(),
            context_length=int(self.datastore.load_ai_settings().get("grading_context_length", 8192) or 8192),
            stream_preview=True,
        )
        self.grade_worker = worker
        worker.stream.connect(self._on_grade_stream)
        worker.status.connect(self.grade_summary.setText)
        worker.finished.connect(lambda report, idx=self.current_history_index: self._on_grade_done(idx, report))
        worker.failed.connect(lambda message, idx=self.current_history_index: self._on_grade_failed(idx, message))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()
        return True

    def _grade(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        user_answer = self.answer_input.toPlainText().strip()
        if not user_answer:
            QMessageBox.warning(self, "Missing answer", "Write an answer before grading.")
            return
        self._start_grade_request()

    def _on_grade_stream(self, markdown_text: str) -> None:
        self.grade_feedback.setMarkdown(markdown_text)

    def _apply_grade_result(self, entry: dict, report: dict) -> None:
        score = float(report.get("marks_out_of_10", 0) or 0)
        entry["grade_report"] = report
        entry["review_markdown"] = self._format_review_markdown(report)
        entry["status"] = "done"
        entry["attempt_logged"] = True
        self.last_grade_report = report
        self.session_scores.append(score)
        self._save_attempt_for_entry(entry, graded=True, grade_payload=report)
        self._refresh_global_recommendations()
        if self.study_state:
            card = entry.get("card")
            session_entry = entry.get("session_entry")
            if isinstance(card, dict):
                result = register_grade_result(self.study_state, card, report)
                if isinstance(session_entry, SessionCardEntry):
                    session_entry.grade_report = report
                mark_card_completed(self.study_state, card)
                if result["weak"]:
                    enqueue_similar_cards(self.study_state, card, self.embedding_service)
                if result["trigger_reinforcement"] and card == self.current_card:
                    self._ask_reinforcement_permission(result["cluster_key"])

    def _mark_entry_grade_failed(self, entry: dict, message: str, *, save_ungraded: bool) -> None:
        entry["status"] = "error"
        entry["review_markdown"] = f"### Grading failed\n{message}"
        if save_ungraded and not entry.get("attempt_logged", False):
            self._save_attempt_for_entry(entry, graded=False, grade_payload={"marks_out_of_10": None, "how_good": None})
            entry["attempt_logged"] = True

    def _on_grade_done(self, entry_index: int, report: dict) -> None:
        self.grade_worker = None
        entry = self._history_entry(entry_index)
        self._set_grading_busy_state(False)
        if entry is not None:
            self._apply_grade_result(entry, report)
        self._show_history_entry(entry_index if entry is not None else self.current_history_index)

    def _ask_reinforcement_permission(self, cluster_key: str) -> None:
        if not self.current_card or self.reinforcement_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            "Reinforcement available",
            "ONCard detected repeated weakness in this topic. Generate 4 temporary reinforcement questions now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        self._run_reinforcement(cluster_key)

    def _run_reinforcement(self, cluster_key: str) -> None:
        if not self.current_card or not self.study_state:
            return
        model_spec = self._feature_text_llm_spec("reinforcement_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Reinforcement"):
            return
        related_cards = self._cluster_cards(cluster_key)
        recent_incorrect = [
            attempt
            for attempt in self.datastore.load_attempts()[-12:]
            if attempt.get("session_id") == self.session_id
            and attempt.get("topic_cluster_key") == cluster_key
            and attempt.get("how_good") is not None
            and float(attempt.get("how_good") or 0.0) < 88.8888
        ]
        ai_settings = self.datastore.load_ai_settings()
        dialog = ReinforcementProgressDialog(self.icons)
        self.reinforcement_dialog = dialog
        dialog.show()
        QApplication.processEvents()

        worker = ReinforcementWorker(
            ollama=self.ollama,
            weak_card=self.current_card,
            similar_cards=related_cards,
            recent_incorrect_answers=recent_incorrect,
            profile_context=self.datastore.load_profile(),
            assistant_tone=str(ai_settings.get("assistant_tone", "")),
            context_length=int(ai_settings.get("reinforcement_context_length", 8192) or 8192),
            model=self._feature_text_model_tag("reinforcement_context_length"),
        )
        self.reinforcement_worker = worker

        worker.progress.connect(self._on_reinforcement_progress)
        worker.finished.connect(self._on_reinforcement_finished)
        worker.failed.connect(self._on_reinforcement_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()
        self.pending_reinforcement_cluster_key = cluster_key

    def _on_reinforcement_progress(self, step_key: str, message: str, done: bool) -> None:
        if self.reinforcement_dialog is not None:
            self.reinforcement_dialog.update_step(step_key, message, done)

    def _on_reinforcement_finished(self, cards: list[dict]) -> None:
        self.reinforcement_worker = None
        temp_cards = list(cards or [])
        self.pending_reinforcement_cards = temp_cards
        if self.reinforcement_dialog is not None:
            self.reinforcement_dialog.update_step("embedding", "Embedding temporary cards...", False)
        if not temp_cards or not self.preflight.semantic_search_available():
            self._finalize_reinforcement_cards()
            return
        missing = [card for card in temp_cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            self._finalize_reinforcement_cards()
            return
        worker = EmbeddingWorker(cards=missing, embedding_service=self.embedding_service)
        self.reinforcement_embedding_worker = worker
        worker.progress.connect(self._on_reinforcement_embedding_progress)
        worker.finished.connect(self._on_reinforcement_embedding_finished)
        worker.failed.connect(self._on_reinforcement_embedding_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_reinforcement_failed(self, message: str) -> None:
        self.reinforcement_worker = None
        self.pending_reinforcement_cards = []
        self.pending_reinforcement_cluster_key = ""
        self._close_reinforcement_dialog()
        QMessageBox.warning(self, "Reinforcement failed", message)

    def _on_reinforcement_embedding_progress(self, label: str, index: int, total: int) -> None:
        if self.reinforcement_dialog is not None:
            self.reinforcement_dialog.update_step("embedding", f"Embedding temporary cards... ({index}/{total}) {label}", False)

    def _on_reinforcement_embedding_finished(self, _cards: list[dict]) -> None:
        self.reinforcement_embedding_worker = None
        self._finalize_reinforcement_cards()

    def _on_reinforcement_embedding_failed(self, message: str) -> None:
        self.reinforcement_embedding_worker = None
        self.pending_reinforcement_cards = []
        self.pending_reinforcement_cluster_key = ""
        self._close_reinforcement_dialog()
        QMessageBox.warning(self, "Embedding unavailable", message)

    def _finalize_reinforcement_cards(self) -> None:
        dialog = self.reinforcement_dialog
        if dialog is not None:
            dialog.update_step("embedding", "Embedding temporary cards...", True)
            dialog.update_step("adding", "Adding to session...", False)
        temp_cards = list(self.pending_reinforcement_cards)
        cluster_key = self.pending_reinforcement_cluster_key
        self.pending_reinforcement_cards = []
        self.pending_reinforcement_cluster_key = ""
        if temp_cards and self.study_state is not None:
            batch_id = str(uuid.uuid4())
            for card in temp_cards:
                card["temp_batch_id"] = batch_id
            self.session_temp_batches[batch_id] = {"expected_count": len(temp_cards), "attempts": [], "card_ids": set()}
            self.session_cards.extend(temp_cards)
            queue_reinforcement_cards(self.study_state, temp_cards, cluster_key)
            self._schedule_topic_cluster_refresh()
        if dialog is not None:
            dialog.update_step("adding", "Adding to session...", True)
        self._close_reinforcement_dialog()

    def _close_reinforcement_dialog(self) -> None:
        if self.reinforcement_dialog is None:
            return
        self.reinforcement_dialog.close()
        self.reinforcement_dialog.deleteLater()
        self.reinforcement_dialog = None

    def _cluster_cards(self, cluster_key: str) -> list[dict]:
        if not self.study_state:
            return []
        return [
            card
            for card in self.study_state.cards
            if card_cluster_key(self.study_state, card) == cluster_key and str(card.get("id", "")) != str(self.current_card.get("id", ""))
        ]

    def _on_queued_grade_done(self, entry_index: int, report: dict) -> None:
        self.queued_grade_worker = None
        self.active_queue_entry_index = -1
        entry = self._history_entry(entry_index)
        if entry is not None:
            self._apply_grade_result(entry, report)
            if self.current_history_index == entry_index:
                self._show_history_entry(entry_index)
        self._process_grade_queue()

    def _on_queued_grade_failed(self, entry_index: int, message: str) -> None:
        self.queued_grade_worker = None
        self.active_queue_entry_index = -1
        entry = self._history_entry(entry_index)
        if entry is not None:
            self._mark_entry_grade_failed(entry, message, save_ungraded=True)
            if self.current_history_index == entry_index:
                self._show_history_entry(entry_index)
        self._process_grade_queue()

    def _on_grade_failed(self, entry_index: int, message: str) -> None:
        self.grade_worker = None
        self._set_grading_busy_state(False)
        entry = self._history_entry(entry_index)
        if entry is not None:
            entry["status"] = "fresh"
        self.grade_summary.setText("Grading failed.")
        self.grade_feedback.setPlainText(message)
        self._set_followup_visible(False)
        self._update_study_controls()

    def _init_followup_feedback_browser(self, browser: QTextBrowser) -> None:
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setStyleSheet(
            """
            QTextBrowser {
                background: transparent;
                border: none;
                color: #22384c;
                padding: 0;
            }
            QTextBrowser > QWidget {
                background: transparent;
                border: none;
            }
            """
        )
        browser.viewport().setAutoFillBackground(False)
        browser.document().setDocumentMargin(0)
        bar = browser.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self._on_followup_feedback_scroll_changed)

    @staticmethod
    def _compute_followup_changed_span(previous: str, current: str) -> tuple[int, int] | None:
        if previous == current:
            return None
        max_prefix = min(len(previous), len(current))
        prefix = 0
        while prefix < max_prefix and previous[prefix] == current[prefix]:
            prefix += 1
        prev_suffix = len(previous)
        curr_suffix = len(current)
        while prev_suffix > prefix and curr_suffix > prefix and previous[prev_suffix - 1] == current[curr_suffix - 1]:
            prev_suffix -= 1
            curr_suffix -= 1
        if curr_suffix <= prefix:
            return None
        return prefix, curr_suffix

    def _set_followup_fade_span_alpha(self, start: int, end: int, alpha: int) -> None:
        document = self.grade_feedback.document()
        max_pos = max(0, document.characterCount() - 1)
        if start < 0:
            start = 0
        if start > max_pos:
            return
        end = min(end, max_pos)
        if end <= start:
            return
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(34, 56, 76, max(0, min(255, alpha))))
        cursor.mergeCharFormat(fmt)

    def _stop_followup_char_fades(self) -> None:
        for animation, _start, _end in self._followup_char_fades:
            animation.stop()
        self._followup_char_fades.clear()

    def _animate_followup_text_fade(self, start: int, end: int) -> None:
        if end <= start:
            return
        app = QApplication.instance()
        if app is not None and bool(app.property("reducedMotion")):
            return
        animation = QVariantAnimation(self)
        animation.setDuration(400)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(118)
        animation.setEndValue(255)
        animation.valueChanged.connect(
            lambda value, span_start=start, span_end=end: self._set_followup_fade_span_alpha(span_start, span_end, int(value))
        )

        def _finalize(span_start: int = start, span_end: int = end, current_animation: QVariantAnimation = animation) -> None:
            self._set_followup_fade_span_alpha(span_start, span_end, 255)
            self._followup_char_fades[:] = [
                (fade_animation, fade_start, fade_end)
                for fade_animation, fade_start, fade_end in self._followup_char_fades
                if fade_animation is not current_animation
            ]
            current_animation.deleteLater()

        animation.finished.connect(_finalize)
        self._followup_char_fades.append((animation, start, end))
        self._set_followup_fade_span_alpha(start, end, 118)
        animation.start()

    def _on_followup_feedback_scroll_changed(self, value: int) -> None:
        if self._followup_programmatic_scroll:
            return
        bar = self.grade_feedback.verticalScrollBar()
        if bar is None:
            return
        bottom_threshold = max(0, bar.maximum() - 6)
        self._followup_autoscroll_enabled = int(value) >= bottom_threshold

    def _scroll_followup_feedback_to_bottom(self) -> None:
        bar = self.grade_feedback.verticalScrollBar()
        if bar is None:
            return
        self._followup_programmatic_scroll = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._followup_programmatic_scroll = False

    def _maybe_autoscroll_followup_feedback(self) -> None:
        if self._followup_autoscroll_enabled:
            self._scroll_followup_feedback_to_bottom()

    def _start_followup_thinking_status(self, text: str = "Thinking") -> None:
        self._followup_thinking_text = " ".join(str(text or "Thinking").split()) or "Thinking"
        self._followup_thinking_steps = []
        if self._followup_thinking_text != "Thinking":
            self._followup_thinking_steps.append(self._followup_thinking_text)
        self._followup_thinking_angle = 0.0
        self._followup_thinking_last_tick = time.perf_counter()
        self._followup_autoscroll_enabled = True
        self._followup_last_rendered_plain = ""
        self._stop_followup_char_fades()
        self.grade_feedback.clear()
        if hasattr(self, "followup_thinking_panel"):
            self.followup_thinking_panel.set_steps(self._followup_thinking_steps)
        if hasattr(self, "followup_response_stack"):
            self.followup_response_stack.setCurrentWidget(self.followup_thinking_panel)
        if not self._followup_thinking_timer.isActive():
            self._followup_thinking_timer.start()
        self._render_followup_thinking_status()

    def _stop_followup_thinking_status(self) -> None:
        self._followup_thinking_timer.stop()
        self._followup_thinking_last_tick = 0.0

    def _on_followup_thinking(self, text: str) -> None:
        cleaned = " ".join(str(text or "Thinking").split()) or "Thinking"
        self._followup_thinking_text = cleaned
        if cleaned != "Thinking":
            steps = list(getattr(self, "_followup_thinking_steps", []))
            if not steps:
                steps.append(cleaned)
            elif cleaned.startswith(steps[-1]) or steps[-1].startswith(cleaned):
                steps[-1] = max((steps[-1], cleaned), key=len)
            else:
                steps.append(cleaned)
            self._followup_thinking_steps = steps[-5:]
            if hasattr(self, "followup_thinking_panel"):
                self.followup_thinking_panel.set_steps(self._followup_thinking_steps)
        if not self._followup_thinking_timer.isActive():
            self._followup_thinking_timer.start()
        self._render_followup_thinking_status()

    def _render_followup_thinking_status(self) -> None:
        now = time.perf_counter()
        last_tick = float(getattr(self, "_followup_thinking_last_tick", 0.0) or 0.0)
        if last_tick <= 0.0:
            last_tick = now
        delta = max(0.0, min(0.05, now - last_tick))
        self._followup_thinking_last_tick = now
        self._followup_thinking_angle = (float(getattr(self, "_followup_thinking_angle", 0.0)) + (delta * 208.0)) % 360.0
        if hasattr(self, "followup_thinking_panel"):
            self.followup_thinking_panel.set_angle(float(getattr(self, "_followup_thinking_angle", 0.0)))

    def _on_followup_chunk(self, markdown_text: str) -> None:
        self._stop_followup_thinking_status()
        if hasattr(self, "followup_response_stack"):
            self.followup_response_stack.setCurrentWidget(self.grade_feedback)
        previous_plain = self._followup_last_rendered_plain
        self.grade_feedback.setMarkdown(markdown_text)
        current_plain = self.grade_feedback.toPlainText()
        changed_span = self._compute_followup_changed_span(previous_plain, current_plain)
        self._followup_last_rendered_plain = current_plain
        if changed_span is not None:
            self._animate_followup_text_fade(*changed_span)
        QTimer.singleShot(0, self._maybe_autoscroll_followup_feedback)

    def _run_followup(self, auto_prompt: str | None = None) -> None:
        if self.followup_worker and self.followup_worker.isRunning():
            return
        if not self.current_card:
            return
        model_spec = MODELS.get(self._followup_model_key()) or self._feature_text_llm_spec("followup_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Follow-up help"):
            return
        prompt = (auto_prompt or self.followup_input.toPlainText()).strip()
        if not prompt:
            QMessageBox.information(self, "Follow up", "Write a follow-up prompt first.")
            return
        context = self._build_followup_context()
        self.followup_btn.setEnabled(False)
        self.followup_model_btn.setEnabled(False)
        self._start_followup_thinking_status("Thinking")
        if auto_prompt is None:
            self.followup_input.clear()
        ai_settings = self.datastore.load_ai_settings()
        profile_context = self.datastore.load_profile()
        self.followup_worker = FollowUpWorker(
            ollama=self.ollama,
            model=self._feature_model_tag_for_key(model_spec.key, "followup_context_length"),
            prompt=prompt,
            context=context,
            context_length=int(ai_settings.get("followup_context_length", 8192) or 8192),
            profile_context=profile_context,
            think=self._followup_reasoning_mode() == "think",
        )
        self.followup_worker.chunk.connect(self._on_followup_chunk)
        self.followup_worker.thinking.connect(self._on_followup_thinking)
        self.followup_worker.finished.connect(lambda: self.followup_btn.setEnabled(True))
        self.followup_worker.finished.connect(lambda: self.followup_model_btn.setEnabled(True))
        self.followup_worker.finished.connect(self._stop_followup_thinking_status)
        self.followup_worker.failed.connect(self._on_followup_failed)
        self.followup_worker.start()

    def _on_followup_failed(self, message: str) -> None:
        self._stop_followup_thinking_status()
        if hasattr(self, "followup_response_stack"):
            self.followup_response_stack.setCurrentWidget(self.grade_feedback)
        self.followup_btn.setEnabled(True)
        self.followup_model_btn.setEnabled(True)
        self.grade_feedback.append("<hr>")
        self.grade_feedback.append(message)

    def _next_card(self) -> None:
        if self.grade_worker and self.grade_worker.isRunning():
            return
        if self.current_history_index < len(self.session_history) - 1:
            self._advance_session()
            return
        entry = self._current_history_entry()
        if self.current_card and entry is not None and not entry.get("attempt_logged", False):
            self._sync_current_entry_snapshot()
            answer_text = str(entry.get("answer_text", "")).strip()
            if self._should_grade_answer_on_next(answer_text):
                if self.study_state:
                    mark_card_completed(self.study_state, self.current_card)
                self._queue_grade_entry(self.current_history_index)
                self._advance_session()
                return
            entry["status"] = "skipped"
            entry["attempt_logged"] = True
            if self.study_state:
                mark_card_completed(self.study_state, self.current_card)
        self._advance_session()

    def _finish_session(self) -> None:
        for batch_id in list(self.session_temp_batches.keys()):
            self._finalize_temp_batch(batch_id)
        avg_marks = sum(self.session_scores) / len(self.session_scores) if self.session_scores else 0.0
        avg_difficulty = (
            sum(int(card.get("natural_difficulty", 5)) for card in self.session_cards) / len(self.session_cards)
            if self.session_cards
            else 0.0
        )
        QMessageBox.information(
            self,
            "Session complete",
            f"Average marks: {avg_marks:.1f}/10\nAverage difficulty: {avg_difficulty:.1f}/10",
        )
        self._cancel_session_prep()
        self.current_card = None
        self.study_state = None
        self.session_id = ""
        self.session_queue = []
        self.session_cards = []
        self.session_scores = []
        self.session_history = []
        self.current_history_index = -1
        self.queued_grade_indexes = []
        self.active_queue_entry_index = -1
        self.session_end_requested = False
        self.session_temp_batches = {}
        self.session_title.setText("Pick a card to start")
        self.session_meta.setText("")
        self.session_question.setText("Press Start for the current section.")
        self.answer_input.setEnabled(True)
        self.answer_input.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("AI grader")
        self._set_followup_visible(False)
        self.prev_card_btn.setEnabled(False)
        self.grade_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.idk_btn.setEnabled(False)
        self._update_study_primary_action()

    def _remove_card_from_session(self, card: dict) -> None:
        card_id = str(card.get("id", ""))
        self.session_queue = [item for item in self.session_queue if str(item.get("id", "")) != card_id]
        self.session_cards = [item for item in self.session_cards if str(item.get("id", "")) != card_id]
        if self.study_state:
            self.study_state.unseen_ids = [item for item in self.study_state.unseen_ids if item != card_id]
            self.study_state.priority_ids = [item for item in self.study_state.priority_ids if item != card_id]
            self.study_state.deferred_ids = [item for item in self.study_state.deferred_ids if item != card_id]
            self.study_state.card_lookup.pop(card_id, None)
            self.study_state.cards = [item for item in self.study_state.cards if str(item.get("id", "")) != card_id]
        if self.current_card and str(self.current_card.get("id", "")) == card_id:
            self._advance_session()
