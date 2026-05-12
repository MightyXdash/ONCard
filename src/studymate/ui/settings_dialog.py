from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import random
import shutil
import tempfile
import threading
import webbrowser
from typing import Any

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, QSignalBlocker, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from studymate.services.account_transfer_service import AccountTransferHostService, AccountTransferPeerClient
from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.model_registry import (
    MODELS,
    ModelSpec,
    QN_SUMMARIZER_AUTO_SELECTED_SETTING,
    QN_SUMMARIZER_CONTEXT_LENGTH,
    QN_SUMMARIZER_MODEL_KEY,
    cloud_llm_specs,
    feature_model_setting_key,
    non_embedding_llm_keys,
    ocr_llm_keys,
    resolve_feature_text_llm_key,
    resolve_feature_text_llm_spec,
    resolve_feature_text_model_tag,
    resolve_active_ocr_llm_key,
    resolve_active_text_llm_spec,
    resolve_active_text_model_tag,
    smallest_supported_ocr_llm_key,
    text_llm_key_for_model_tag,
    wiki_summarizer_llm_keys,
)
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.services.settings_search_service import SettingsSearchService
from studymate.theme import is_dark_theme, normalize_theme_mode, theme_tokens
from studymate.ui.animated import AnimatedComboBox, AnimatedLineEdit, polish_surface
from studymate.ui.wizard import FieldBlock, GenderPickerDialog, GradePickerDialog, PlaceholderComboBox
from studymate.ui.window_effects import polish_popup_window, polish_windows_window
from studymate.workers.install_worker import ModelInstallWorker
from studymate.workers.mcq_worker import MCQBulkWorker

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QVideoWidget = None  # type: ignore[assignment]


MIN_CONTEXT_LENGTH = 2000
MAX_CONTEXT_LENGTH = 86000
SETTINGS_WIDGET_HEIGHT = 48
CONTEXT_LENGTH_SETTINGS = [
    ("autofill_context_length", "Card autofill", "Creates card metadata, hints, answer choices, and a starter answer.", 8192),
    ("grading_context_length", "Answer grading", "Grades written answers and builds the feedback report.", 8192),
    ("mcq_context_length", "MCQ generation", "Creates multiple-choice answers and tricky distractors for cards.", 8192),
    ("ask_ai_planner_context_length", "Ask AI planner", "Decides whether Ask AI should browse cards, images, or answer directly.", 4400),
    ("ask_ai_answer_context_length", "Ask AI answer", "Writes the final Ask AI response from retrieved cards and study context.", 9216),
    ("ask_ai_image_context_length", "Image search terms", "Reads an attached image and turns it into searchable study terms.", 8192),
    ("wiki_breakdown_context_length", "Wiki Summarizer", "Reads a cleaned Wikipedia extract and explains it in simple study-ready language.", 6000),
    ("followup_context_length", "Follow-up chat", "Answers follow-up questions about the current card and feedback.", 9216),
    ("reinforcement_context_length", "Reinforcement cards", "Creates temporary practice cards after weak answers.", 8192),
    ("files_to_cards_ocr_context_length", "Files To Cards OCR", "Extracts text from PDFs, slides, and images before card generation.", 8192),
    ("files_to_cards_paper_context_length", "Files To Cards paper", "Builds revision notes from uploaded source material.", 8192),
    ("files_to_cards_cards_context_length", "Files To Cards cards", "Converts revision notes into final study cards.", 8192),
    ("stats_context_length", "Stats summary", "Summarizes progress charts, weak subjects, and next study steps.", 4000),
]
ASK_AI_TONE_OPTIONS = [
    ("Warm", "warm"),
    ("Funny", "funny"),
    ("Sarcastic", "sarcastic"),
    ("Glazer", "glazer"),
    ("Shakespeare", "shakespeare"),
]
ASK_AI_EMOJI_LABELS = {
    1: "Emoji usage: none",
    2: "Emoji usage: some",
    3: "Emoji usage: good amount",
    4: "Emoji usage: a lot",
}
MODEL_ROLE_COPY = {
    "gemma4_e2b": "Default lightweight LLM for cards, Files To Cards, grading, follow-up help, and Ask AI.",
    "gemma4_e4b": "Optional small LLM for text features.",
    "gemma4_26b": "Optional larger LLM for higher-quality text features.",
    "qwen3_5_2b": "Optional compact Qwen LLM for text features.",
    "qwen3_5_4b": "Optional small Qwen LLM for text features.",
    "qwen3_5_9b": "Optional balanced Qwen LLM for text features.",
    "qwen3_5_27b": "Optional larger Qwen LLM for text features.",
    "qwen3_5_35b": "Optional high-capacity Qwen LLM for text features.",
    "nomic_embed_text_v2_moe": "Semantic search, recommendations, topic clustering, and adaptive study features.",
    "qn_summarizer_1": "Wiki Summarizer-only model for fast Wikipedia summaries inside ONCard.",
}
OLLAMA_CLOUD_KEYS_URL = "https://ollama.com/settings/keys"
CHECK_ICON_URL = (Path(__file__).resolve().parents[3] / "assets" / "icons" / "common" / "check_white_small.svg").as_posix()
SETTINGS_SEARCH_ICON_PATH = Path(__file__).resolve().parents[3] / "assets" / "icons" / "common" / "cards_search_empty.png"
SETTINGS_SEARCH_LOADING_VIDEO_PATH = Path(__file__).resolve().parents[3] / "assets" / "vids" / "settings_loading.mp4"
SETTINGS_SEARCH_LOADING_PENALTY_CACHE_KEY = "settings_search_loading_penalties"
SETTINGS_SEARCH_LOADING_PENALTY_HOURS = 90
SETTINGS_SEARCH_LOADING_LINES = (
    "Let me search that thing for you.",
    "Ohh you bet. Let me get that for you.",
    "I am rummaging through the settings drawer.",
    "I have my tiny flashlight out for this one.",
    "Let me poke the settings until it confesses.",
    "I am asking the settings politely.",
    "One sec, I am doing the dramatic search walk.",
    "I am speed-reading the control panel.",
    "Let me summon the exact knob you meant.",
    "I am checking under the digital couch cushions.",
    "I have entered detective mode.",
    "I am tracking down the right setting.",
    "Let me find the button that started all this.",
    "I am interrogating tabs with confidence.",
    "I am digging through the useful nonsense.",
    "Hold up, I am doing the fancy search thing.",
    "I am browsing the settings buffet for you.",
    "Let me chase that option down.",
    "I am negotiating with the search index.",
    "I am about to make this look intentional.",
    "I am checking the settings pantry.",
    "Let me ask the tabs where they hid it.",
    "I am opening every tiny drawer in my head.",
    "I am doing the responsible snooping now.",
    "Let me find the setting with main character energy.",
    "I am giving the search index a gentle nudge.",
    "I am looking under Advanced, because of course.",
    "Let me do the ctrl-f cosplay.",
    "I am following the breadcrumb trail.",
    "I am sorting through buttons with purpose.",
    "Let me make the settings behave for a second.",
    "I am checking the usual suspicious places.",
    "I am speedrunning the preferences maze.",
    "Let me pull the right lever for you.",
    "I am dusting off the exact option.",
    "I am asking the UI nicely one more time.",
    "Let me see which toggle is being dramatic.",
    "I am scanning labels like I studied for this.",
    "I am about to reveal the obvious hiding spot.",
    "Let me fetch the setting from backstage.",
    "I am doing tiny admin magic.",
    "I am looking for the checkbox with attitude.",
    "Let me find the knob that fixes the vibe.",
    "I am checking the settings group chat.",
    "I am convincing the right panel to cooperate.",
    "Let me pull this out of the options pile.",
    "I am searching with unnecessary confidence.",
    "I am decoding the preference spaghetti.",
    "Let me find the thing behind the thing.",
    "I am narrowing it down without making a scene.",
    "I am interrogating the settings with a warm lamp and bad cop energy.",
    "I am rifling through menus like they owe me rent.",
    "I am checking whether the option is hiding behind three dots again.",
    "I am opening cabinets in the UI that should frankly already be labeled.",
    "I am about to pull the exact lever and act like I knew it all along.",
    "I am searching this panel like it just talked back.",
    "I am doing premium-grade button archaeology.",
    "I am reading tiny labels so you do not have to damage your soul.",
    "I am chasing this setting like it left the scene.",
    "I am knocking on every submenu until one answers.",
    "I am looking for the option with suspiciously specific wording.",
    "I am checking whether the dev who named this was feeling poetic.",
    "I am sweeping the floor for dropped toggles.",
    "I am walking directly into the maze with no map and great posture.",
    "I am checking if the setting got promoted to a different tab overnight.",
    "I am opening the mystery box labeled preferences.",
    "I am reverse-engineering the logic of whoever organized this.",
    "I am tracing the scent of overengineered nomenclature.",
    "I am going shelf by shelf like an annoyed librarian.",
    "I am peeking behind every dropdown curtain.",
    "I am searching for the one control that thinks it is special.",
    "I am pulling threads until the right menu falls out.",
    "I am doing a quiet little manhunt for that option.",
    "I am asking the interface where it put your stuff.",
    "I am checking the panel, the subpanel, and the secret subpanel.",
    "I am negotiating with the settings taxonomy.",
    "I am looking for the button that would absolutely lose a game of hide and seek.",
    "I am traversing the land of slightly-too-clever labels.",
    "I am opening tabs like a detective with a caffeine problem.",
    "I am checking whether the setting got a rebrand.",
    "I am reading every caption like there is a prize at the end.",
    "I am searching this UI with the energy of a disappointed architect.",
    "I am shaking the tree to see which toggle falls out.",
    "I am hunting for the setting that definitely swore it was obvious.",
    "I am checking all the places the product team thought were intuitive.",
    "I am sorting the useful from the decorative in real time.",
    "I am doing careful violence to the information architecture.",
    "I am opening yet another section called something unhelpfully broad.",
    "I am trying the place it should be, then the place it actually is.",
    "I am following the trail of mildly confusing terminology.",
)

_ACTIVE_TRANSFER_IMPORT_DIALOGS: list[QDialog] = []


def _format_transfer_size(size_bytes: object) -> str:
    try:
        value = float(size_bytes)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, value)
    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def _retain_transfer_import_dialog(dialog: QDialog) -> None:
    _ACTIVE_TRANSFER_IMPORT_DIALOGS.append(dialog)

    def _release(_result: int, tracked: QDialog = dialog) -> None:
        if tracked in _ACTIVE_TRANSFER_IMPORT_DIALOGS:
            _ACTIVE_TRANSFER_IMPORT_DIALOGS.remove(tracked)

    dialog.finished.connect(_release)


class PopupMenuComboBox(AnimatedComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._popup_handler = None

    def set_popup_handler(self, handler) -> None:
        self._popup_handler = handler

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def showPopup(self) -> None:
        if callable(self._popup_handler):
            self._popup_handler()
            return
        super().showPopup()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint


class SettingsComboBox(AnimatedComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint


class SettingsSlider(QSlider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class SettingsSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setHeight(SETTINGS_WIDGET_HEIGHT)
        return hint


class SettingsRailButton(QAbstractButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setProperty("disablePressMotion", True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._icon = QIcon()
        self._icon_size = QSize(17, 17)
        self._hover_progress = 0.0
        self._reveal_progress = 0.0
        self._reveal_duration_ms = 420
        self._reveal_elapsed = QElapsedTimer()
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._reveal_timer.setInterval(16)
        self._reveal_timer.timeout.connect(self._advance_reveal)

    def setIcon(self, icon: QIcon) -> None:
        self._icon = icon
        self.update()

    def icon(self) -> QIcon:
        return self._icon

    def setIconSize(self, size: QSize) -> None:
        self._icon_size = QSize(size)
        self.update()

    def iconSize(self) -> QSize:
        return QSize(self._icon_size)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        if not checked:
            self._reveal_timer.stop()
            self._reveal_progress = 0.0
        elif not self._reveal_timer.isActive() and self._reveal_progress <= 0.0:
            self._reveal_progress = 1.0
        self.update()

    def nextCheckState(self) -> None:
        pass

    def begin_reveal(self) -> None:
        if self._reveal_timer.isActive():
            return
        self._reveal_progress = 0.0
        self._reveal_elapsed.restart()
        self._reveal_timer.start()
        self.update()

    def _set_reveal_progress(self, value) -> None:
        self._reveal_progress = max(0.0, min(1.0, float(value)))
        self.update()

    def _advance_reveal(self) -> None:
        elapsed = max(0, self._reveal_elapsed.elapsed())
        t = min(1.0, elapsed / float(self._reveal_duration_ms))
        self._reveal_progress = self._reveal_curve(t)
        if t >= 1.0:
            self._reveal_timer.stop()
            self._reveal_progress = 1.0
        self.update()

    @staticmethod
    def _reveal_curve(t: float) -> float:
        t = max(0.0, min(1.0, float(t)))
        if t < 0.46:
            return t / 0.46
        bounce_t = (t - 0.46) / 0.54
        damping = pow(1.0 - bounce_t, 1.75)
        return 1.0 + (0.11 * damping * abs(math.sin(bounce_t * 8.0 * math.pi)))

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hover_progress = 1.0
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover_progress = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            reveal = self._reveal_progress if (self.isChecked() or self.isDown() or self._reveal_progress > 0.0) else 0.0
            if reveal > 0.0:
                outer = QRectF(self.rect().adjusted(0, 0, -1, -1))
                bounce_room = 4.0
                full = outer.adjusted(bounce_room, 2.0, -bounce_room, -2.0)
                center = outer.center()
                start_size = min(float(self.height() - 2), 34.0)
                reveal_base = min(1.0, reveal)
                active_rect = QRectF(
                    center.x() - ((start_size + (full.width() - start_size) * reveal_base) / 2.0),
                    center.y() - ((start_size + (full.height() - start_size) * reveal_base) / 2.0),
                    start_size + (full.width() - start_size) * reveal_base,
                    start_size + (full.height() - start_size) * reveal_base,
                )
                if reveal > 1.0:
                    overshoot = min(1.0, (reveal - 1.0) / 0.11)
                    active_rect = QRectF(
                        active_rect.left() + ((outer.left() - active_rect.left()) * overshoot),
                        active_rect.top() + ((outer.top() - active_rect.top()) * overshoot),
                        active_rect.width() + ((outer.width() - active_rect.width()) * overshoot),
                        active_rect.height() + ((outer.height() - active_rect.height()) * overshoot),
                    )
                radius = 17.0 + ((9.0 - 17.0) * reveal)
                blur_phase = max(0.0, min(1.0, 1.0 - reveal_base))
                if blur_phase > 0.0:
                    blur_strength = blur_phase * blur_phase
                    trail_opacity = int(52 * blur_strength)
                    if trail_opacity > 0:
                        trail_dx = max(1.5, 9.0 * blur_strength)
                        trail_expand_x = max(0.0, 7.0 * blur_strength)
                        trail_expand_y = max(0.0, 2.0 * blur_strength)
                        for layer, scale in enumerate((1.0, 0.72, 0.48), start=1):
                            layer_strength = scale * blur_strength
                            trail_rect = active_rect.adjusted(
                                -(trail_expand_x * scale),
                                -(trail_expand_y * scale),
                                trail_expand_x * scale,
                                trail_expand_y * scale,
                            )
                            trail_rect.translate(-trail_dx * layer, 0.0)
                            trail_radius = radius + (6.0 * scale * blur_phase)
                            painter.setBrush(QColor(22, 119, 232, int(trail_opacity * scale)))
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.drawRoundedRect(trail_rect, trail_radius, trail_radius)
                painter.setBrush(QColor("#1677e8"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(active_rect, radius, radius)
                text_color = QColor(246, 250, 255, int(160 + (78 * reveal)))
                icon_opacity = 0.50 + (0.45 * reveal)
            else:
                text_color = QColor(76, 84, 91, int(104 + (88 * self._hover_progress)))
                icon_opacity = 0.32 + (0.42 * self._hover_progress)

            icon_x = 15
            icon_y = (self.height() - self._icon_size.height()) // 2
            text_x = icon_x + self._icon_size.width() + 13
            if not self._icon.isNull():
                dpr = max(1.0, float(self.devicePixelRatioF()))
                pixmap = self._icon.pixmap(
                    int(self._icon_size.width() * dpr),
                    int(self._icon_size.height() * dpr),
                )
                pixmap.setDevicePixelRatio(dpr)
                painter.setOpacity(icon_opacity)
                painter.drawPixmap(QRect(icon_x, icon_y, self._icon_size.width(), self._icon_size.height()), pixmap)
                painter.setOpacity(1.0)
            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(12)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            text_rect = QRect(text_x, 0, max(1, self.width() - text_x - 12), self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        finally:
            painter.end()


class SettingsAvatarChoiceButton(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(62, 62)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)
        self.setAutoFillBackground(False)
        self.setProperty("disablePressMotion", True)
        self.setStyleSheet(
            """
            SettingsAvatarChoiceButton,
            SettingsAvatarChoiceButton:hover,
            SettingsAvatarChoiceButton:pressed,
            SettingsAvatarChoiceButton:checked {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            """
        )
        self._avatar = QPixmap()

    def set_avatar_pixmap(self, pixmap: QPixmap) -> None:
        self._avatar = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if not self._avatar.isNull():
                icon_size = min(self.width(), self.height())
                x = (self.width() - icon_size) // 2
                y = (self.height() - icon_size) // 2
                painter.drawPixmap(QRect(x, y, icon_size, icon_size), self._avatar)
            if self.isChecked():
                ring = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
                painter.setBrush(QColor(31, 102, 184, 20))
                painter.setPen(QPen(QColor(31, 102, 184, 230), 1.6))
                painter.drawEllipse(ring)
        finally:
            painter.end()


class SettingsPickerButton(QPushButton):
    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._items: list[str] = []
        self._current_text = ""
        self.setObjectName("SettingsPickerButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("disablePressMotion", True)
        self.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        self._refresh_text()

    def addItem(self, text: str) -> None:
        clean = str(text or "").strip()
        if clean and clean not in self._items:
            self._items.append(clean)

    def addItems(self, items: list[str]) -> None:
        for item in items:
            self.addItem(item)

    def findText(self, text: str) -> int:
        try:
            return self._items.index(str(text or "").strip())
        except ValueError:
            return -1

    def currentText(self) -> str:
        return self._current_text

    def setCurrentText(self, text: str) -> None:
        self._current_text = str(text or "").strip()
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.setText(self._current_text or self._placeholder)
        self.setProperty("placeholder", not bool(self._current_text))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class SettingsSearchLoadingWidget(QWidget):
    def __init__(self, texts: tuple[str, ...] | list[str] | str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if isinstance(texts, str):
            self._texts = [texts]
        else:
            self._texts = [str(text).strip() for text in texts if str(text).strip()]
        if not self._texts:
            self._texts = ["Let me search that thing for you."]
        self._active_texts = self._texts[:1]
        self._last_texts: list[str] = []
        self._line_index = 0
        self._text_elapsed_ms = 0
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
            count = 1
            candidates = [text for text in self._texts if text not in self._last_texts]
            if len(candidates) < count:
                candidates = self._texts[:]
            self._active_texts = random.sample(candidates, count) if count > 1 else candidates[:1]
        self._last_texts = self._active_texts[:]
        self._line_index = 0
        self._text_elapsed_ms = 0
        self._phase = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._phase = 0.0
        self._line_index = 0
        self._text_elapsed_ms = 0
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.005) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            text_rect = self.rect().adjusted(2, 0, -2, 0)
            line_index = min(self._line_index, len(self._active_texts) - 1)
            text = self._active_texts[line_index]
            painter.setPen(QColor("#8798ab"))
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)

            shimmer_width = max(104.0, text_rect.width() * 0.36)
            track = max(1.0, text_rect.width() + shimmer_width)
            x = text_rect.left() - shimmer_width + (track * self._phase)
            highlight = QRectF(float(x), float(text_rect.top()), float(shimmer_width), float(text_rect.height()))
            gradient = QLinearGradient(highlight.left(), highlight.center().y(), highlight.right(), highlight.center().y())
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(0.2, QColor(255, 255, 255, 28))
            gradient.setColorAt(0.5, QColor(255, 255, 255, 150))
            gradient.setColorAt(0.8, QColor(255, 255, 255, 28))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(highlight, gradient)
        finally:
            painter.end()


class SettingsSearchSkeletonPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.16
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._phase = 0.16
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.014) % 1.0
        self.update()

    def _draw_bar(self, painter: QPainter, rect: QRectF, color: QColor, radius: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, radius, radius)

        shimmer_width = max(118.0, rect.width() * 0.42)
        track = max(1.0, rect.width() + shimmer_width)
        x = rect.left() - shimmer_width + (track * self._phase)
        highlight = QRectF(x, rect.top(), shimmer_width, rect.height())
        gradient = QLinearGradient(highlight.left(), highlight.center().y(), highlight.right(), highlight.center().y())
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.18, QColor(255, 255, 255, 34))
        gradient.setColorAt(0.5, QColor(255, 255, 255, 176))
        gradient.setColorAt(0.82, QColor(255, 255, 255, 34))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(highlight, gradient)

    def _draw_card(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(191, 205, 221, 150), 1))
        painter.setBrush(QColor(255, 255, 255, 252))
        painter.drawRoundedRect(rect, 18.0, 18.0)

        inner = rect.adjusted(18.0, 18.0, -18.0, -18.0)
        y = inner.top()
        bars = (
            (0.26, 17.0, QColor(202, 216, 232, 252), 8.0, 18.0),
            (0.92, 12.0, QColor(219, 229, 240, 252), 6.0, 16.0),
            (0.84, 12.0, QColor(219, 229, 240, 252), 6.0, 14.0),
            (0.88, 12.0, QColor(219, 229, 240, 252), 6.0, 16.0),
        )
        for ratio, height, color, radius, gap in bars:
            bar = QRectF(inner.left(), y, inner.width() * ratio, height)
            self._draw_bar(painter, bar, color, radius)
            y += height + gap

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillRect(self.rect(), QColor(248, 250, 252, 0))

            outer = QRectF(self.rect()).adjusted(6.0, 10.0, -18.0, -16.0)
            if outer.width() <= 0 or outer.height() <= 0:
                return

            top_bar = QRectF(outer.left(), outer.top(), min(360.0, outer.width() * 0.42), 16.0)
            sub_bar = QRectF(outer.left(), top_bar.bottom() + 14.0, min(520.0, outer.width() * 0.62), 12.0)
            self._draw_bar(painter, top_bar, QColor(207, 220, 234, 250), 8.0)
            self._draw_bar(painter, sub_bar, QColor(220, 230, 241, 250), 6.0)

            card_top = sub_bar.bottom() + 22.0
            card_height = min(196.0, max(150.0, (outer.height() - 38.0) / 3.0))
            spacing = 16.0
            for index in range(3):
                rect = QRectF(outer.left(), card_top + (index * (card_height + spacing)), outer.width(), card_height)
                if rect.bottom() > outer.bottom():
                    break
                self._draw_card(painter, rect)
        finally:
            painter.end()


class SettingsSearchVideoPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self._video_display_size = QSize(280, 280)
        self._duration_ms = 0
        self._last_position_ms = 0
        self._loop_count = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._available = bool(QMediaPlayer is not None and QVideoWidget is not None and SETTINGS_SEARCH_LOADING_VIDEO_PATH.exists())
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity_effect)

        if not self._available:
            fallback = SettingsSearchSkeletonPage(self)
            layout.addWidget(fallback, 1)
            self.fallback = fallback
            self.video_host = None
            self.video_widget = None
            self.player = None
            self.audio_output = None
            return

        self.video_host = QWidget(self)
        self.video_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.video_host.setStyleSheet("background: transparent; border: none;")
        self.video_host.setFixedSize(self._video_display_size)

        host_layout = QVBoxLayout(self.video_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.video_widget = QVideoWidget(self.video_host)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_widget.setStyleSheet("background: transparent; border: none;")
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        host_layout.addWidget(self.video_widget)
        self.video_host.raise_()

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self) if QAudioOutput is not None else None
        if self.audio_output is not None:
            self.audio_output.setVolume(0.0)
            self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.setSource(QUrl.fromLocalFile(str(SETTINGS_SEARCH_LOADING_VIDEO_PATH)))
        if hasattr(self.player, "setLoops"):
            self.player.setLoops(-1)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.fallback = None

    def is_available(self) -> bool:
        return bool(self._available and self.player is not None and self.video_widget is not None)

    def reset_opacity(self) -> None:
        self.opacity_effect.setOpacity(1.0)

    def reset_loop_tracking(self) -> None:
        self._last_position_ms = 0
        self._loop_count = 0

    def loop_count(self) -> int:
        return int(self._loop_count)

    def refresh_video_host_geometry(self) -> None:
        if self.video_host is None:
            return
        size = self._video_display_size
        x = max(0, (self.width() - size.width()) // 2)
        y = max(0, (self.height() - size.height()) // 2)
        self.video_host.setGeometry(x, y, size.width(), size.height())

    def _on_duration_changed(self, duration: int) -> None:
        self._duration_ms = max(0, int(duration or 0))

    def _on_position_changed(self, position: int) -> None:
        position_ms = max(0, int(position or 0))
        if self._duration_ms > 400 and self._last_position_ms > max(300, self._duration_ms - 250) and position_ms < 200:
            self._loop_count += 1
        self._last_position_ms = position_ms

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_video_host_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_video_host_geometry()


class FTCPopupChoiceDialog(QDialog):
    MAX_VERTICAL_CHOICES_PER_COLUMN = 7
    MAX_VERTICAL_CHOICE_COLUMNS = 3

    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        title: str,
        options: list[tuple[str, str]],
        current_value: str,
        vertical_choices: bool = False,
        icon_provider=None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        polish_popup_window(self)
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._selected_value = str(current_value or "")
        self._choice_buttons: dict[str, QPushButton] = {}

        options_clean = [(str(label), str(value)) for label, value in options if str(value).strip()]
        if not options_clean:
            options_clean = [("Normal", "normal")]
        known_values = {value for _label, value in options_clean}
        if self._selected_value not in known_values:
            self._selected_value = options_clean[0][1]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("FTCControlsPopupCard")
        root.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(24, 22, 24, 20)
        body.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header_title = QLabel(title)
        header_title.setObjectName("SectionTitle")
        header.addWidget(header_title)
        header.addStretch(1)

        if icon_provider is not None and hasattr(icon_provider, "icon"):
            save_icon = icon_provider.icon("common", "check", "C")
            close_icon = icon_provider.icon("common", "cross_two", "X")
        else:
            save_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            close_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)

        self.save_btn = QToolButton()
        self.save_btn.setObjectName("FTCPopupIconButton")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setIcon(save_icon if isinstance(save_icon, QIcon) else QIcon())
        self.save_btn.setIconSize(QSize(15, 15))
        self.save_btn.setFixedSize(34, 34)
        self.save_btn.clicked.connect(self._save_and_accept)
        header.addWidget(self.save_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("FTCPopupIconButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setIcon(close_icon if isinstance(close_icon, QIcon) else QIcon())
        self.close_btn.setIconSize(QSize(15, 15))
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn)
        body.addLayout(header)

        choices_shell = QFrame()
        choices_shell.setObjectName("FTCPopupFieldShell")
        choices_layout = QHBoxLayout(choices_shell)
        choices_layout.setContentsMargins(8, 8, 8, 8)
        choices_layout.setSpacing(8)

        column_count = 1
        if vertical_choices:
            column_count = min(
                self.MAX_VERTICAL_CHOICE_COLUMNS,
                max(1, (len(options_clean) + self.MAX_VERTICAL_CHOICES_PER_COLUMN - 1) // self.MAX_VERTICAL_CHOICES_PER_COLUMN),
            )
        columns: list[QVBoxLayout] = []
        if vertical_choices:
            for _index in range(column_count):
                column = QVBoxLayout()
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(8)
                choices_layout.addLayout(column, 1)
                columns.append(column)

        rows_per_column = max(1, (len(options_clean) + column_count - 1) // column_count)
        for index, (label, value) in enumerate(options_clean):
            button = QPushButton(label)
            button.setObjectName("FTCPopupChoiceButton")
            button.setCheckable(True)
            button.setProperty("disablePressMotion", True)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_value(selected))
            if vertical_choices:
                column_index = min(column_count - 1, index // rows_per_column)
                columns[column_index].addWidget(button)
            else:
                choices_layout.addWidget(button, 1)
            self._choice_buttons[value] = button
        for column in columns:
            column.addStretch(1)
        body.addWidget(choices_shell)
        self._refresh_buttons()
        self.setMinimumWidth((300 * column_count) + 60 if vertical_choices else 500)

    def selected_value(self) -> str:
        return str(self._selected_value or "")

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self.adjustSize()
            self._center_on_parent()
            return self.exec()
        finally:
            self._clear_backdrop()

    def mousePressEvent(self, event) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)

    def _set_value(self, value: str) -> None:
        self._selected_value = str(value or "")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for value, button in self._choice_buttons.items():
            selected = value == self._selected_value
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _save_and_accept(self) -> None:
        self.done(QDialog.DialogCode.Accepted)

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(255, 255, 255, 0.10);")
        top_left = self._blur_target.mapTo(self._overlay_target, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, self._blur_target.size()))
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _clear_backdrop(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        if self._blur_target is not None:
            try:
                self._blur_target.setGraphicsEffect(self._previous_effect)
            except RuntimeError:
                try:
                    self._blur_target.setGraphicsEffect(None)
                except RuntimeError:
                    pass
        self._previous_effect = None


class ExportAccountDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        icons_root: Path | None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        polish_popup_window(self)
        self._download_requested = False
        self._blur_target = blur_target
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._icons_root = icons_root

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("ExportAccountPopupCard")
        card.setStyleSheet(
            """
            QFrame#ExportAccountPopupCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(220, 228, 236, 0.85);
                border-radius: 28px;
            }
            QToolButton#ExportAccountIconButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 0px;
            }
            QToolButton#ExportAccountIconButton:hover {
                background-color: transparent;
                border-color: transparent;
            }
            QToolButton#ExportAccountIconButton:pressed {
                background-color: rgba(15, 37, 57, 0.14);
                border-color: rgba(15, 37, 57, 0.14);
            }
            """
        )
        root.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(24, 22, 24, 20)
        body.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Export account")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        body.addLayout(header)

        message = QLabel("We made a copy of your data. Press download to save it to your Downloads folder.")
        message.setObjectName("SectionText")
        message.setWordWrap(True)
        body.addWidget(message)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        download_btn = self._icon_button("download", "Download to Downloads")
        download_btn.clicked.connect(self._download)
        actions.addWidget(download_btn)
        close_btn = self._icon_button("cross_two", "Cancel")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        body.addLayout(actions)

        self.setFixedSize(560, 270)

    def download_requested(self) -> bool:
        return self._download_requested

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            return self.exec()
        finally:
            self._clear_backdrop()

    def _download(self) -> None:
        self._download_requested = True
        self.accept()

    def _icon_button(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ExportAccountIconButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        button.setFixedSize(34, 34)
        if self._icons_root is not None:
            button.setIcon(QIcon(str(self._icons_root / "common" / f"{icon_name}.png")))
            button.setIconSize(QSize(15, 15))
        return button

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(255, 255, 255, 0.10);")
        top_left = self._blur_target.mapTo(self._overlay_target, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, self._blur_target.size()))
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _clear_backdrop(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        if self._blur_target is not None:
            try:
                self._blur_target.setGraphicsEffect(self._previous_effect)
            except RuntimeError:
                try:
                    self._blur_target.setGraphicsEffect(None)
                except RuntimeError:
                    pass
        self._previous_effect = None


class TransferCodeLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("--", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(70, 54)
        self.setStyleSheet(
            """
            QLabel {
                background: rgba(22, 119, 232, 0.10);
                border: 1px solid rgba(22, 119, 232, 0.22);
                border-radius: 14px;
                color: #0f172a;
                font-size: 20px;
                font-weight: 800;
            }
            """
        )


class AccountTransferImportDialog(QDialog):
    def __init__(
        self,
        *,
        session_controller,
        host: dict[str, Any],
        transfer_request: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        self.session_controller = session_controller
        self.host = dict(host)
        self.transfer_request = dict(transfer_request)
        self._client = AccountTransferPeerClient()
        self._state_lock = threading.Lock()
        self._download_state = {
            "stage": "queued",
            "downloaded": 0,
            "total": 0,
            "path": "",
            "error": "",
        }
        self._import_started = False
        self._worker_thread: threading.Thread | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._tick)

        self.setWindowTitle("Transfer account")
        self.setModal(True)
        self.setFixedSize(420, 180)
        self.setStyleSheet(
            """
            QDialog {
                background: #ffffff;
            }
            QLabel#TransferTitle {
                font-size: 18px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#TransferText {
                font-size: 13px;
                color: #64748b;
            }
            QProgressBar {
                border: none;
                border-radius: 8px;
                background: rgba(148, 163, 184, 0.18);
                text-align: center;
                min-height: 14px;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: #1677e8;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("Loading transferred account")
        title.setObjectName("TransferTitle")
        layout.addWidget(title)

        self.message_label = QLabel("Downloading account data from the host...")
        self.message_label.setObjectName("TransferText")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.detail_label = QLabel("Waiting for the host archive...")
        self.detail_label.setObjectName("TransferText")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

    def start(self) -> None:
        if self._worker_thread is not None:
            return
        self._worker_thread = threading.Thread(target=self._download_worker, daemon=True)
        self._worker_thread.start()
        self._poll_timer.start(120)

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        super().closeEvent(event)

    def _download_worker(self) -> None:
        temp_file = Path(tempfile.mkdtemp(prefix="oncard_transfer_peer_")) / "account_transfer.zip"

        def on_progress(downloaded: int, total: int) -> None:
            with self._state_lock:
                self._download_state["stage"] = "downloading"
                self._download_state["downloaded"] = int(downloaded)
                self._download_state["total"] = int(total)

        try:
            archive_path = self._client.download_archive(
                self.host,
                session_id=str(self.transfer_request.get("session_id", "")),
                auth_token=str(self.transfer_request.get("auth_token", "")),
                destination=temp_file,
                progress_callback=on_progress,
            )
            self._client.mark_complete(
                self.host,
                session_id=str(self.transfer_request.get("session_id", "")),
                auth_token=str(self.transfer_request.get("auth_token", "")),
            )
        except Exception as exc:
            with self._state_lock:
                self._download_state["stage"] = "error"
                self._download_state["error"] = str(exc)
            shutil.rmtree(temp_file.parent, ignore_errors=True)
            return

        with self._state_lock:
            self._download_state["stage"] = "downloaded"
            self._download_state["path"] = str(archive_path)

    def _tick(self) -> None:
        with self._state_lock:
            stage = str(self._download_state.get("stage", "queued"))
            downloaded = int(self._download_state.get("downloaded", 0))
            total = int(self._download_state.get("total", 0))
            archive_path = str(self._download_state.get("path", ""))
            error = str(self._download_state.get("error", ""))

        if stage in {"queued", "downloading"}:
            if total > 0:
                percent = max(0, min(100, int((downloaded / total) * 100)))
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(percent)
                self.detail_label.setText(f"{_format_transfer_size(downloaded)} of {_format_transfer_size(total)}")
            else:
                self.progress_bar.setRange(0, 0)
                self.detail_label.setText("Downloading account data...")
            return

        if stage == "error":
            self._poll_timer.stop()
            QMessageBox.warning(self, "Transfer account", error or "Account transfer failed.")
            self.reject()
            return

        if stage == "downloaded" and not self._import_started:
            self._import_started = True
            self._poll_timer.stop()
            self.message_label.setText("Processing account data and loading it into this ONCard instance...")
            self.detail_label.setText("Your current account on this device will be overwritten.")
            self.progress_bar.setRange(0, 0)
            QApplication.processEvents()
            try:
                if self.session_controller is None:
                    raise RuntimeError("Session controller is not available.")
                self.session_controller.import_transfer_archive_with_feedback(Path(archive_path))
            except Exception as exc:
                QMessageBox.warning(self, "Transfer account", str(exc))
                self.reject()
                return
            finally:
                if archive_path:
                    shutil.rmtree(Path(archive_path).parent, ignore_errors=True)
            self.accept()


class TransferAccountHostDialog(QDialog):
    def __init__(self, *, parent: QWidget | None, session_controller) -> None:
        super().__init__(parent, Qt.Dialog)
        self.session_controller = session_controller
        self._service: AccountTransferHostService | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_requests)
        self._selected_session_id = ""

        self.setWindowTitle("Transfer Acc (Host)")
        self.setModal(True)
        self.resize(620, 470)
        self.setStyleSheet(
            """
            QDialog {
                background: #ffffff;
            }
            QLabel#TransferTitle {
                font-size: 18px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#TransferText {
                font-size: 13px;
                color: #64748b;
            }
            QListWidget {
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 14px;
                background: rgba(248, 250, 252, 0.92);
                padding: 6px;
            }
            QListWidget::item {
                border-radius: 10px;
                padding: 10px 12px;
                margin: 3px 0px;
            }
            QListWidget::item:selected {
                background: rgba(22, 119, 232, 0.12);
                color: #0f172a;
            }
            QPushButton {
                min-height: 34px;
                border-radius: 10px;
                border: none;
                padding: 6px 14px;
                background: rgba(15, 37, 57, 0.08);
                color: #0f172a;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.12);
            }
            QPushButton#PrimaryButton {
                background: #1677e8;
                color: white;
            }
            QPushButton#PrimaryButton:hover {
                background: #1468ca;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("Transfer Acc (Host)")
        title.setObjectName("TransferTitle")
        layout.addWidget(title)

        self.exposure_label = QLabel("")
        self.exposure_label.setObjectName("TransferText")
        self.exposure_label.setWordWrap(True)
        layout.addWidget(self.exposure_label)

        self.request_list = QListWidget()
        self.request_list.currentItemChanged.connect(self._refresh_detail_panel)
        layout.addWidget(self.request_list, 1)

        self.detail_label = QLabel("Numbers appear only after a peer requests this host.")
        self.detail_label.setObjectName("TransferText")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        codes_row = QHBoxLayout()
        codes_row.setContentsMargins(0, 0, 0, 0)
        codes_row.setSpacing(10)
        self.code_labels = [TransferCodeLabel(self) for _ in range(3)]
        for label in self.code_labels:
            codes_row.addWidget(label)
        codes_row.addStretch(1)
        layout.addLayout(codes_row)

        self.status_label = QLabel("Waiting for peer requests.")
        self.status_label.setObjectName("TransferText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        self.confirm_btn = QPushButton("Confirm transfer")
        self.confirm_btn.setObjectName("PrimaryButton")
        self.confirm_btn.clicked.connect(self._confirm_selected_request)
        actions.addWidget(self.confirm_btn)
        self.reject_btn = QPushButton("Reject")
        self.reject_btn.clicked.connect(self._reject_selected_request)
        actions.addWidget(self.reject_btn)
        actions.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        try:
            if self.session_controller is None:
                raise RuntimeError("Session controller is not available.")
            self._service = AccountTransferHostService(
                host_name=self.session_controller.active_transfer_profile_name(),
                estimate_size_bytes=self.session_controller.estimate_current_account_size,
                create_export_archive=self.session_controller.create_transfer_export,
            )
            self._service.start()
        except Exception as exc:
            QMessageBox.warning(self, "Transfer account", str(exc))
            QTimer.singleShot(0, self.reject)
            return

        self._refresh_requests()
        self._refresh_timer.start(500)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        if self._service is not None:
            self._service.stop()
            self._service = None
        super().closeEvent(event)

    def _refresh_requests(self) -> None:
        service = self._service
        if service is None:
            return
        self.exposure_label.setText(
            f'"{service.host_name}" is exposed on your local network while this window stays open.'
        )
        requests = service.list_requests()
        selected_id = self._selected_session_id
        self.request_list.blockSignals(True)
        self.request_list.clear()
        for request in requests:
            peer_name = str(request.get("peer_name", "")).strip() or "Unknown device"
            status = str(request.get("status", "")).strip().capitalize()
            item = QListWidgetItem(f"{peer_name}\n{status}")
            item.setData(Qt.ItemDataRole.UserRole, str(request.get("session_id", "")))
            self.request_list.addItem(item)
            if str(request.get("session_id", "")) == selected_id:
                self.request_list.setCurrentItem(item)
        if self.request_list.count() and self.request_list.currentItem() is None:
            self.request_list.setCurrentRow(0)
        self.request_list.blockSignals(False)
        self._refresh_detail_panel()
        if not requests:
            self.detail_label.setText("Numbers appear only after a peer requests this host.")
            self.status_label.setText("Waiting for peer requests.")
            for label in self.code_labels:
                label.setText("--")
            self.confirm_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)

    def _current_request(self) -> dict[str, Any] | None:
        service = self._service
        item = self.request_list.currentItem()
        if service is None or item is None:
            self._selected_session_id = ""
            return None
        session_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        self._selected_session_id = session_id
        for request in service.list_requests():
            if str(request.get("session_id", "")) == session_id:
                return request
        return None

    def _refresh_detail_panel(self) -> None:
        request = self._current_request()
        if request is None:
            return
        peer_name = str(request.get("peer_name", "")).strip() or "Unknown device"
        status = str(request.get("status", "")).strip()
        codes = [str(code).zfill(2) for code in list(request.get("confirmation_codes", []))[:3]]
        while len(codes) < 3:
            codes.append("--")
        for label, code in zip(self.code_labels, codes):
            label.setText(code)
        if status == "pending":
            self.detail_label.setText(
                f'Request from "{peer_name}". Confirm the number you see on the device you are requesting match the number you see on the screen.'
            )
            self.status_label.setText(
                f'If you confirm, this peer will overwrite its current account with "{self._service.host_name if self._service is not None else ""}". Estimated size: {_format_transfer_size(request.get("estimated_size_bytes", 0))}.'
            )
        elif status == "preparing":
            self.detail_label.setText(f'Request from "{peer_name}" was confirmed. Preparing the account copy now.')
            self.status_label.setText("Building the transfer archive for the peer.")
        elif status == "ready":
            self.detail_label.setText(f'Request from "{peer_name}" is ready for download.')
            self.status_label.setText(
                f'Prepared archive size: {_format_transfer_size(request.get("archive_size_bytes", 0))}.'
            )
        elif status == "completed":
            self.detail_label.setText(f'Request from "{peer_name}" finished downloading the account copy.')
            self.status_label.setText("This transfer is complete.")
        else:
            error = str(request.get("error", "")).strip()
            self.detail_label.setText(f'Request from "{peer_name}" is {status}.'.strip())
            self.status_label.setText(error or f"Status: {status or 'unknown'}.")
        self.confirm_btn.setEnabled(status == "pending")
        self.reject_btn.setEnabled(status in {"pending", "preparing", "ready"})

    def _confirm_selected_request(self) -> None:
        request = self._current_request()
        if request is None or self._service is None:
            return
        try:
            self._service.approve_request(str(request.get("session_id", "")))
        except Exception as exc:
            QMessageBox.warning(self, "Transfer account", str(exc))
        self._refresh_requests()

    def _reject_selected_request(self) -> None:
        request = self._current_request()
        if request is None or self._service is None:
            return
        try:
            self._service.reject_request(str(request.get("session_id", "")))
        except Exception as exc:
            QMessageBox.warning(self, "Transfer account", str(exc))
        self._refresh_requests()


class TransferAccountPeerDialog(QDialog):
    def __init__(self, *, parent: QWidget | None, session_controller) -> None:
        super().__init__(parent, Qt.Dialog)
        self.session_controller = session_controller
        self._client = AccountTransferPeerClient()
        self._active_request: dict[str, Any] | None = None
        self._active_host: dict[str, Any] | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_request_status)

        self.setWindowTitle("Transfer Acc (Peer)")
        self.setModal(True)
        self.resize(620, 520)
        self.setStyleSheet(
            """
            QDialog {
                background: #ffffff;
            }
            QLabel#TransferTitle {
                font-size: 18px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#TransferText {
                font-size: 13px;
                color: #64748b;
            }
            QListWidget {
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 14px;
                background: rgba(248, 250, 252, 0.92);
                padding: 6px;
            }
            QListWidget::item {
                border-radius: 10px;
                padding: 10px 12px;
                margin: 3px 0px;
            }
            QListWidget::item:selected {
                background: rgba(22, 119, 232, 0.12);
                color: #0f172a;
            }
            QPushButton {
                min-height: 34px;
                border-radius: 10px;
                border: none;
                padding: 6px 14px;
                background: rgba(15, 37, 57, 0.08);
                color: #0f172a;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.12);
            }
            QPushButton#PrimaryButton {
                background: #1677e8;
                color: white;
            }
            QPushButton#PrimaryButton:hover {
                background: #1468ca;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("Transfer Acc (Peer)")
        title.setObjectName("TransferTitle")
        layout.addWidget(title)

        intro = QLabel(
            "You will see profile names of all ONCard accounts exposed right now. To expose, go to Settings -> Account -> Transfer Acc (Host)."
        )
        intro.setObjectName("TransferText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        warning = QLabel(
            "If the host confirms this request, all data in this account will be overwritten by the host account data."
        )
        warning.setObjectName("TransferText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.host_list = QListWidget()
        layout.addWidget(self.host_list, 1)

        self.status_label = QLabel("Refresh to search for exposed ONCard accounts on your local network.")
        self.status_label.setObjectName("TransferText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        codes_row = QHBoxLayout()
        codes_row.setContentsMargins(0, 0, 0, 0)
        codes_row.setSpacing(10)
        self.code_labels = [TransferCodeLabel(self) for _ in range(3)]
        for label in self.code_labels:
            codes_row.addWidget(label)
        codes_row.addStretch(1)
        layout.addLayout(codes_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_hosts)
        actions.addWidget(self.refresh_btn)
        self.request_btn = QPushButton("Request transfer")
        self.request_btn.setObjectName("PrimaryButton")
        self.request_btn.clicked.connect(self._request_selected_host)
        actions.addWidget(self.request_btn)
        actions.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._refresh_hosts()

    def reject(self) -> None:
        self._poll_timer.stop()
        super().reject()

    def _refresh_hosts(self) -> None:
        if self._active_request is not None:
            return
        try:
            hosts = self._client.discover_hosts()
        except Exception as exc:
            QMessageBox.warning(self, "Transfer account", str(exc))
            return
        self.host_list.clear()
        for host in hosts:
            host_name = str(host.get("host_name", "")).strip() or "ONCard Account"
            address = str(host.get("address", "")).strip()
            item = QListWidgetItem(f"{host_name}\n{address}")
            item.setData(Qt.ItemDataRole.UserRole, dict(host))
            self.host_list.addItem(item)
        if self.host_list.count():
            self.host_list.setCurrentRow(0)
            self.status_label.setText(f"Found {self.host_list.count()} exposed account(s).")
        else:
            self.status_label.setText("No exposed account hosts were found on your local network.")

    def _selected_host(self) -> dict[str, Any] | None:
        item = self.host_list.currentItem()
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        return dict(payload) if isinstance(payload, dict) else None

    def _request_selected_host(self) -> None:
        if self._active_request is not None:
            return
        host = self._selected_host()
        if host is None:
            QMessageBox.information(self, "Transfer account", "Select an exposed ONCard account first.")
            return
        confirm = QMessageBox.question(
            self,
            "Transfer account",
            "If the host confirms this request, this account on this device will be overwritten. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            peer_name = self.session_controller.active_transfer_profile_name() if self.session_controller is not None else "ONCard Peer"
            request = self._client.request_transfer(host, peer_name=peer_name)
        except Exception as exc:
            QMessageBox.warning(self, "Transfer account", str(exc))
            return
        self._active_host = dict(host)
        self._active_request = dict(request)
        codes = [str(code).zfill(2) for code in list(request.get("confirmation_codes", []))[:3]]
        while len(codes) < 3:
            codes.append("--")
        for label, code in zip(self.code_labels, codes):
            label.setText(code)
        host_name = str(host.get("host_name", "")).strip() or "ONCard Account"
        estimate = _format_transfer_size(request.get("estimated_size_bytes", 0))
        self.status_label.setText(
            f'Waiting for "{host_name}" to confirm the matching number. Estimated account size: {estimate}.'
        )
        self.refresh_btn.setEnabled(False)
        self.request_btn.setEnabled(False)
        self.host_list.setEnabled(False)
        self._poll_timer.start(900)

    def _poll_request_status(self) -> None:
        if self._active_host is None or self._active_request is None:
            self._poll_timer.stop()
            return
        try:
            status = self._client.request_status(
                self._active_host,
                session_id=str(self._active_request.get("session_id", "")),
                auth_token=str(self._active_request.get("auth_token", "")),
            )
        except Exception as exc:
            self._poll_timer.stop()
            QMessageBox.warning(self, "Transfer account", str(exc))
            self._reset_request_state()
            return
        state = str(status.get("status", "")).strip()
        if state == "pending":
            self.status_label.setText("Request sent. Waiting for the host to confirm the matching number.")
            return
        if state == "preparing":
            self.status_label.setText("Host confirmed the number. Preparing account data now...")
            return
        if state == "ready":
            self._poll_timer.stop()
            self.status_label.setText("Host confirmed the transfer. Starting download...")
            self._launch_import_dialog()
            return
        if state == "completed":
            self._poll_timer.stop()
            self.status_label.setText("Transfer archive was already completed.")
            self._reset_request_state()
            return
        self._poll_timer.stop()
        message = str(status.get("error", "")).strip() or f"Transfer request status: {state or 'unknown'}."
        QMessageBox.warning(self, "Transfer account", message)
        self._reset_request_state()

    def _launch_import_dialog(self) -> None:
        if self._active_host is None or self._active_request is None:
            return
        dialog = AccountTransferImportDialog(
            session_controller=self.session_controller,
            host=self._active_host,
            transfer_request=self._active_request,
            parent=None,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        _retain_transfer_import_dialog(dialog)
        dialog.show()
        dialog.start()
        self.accept()

    def _reset_request_state(self) -> None:
        self._active_host = None
        self._active_request = None
        self.refresh_btn.setEnabled(True)
        self.request_btn.setEnabled(True)
        self.host_list.setEnabled(True)
        for label in self.code_labels:
            label.setText("--")
        self._refresh_hosts()


class SettingsDialog(QDialog):
    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        preflight: ModelPreflightService,
        parent=None,
        *,
        session_controller=None,
        auto_install_model_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.datastore = datastore
        self.ollama = ollama
        self.preflight = preflight
        self.session_controller = session_controller
        self._auto_install_model_key = str(auto_install_model_key or "").strip()
        self.paths = getattr(parent, "paths", None)
        self.settings_search_service = SettingsSearchService(datastore)
        self._install_worker: ModelInstallWorker | None = None
        self._mcq_bulk_worker: MCQBulkWorker | None = None
        self._install_target_key = ""
        self._model_rows: dict[str, dict[str, object]] = {}
        self._context_length_spins: dict[str, SettingsSpinBox] = {}
        self._context_model_combos: dict[str, PopupMenuComboBox] = {}
        self._account_action_buttons: list[QPushButton] = []
        self._sfx_ready = False
        self._last_attention_value = 5
        self._last_ask_ai_emoji_value = 2
        self._model_worker_action = "install"
        self._cloud_model_tags: list[str] = []
        self._loading_cloud_models = False
        self._backdrop_overlay: QWidget | None = None
        self._backdrop_target: QWidget | None = None
        self._backdrop_previous_effect = None
        self._settings_nav_buttons: list[SettingsRailButton] = []
        self._settings_search_targets: dict[str, dict[str, object]] = {}
        self._settings_tab_scrolls: dict[str, QScrollArea] = {}
        self._settings_search_loading = False
        self._settings_search_pending_result: dict[str, object] | None = None
        self._settings_search_result_ready = False
        self._settings_search_video_loops = 0
        self._settings_search_required_video_loops = 2
        self._settings_search_fade_animation: QPropertyAnimation | None = None
        self._avatar_category = ""
        self._avatar_file = ""
        self._avatar_buttons: list[SettingsAvatarChoiceButton] = []
        self._avatar_grid_column_count = 0
        self._deferred_status_loaded = False
        self._settings_search_timer = QTimer(self)
        self._settings_search_timer.setSingleShot(True)
        self._settings_search_timer.timeout.connect(self._refresh_settings_search_suggestions)
        self._settings_search_blur_timer = QTimer(self)
        self._settings_search_blur_timer.setSingleShot(True)
        self._settings_search_blur_timer.timeout.connect(self._hide_settings_search_dropdown_if_unfocused)

        self.setWindowTitle("Settings")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("SettingsDialog")
        self.setModal(True)
        self.setStyleSheet(
            """
            QDialog#SettingsDialog {
                background: transparent;
            }
            QFrame#SettingsWindowShell {
                background: rgba(244, 246, 246, 0.62);
                border: 1px solid rgba(255, 255, 255, 0.58);
                border-radius: 34px;
            }
            QWidget#SettingsSidebar,
            QWidget#SettingsRightPanel {
                background: transparent;
            }
            QFrame#SettingsGlassDivider {
                background: rgba(255, 255, 255, 0.72);
                border: none;
            }
            QStackedWidget#SettingsPages,
            QScrollArea#SettingsScrollArea,
            QScrollArea#SettingsScrollArea > QWidget,
            QScrollArea#SettingsScrollArea > QWidget > QWidget,
            QWidget#SettingsTabCanvas {
                background: transparent;
                border: none;
            }
            QFrame#SettingsCard {
                background: rgba(237, 244, 249, 0.28);
                border: 1px solid rgba(116, 138, 158, 0.10);
                border-radius: 18px;
            }
            QFrame#SettingsCard:hover {
                border: 1px solid rgba(116, 138, 158, 0.14);
            }
            QFrame#SettingsSectionCard {
                background: rgba(234, 241, 247, 0.24);
                border: 1px solid rgba(116, 138, 158, 0.08);
                border-radius: 16px;
            }
            QAbstractButton#SettingsRailNavButton {
                background: rgba(255, 255, 255, 0);
                background-color: rgba(255, 255, 255, 0);
                border: none;
                border-radius: 9px;
                padding: 5px 12px;
                color: rgba(76, 84, 91, 0.46);
                font-size: 12px;
                font-weight: 800;
                text-align: left;
            }
            QAbstractButton#SettingsRailNavButton:hover {
                background: rgba(255, 255, 255, 0);
                background-color: rgba(255, 255, 255, 0);
                border: none;
                color: rgba(76, 84, 91, 0.75);
            }
            QAbstractButton#SettingsRailNavButton:checked {
                background: #1677e8;
                border: none;
                color: rgba(246, 250, 255, 0.93);
            }
            QAbstractButton#SettingsRailNavButton:pressed {
                background: #1677e8;
                border: none;
                color: rgba(246, 250, 255, 0.93);
                padding: 5px 12px;
            }
            QAbstractButton#SettingsRailNavButton:checked:pressed,
            QAbstractButton#SettingsRailNavButton:checked:hover {
                background: #1677e8;
                border: none;
                padding: 5px 12px;
            }
            QLabel#SettingsSidebarTitle,
            QLabel#SettingsProfileName,
            QLabel#SettingsProfileSubtitle {
                background: transparent;
            }
            QLabel#SectionTitle {
                color: #627181;
            }
            QLabel#SectionText,
            QLabel#SmallMeta {
                color: #748596;
            }
            QLabel#SettingsProfileName {
                color: rgba(77, 92, 105, 0.72);
                font-size: 27px;
                font-weight: 500;
            }
            QLabel#SettingsProfileSubtitle {
                color: rgba(109, 119, 127, 0.50);
                font-size: 13px;
                font-weight: 700;
            }
            QToolButton#SettingsHeaderIconButton,
            QToolButton#SettingsHeaderActionButton {
                background-color: transparent;
                border: 2px solid transparent;
                border-radius: 12px;
                padding: 4px;
                outline: none;
            }
            QToolButton#SettingsHeaderIconButton:hover,
            QToolButton#SettingsHeaderActionButton:hover {
                background-color: transparent;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked {
                background-color: #0f2539;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked:hover {
                background-color: #0f2539;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked:focus {
                border: 2px solid rgba(15, 37, 57, 0.4);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background-color: #e2e8f0;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:focus,
            QToolButton#SettingsHeaderActionButton:focus {
                border: 2px solid rgba(15, 37, 57, 0.3);
            }
            QToolButton#SettingsNavTab {
                background-color: rgba(241, 245, 249, 0.58);
                border: 1px solid rgba(226, 232, 240, 0.72);
                border-radius: 12px;
                padding: 4px 8px;
                color: #64748b;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton#SettingsNavTab:hover {
                background-color: rgba(241, 245, 249, 0.58);
                border-color: rgba(226, 232, 240, 0.72);
                color: #64748b;
            }
            QToolButton#SettingsNavTab:checked {
                background-color: #0f2539;
                border: 1px solid #0f2539;
                color: #ffffff;
            }
            QFrame#SettingsSearchShell {
                background: rgba(244, 248, 251, 0.42);
                border: 1px solid rgba(116, 138, 158, 0.14);
                border-radius: 14px;
            }
            QFrame#SettingsSearchShell[focusRing="true"] {
                background: rgba(248, 251, 253, 0.66);
                border: 1px solid rgba(82, 123, 161, 0.34);
            }
            QLineEdit#SettingsHeaderSearchInput {
                background: transparent;
                border: none;
                padding: 0px;
                color: #334155;
                font-size: 13px;
                selection-background-color: rgba(122, 168, 220, 0.2);
            }
            QLineEdit#SettingsHeaderSearchInput:focus {
                background: transparent;
                border: none;
            }
            QPushButton#SettingsPickerButton {
                background: rgba(244, 248, 251, 0.56);
                border: 1px solid rgba(123, 146, 168, 0.18);
                border-radius: 12px;
                padding: 10px 14px;
                color: #1e293b;
                font-size: 13px;
                font-weight: 500;
                text-align: left;
            }
            QPushButton#SettingsPickerButton:hover {
                background: rgba(247, 250, 253, 0.70);
                border: 1px solid rgba(82, 123, 161, 0.24);
            }
            QPushButton#SettingsPickerButton:pressed {
                background: rgba(229, 238, 246, 0.82);
                border: 1px solid rgba(82, 123, 161, 0.30);
            }
            QPushButton#SettingsPickerButton[placeholder="true"] {
                color: #94a3b8;
            }
            """
            + (self._settings_dialog_dark_stylesheet() if is_dark_theme() else "")
        )
        self._apply_initial_geometry()
        self._build_ui()
        self._sync_settings_bordered_widget_heights()
        self.settings_search_service.ensure_index()
        self._disable_settings_motion_transforms()
        self._load()
        self._sync_settings_bordered_widget_heights()
        self._sfx_ready = True
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        if self._auto_install_model_key:
            QTimer.singleShot(0, self._run_deferred_auto_install)

    @staticmethod
    def _settings_surface_colors() -> dict[str, str]:
        if is_dark_theme():
            return {
                "card": "rgba(26, 35, 46, 0.74)",
                "section": "rgba(31, 42, 54, 0.64)",
                "border": "rgba(121, 183, 255, 0.18)",
                "title": "#d7e8ff",
                "text": "#9aa8b7",
            }
        return {
            "card": "rgba(237, 244, 249, 0.28)",
            "section": "rgba(234, 241, 247, 0.24)",
            "border": "rgba(116, 138, 158, 0.10)",
            "title": "#627181",
            "text": "#748596",
        }

    def _settings_dialog_dark_stylesheet(self) -> str:
        tokens = theme_tokens("dark")
        return f"""
            QFrame#SettingsWindowShell {{
                background: rgba(17, 24, 32, 0.78);
                border: 1px solid {tokens["border"]};
            }}
            QFrame#SettingsGlassDivider {{
                background: rgba(122, 142, 164, 0.22);
            }}
            QFrame#SettingsCard, QFrame#SettingsSectionCard,
            QFrame#SettingsSearchShell, QFrame#SettingsSearchSuggestionDropdown {{
                background: {tokens["surface"]};
                border-color: {tokens["border"]};
            }}
            QFrame#SettingsSearchShell[focusRing="true"] {{
                background: {tokens["elevated"]};
                border-color: {tokens["primary"]};
            }}
            QAbstractButton#SettingsRailNavButton {{
                color: {tokens["muted"]};
            }}
            QAbstractButton#SettingsRailNavButton:hover {{
                color: {tokens["text"]};
            }}
            QAbstractButton#SettingsRailNavButton:checked,
            QAbstractButton#SettingsRailNavButton:pressed,
            QAbstractButton#SettingsRailNavButton:checked:pressed,
            QAbstractButton#SettingsRailNavButton:checked:hover,
            QToolButton#SettingsNavTab:checked,
            QToolButton#SettingsHeaderIconButton:checked,
            QToolButton#SettingsHeaderIconButton:checked:hover {{
                background: {tokens["primary"]};
                border-color: {tokens["primary"]};
                color: #07111b;
            }}
            QLabel#SettingsProfileName {{
                color: {tokens["text"]};
            }}
            QLabel#SettingsProfileSubtitle,
            QToolButton#SettingsNavTab {{
                color: {tokens["muted"]};
            }}
            QToolButton#SettingsHeaderActionButton:pressed,
            QPushButton#SettingsPickerButton:pressed {{
                background: {tokens["pressed"]};
            }}
            QToolButton#SettingsNavTab,
            QPushButton#SettingsPickerButton {{
                background: {tokens["surface"]};
                border-color: {tokens["border"]};
                color: {tokens["text"]};
            }}
            QLineEdit#SettingsHeaderSearchInput {{
                color: {tokens["text"]};
                selection-background-color: {tokens["selection"]};
            }}
            QPushButton#SettingsPickerButton:hover {{
                background: {tokens["hover"]};
                border-color: rgba(121, 183, 255, 0.62);
            }}
            QPushButton#SettingsPickerButton[placeholder="true"] {{
                color: {tokens["muted"]};
            }}
        """

    def _apply_initial_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 840)
            return
        available = screen.availableGeometry()
        width = min(1180, max(960, available.width() - 120))
        height = min(860, max(700, available.height() - 80))
        self.resize(width, height)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(58, 58, 58, 58)
        root.setSpacing(0)

        shell_surface = QFrame(self)
        shell_surface.setObjectName("SettingsWindowShell")
        polish_surface(shell_surface)
        shell_shadow = QGraphicsDropShadowEffect(shell_surface)
        shell_shadow.setBlurRadius(50)
        shell_shadow.setOffset(0, 0)
        shell_shadow.setColor(QColor(15, 23, 42, 90))
        shell_surface.setGraphicsEffect(shell_shadow)
        self._shell_surface = shell_surface
        root.addWidget(shell_surface, 1)
        shell = QVBoxLayout(shell_surface)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        page_specs = [
            ("General", "general", self._build_general_tab()),
            ("Smart features", "ai", self._build_smart_features_tab()),
            ("Audio", "stats", self._build_audio_tab()),
            ("Performance", "performance", self._build_performance_tab()),
            ("Models", "ai", self._build_ai_tab()),
            ("Account", "user", self._build_account_tab()),
        ]

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)
        shell.addLayout(content_row, 1)

        self.settings_sidebar = self._build_settings_sidebar(page_specs)
        content_row.addWidget(self.settings_sidebar, 0)

        divider = QFrame()
        divider.setObjectName("SettingsGlassDivider")
        divider.setFixedWidth(1)
        content_row.addWidget(divider)

        right_panel = QWidget()
        right_panel.setObjectName("SettingsRightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(28, 20, 28, 22)
        right_layout.setSpacing(14)
        content_row.addWidget(right_panel, 1)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addStretch(1)

        self.settings_search_shell = QFrame()
        self.settings_search_shell.setObjectName("SettingsSearchShell")
        polish_surface(self.settings_search_shell)
        self.settings_search_shell.setFixedSize(420, 34)
        search_shell_layout = QHBoxLayout(self.settings_search_shell)
        search_shell_layout.setContentsMargins(8, 0, 14, 0)
        search_shell_layout.setSpacing(8)

        self.settings_search_btn = QToolButton()
        self.settings_search_btn.setObjectName("SettingsHeaderSearchButton")
        self.settings_search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_search_btn.setToolTip("Search settings")
        self.settings_search_btn.setAutoRaise(False)
        self.settings_search_btn.setFixedSize(24, 24)
        if SETTINGS_SEARCH_ICON_PATH.exists():
            self.settings_search_btn.setIcon(self._header_padded_icon(SETTINGS_SEARCH_ICON_PATH, QSize(15, 15)))
            self.settings_search_btn.setIconSize(QSize(15, 15))
        self.settings_search_btn.setStyleSheet(
            """
            QToolButton#SettingsHeaderSearchButton {
                background: transparent;
                border: none;
                border-radius: 8px;
            }
            QToolButton#SettingsHeaderSearchButton:hover {
                background: transparent;
            }
            QToolButton#SettingsHeaderSearchButton:pressed {
                background: rgba(15, 37, 57, 0.12);
            }
            """
        )
        self.settings_search_btn.clicked.connect(self._execute_settings_search)
        search_shell_layout.addWidget(self.settings_search_btn, 0, Qt.AlignVCenter)

        self.settings_search_stack = QStackedWidget()
        self.settings_search_stack.setStyleSheet("background: transparent; border: none;")
        self.settings_search_edit = AnimatedLineEdit()
        self.settings_search_edit.setObjectName("SettingsHeaderSearchInput")
        self.settings_search_edit.setPlaceholderText("Search settings")
        self.settings_search_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.settings_search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.settings_search_edit.installEventFilter(self)
        self.settings_search_edit.textChanged.connect(self._queue_settings_search_suggestions)
        self.settings_search_edit.returnPressed.connect(self._execute_settings_search)
        self.settings_search_stack.addWidget(self.settings_search_edit)

        self.settings_search_loading_widget = SettingsSearchLoadingWidget(SETTINGS_SEARCH_LOADING_LINES)
        self.settings_search_stack.addWidget(self.settings_search_loading_widget)
        search_shell_layout.addWidget(self.settings_search_stack, 1)
        header.addWidget(self.settings_search_shell)

        self.save_btn = self._header_icon_button("check", "Save")
        self.cancel_btn = self._header_icon_button("cross_two", "Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setStyleSheet(
            """
            QToolButton#SettingsHeaderActionButton {
                background: rgba(244, 248, 251, 0.46);
                border: 1px solid rgba(116, 138, 158, 0.14);
                border-radius: 12px;
            }
            QToolButton#SettingsHeaderActionButton:hover {
                background: rgba(247, 250, 253, 0.62);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background: rgba(229, 238, 246, 0.82);
            }
            """
        )
        self.cancel_btn.setStyleSheet(
            """
            QToolButton#SettingsHeaderActionButton {
                background: rgba(244, 248, 251, 0.36);
                border: 1px solid rgba(116, 138, 158, 0.12);
                border-radius: 12px;
            }
            QToolButton#SettingsHeaderActionButton:hover {
                background: rgba(247, 250, 253, 0.54);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background: rgba(229, 238, 246, 0.76);
            }
            """
        )
        header.addWidget(self.save_btn)
        header.addWidget(self.cancel_btn)
        right_layout.addLayout(header)

        for index, (label, icon_name, page) in enumerate(page_specs):
            self.pages.addWidget(page)
        self.settings_search_dropdown = QFrame(shell_surface)
        self.settings_search_dropdown.setObjectName("SearchSuggestionDropdown")
        polish_surface(self.settings_search_dropdown)
        dropdown_shadow = QGraphicsDropShadowEffect(self.settings_search_dropdown)
        dropdown_shadow.setBlurRadius(42)
        dropdown_shadow.setOffset(0, 10)
        dropdown_shadow.setColor(QColor(15, 37, 57, 92))
        self.settings_search_dropdown.setGraphicsEffect(dropdown_shadow)
        self.settings_search_dropdown.setVisible(False)
        dropdown_layout = QVBoxLayout(self.settings_search_dropdown)
        dropdown_layout.setContentsMargins(10, 10, 10, 10)
        dropdown_layout.setSpacing(6)
        self.settings_search_label = QLabel("Did you mean something like:")
        self.settings_search_label.setObjectName("SmallMeta")
        dropdown_layout.addWidget(self.settings_search_label)
        self.settings_search_list = QListWidget()
        self.settings_search_list.setObjectName("SearchSuggestionList")
        self.settings_search_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_search_list.itemClicked.connect(self._settings_search_suggestion_clicked)
        self.settings_search_list.itemActivated.connect(self._settings_search_suggestion_clicked)
        self.settings_search_list.installEventFilter(self)
        dropdown_layout.addWidget(self.settings_search_list)

        self.settings_content_stack = QStackedWidget()
        self.settings_content_stack.setStyleSheet("background: transparent; border: none;")
        self.settings_search_skeleton = SettingsSearchSkeletonPage()
        self.settings_content_stack.addWidget(self.pages)
        self.settings_content_stack.addWidget(self.settings_search_skeleton)
        right_layout.addWidget(self.settings_content_stack, 1)
        self.settings_search_edit.clearFocus()
        self._set_settings_page(0)

    def _build_settings_sidebar(self, page_specs: list[tuple[str, str, QWidget]]) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(300)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)
        title = QLabel("Settings - ONCard")
        title.setObjectName("SettingsSidebarTitle")
        title.setStyleSheet("QLabel#SettingsSidebarTitle { color: rgba(91, 99, 107, 0.34); font-size: 12px; font-weight: 800; }")
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        layout.addSpacing(58)

        self.sidebar_avatar_label = QLabel()
        self.sidebar_avatar_label.setObjectName("SettingsSidebarAvatar")
        self.sidebar_avatar_label.setFixedSize(154, 154)
        self.sidebar_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_avatar_label.setStyleSheet(
            """
            QLabel#SettingsSidebarAvatar {
                background: transparent;
                border: none;
                padding: 0px;
            }
            """
        )
        layout.addWidget(self.sidebar_avatar_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(0)

        self.sidebar_name_label = QLabel("Random Person")
        self.sidebar_name_label.setObjectName("SettingsProfileName")
        self.sidebar_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_name_label.setFixedHeight(34)
        layout.addWidget(self.sidebar_name_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.sidebar_subtitle_label = QLabel("I like gaming and ML")
        self.sidebar_subtitle_label.setObjectName("SettingsProfileSubtitle")
        self.sidebar_subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_subtitle_label.setWordWrap(True)
        self.sidebar_subtitle_label.setFixedWidth(230)
        self.sidebar_subtitle_label.setFixedHeight(34)
        layout.addWidget(self.sidebar_subtitle_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        self._settings_nav_buttons = []
        for index, (label, icon_name, _page) in enumerate(page_specs):
            button = self._settings_rail_button(icon_name, label)
            button.clicked.connect(lambda _checked=False, selected=index: self._set_settings_page(selected, animate=True))
            self._settings_nav_buttons.append(button)
            layout.addWidget(button)
            if index < len(page_specs) - 1:
                layout.addSpacing(8)
        layout.addSpacing(12)
        return sidebar

    def _settings_rail_button(self, icon_name: str, label: str) -> SettingsRailButton:
        button = SettingsRailButton(label)
        button.setObjectName("SettingsRailNavButton")
        icon_path = self._icon_path(icon_name)
        if icon_path is not None:
            button.setIcon(QIcon(str(icon_path)))
            button.setIconSize(QSize(17, 17))
        return button

    def _icon_path(self, icon_name: str) -> Path | None:
        parent = self.parentWidget()
        icons_root = getattr(getattr(parent, "paths", None), "icons", None)
        if isinstance(icons_root, Path):
            return icons_root / "common" / f"{icon_name}.png"
        fallback = Path(__file__).resolve().parents[3] / "assets" / "icons" / "common" / f"{icon_name}.png"
        return fallback if fallback.exists() else None

    def _header_icon_button(self, icon_name: str, tooltip: str, *, checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("SettingsNavTab" if checkable else "SettingsHeaderActionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly if checkable else Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setAutoRaise(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if checkable:
            button.setText(tooltip)
            button.setFixedSize(108, 32)
        else:
            button.setFixedSize(36, 36)
        icon_path = self._icon_path(icon_name)
        if icon_path is not None:
            if checkable:
                icon_size = QSize(14, 14)
                icon = QIcon(str(icon_path))
                button.setIcon(icon)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            else:
                icon_size = QSize(16, 16)
                padded = self._header_padded_icon(icon_path, icon_size)
                button.setIcon(padded if not padded.isNull() else QIcon(str(icon_path)))
                button.setIconSize(icon_size)
        return button

    def _header_padded_icon(self, icon_path: Path, target_size: QSize) -> QIcon:
        source = QPixmap(str(icon_path))
        if source.isNull():
            return QIcon(str(icon_path))

        width = max(1, int(target_size.width()))
        height = max(1, int(target_size.height()))

        # Keep a transparent inset so tiny antialias pixels do not touch icon bounds.
        inner = QSize(max(1, width - 2), max(1, height - 2))
        scaled = source.scaled(inner, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        x = (width - scaled.width()) // 2
        y = (height - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return QIcon(canvas)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "settings_search_edit", None):
            if event.type() == QEvent.Type.FocusIn:
                self.settings_search_shell.setProperty("focusRing", True)
                self.settings_search_shell.style().unpolish(self.settings_search_shell)
                self.settings_search_shell.style().polish(self.settings_search_shell)
                self.settings_search_shell.update()
                if self.settings_search_list.count() > 0 and not self._settings_search_loading:
                    QTimer.singleShot(0, self._reposition_settings_search_dropdown)
                    QTimer.singleShot(0, lambda: self._set_settings_search_dropdown_visible(True))
            elif event.type() == QEvent.Type.FocusOut:
                self.settings_search_shell.setProperty("focusRing", False)
                self.settings_search_shell.style().unpolish(self.settings_search_shell)
                self.settings_search_shell.style().polish(self.settings_search_shell)
                self.settings_search_shell.update()
                self._settings_search_blur_timer.start(120)
        elif watched is getattr(self, "settings_search_list", None) and event.type() == QEvent.Type.FocusOut:
            self._settings_search_blur_timer.start(120)
        elif watched is getattr(self, "avatar_grid_host", None) and event.type() == QEvent.Type.Resize:
            self._refresh_avatar_grid_if_columns_changed()
        return super().eventFilter(watched, event)

    def _set_settings_page(self, index: int, *, animate: bool = False, show_active: bool = True) -> None:
        self._reset_settings_transient_state()
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self._settings_nav_buttons):
            is_current = bool(show_active and button_index == index)
            button.setChecked(is_current)
            if not is_current:
                button._hover_progress = 0.0
                button.update()
            if is_current and animate:
                button.begin_reveal()
        self._reset_settings_transient_state()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_settings_bordered_widget_heights()
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._reposition_settings_search_dropdown()
        if not self._deferred_status_loaded:
            self._deferred_status_loaded = True
            QTimer.singleShot(250, self._refresh_model_status)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_settings_bordered_widget_heights()
        self._reposition_settings_search_dropdown()

    def _disable_settings_motion_transforms(self) -> None:
        """Disable scale/lift/grow motion in Settings to prevent hover jitter."""
        for widget in self.findChildren(QWidget):
            if hasattr(widget, "set_motion_scale_range"):
                widget.set_motion_scale_range(0.0)
            if hasattr(widget, "set_motion_lift"):
                widget.set_motion_lift(0.0)
            if hasattr(widget, "set_motion_press_scale"):
                widget.set_motion_press_scale(0.0)
            if hasattr(widget, "set_motion_hover_grow"):
                widget.set_motion_hover_grow(0, 0)
            # Covers AnimatedButton / AnimatedToolButton-style press offset logic.
            if widget.property("disablePressMotion") is not None or hasattr(widget, "_press_animation"):
                widget.setProperty("disablePressMotion", True)
            if isinstance(widget, (QPushButton, QToolButton)):
                widget.setProperty("disablePressMotion", True)
            for animation_name in ("_press_animation", "_hover_animation", "_size_animation"):
                animation = getattr(widget, animation_name, None)
                if animation is not None and hasattr(animation, "stop"):
                    animation.stop()
            if hasattr(widget, "_press_progress"):
                widget._press_progress = 0.0
            if hasattr(widget, "_hover_progress"):
                widget._hover_progress = 0.0
            if hasattr(widget, "_motion_hover_grow_x"):
                widget._motion_hover_grow_x = 0
            if hasattr(widget, "_motion_hover_grow_y"):
                widget._motion_hover_grow_y = 0

    def _reset_settings_transient_state(self) -> None:
        """Clear stale hover/focus dynamic state when pages are swapped in/out."""
        focus_widget = self.focusWidget()
        if isinstance(focus_widget, QWidget) and (focus_widget is self or self.isAncestorOf(focus_widget)):
            focus_widget.clearFocus()

        for widget in self.findChildren(QWidget):
            changed = False
            if widget.property("hovered") is not None:
                widget.setProperty("hovered", False)
                changed = True
            if widget.property("focusRing") is not None:
                widget.setProperty("focusRing", False)
                changed = True
            if isinstance(widget, SettingsRailButton) and not widget.underMouse() and not widget.isChecked():
                widget._hover_progress = 0.0
                widget.update()
            if changed:
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()

    def _register_settings_search_target(
        self,
        target_key: str,
        *,
        tab_key: str,
        scroll: QScrollArea | None,
        widget: QWidget,
    ) -> None:
        self._settings_search_targets[str(target_key)] = {
            "tab_key": str(tab_key),
            "scroll": scroll,
            "widget": widget,
        }
        if isinstance(scroll, QScrollArea):
            self._settings_tab_scrolls[str(tab_key)] = scroll

    def _queue_settings_search_suggestions(self, _text: str) -> None:
        if self._settings_search_loading:
            return
        self._settings_search_timer.start(110)

    def _refresh_settings_search_suggestions(self) -> None:
        if self._settings_search_loading or not self.settings_search_edit.hasFocus():
            self._set_settings_search_dropdown_visible(False)
            return
        query = self.settings_search_edit.text().strip()
        if len(query) < 2:
            self.settings_search_list.clear()
            self._set_settings_search_dropdown_visible(False)
            return
        suggestions = self.settings_search_service.suggestions(query, limit=5)
        self.settings_search_list.clear()
        for entry in suggestions:
            row = QListWidgetItem(self._settings_search_entry_path(entry))
            row.setData(Qt.ItemDataRole.UserRole, dict(entry))
            row.setData(Qt.ItemDataRole.ToolTipRole, str(entry.get("description", "")).strip())
            row.setSizeHint(QSize(0, 40))
            self.settings_search_list.addItem(row)
        self._set_settings_search_dropdown_visible(self.settings_search_list.count() > 0)

    def _settings_search_entry_path(self, entry: dict[str, object]) -> str:
        tab_title = str(entry.get("tab_title", "Settings")).strip() or "Settings"
        group_title = str(entry.get("group_title", "")).strip()
        feature_label = str(entry.get("feature_label", "")).strip()
        kind = str(entry.get("kind", "")).strip().lower()
        if kind == "tab":
            return tab_title
        if kind == "group":
            if group_title and group_title.lower() != tab_title.lower():
                return " -> ".join([tab_title, group_title])
            return tab_title
        parts = [tab_title]
        if group_title and group_title.lower() != tab_title.lower():
            parts.append(group_title)
        if feature_label and feature_label.lower() not in {tab_title.lower(), group_title.lower()}:
            parts.append(feature_label)
        return " -> ".join(parts)

    def _set_settings_search_dropdown_visible(self, visible: bool) -> None:
        if visible:
            self._reposition_settings_search_dropdown()
            self.settings_search_dropdown.raise_()
            self.settings_search_dropdown.show()
            return
        self.settings_search_dropdown.hide()

    def _hide_settings_search_dropdown_if_unfocused(self) -> None:
        if self.settings_search_edit.hasFocus() or self.settings_search_list.hasFocus():
            return
        self._set_settings_search_dropdown_visible(False)

    def _reposition_settings_search_dropdown(self) -> None:
        if not hasattr(self, "settings_search_shell") or not hasattr(self, "_shell_surface"):
            return
        if not self.settings_search_dropdown.isVisible() and self.settings_search_list.count() <= 0:
            return
        top_left = self.settings_search_shell.mapTo(self._shell_surface, QPoint(0, self.settings_search_shell.height() + 8))
        width = self.settings_search_shell.width()
        list_rows = max(1, self.settings_search_list.count())
        height = 44 + min(5, list_rows) * 46
        self.settings_search_dropdown.setGeometry(top_left.x(), top_left.y(), width, height)

    def _settings_search_suggestion_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return
        with QSignalBlocker(self.settings_search_edit):
            self.settings_search_edit.setText(self._settings_search_entry_path(entry))
        self._set_settings_search_dropdown_visible(False)
        self._execute_settings_search(required_video_loops=1)

    def _begin_settings_search_loading(self) -> None:
        self._settings_search_loading = True
        self._settings_search_result_ready = False
        self._settings_search_video_loops = 0
        self._set_settings_search_dropdown_visible(False)
        self.settings_search_loading_widget.start(self._select_settings_search_loading_lines())
        self.settings_search_stack.setCurrentWidget(self.settings_search_loading_widget)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _load_settings_search_loading_penalties(self) -> dict[str, dict[str, object]]:
        payload = self.datastore.load_cache_entry(SETTINGS_SEARCH_LOADING_PENALTY_CACHE_KEY) or {}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return {}
        cleaned: dict[str, dict[str, object]] = {}
        now = self._utc_now()
        changed = False
        for line, entry in entries.items():
            text = str(line or "").strip()
            if text not in SETTINGS_SEARCH_LOADING_LINES or not isinstance(entry, dict):
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
            self._save_settings_search_loading_penalties(cleaned)
        return cleaned

    def _save_settings_search_loading_penalties(self, entries: dict[str, dict[str, object]]) -> None:
        self.datastore.put_cache_entry(
            SETTINGS_SEARCH_LOADING_PENALTY_CACHE_KEY,
            {
                "entries": entries,
                "updated_at": self.datastore.now_iso(),
            },
        )

    def _select_settings_search_loading_lines(self) -> list[str]:
        penalties = self._load_settings_search_loading_penalties()
        candidates = list(SETTINGS_SEARCH_LOADING_LINES)
        previous = list(getattr(self.settings_search_loading_widget, "_last_texts", []))
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
            choice = random.choice(candidates or list(SETTINGS_SEARCH_LOADING_LINES))
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
        expires_at = now + timedelta(hours=SETTINGS_SEARCH_LOADING_PENALTY_HOURS)
        current_penalty = max(0, int(penalties.get(choice, {}).get("penalty", 0) or 0))
        penalties[choice] = {
            "penalty": current_penalty + 1,
            "applied_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        self._save_settings_search_loading_penalties(penalties)
        return [choice]

    def _finish_settings_search_loading(self) -> None:
        if not self._settings_search_loading:
            return
        self._settings_search_loading = False
        self._complete_settings_search()

    def _execute_settings_search(self, _checked: bool = False, *, required_video_loops: int = 2) -> None:
        if self._settings_search_loading:
            return
        query = " ".join(self.settings_search_edit.text().split())
        if not query:
            return
        self._settings_search_required_video_loops = max(1, int(required_video_loops or 2))
        self._settings_search_pending_result = self.settings_search_service.top_match(query)
        with QSignalBlocker(self.settings_search_edit):
            self.settings_search_edit.clear()
        self._begin_settings_search_loading()
        self._settings_search_result_ready = True
        QTimer.singleShot(4100, self._finish_settings_search_loading)

    def _complete_settings_search(self) -> None:
        result = dict(self._settings_search_pending_result or {}) if isinstance(self._settings_search_pending_result, dict) else None
        self._settings_search_pending_result = None
        self._settings_search_result_ready = False
        self.settings_search_loading_widget.stop()
        self.settings_search_stack.setCurrentWidget(self.settings_search_edit)
        self._settings_search_fade_animation = None
        QTimer.singleShot(90, lambda entry=result: self._finalize_settings_search_display(entry))

    def _finalize_settings_search_display(self, result: dict[str, object] | None) -> None:
        self.settings_search_skeleton.stop()
        self.settings_content_stack.setCurrentWidget(self.pages)
        self._sync_settings_bordered_widget_heights()
        if result:
            self._navigate_to_settings_search_result(result)

    def _navigate_to_settings_search_result(self, entry: dict[str, object]) -> None:
        target_key = str(entry.get("target_key", "")).strip()
        target = self._settings_search_targets.get(target_key)
        if not isinstance(target, dict):
            target = self._settings_search_targets.get(f"tab.{str(entry.get('tab_key', '')).strip()}")
            if not isinstance(target, dict):
                return

        tab_key = str(target.get("tab_key", "")).strip()
        tab_aliases = {
            "ai": "models",
            "model": "models",
        }
        tab_key = tab_aliases.get(tab_key, tab_key)
        tab_order = ["general", "smart", "audio", "performance", "models", "account"]
        if tab_key in tab_order:
            self._set_settings_page(tab_order.index(tab_key))

        widget = target.get("widget")
        if not isinstance(widget, QWidget):
            return
        scroll = target.get("scroll")

        def _scroll_into_view() -> None:
            if isinstance(scroll, QScrollArea):
                if target_key.startswith("tab."):
                    scroll.verticalScrollBar().setValue(0)
                    self._sync_settings_bordered_widget_heights()
                    return
                scroll.ensureWidgetVisible(widget, 24, 120)
                self._sync_settings_bordered_widget_heights()
                return
            if widget.focusPolicy() != Qt.FocusPolicy.NoFocus:
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
            self._sync_settings_bordered_widget_heights()

        QTimer.singleShot(60, _scroll_into_view)

    def exec(self) -> int:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            return super().exec()
        finally:
            self._clear_backdrop()

    def done(self, result: int) -> None:
        self._clear_backdrop()
        super().done(result)

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _resolve_backdrop_target(self) -> QWidget | None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return None
        app_shell = getattr(parent_widget, "_app_shell", None)
        if isinstance(app_shell, QWidget):
            return app_shell
        return parent_widget

    def _apply_backdrop(self) -> None:
        if self._backdrop_target is not None:
            return
        target = self._resolve_backdrop_target()
        parent_widget = self.parentWidget()
        if target is None or parent_widget is None:
            return
        self._backdrop_target = target
        self._backdrop_previous_effect = target.graphicsEffect()
        blur = QGraphicsBlurEffect(target)
        blur.setBlurRadius(30.0)
        target.setGraphicsEffect(blur)

        overlay = QWidget(parent_widget)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(226, 232, 240, 0.28);")
        top_left = target.mapTo(parent_widget, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, target.size()))
        overlay.show()
        overlay.raise_()
        self._backdrop_overlay = overlay

    def _clear_backdrop(self) -> None:
        changed = self._backdrop_overlay is not None or self._backdrop_target is not None
        if self._backdrop_overlay is not None:
            overlay = self._backdrop_overlay
            overlay.hide()
            overlay.close()
            overlay.setParent(None)
            overlay.deleteLater()
            self._backdrop_overlay = None
        if self._backdrop_target is not None:
            target = self._backdrop_target
            try:
                target.setGraphicsEffect(self._backdrop_previous_effect)
                target.repaint()
            except RuntimeError:
                pass
        self._backdrop_target = None
        self._backdrop_previous_effect = None
        if changed:
            app = QApplication.instance()
            if app is not None:
                app.processEvents()

    def _settings_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setViewportMargins(0, 8, 16, 0)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _settings_label_stylesheet(
        self,
        object_name: str,
        *,
        size: int,
        strong: bool = False,
        bottom_padding: int = 0,
    ) -> str:
        colors = self._settings_surface_colors()
        color = colors["title"] if strong else colors["text"]
        weight = 700 if strong else 500
        return (
            f"QLabel#{object_name} {{ "
            f"font-size: {size}px; font-weight: {weight}; color: {color}; "
            "background: transparent; border: none; "
            f"padding: 0px 0px {bottom_padding}px 0px; "
            "}"
        )

    def _apply_settings_input_chrome(self, widget: QWidget) -> None:
        widget.setObjectName("SettingsFieldInput")
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        widget.setMinimumHeight(SETTINGS_WIDGET_HEIGHT)
        widget.setMaximumHeight(SETTINGS_WIDGET_HEIGHT)
        dark = is_dark_theme()
        tokens = theme_tokens("dark" if dark else "light")
        field_bg = "rgba(31, 42, 54, 0.92)" if dark else "rgba(244, 248, 251, 0.56)"
        field_focus = "#223044" if dark else "rgba(248, 251, 253, 0.82)"
        field_hover = "rgba(35, 48, 62, 0.96)" if dark else "rgba(247, 250, 253, 0.70)"
        field_border = tokens["border"] if dark else "rgba(123, 146, 168, 0.18)"
        field_focus_border = tokens["primary"] if dark else "rgba(82, 123, 161, 0.30)"
        text = tokens["text"]
        selection = tokens["selection"]
        if isinstance(widget, QLineEdit):
            widget.setStyleSheet(
                f"""
                QLineEdit#SettingsFieldInput {{
                    background: {field_bg};
                    border: 1px solid {field_border};
                    border-radius: 16px;
                    padding: 10px 18px;
                    color: {text};
                    font-size: 13px;
                    selection-background-color: {selection};
                }}
                QLineEdit#SettingsFieldInput:hover {{
                    background: {field_hover};
                    border: 1px solid {field_border};
                }}
                QLineEdit#SettingsFieldInput[focusRing="true"],
                QLineEdit#SettingsFieldInput:focus {{
                    background: {field_focus};
                    border: 1px solid {field_focus_border};
                }}
                """
            )
            widget.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        elif isinstance(widget, QComboBox):
            arrow_path = self._icon_path("angle-down")
            arrow_url = arrow_path.as_posix() if arrow_path is not None else ""
            widget.setStyleSheet(
                f"""
                QComboBox#SettingsFieldInput {{
                    background: {field_bg};
                    border: 1px solid {field_border};
                    border-radius: 14px;
                    padding: 10px 34px 10px 14px;
                    color: {text};
                    font-size: 13px;
                    font-weight: 600;
                }}
                QComboBox#SettingsFieldInput:hover {{
                    background: {field_hover};
                    border: 1px solid {field_border};
                }}
                QComboBox#SettingsFieldInput[focusRing="true"],
                QComboBox#SettingsFieldInput:focus {{
                    background: {field_focus};
                    border: 1px solid {field_focus_border};
                }}
                QComboBox#SettingsFieldInput::drop-down {{
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 34px;
                    border: none;
                    background: transparent;
                }}
                QComboBox#SettingsFieldInput::down-arrow {{
                    image: url("__ARROW__");
                    width: 12px;
                    height: 12px;
                }}
                """.replace("__ARROW__", arrow_url)
            )
            widget.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        elif isinstance(widget, QSpinBox):
            widget.setStyleSheet(
                f"""
                QSpinBox#SettingsFieldInput {{
                    background: {field_bg};
                    border: 1px solid {field_border};
                    border-radius: 16px;
                    padding: 10px 28px 10px 14px;
                    color: {text};
                    font-size: 13px;
                }}
                QSpinBox#SettingsFieldInput:hover {{
                    background: {field_hover};
                    border: 1px solid {field_border};
                }}
                QSpinBox#SettingsFieldInput:focus,
                QSpinBox#SettingsFieldInput[focusRing="true"] {{
                    background: {field_focus};
                    border: 1px solid {field_focus_border};
                }}
                QSpinBox#SettingsFieldInput::up-button,
                QSpinBox#SettingsFieldInput::down-button {{
                    width: 20px;
                    border: none;
                    background: transparent;
                }}
                QSpinBox#SettingsFieldInput::up-arrow,
                QSpinBox#SettingsFieldInput::down-arrow {{
                    width: 8px;
                    height: 8px;
                }}
                """
            )
            widget.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _mark_settings_bordered_button(self, button: QPushButton) -> None:
        button.setProperty("settingsBorderedControl", True)
        button.setProperty("disablePressMotion", True)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(SETTINGS_WIDGET_HEIGHT)
        button.setMaximumHeight(SETTINGS_WIDGET_HEIGHT)
        button.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        button.setStyleSheet(
            """
            QPushButton {
                background: rgba(255, 255, 255, 0.36);
                color: #0f2539;
                border: 1px solid rgba(15, 37, 57, 0.18);
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.36);
                border: 1px solid rgba(15, 37, 57, 0.18);
            }
            QPushButton:pressed {
                background: rgba(232, 238, 244, 0.78);
                border: 1px solid rgba(15, 37, 57, 0.18);
                padding: 7px 14px;
            }
            QPushButton:disabled {
                background: rgba(203, 213, 225, 0.34);
                color: rgba(100, 116, 139, 0.64);
                border: 1px solid rgba(148, 163, 184, 0.18);
            }
            """
        )

    def _settings_reference_widget_height(self) -> int:
        return SETTINGS_WIDGET_HEIGHT

    def _sync_settings_bordered_widget_heights(self) -> None:
        target_height = self._settings_reference_widget_height()
        for widget in self.findChildren(QWidget):
            if widget.objectName() == "SettingsFieldInput":
                widget.setMinimumHeight(target_height)
                widget.setMaximumHeight(target_height)
                widget.setFixedHeight(target_height)
            elif isinstance(widget, QPushButton) and bool(widget.property("settingsBorderedControl")):
                widget.setMinimumHeight(target_height)
                widget.setMaximumHeight(target_height)
                widget.setFixedHeight(target_height)

    def _settings_card(self, layout_type: QVBoxLayout | QFormLayout | None = None, *, padding: int = 22) -> tuple[QFrame, QVBoxLayout | QFormLayout]:
        surface = QFrame()
        surface.setObjectName("SettingsCard")
        colors = self._settings_surface_colors()
        surface.setStyleSheet(
            f"""
            QFrame#SettingsCard {{
                background: {colors["card"]};
                border: 1px solid {colors["border"]};
                border-radius: 18px;
            }}
            """
        )
        if layout_type is QFormLayout:
            layout = QFormLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setHorizontalSpacing(18)
            layout.setVerticalSpacing(16)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
        else:
            layout = QVBoxLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setSpacing(12)
        return surface, layout

    def _settings_section_card(self, layout_type: QVBoxLayout | QFormLayout | None = None, *, padding: int = 20) -> tuple[QFrame, QVBoxLayout | QFormLayout]:
        surface = QFrame()
        surface.setObjectName("SettingsSectionCard")
        colors = self._settings_surface_colors()
        surface.setStyleSheet(
            f"""
            QFrame#SettingsSectionCard {{
                background: {colors["section"]};
                border: 1px solid {colors["border"]};
                border-radius: 16px;
            }}
            """
        )
        if layout_type is QFormLayout:
            layout = QFormLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setHorizontalSpacing(16)
            layout.setVerticalSpacing(14)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
        else:
            layout = QVBoxLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setSpacing(10)
        return surface, layout

    def _context_row_label(self, title: str, description: str) -> QWidget:
        host = QWidget()
        host.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("SectionText")
        title_label.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #627181; font-weight: 600; }")
        description_label = QLabel(description)
        description_label.setObjectName("SmallMeta")
        description_label.setWordWrap(True)
        description_label.setStyleSheet("QLabel#SmallMeta { font-size: 11px; color: #64748b; }")
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return host

    def _build_settings_micro_card(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        surface, layout = self._settings_section_card(padding=18)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setStyleSheet(
            "QLabel#SectionTitle { font-size: 15px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px; }"
        )
        description_label = QLabel(description)
        description_label.setObjectName("SmallMeta")
        description_label.setWordWrap(True)
        description_label.setStyleSheet(
            "QLabel#SmallMeta { font-size: 12px; color: #64748b; background: transparent; border: none; padding: 0px; }"
        )
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return surface, layout

    def _build_context_model_combo(self, context_key: str, feature_label: str) -> PopupMenuComboBox:
        combo = PopupMenuComboBox()
        combo.set_popup_handler(
            lambda key=context_key, label=feature_label, control=combo: self._open_combo_choice_picker(
                title=f"{label} model",
                control=control,
                fallback_value=str(control.currentData() or ""),
            )
        )
        self._apply_settings_input_chrome(combo)
        self._context_model_combos[context_key] = combo
        return combo

    def _refresh_context_model_choices(self, ai_settings: dict | None = None, installed_keys: list[str] | None = None) -> None:
        settings = dict(ai_settings or self.datastore.load_ai_settings())
        if installed_keys is None:
            setup = self.datastore.load_setup()
            installed_map = dict(setup.get("installed_models", {}))
            installed_keys = [key for key in MODELS if bool(installed_map.get(key, False))]

        for context_key, combo in self._context_model_combos.items():
            saved_key = str(settings.get(feature_model_setting_key(context_key), "")).strip()
            supported_keys = wiki_summarizer_llm_keys() if context_key == "wiki_breakdown_context_length" else non_embedding_llm_keys()
            available_keys = [key for key in supported_keys if key in set(installed_keys or [])]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Text Model", "")
            for key in available_keys:
                spec = MODELS.get(key)
                if spec is not None:
                    combo.addItem(spec.display_name, key)
            selected_index = combo.findData(saved_key)
            if selected_index < 0:
                selected_index = 0
            combo.setCurrentIndex(selected_index)
            combo.setEnabled(combo.count() > 0)
            combo.blockSignals(False)
            self._sync_context_spin_lock(context_key)

    def _sync_context_spin_lock(self, context_key: str) -> None:
        spin = self._context_length_spins.get(context_key)
        combo = self._context_model_combos.get(context_key)
        if spin is None or combo is None:
            return
        is_qn_summarizer = context_key == "wiki_breakdown_context_length" and str(combo.currentData() or "").strip() == QN_SUMMARIZER_MODEL_KEY
        if is_qn_summarizer:
            spin.setValue(QN_SUMMARIZER_CONTEXT_LENGTH)
            spin.setEnabled(False)
            spin.setToolTip("QN-Summarizer-1 uses an 8,000-token context.")
        else:
            spin.setEnabled(True)
            spin.setToolTip("")

    def _build_general_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()
        self._settings_tab_scrolls["general"] = scroll

        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._register_settings_search_target("tab.general", tab_key="general", scroll=scroll, widget=host)

        intro = QLabel("Update the basic student profile ONCard uses when generating and grading responses.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            """
            QLabel#SectionText {
                font-size: 14px;
                line-height: 1.6;
                color: #62778a;
            }
            """
        )
        layout.addWidget(intro)

        # Appearance card
        appearance_surface, appearance_layout = self._settings_card()
        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName("SectionTitle")
        appearance_title.setStyleSheet(self._settings_label_stylesheet("SectionTitle", size=18, strong=True, bottom_padding=8))
        appearance_note = QLabel("Choose how ONCard looks on this account.")
        appearance_note.setObjectName("SectionText")
        appearance_note.setWordWrap(True)
        appearance_note.setStyleSheet(self._settings_label_stylesheet("SectionText", size=13))
        appearance_layout.addWidget(appearance_title)
        appearance_layout.addWidget(appearance_note)

        self.theme_combo = PopupMenuComboBox()
        self.theme_combo.addItem("System (Beta)", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark (Beta)", "dark")
        self.theme_combo.set_popup_handler(self._open_theme_picker)
        self._apply_settings_input_chrome(self.theme_combo)
        appearance_layout.addWidget(FieldBlock("Theme", self.theme_combo))
        self._register_settings_search_target("general.appearance.group", tab_key="general", scroll=scroll, widget=appearance_surface)
        self._register_settings_search_target("general.appearance.theme", tab_key="general", scroll=scroll, widget=self.theme_combo)
        layout.addWidget(appearance_surface)

        # Profile card
        surface, form = self._settings_card(layout_type=QFormLayout)
        form_title = QLabel("Profile")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet(
            """
            QLabel#SectionTitle {
                font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 18px;
                font-weight: 700;
                color: #627181;
                background: transparent;
                border: none;
            }
            """
        )
        form_title.setStyleSheet(
            "QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 12px 0px; }"
        )
        form.addRow(form_title)

        self.name_edit = AnimatedLineEdit()
        self.name_edit.setPlaceholderText("User name")
        self.profile_name_edit = AnimatedLineEdit()
        self.profile_name_edit.setPlaceholderText("Profile name")
        self.age_spin = SettingsSpinBox()
        self.age_spin.setRange(4, 99)
        self.hobbies_edit = AnimatedLineEdit()
        self.hobbies_edit.setPlaceholderText("Hobbies / interests")
        self.name_edit.textChanged.connect(lambda *_: self._refresh_sidebar_profile())
        self.profile_name_edit.textChanged.connect(lambda *_: self._refresh_sidebar_profile())
        self.hobbies_edit.textChanged.connect(lambda *_: self._refresh_sidebar_profile())
        self._apply_settings_input_chrome(self.name_edit)
        self._apply_settings_input_chrome(self.profile_name_edit)
        self._apply_settings_input_chrome(self.age_spin)
        self._apply_settings_input_chrome(self.hobbies_edit)
        self.grade_combo = PlaceholderComboBox("grade")
        self.grade_combo.addItems([f"Grade {value}" for value in range(3, 13)])
        self.grade_combo.setMaxVisibleItems(6)
        self.grade_combo.set_popup_handler(self._open_grade_picker)
        self.grade_combo.setCurrentText("Grade 3")
        self._apply_settings_input_chrome(self.grade_combo)
        self.gender_combo = PlaceholderComboBox("gender")
        self.gender_combo.addItems(["Male", "Female", "Custom"])
        self.gender_combo.setMaxVisibleItems(6)
        self.gender_combo.set_popup_handler(self._open_gender_picker)
        self.gender_combo.currentIndexChanged.connect(self._on_gender_mode_changed)
        self._apply_settings_input_chrome(self.gender_combo)
        self.gender_custom_edit = AnimatedLineEdit()
        self.gender_custom_edit.setMaxLength(64)
        self.gender_custom_edit.setPlaceholderText("Gender | Pronoun(s)")
        self.gender_custom_edit.setVisible(False)
        self._apply_settings_input_chrome(self.gender_custom_edit)
        gender_shell = QWidget()
        gender_shell.setObjectName("SettingsGenderShell")
        gender_shell.setStyleSheet("QWidget#SettingsGenderShell { background: transparent; }")
        gender_layout = QVBoxLayout(gender_shell)
        gender_layout.setContentsMargins(0, 0, 0, 0)
        gender_layout.setSpacing(6)
        gender_layout.addWidget(self.gender_combo)
        gender_layout.addWidget(self.gender_custom_edit)
        self.attention_slider = SettingsSlider(Qt.Horizontal)
        self.attention_slider.setObjectName("SettingsAttentionSlider")
        self.attention_slider.setRange(1, 10)
        self.attention_slider.setSingleStep(1)
        self.attention_slider.setPageStep(1)
        self.attention_slider.setValue(5)
        self.attention_slider.setStyleSheet(
            """
            QSlider#SettingsAttentionSlider {
                min-height: 24px;
                background: transparent;
            }
            QSlider#SettingsAttentionSlider::groove:horizontal {
                height: 6px;
                border-radius: 4px;
                background: #d4deea;
            }
            QSlider#SettingsAttentionSlider::sub-page:horizontal {
                background: #d4deea;
                border-radius: 4px;
            }
            QSlider#SettingsAttentionSlider::add-page:horizontal {
                background: #d4deea;
                border-radius: 4px;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #0f2539;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal:hover {
                background: #0f2539;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal:pressed {
                background: #1a4466;
            }
            """
        )
        self.attention_slider.valueChanged.connect(self._on_attention_changed)
        self.attention_value = QLabel("Attention span per question: 5 min")
        self.attention_value.setObjectName("SectionText")
        for control in (
            self.name_edit,
            self.profile_name_edit,
            self.age_spin,
            self.grade_combo,
            self.gender_combo,
            self.hobbies_edit,
        ):
            control.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        self.gender_custom_edit.setFixedHeight(SETTINGS_WIDGET_HEIGHT)
        profile_grid_host = QWidget()
        profile_grid_host.setStyleSheet("background: transparent;")
        profile_grid = QGridLayout(profile_grid_host)
        profile_grid.setContentsMargins(0, 0, 0, 0)
        profile_grid.setHorizontalSpacing(12)
        profile_grid.setVerticalSpacing(8)
        profile_grid.setColumnStretch(0, 1)
        profile_grid.setColumnStretch(1, 1)
        attention_shell = QWidget()
        attention_shell.setObjectName("SettingsAttentionShell")
        attention_shell.setStyleSheet("QWidget#SettingsAttentionShell { background: transparent; }")
        attention_layout = QVBoxLayout(attention_shell)
        attention_layout.setContentsMargins(0, 6, 0, 2)
        attention_layout.setSpacing(4)
        attention_layout.addWidget(self.attention_value)
        attention_layout.addWidget(self.attention_slider)
        attention_shell.setFixedHeight(64)
        attention_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        profile_grid.addWidget(FieldBlock("", self.name_edit), 0, 0)
        profile_grid.addWidget(FieldBlock("", self.profile_name_edit), 0, 1)
        profile_grid.addWidget(FieldBlock("", self.age_spin), 1, 0)
        profile_grid.addWidget(FieldBlock("", self.grade_combo), 1, 1)
        profile_grid.addWidget(FieldBlock("", self.hobbies_edit), 2, 0)
        profile_grid.addWidget(FieldBlock("", gender_shell), 2, 1)
        profile_grid.addWidget(attention_shell, 3, 0, 1, 2)
        form.addWidget(profile_grid_host)
        self._register_settings_search_target("general.profile.group", tab_key="general", scroll=scroll, widget=surface)
        self._register_settings_search_target("general.profile.user_name", tab_key="general", scroll=scroll, widget=self.name_edit)
        self._register_settings_search_target("general.profile.profile_name", tab_key="general", scroll=scroll, widget=self.profile_name_edit)
        self._register_settings_search_target("general.profile.age", tab_key="general", scroll=scroll, widget=self.age_spin)
        self._register_settings_search_target("general.profile.hobbies", tab_key="general", scroll=scroll, widget=self.hobbies_edit)
        self._register_settings_search_target("general.profile.grade", tab_key="general", scroll=scroll, widget=self.grade_combo)
        self._register_settings_search_target("general.profile.gender", tab_key="general", scroll=scroll, widget=gender_shell)
        self._register_settings_search_target("general.profile.attention_span", tab_key="general", scroll=scroll, widget=attention_shell)

        layout.addWidget(surface)

        # FTC card
        ftc_surface, ftc_layout = self._settings_card()
        ftc_title = QLabel("FTC")
        ftc_title.setObjectName("SectionTitle")
        ftc_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        ftc_note = QLabel("Default Files To Cards settings. Question counts are capped by available units per run.")
        ftc_note.setObjectName("SectionText")
        ftc_note.setWordWrap(True)
        ftc_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #6f8194; }")
        ftc_layout.addWidget(ftc_title)
        ftc_layout.addWidget(ftc_note)

        ftc_form = QFormLayout()
        ftc_form.setHorizontalSpacing(18)
        ftc_form.setVerticalSpacing(16)
        ftc_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ftc_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        ftc_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.ftc_default_mode = PopupMenuComboBox()
        self.ftc_default_mode.addItem("Standard", "standard")
        self.ftc_default_mode.addItem("Force", "force")
        self.ftc_default_mode.set_popup_handler(self._open_ftc_mode_picker)
        self._apply_settings_input_chrome(self.ftc_default_mode)

        self.ftc_questions_standard = SettingsSpinBox()
        self.ftc_questions_standard.setRange(1, 30)
        self.ftc_questions_standard.setMinimumWidth(140)
        self.ftc_questions_force = SettingsSpinBox()
        self.ftc_questions_force.setRange(1, 30)
        self.ftc_questions_force.setMinimumWidth(140)
        self._apply_settings_input_chrome(self.ftc_questions_standard)
        self._apply_settings_input_chrome(self.ftc_questions_force)

        self.ftc_difficulty = PopupMenuComboBox()
        self.ftc_difficulty.addItem("Easy", "easy")
        self.ftc_difficulty.addItem("Kinda easy", "kinda easy")
        self.ftc_difficulty.addItem("Normal", "normal")
        self.ftc_difficulty.addItem("Kinda difficult", "kinda difficult")
        self.ftc_difficulty.addItem("Difficult", "difficult")
        self.ftc_difficulty.set_popup_handler(self._open_ftc_difficulty_picker)
        self._apply_settings_input_chrome(self.ftc_difficulty)

        self.ftc_ocr_checkbox = QCheckBox("Use OCR in Files To Cards")

        ftc_form.addRow("Default mode", self.ftc_default_mode)
        ftc_form.addRow("Question quantity (Standard)", self.ftc_questions_standard)
        ftc_form.addRow("Question quantity (Force)", self.ftc_questions_force)
        ftc_form.addRow("Difficulty", self.ftc_difficulty)
        ftc_form.addRow("Files To Cards OCR", self.ftc_ocr_checkbox)
        self._register_settings_search_target("general.ftc.group", tab_key="general", scroll=scroll, widget=ftc_surface)
        self._register_settings_search_target("general.ftc.default_mode", tab_key="general", scroll=scroll, widget=self.ftc_default_mode)
        self._register_settings_search_target("general.ftc.question_standard", tab_key="general", scroll=scroll, widget=self.ftc_questions_standard)
        self._register_settings_search_target("general.ftc.question_force", tab_key="general", scroll=scroll, widget=self.ftc_questions_force)
        self._register_settings_search_target("general.ftc.difficulty", tab_key="general", scroll=scroll, widget=self.ftc_difficulty)
        self._register_settings_search_target("general.ftc.ocr", tab_key="general", scroll=scroll, widget=self.ftc_ocr_checkbox)
        ftc_layout.addLayout(ftc_form)

        ftc_hint = QLabel(
            "Custom instructions will be pre-filled in Files To Cards based on the selected difficulty and profile."
        )
        ftc_hint.setObjectName("SmallMeta")
        ftc_hint.setWordWrap(True)
        ftc_hint.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #8aa0b5; margin-top: 8px; }")
        ftc_layout.addWidget(ftc_hint)

        layout.addWidget(ftc_surface)

        # MCQ card
        mcq_surface, mcq_layout = self._settings_card()
        mcq_title = QLabel("MCQ")
        mcq_title.setObjectName("SectionTitle")
        mcq_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        mcq_note = QLabel("Turn saved cards into multiple choice practice with short, similar answer choices.")
        mcq_note.setObjectName("SectionText")
        mcq_note.setWordWrap(True)
        mcq_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #6f8194; }")
        mcq_layout.addWidget(mcq_title)
        mcq_layout.addWidget(mcq_note)

        self.mcq_enabled_checkbox = QCheckBox("Enable Cards to MCQ")
        self.mcq_enabled_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        mcq_layout.addWidget(self.mcq_enabled_checkbox)

        mcq_difficulty_form = QFormLayout()
        mcq_difficulty_form.setHorizontalSpacing(18)
        mcq_difficulty_form.setVerticalSpacing(12)
        mcq_difficulty_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.mcq_difficulty = PopupMenuComboBox()
        mcq_difficulty_options = [
            ("Easier", "easier"),
            ("Standard", "standard"),
            ("Slightly harder", "slightly_harder"),
            ("Harder", "harder"),
            ("Much harder", "much_harder"),
        ]
        for label, value in mcq_difficulty_options:
            self.mcq_difficulty.addItem(label, value)
        self.mcq_difficulty.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="MCQ difficulty",
                control=self.mcq_difficulty,
                fallback_value="slightly_harder",
            )
        )
        self._apply_settings_input_chrome(self.mcq_difficulty)
        mcq_difficulty_form.addRow("MCQ difficulty", self.mcq_difficulty)
        mcq_layout.addLayout(mcq_difficulty_form)

        mcq_action_row = QHBoxLayout()
        self.cards_to_mcq_btn = QPushButton("Cards to MCQ")
        self.cards_to_mcq_btn.setStyleSheet(
            """
            QPushButton {
                background: #0f2539;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0f2539;
            }
            QPushButton:pressed {
                background: #1a4466;
            }
            QPushButton:disabled {
                background: #cbd5e1;
                color: #94a3b8;
            }
            """
        )
        self._mark_settings_bordered_button(self.cards_to_mcq_btn)
        self.cards_to_mcq_btn.clicked.connect(self._run_cards_to_mcq)
        self.mcq_status_label = QLabel("Generate choices now, or let the MCQ tab make them when needed.")
        self.mcq_status_label.setObjectName("SmallMeta")
        self.mcq_status_label.setWordWrap(True)
        self.mcq_status_label.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        mcq_action_row.addWidget(self.cards_to_mcq_btn, 0)
        mcq_action_row.addWidget(self.mcq_status_label, 1)
        mcq_layout.addLayout(mcq_action_row)
        self._register_settings_search_target("general.mcq.group", tab_key="general", scroll=scroll, widget=mcq_surface)
        self._register_settings_search_target("general.mcq.enable", tab_key="general", scroll=scroll, widget=self.mcq_enabled_checkbox)
        self._register_settings_search_target("general.mcq.difficulty", tab_key="general", scroll=scroll, widget=self.mcq_difficulty)
        self._register_settings_search_target("general.mcq.run", tab_key="general", scroll=scroll, widget=self.cards_to_mcq_btn)
        layout.addWidget(mcq_surface)

        stats_surface, stats_form = self._settings_card(layout_type=QFormLayout)
        stats_title = QLabel("Stats defaults")
        stats_title.setObjectName("SectionTitle")
        stats_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        stats_form.addRow(stats_title)

        self.stats_default_range = PopupMenuComboBox()
        self.stats_default_range.addItem("Hourly", "hourly")
        self.stats_default_range.addItem("Daily 3 days", "daily")
        self.stats_default_range.addItem("Weekly", "weekly")
        self.stats_default_range.addItem("2 Weeks", "2weeks")
        self.stats_default_range.addItem("Monthly", "monthly")
        self.stats_default_range.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Default time range",
                control=self.stats_default_range,
                fallback_value="daily",
            )
        )
        self._apply_settings_input_chrome(self.stats_default_range)
        stats_form.addRow("Default time range", self.stats_default_range)
        self._register_settings_search_target("general.stats.group", tab_key="general", scroll=scroll, widget=stats_surface)
        self._register_settings_search_target("general.stats.range", tab_key="general", scroll=scroll, widget=self.stats_default_range)
        layout.addWidget(stats_surface)

        stats_note = QLabel("This only sets the initial selection. You can still switch range in View stats anytime.")
        stats_note.setObjectName("SmallMeta")
        stats_note.setWordWrap(True)
        stats_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        layout.addWidget(stats_note)

        self._set_account_actions_enabled(self.session_controller is not None)
        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_smart_features_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()
        self._settings_tab_scrolls["smart"] = scroll
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._register_settings_search_target("tab.smart", tab_key="smart", scroll=scroll, widget=host)
        context_surface = self._build_context_settings_card(scroll=scroll, tab_key="smart")
        layout.addWidget(context_surface)
        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_context_settings_card(self, *, scroll: QScrollArea, tab_key: str) -> QFrame:
        context_surface, context_layout = self._settings_card()
        context_title = QLabel("Context")
        context_title.setObjectName("SectionTitle")
        context_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        context_note = QLabel(
            "Choose the context size and model for each smart ONCard feature. Larger context values can use more memory and may run slower on weaker devices."
        )
        context_note.setObjectName("SectionText")
        context_note.setWordWrap(True)
        context_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        context_layout.addWidget(context_title)
        context_layout.addWidget(context_note)

        self._context_length_spins = {}
        context_target_map = {
            "autofill_context_length": f"{tab_key}.context.autofill",
            "grading_context_length": f"{tab_key}.context.grading",
            "mcq_context_length": f"{tab_key}.context.mcq",
            "ask_ai_planner_context_length": f"{tab_key}.context.ask_planner",
            "ask_ai_answer_context_length": f"{tab_key}.context.ask_answer",
            "ask_ai_image_context_length": f"{tab_key}.context.ask_image",
            "wiki_breakdown_context_length": f"{tab_key}.context.wiki",
            "followup_context_length": f"{tab_key}.context.followup",
            "reinforcement_context_length": f"{tab_key}.context.reinforcement",
            "files_to_cards_ocr_context_length": f"{tab_key}.context.ftc_ocr",
            "files_to_cards_paper_context_length": f"{tab_key}.context.ftc_paper",
            "files_to_cards_cards_context_length": f"{tab_key}.context.ftc_cards",
            "stats_context_length": f"{tab_key}.context.stats",
        }

        context_list = QVBoxLayout()
        context_list.setContentsMargins(0, 8, 0, 0)
        context_list.setSpacing(12)

        for key, label, description, _minimum in CONTEXT_LENGTH_SETTINGS:
            spin = SettingsSpinBox()
            spin.setRange(MIN_CONTEXT_LENGTH, MAX_CONTEXT_LENGTH)
            spin.setSingleStep(1024)
            spin.setSuffix(" tokens")
            self._context_length_spins[key] = spin
            self._apply_settings_input_chrome(spin)
            card, card_layout = self._build_settings_micro_card(label, description)
            controls_row = QHBoxLayout()
            controls_row.setContentsMargins(0, 8, 0, 0)
            controls_row.setSpacing(12)

            spin_column = QVBoxLayout()
            spin_column.setContentsMargins(0, 0, 0, 0)
            spin_column.setSpacing(6)
            spin_label = QLabel("Context")
            spin_label.setObjectName("SmallMeta")
            spin_label.setStyleSheet("QLabel#SmallMeta { font-size: 11px; color: #64748b; }")
            spin.setMinimumWidth(180)
            spin_column.addWidget(spin_label)
            spin_column.addWidget(spin)

            model_combo = self._build_context_model_combo(key, label)
            model_combo.setMinimumWidth(180)
            model_combo.currentIndexChanged.connect(lambda _index, context_key=key: self._sync_context_spin_lock(context_key))
            model_column = QVBoxLayout()
            model_column.setContentsMargins(0, 0, 0, 0)
            model_column.setSpacing(6)
            model_label = QLabel("Model")
            model_label.setObjectName("SmallMeta")
            model_label.setStyleSheet("QLabel#SmallMeta { font-size: 11px; color: #64748b; }")
            model_column.addWidget(model_label)
            model_column.addWidget(model_combo)

            controls_row.addLayout(spin_column, 1)
            controls_row.addLayout(model_column, 1)
            card_layout.addLayout(controls_row)
            context_list.addWidget(card)
            target_key = context_target_map.get(key)
            if target_key:
                self._register_settings_search_target(target_key, tab_key=tab_key, scroll=scroll, widget=spin)
                self._register_settings_search_target(f"{target_key}.model", tab_key=tab_key, scroll=scroll, widget=model_combo)
        self._refresh_context_model_choices()

        context_minimum_note = QLabel("Each value can be set from 2,000 to 86,000 tokens.")
        context_minimum_note.setObjectName("SmallMeta")
        context_minimum_note.setWordWrap(True)
        context_minimum_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 8px; }")
        context_layout.addLayout(context_list)
        context_layout.addWidget(context_minimum_note)
        self._register_settings_search_target(f"{tab_key}.context.group", tab_key=tab_key, scroll=scroll, widget=context_surface)
        return context_surface

    def _open_ftc_mode_picker(self) -> None:
        self._open_ftc_choice_picker(
            title="Default mode",
            control=self.ftc_default_mode,
            fallback_value="standard",
        )

    def _open_theme_picker(self) -> None:
        self._open_combo_choice_picker(
            title="Theme",
            control=self.theme_combo,
            fallback_value="light",
            vertical_choices=True,
        )

    def _open_ftc_difficulty_picker(self) -> None:
        self._open_ftc_choice_picker(
            title="Difficulty",
            control=self.ftc_difficulty,
            fallback_value="normal",
            vertical_choices=True,
        )

    def _open_ftc_choice_picker(
        self,
        *,
        title: str,
        control: QComboBox,
        fallback_value: str,
        vertical_choices: bool = False,
    ) -> None:
        self._open_combo_choice_picker(
            title=title,
            control=control,
            fallback_value=fallback_value,
            vertical_choices=vertical_choices,
        )

    def _run_cards_to_mcq(self) -> None:
        if self._mcq_bulk_worker is not None:
            return
        cards = self.datastore.list_all_cards()
        if not cards:
            self.mcq_status_label.setText("No cards are available yet.")
            return
        self.mcq_enabled_checkbox.setChecked(True)
        setup = self.datastore.load_setup()
        setup["mcq"] = {
            "enabled": True,
            "difficulty": str(self.mcq_difficulty.currentData() or "slightly_harder"),
        }
        self.datastore.save_setup(setup)
        ai_settings = self.datastore.load_ai_settings()
        model_spec = resolve_feature_text_llm_spec(ai_settings, "mcq_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Cards to MCQ"):
            return
        mcq_difficulty = str(self.mcq_difficulty.currentData() or "slightly_harder")
        worker = MCQBulkWorker(
            cards=cards,
            datastore=self.datastore,
            ollama=self.ollama,
            model=resolve_feature_text_model_tag(ai_settings, "mcq_context_length"),
            profile_context=self.datastore.load_profile(),
            difficulty=mcq_difficulty,
        )
        self._mcq_bulk_worker = worker
        self.cards_to_mcq_btn.setEnabled(False)
        self.mcq_status_label.setText("Generating MCQs...")
        worker.progress.connect(self._on_cards_to_mcq_progress)
        worker.finished.connect(self._on_cards_to_mcq_finished)
        worker.failed.connect(self._on_cards_to_mcq_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_cards_to_mcq_progress(self, current: int, total: int, generated: int, failed: int) -> None:
        self.mcq_status_label.setText(f"Generating MCQs... {current}/{total} | Generated {generated} | Failed {failed}")

    def _on_cards_to_mcq_finished(self, generated: int, skipped: int, failed: int) -> None:
        self._mcq_bulk_worker = None
        self.cards_to_mcq_btn.setEnabled(True)
        self.mcq_status_label.setText(f"MCQ generation finished. Generated {generated}, skipped {skipped}, failed {failed}.")

    def _on_cards_to_mcq_failed(self, message: str) -> None:
        self._mcq_bulk_worker = None
        self.cards_to_mcq_btn.setEnabled(True)
        self.mcq_status_label.setText(f"MCQ generation failed: {message}")

    def _open_combo_choice_picker(
        self,
        *,
        title: str,
        control: QComboBox,
        fallback_value: str,
        vertical_choices: bool = True,
    ) -> None:
        options: list[tuple[str, str]] = []
        for index in range(control.count()):
            label = str(control.itemText(index)).strip()
            value = str(control.itemData(index) or "").strip()
            if label and value:
                options.append((label, value))
        if not options:
            return
        current_value = str(control.currentData() or fallback_value).strip() or fallback_value
        parent_widget = self
        blur_target = self._settings_popup_blur_target()
        app_window = self.window() if isinstance(self.window(), QWidget) else self
        icon_provider = getattr(app_window, "icons", None) or getattr(self.parentWidget(), "icons", None)
        picker = FTCPopupChoiceDialog(
            parent=parent_widget,
            blur_target=blur_target,
            title=title,
            options=options,
            current_value=current_value,
            vertical_choices=vertical_choices,
            icon_provider=icon_provider,
        )
        if picker.exec_with_backdrop() != QDialog.DialogCode.Accepted:
            return
        selected = picker.selected_value().strip() or fallback_value
        selected_index = control.findData(selected)
        if selected_index >= 0:
            control.setCurrentIndex(selected_index)

    def _open_grade_picker(self) -> None:
        if not self.grade_combo.isEnabled():
            return
        options = [f"Grade {value}" for value in range(3, 13)]
        current_value = self.grade_combo.currentText().strip()
        selected = GradePickerDialog(
            parent=self,
            blur_target=self._settings_popup_blur_target(),
            anchor=self.grade_combo,
            options=options,
            current_value=current_value,
        ).exec_with_backdrop()
        if not selected:
            return
        if self.grade_combo.findText(selected) < 0:
            self.grade_combo.addItem(selected)
        self.grade_combo.setCurrentText(selected)
        self.grade_combo.setFocus()

    def _open_gender_picker(self) -> None:
        if not self.gender_combo.isEnabled():
            return
        selected = GenderPickerDialog(
            parent=self,
            blur_target=self._settings_popup_blur_target(),
            current_value=self._effective_gender_value(),
        ).exec_with_backdrop()
        if not selected:
            return
        normalized = selected.strip()
        lowered = normalized.lower()
        if lowered == "male":
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        elif lowered == "female":
            self.gender_combo.setCurrentText("Female")
            self.gender_custom_edit.clear()
        else:
            self.gender_combo.setCurrentText("Custom")
            self.gender_custom_edit.setText(normalized[:64])
        self._on_gender_mode_changed()
        self.gender_combo.setFocus()

    def _settings_popup_blur_target(self) -> QWidget:
        return self.pages if hasattr(self, "pages") and isinstance(self.pages, QWidget) else self

    def _build_ai_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()

        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._settings_tab_scrolls["ai"] = scroll
        self._register_settings_search_target("tab.ai", tab_key="ai", scroll=scroll, widget=host)

        ai_model_surface, ai_model_layout = self._settings_card()
        ai_model_title = QLabel("AI-Model")
        ai_model_title.setObjectName("SectionTitle")
        ai_model_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        ai_model_note = QLabel("Choose the main text model and the model ONCard uses for OCR extraction.")
        ai_model_note.setObjectName("SectionText")
        ai_model_note.setWordWrap(True)
        ai_model_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        ai_model_layout.addWidget(ai_model_title)
        ai_model_layout.addWidget(ai_model_note)

        ai_model_form = QFormLayout()
        ai_model_form.setHorizontalSpacing(18)
        ai_model_form.setVerticalSpacing(16)
        ai_model_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.selected_text_llm = PopupMenuComboBox()
        self.selected_text_llm.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="AI text model",
                control=self.selected_text_llm,
                fallback_value=str(self.selected_text_llm.currentData() or ""),
            )
        )
        self._apply_settings_input_chrome(self.selected_text_llm)
        self.selected_ocr_llm = PopupMenuComboBox()
        self.selected_ocr_llm.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="OCR model",
                control=self.selected_ocr_llm,
                fallback_value=str(self.selected_ocr_llm.currentData() or ""),
            )
        )
        self._apply_settings_input_chrome(self.selected_ocr_llm)
        ai_model_form.addRow("Text AI model", self.selected_text_llm)
        ai_model_form.addRow("OCR model", self.selected_ocr_llm)
        ai_model_layout.addLayout(ai_model_form)
        self._register_settings_search_target("ai.model.group", tab_key="ai", scroll=scroll, widget=ai_model_surface)
        self._register_settings_search_target("ai.model.text", tab_key="ai", scroll=scroll, widget=self.selected_text_llm)
        self._register_settings_search_target("ai.model.ocr", tab_key="ai", scroll=scroll, widget=self.selected_ocr_llm)
        ai_model_footer = QLabel(
            "OCR falls back to the smallest installed supported model each time model status refreshes, so deleted selections do not stick."
        )
        ai_model_footer.setObjectName("SmallMeta")
        ai_model_footer.setWordWrap(True)
        ai_model_footer.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 6px; }")
        ai_model_layout.addWidget(ai_model_footer)
        layout.addWidget(ai_model_surface)

        # Cloud service card
        cloud_surface, cloud_layout = self._settings_card()
        cloud_title = QLabel("Ollama cloud")
        cloud_title.setObjectName("SectionTitle")
        cloud_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        cloud_note = QLabel(
            "Use Ollama Cloud inference with your API key. Cloud mode is off by default. "
            "When enabled, cloud inference overrides local AI text-model selection until turned off. "
            "Embedding stays local."
        )
        cloud_note.setObjectName("SectionText")
        cloud_note.setWordWrap(True)
        cloud_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        cloud_layout.addWidget(cloud_title)
        cloud_layout.addWidget(cloud_note)

        cloud_form = QFormLayout()
        cloud_form.setHorizontalSpacing(18)
        cloud_form.setVerticalSpacing(14)
        cloud_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.cloud_enabled_checkbox = QCheckBox("Enable cloud service")
        self.cloud_enabled_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        self.cloud_enabled_checkbox.toggled.connect(self._on_cloud_mode_toggled)
        self.cloud_api_key_edit = AnimatedLineEdit()
        self.cloud_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_api_key_edit.setPlaceholderText("Paste Ollama API key")
        self.cloud_api_key_edit.textChanged.connect(self._on_cloud_api_key_changed)
        self._apply_settings_input_chrome(self.cloud_api_key_edit)
        self.cloud_model_combo = PopupMenuComboBox()
        self.cloud_model_combo.setEnabled(False)
        self.cloud_model_combo.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Cloud model variant",
                control=self.cloud_model_combo,
                fallback_value=str(self.cloud_model_combo.currentData() or ""),
            )
        )
        self._apply_settings_input_chrome(self.cloud_model_combo)

        cloud_form.addRow("Cloud inference", self.cloud_enabled_checkbox)
        cloud_form.addRow("API key", self.cloud_api_key_edit)
        cloud_form.addRow("Cloud model variant", self.cloud_model_combo)
        cloud_layout.addLayout(cloud_form)
        self._register_settings_search_target("ai.cloud.group", tab_key="ai", scroll=scroll, widget=cloud_surface)
        self._register_settings_search_target("ai.cloud.enabled", tab_key="ai", scroll=scroll, widget=self.cloud_enabled_checkbox)
        self._register_settings_search_target("ai.cloud.api_key", tab_key="ai", scroll=scroll, widget=self.cloud_api_key_edit)
        self._register_settings_search_target("ai.cloud.variant", tab_key="ai", scroll=scroll, widget=self.cloud_model_combo)

        cloud_actions = QHBoxLayout()
        cloud_actions.setContentsMargins(0, 6, 0, 0)
        cloud_actions.setSpacing(10)
        self.open_cloud_keys_btn = QPushButton("Open API key page")
        self.open_cloud_keys_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.open_cloud_keys_btn.clicked.connect(self._open_ollama_cloud_keys)
        self._mark_settings_bordered_button(self.open_cloud_keys_btn)
        self.refresh_cloud_models_btn = QPushButton("Load cloud models")
        self.refresh_cloud_models_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.refresh_cloud_models_btn.clicked.connect(lambda: self._refresh_cloud_models(force=True))
        self._mark_settings_bordered_button(self.refresh_cloud_models_btn)
        cloud_actions.addWidget(self.open_cloud_keys_btn)
        cloud_actions.addWidget(self.refresh_cloud_models_btn)
        cloud_actions.addStretch(1)
        cloud_layout.addLayout(cloud_actions)
        self._register_settings_search_target("ai.cloud.open_keys", tab_key="ai", scroll=scroll, widget=self.open_cloud_keys_btn)
        self._register_settings_search_target("ai.cloud.refresh_models", tab_key="ai", scroll=scroll, widget=self.refresh_cloud_models_btn)

        self.cloud_status = QLabel("")
        self.cloud_status.setObjectName("SmallMeta")
        self.cloud_status.setWordWrap(True)
        self.cloud_status.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 8px; }")
        cloud_layout.addWidget(self.cloud_status)
        layout.addWidget(cloud_surface)

        runtime_surface, runtime_layout = self._settings_section_card()
        runtime_title = QLabel("Ollama runtime")
        runtime_title.setObjectName("SectionTitle")
        runtime_title.setStyleSheet("QLabel#SectionTitle { font-size: 16px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 6px 0px; }")
        self.ollama_status = QLabel("")
        self.ollama_status.setObjectName("SectionText")
        self.ollama_status.setWordWrap(True)
        self.ollama_status.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        self.ollama_hint = QLabel("")
        self.ollama_hint.setObjectName("SmallMeta")
        self.ollama_hint.setWordWrap(True)
        self.ollama_hint.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        self.refresh_models_btn = QPushButton("Refresh model status")
        self.refresh_models_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.refresh_models_btn.clicked.connect(self._refresh_model_status)
        self._mark_settings_bordered_button(self.refresh_models_btn)
        runtime_layout.addWidget(runtime_title)
        runtime_layout.addWidget(self.ollama_status)
        runtime_layout.addWidget(self.ollama_hint)
        runtime_layout.addWidget(self.refresh_models_btn, 0, Qt.AlignLeft)
        layout.addWidget(runtime_surface)
        self._register_settings_search_target("ai.runtime.group", tab_key="ai", scroll=scroll, widget=runtime_surface)
        self._register_settings_search_target("ai.runtime.refresh_status", tab_key="ai", scroll=scroll, widget=self.refresh_models_btn)

        models_surface, models_layout = self._settings_card()
        models_title = QLabel("Installed Ollama models")
        models_title.setObjectName("SectionTitle")
        models_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 6px 0px; }")
        models_note = QLabel("These are the Ollama models ONCard currently uses.")
        models_note.setObjectName("SectionText")
        models_note.setWordWrap(True)
        models_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        models_layout.addWidget(models_title)
        models_layout.addWidget(models_note)

        model_list = QVBoxLayout()
        model_list.setContentsMargins(0, 0, 0, 0)
        model_list.setSpacing(10)
        for spec in MODELS.values():
            row = self._build_model_row(spec)
            model_list.addWidget(row["container"])
            self._model_rows[spec.key] = row
            self._register_settings_search_target(f"ai.models.{spec.key}", tab_key="ai", scroll=scroll, widget=row["container"])
        models_layout.addLayout(model_list)

        self.install_log = QTextEdit()
        self.install_log.setReadOnly(True)
        self.install_log.setPlaceholderText("Model install activity will appear here.")
        self.install_log.setMinimumHeight(120)
        self.install_log.setMaximumHeight(160)
        self.install_log.setStyleSheet(
            """
            QTextEdit {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 12px;
                color: #475569;
                font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
                font-size: 12px;
            }
            """
        )
        models_layout.addWidget(self.install_log)
        layout.addWidget(models_surface)
        self._register_settings_search_target("ai.models.group", tab_key="ai", scroll=scroll, widget=models_surface)
        self._register_settings_search_target("ai.models.actions", tab_key="ai", scroll=scroll, widget=models_surface)

        ask_ai_surface, ask_ai_layout = self._settings_card()
        ask_ai_title = QLabel("Ask AI style")
        ask_ai_title.setObjectName("SectionTitle")
        ask_ai_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        ask_ai_note = QLabel(
            "Set the default personality and emoji level Ask AI should use when replying."
        )
        ask_ai_note.setObjectName("SectionText")
        ask_ai_note.setWordWrap(True)
        ask_ai_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        ask_ai_layout.addWidget(ask_ai_title)
        ask_ai_layout.addWidget(ask_ai_note)

        self.ask_ai_tone = PopupMenuComboBox()
        for label, value in ASK_AI_TONE_OPTIONS:
            self.ask_ai_tone.addItem(label, value)
        self.ask_ai_tone.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Ask AI tone",
                control=self.ask_ai_tone,
                fallback_value="warm",
            )
        )
        self._apply_settings_input_chrome(self.ask_ai_tone)
        self.ask_ai_emoji_slider = SettingsSlider(Qt.Orientation.Horizontal)
        self.ask_ai_emoji_slider.setObjectName("SettingsAskAiEmojiSlider")
        self.ask_ai_emoji_slider.setRange(1, 4)
        self.ask_ai_emoji_slider.setSingleStep(1)
        self.ask_ai_emoji_slider.setPageStep(1)
        self.ask_ai_emoji_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.ask_ai_emoji_slider.setTickInterval(1)
        self.ask_ai_emoji_slider.setStyleSheet(
            """
            QSlider#SettingsAskAiEmojiSlider {
                min-height: 28px;
                background: transparent;
            }
            QSlider#SettingsAskAiEmojiSlider::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: #d4deea;
            }
            QSlider#SettingsAskAiEmojiSlider::sub-page:horizontal {
                border-radius: 3px;
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::add-page:horizontal {
                border-radius: 3px;
                background: #d4deea;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal:hover {
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal:pressed {
                background: #1a4466;
            }
            """
        )
        self.ask_ai_emoji_slider.valueChanged.connect(self._on_ask_ai_emoji_changed)
        self.ask_ai_emoji_value = QLabel(ASK_AI_EMOJI_LABELS[2])
        self.ask_ai_emoji_value.setObjectName("SectionText")
        self.ask_ai_emoji_value.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #475569; }")
        emoji_shell = QWidget()
        emoji_shell.setObjectName("SettingsAskAiEmojiShell")
        emoji_shell.setStyleSheet("QWidget#SettingsAskAiEmojiShell { background: transparent; }")
        emoji_layout = QVBoxLayout(emoji_shell)
        emoji_layout.setContentsMargins(0, 0, 0, 0)
        emoji_layout.setSpacing(6)
        emoji_layout.addWidget(self.ask_ai_emoji_value)
        emoji_layout.addWidget(self.ask_ai_emoji_slider)

        ask_ai_form = QFormLayout()
        ask_ai_form.setContentsMargins(0, 8, 0, 0)
        ask_ai_form.setHorizontalSpacing(16)
        ask_ai_form.setVerticalSpacing(14)
        ask_ai_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ask_ai_form.addRow("Tone", self.ask_ai_tone)
        ask_ai_form.addRow("Emoji level", emoji_shell)
        ask_ai_layout.addLayout(ask_ai_form)
        tone_note = QLabel(
            "Ask AI can use a saved tone preset and emoji intensity. The model still adapts to the situation, but this sets the default style."
        )
        tone_note.setObjectName("SmallMeta")
        tone_note.setWordWrap(True)
        tone_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 6px; }")
        ask_ai_layout.addWidget(tone_note)
        self._register_settings_search_target("ai.ask_style.group", tab_key="ai", scroll=scroll, widget=ask_ai_surface)
        self._register_settings_search_target("ai.ask_style.ask_tone", tab_key="ai", scroll=scroll, widget=self.ask_ai_tone)
        self._register_settings_search_target("ai.ask_style.ask_emoji", tab_key="ai", scroll=scroll, widget=emoji_shell)

        layout.insertWidget(1, ask_ai_surface)

        search_surface, search_layout = self._settings_card()
        search_title = QLabel("Search")
        search_title.setObjectName("SectionTitle")
        search_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        search_note = QLabel("Control semantic search and image search query generation.")
        search_note.setObjectName("SectionText")
        search_note.setWordWrap(True)
        search_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        search_layout.addWidget(search_title)
        search_layout.addWidget(search_note)

        search_form = QFormLayout()
        search_form.setHorizontalSpacing(18)
        search_form.setVerticalSpacing(16)
        search_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.neural_acceleration_checkbox = QCheckBox("Neural Acceleration")
        self.neural_acceleration_checkbox.setChecked(True)
        self.neural_acceleration_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #3d5368;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        self.image_search_term_count = SettingsSpinBox()
        self.image_search_term_count.setRange(2, 6)
        self.image_search_term_count.setValue(4)
        self.image_search_term_count.setMinimumWidth(140)
        self.image_search_term_count.setSuffix(" terms")
        self._apply_settings_input_chrome(self.image_search_term_count)
        search_form.addRow("Search mode", self.neural_acceleration_checkbox)
        search_form.addRow("Image Search", self.image_search_term_count)
        search_layout.addLayout(search_form)
        self._register_settings_search_target("ai.search.group", tab_key="ai", scroll=scroll, widget=search_surface)
        self._register_settings_search_target("ai.search.mode", tab_key="ai", scroll=scroll, widget=self.neural_acceleration_checkbox)
        self._register_settings_search_target("ai.search.image_terms", tab_key="ai", scroll=scroll, widget=self.image_search_term_count)

        search_hint = QLabel(
            "When Neural Acceleration is off, Cards and MCQ search use keyword matching instead of semantic embeddings."
        )
        search_hint.setObjectName("SmallMeta")
        search_hint.setWordWrap(True)
        search_hint.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 6px; }")
        search_layout.addWidget(search_hint)
        layout.addWidget(search_surface)

        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_account_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()
        self._settings_tab_scrolls["account"] = scroll
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._register_settings_search_target("tab.account", tab_key="account", scroll=scroll, widget=host)

        avatar_surface, avatar_layout = self._settings_card()
        avatar_title = QLabel("Avatar")
        avatar_title.setObjectName("SectionTitle")
        avatar_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        avatar_note = QLabel("Pick the avatar shown in the Settings profile rail.")
        avatar_note.setObjectName("SectionText")
        avatar_note.setWordWrap(True)
        avatar_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        avatar_layout.addWidget(avatar_title)
        avatar_layout.addWidget(avatar_note)

        avatar_top = QHBoxLayout()
        avatar_top.setContentsMargins(0, 10, 0, 4)
        avatar_top.setSpacing(18)
        self.account_avatar_label = QLabel()
        self.account_avatar_label.setObjectName("SettingsAccountAvatar")
        self.account_avatar_label.setFixedSize(116, 116)
        self.account_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.account_avatar_label.setStyleSheet(
            """
            QLabel#SettingsAccountAvatar {
                background: transparent;
                border: none;
                padding: 0px;
            }
            """
        )
        avatar_top.addWidget(self.account_avatar_label, 0, Qt.AlignmentFlag.AlignTop)
        avatar_copy = QVBoxLayout()
        avatar_copy.setContentsMargins(0, 0, 0, 0)
        avatar_copy.setSpacing(8)
        self.avatar_status_label = QLabel("Avatar follows your profile gender.")
        self.avatar_status_label.setObjectName("SectionText")
        self.avatar_status_label.setWordWrap(True)
        self.avatar_status_label.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        random_btn = QPushButton("Random avatar")
        random_btn.setObjectName("SettingsAvatarRandomButton")
        random_btn.clicked.connect(self._randomize_avatar_from_current_gender)
        self._mark_settings_bordered_button(random_btn)
        avatar_copy.addWidget(self.avatar_status_label)
        avatar_copy.addWidget(random_btn, 0, Qt.AlignmentFlag.AlignLeft)
        avatar_copy.addStretch(1)
        avatar_top.addLayout(avatar_copy, 1)
        avatar_layout.addLayout(avatar_top)

        self.avatar_grid_host = QWidget()
        self.avatar_grid_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.avatar_grid_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.avatar_grid_host.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.avatar_grid_host.setAutoFillBackground(False)
        self.avatar_grid_host.setStyleSheet("background: transparent; border: none;")
        self.avatar_grid_host.installEventFilter(self)
        self.avatar_grid = QGridLayout(self.avatar_grid_host)
        self.avatar_grid.setContentsMargins(0, 10, 0, 0)
        self.avatar_grid.setHorizontalSpacing(0)
        self.avatar_grid.setVerticalSpacing(14)
        self.avatar_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        avatar_layout.addWidget(self.avatar_grid_host)
        self._register_settings_search_target("account.avatar.group", tab_key="account", scroll=scroll, widget=avatar_surface)
        layout.addWidget(avatar_surface)

        account_surface, account_layout = self._settings_section_card()
        account_title = QLabel("Account actions")
        account_title.setObjectName("SectionTitle")
        account_title.setStyleSheet("QLabel#SectionTitle { font-size: 16px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        account_note = QLabel("Manage local account data and profiles.")
        account_note.setObjectName("SectionText")
        account_note.setWordWrap(True)
        account_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        account_layout.addWidget(account_title)
        account_layout.addWidget(account_note)

        actions_grid = QGridLayout()
        actions_grid.setContentsMargins(0, 4, 0, 0)
        actions_grid.setHorizontalSpacing(10)
        actions_grid.setVerticalSpacing(10)
        for index, (text, handler, target_key, legacy_key) in enumerate((
            ("export account", self._export_account_flow, "account.actions.export", "general.account.export"),
            ("delete account", self._delete_account_flow, "account.actions.delete", "general.account.delete"),
            ("change account", self._change_account_flow, "account.actions.change", "general.account.change"),
            ("New account", self._new_account_flow, "account.actions.new", "general.account.new"),
            ("Transfer Acc (Peer)", self._transfer_account_peer_flow, "account.actions.transfer_peer", "general.account.transfer_peer"),
            ("Transfer Acc (Host)", self._transfer_account_host_flow, "account.actions.transfer_host", "general.account.transfer_host"),
        )):
            button = self._account_action_button(text, handler)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            actions_grid.addWidget(button, index // 2, index % 2)
            self._account_action_buttons.append(button)
            self._register_settings_search_target(target_key, tab_key="account", scroll=scroll, widget=button)
            self._register_settings_search_target(legacy_key, tab_key="account", scroll=scroll, widget=button)
        account_layout.addLayout(actions_grid)
        self._register_settings_search_target("account.actions.group", tab_key="account", scroll=scroll, widget=account_surface)
        self._register_settings_search_target("general.account.group", tab_key="account", scroll=scroll, widget=account_surface)
        layout.addWidget(account_surface)

        self._set_account_actions_enabled(self.session_controller is not None)
        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _account_action_button(self, text: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("SettingsTinyLink")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFlat(True)
        button.clicked.connect(handler)
        button.setStyleSheet(
            """
            QPushButton#SettingsTinyLink {
                border: none;
                background: rgba(255, 255, 255, 0.26);
                color: #64748b;
                font-size: 12px;
                padding: 8px 12px;
                text-align: left;
                font-weight: 700;
                border-radius: 9px;
            }
            QPushButton#SettingsTinyLink:hover {
                color: #64748b;
                background: rgba(255, 255, 255, 0.26);
            }
            QPushButton#SettingsTinyLink:pressed {
                background: rgba(15, 37, 57, 0.10);
            }
            """
        )
        return button

    def _avatars_root(self) -> Path:
        assets_root = getattr(self.paths, "assets", None)
        if isinstance(assets_root, Path):
            return assets_root / "pfp" / "Avatars"
        return Path(__file__).resolve().parents[3] / "assets" / "pfp" / "Avatars"

    def _avatar_category_dir(self, category: str) -> Path | None:
        root = self._avatars_root()
        target = str(category or "").strip().lower()
        if not target or not root.exists():
            return None
        for child in root.iterdir():
            if child.is_dir() and child.name.lower() == target:
                return child
        candidate = root / category
        return candidate if candidate.exists() else None

    def _avatar_files_for_category(self, category: str) -> list[Path]:
        folder = self._avatar_category_dir(category)
        if folder is None:
            return []
        files = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".png" and path.stem.isdigit()
        ]
        return sorted(files, key=lambda path: int(path.stem))

    def _avatar_allowed_categories_for_gender(self, gender: str) -> list[str]:
        lowered = str(gender or "").strip().lower()
        if lowered == "male":
            return ["Male"]
        if lowered == "female":
            return ["Female"]
        return ["Female", "Male"]

    def _avatar_filter_gender(self) -> str:
        if hasattr(self, "gender_combo") and self.gender_combo.currentText().strip().lower() == "custom":
            return "__custom__"
        if hasattr(self, "gender_combo"):
            return self.gender_combo.currentText().strip()
        return str(self.datastore.load_profile().get("gender", "")).strip()

    def _avatar_candidates_for_gender(self, gender: str) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        for category in self._avatar_allowed_categories_for_gender(gender):
            for path in self._avatar_files_for_category(category):
                candidates.append((category, path))
        return candidates

    def _avatar_path(self, category: str, filename: str) -> Path | None:
        folder = self._avatar_category_dir(category)
        if folder is None:
            return None
        wanted = str(filename or "").strip().lower()
        if not wanted:
            return None
        for path in folder.iterdir():
            if path.is_file() and path.name.lower() == wanted and path.suffix.lower() == ".png":
                return path
        return None

    def _profile_avatar_is_valid(self, profile: dict, gender: str) -> bool:
        category = str(profile.get("avatar_category", "")).strip()
        filename = str(profile.get("avatar_file", "")).strip()
        if category not in self._avatar_allowed_categories_for_gender(gender):
            return False
        return self._avatar_path(category, filename) is not None

    def _choose_random_avatar(self, gender: str) -> tuple[str, Path] | None:
        candidates = self._avatar_candidates_for_gender(gender)
        if not candidates:
            return None
        return random.choice(candidates)

    def _set_current_avatar(self, category: str, path: Path, *, refresh_grid: bool = True) -> None:
        self._avatar_category = str(category or "").strip()
        self._avatar_file = path.name
        self._refresh_avatar_previews()
        if refresh_grid:
            self._refresh_avatar_grid()

    def _ensure_profile_avatar(self, profile: dict) -> bool:
        gender = str(profile.get("gender", "")).strip()
        if self._profile_avatar_is_valid(profile, gender):
            category = str(profile.get("avatar_category", "")).strip()
            filename = str(profile.get("avatar_file", "")).strip()
            path = self._avatar_path(category, filename)
            if path is not None:
                self._set_current_avatar(category, path, refresh_grid=False)
                return False
        chosen = self._choose_random_avatar(gender)
        if chosen is None:
            self._avatar_category = ""
            self._avatar_file = ""
            self._refresh_avatar_previews()
            return False
        category, path = chosen
        profile["avatar_category"] = category
        profile["avatar_file"] = path.name
        profile["avatar_index"] = path.stem
        self._set_current_avatar(category, path, refresh_grid=False)
        return True

    def _current_gender_for_avatar(self) -> str:
        return self._avatar_filter_gender()

    def _randomize_avatar_from_current_gender(self) -> None:
        chosen = self._choose_random_avatar(self._current_gender_for_avatar())
        if chosen is None:
            self.avatar_status_label.setText("No avatar images were found.")
            return
        category, path = chosen
        self._set_current_avatar(category, path)

    def _select_avatar(self, category: str, path: Path) -> None:
        self._set_current_avatar(category, path)

    def _refresh_avatar_previews(self) -> None:
        path = self._avatar_path(self._avatar_category, self._avatar_file)
        labels = [
            getattr(self, "sidebar_avatar_label", None),
            getattr(self, "account_avatar_label", None),
        ]
        for label in labels:
            if not isinstance(label, QLabel):
                continue
            if path is None:
                label.clear()
                label.setText("?")
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                label.clear()
                label.setText("?")
                continue
            size = min(label.width(), label.height())
            label.setPixmap(self._rounded_avatar_pixmap(pixmap, size))
        if hasattr(self, "avatar_status_label"):
            if path is None:
                self.avatar_status_label.setText("No avatar selected yet.")
            else:
                self.avatar_status_label.setText(f"Using {self._avatar_category} avatar {Path(self._avatar_file).stem}.")

    def _rounded_avatar_pixmap(self, pixmap: QPixmap, size: int) -> QPixmap:
        size = max(1, int(size))
        zoom = 1.12
        screen = QGuiApplication.primaryScreen()
        dpr = max(1.0, float(screen.devicePixelRatio() if screen is not None else 1.0))
        physical_size = max(1, int(round(size * dpr)))
        physical_avatar = max(1, int(round(size * zoom * dpr)))
        scaled = pixmap.scaled(QSize(physical_avatar, physical_avatar), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        output = QPixmap(physical_size, physical_size)
        output.setDevicePixelRatio(dpr)
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            circle = QRectF(0.5, 0.5, size - 1.0, size - 1.0)
            path = QPainterPath()
            path.addEllipse(circle)
            painter.setClipPath(path)
            painter.setBrush(QColor(64, 151, 232, 210))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(circle)
            scaled_width = scaled.width() / dpr
            scaled_height = scaled.height() / dpr
            x = (size - scaled_width) / 2.0
            y = (size - scaled_height) / 2.0
            painter.drawPixmap(QRectF(x, y, scaled_width, scaled_height), scaled, QRectF(0, 0, scaled.width(), scaled.height()))
        finally:
            painter.end()
        return output

    def _avatar_grid_column_count_for(self, candidate_count: int) -> int:
        if candidate_count <= 0:
            return 1
        button_width = 66
        host = getattr(self, "avatar_grid_host", None)
        available_width = 0
        if isinstance(host, QWidget):
            available_width = host.contentsRect().width()
        if available_width <= 0:
            return min(candidate_count, 10)
        columns = max(1, int(available_width // button_width))
        return min(candidate_count, columns)

    def _refresh_avatar_grid_if_columns_changed(self) -> None:
        candidates = self._avatar_candidates_for_gender(self._current_gender_for_avatar())
        column_count = self._avatar_grid_column_count_for(len(candidates))
        if column_count != self._avatar_grid_column_count:
            self._refresh_avatar_grid()

    def _refresh_avatar_grid(self) -> None:
        grid = getattr(self, "avatar_grid", None)
        if not isinstance(grid, QGridLayout):
            return
        previous_columns = max(self._avatar_grid_column_count, grid.columnCount())
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._avatar_buttons = []
        candidates = self._avatar_candidates_for_gender(self._current_gender_for_avatar())
        if not candidates:
            empty = QLabel("No avatar files found.")
            empty.setObjectName("SmallMeta")
            empty.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
            grid.addWidget(empty, 0, 0)
            self._avatar_grid_column_count = 1
            return
        column_count = self._avatar_grid_column_count_for(len(candidates))
        for column in range(max(previous_columns, column_count, 1)):
            grid.setColumnStretch(column, 0)
            grid.setColumnMinimumWidth(column, 0)
        for column in range(column_count):
            grid.setColumnStretch(column, 1)
            grid.setColumnMinimumWidth(column, 66)
        self._avatar_grid_column_count = column_count
        for index, (category, path) in enumerate(candidates):
            button = SettingsAvatarChoiceButton()
            button.setObjectName("SettingsAvatarChoice")
            button.setStyleSheet(
                """
                QAbstractButton#SettingsAvatarChoice,
                QAbstractButton#SettingsAvatarChoice:hover,
                QAbstractButton#SettingsAvatarChoice:pressed,
                QAbstractButton#SettingsAvatarChoice:checked {
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }
                """
            )
            source_pixmap = QPixmap(str(path))
            if source_pixmap.isNull():
                button.set_avatar_pixmap(QPixmap())
            else:
                button.set_avatar_pixmap(self._rounded_avatar_pixmap(source_pixmap, 62))
            button.setToolTip(f"{category} avatar {path.stem}")
            button.setChecked(category == self._avatar_category and path.name.lower() == self._avatar_file.lower())
            button.clicked.connect(lambda _checked=False, avatar_category=category, avatar_path=path: self._select_avatar(avatar_category, avatar_path))
            self._avatar_buttons.append(button)
            grid.addWidget(button, index // column_count, index % column_count, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def _refresh_sidebar_profile(self) -> None:
        if not hasattr(self, "sidebar_name_label") or not hasattr(self, "sidebar_subtitle_label"):
            return
        profile_name = ""
        hobbies = ""
        if hasattr(self, "profile_name_edit"):
            profile_name = self.profile_name_edit.text().strip()
        if not profile_name and hasattr(self, "name_edit"):
            profile_name = self.name_edit.text().strip()
        if hasattr(self, "hobbies_edit"):
            hobbies = self.hobbies_edit.text().strip()
        self.sidebar_name_label.setText(profile_name or "Random Person")
        self.sidebar_subtitle_label.setText(f"I like {hobbies}" if hobbies else "I like gaming and ML")

    def _build_audio_tab(self) -> QWidget:
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._register_settings_search_target("tab.audio", tab_key="audio", scroll=None, widget=host)

        intro = QLabel("Choose which sounds ONCard uses for clicks, transitions, and notifications.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet("QLabel#SectionText { font-size: 14px; line-height: 1.6; color: #475569; }")
        layout.addWidget(intro)

        surface, form = self._settings_card(layout_type=QFormLayout)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_title = QLabel("Audio")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        form.addWidget(form_title)

        self.audio_enabled_checkbox = QCheckBox("Audio")
        self.audio_enabled_checkbox.setChecked(True)
        form.addRow("Master audio", self.audio_enabled_checkbox)
        self._register_settings_search_target("audio.group", tab_key="audio", scroll=None, widget=surface)
        self._register_settings_search_target("audio.master", tab_key="audio", scroll=None, widget=self.audio_enabled_checkbox)

        self.click_enabled_checkbox = QCheckBox("Mouse Click")
        self.click_sound_combo = PopupMenuComboBox()
        for label, value in (
            ("Soft tap", "click3"),
            ("Classic tap", "click"),
            ("Crisp tap", "click4"),
            ("Deep tap", "click5"),
        ):
            self.click_sound_combo.addItem(label, value)
        self.click_sound_combo.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Mouse click sound",
                control=self.click_sound_combo,
                fallback_value="click3",
            )
        )
        self._apply_settings_input_chrome(self.click_sound_combo)
        click_row = self._audio_choice_row(self.click_enabled_checkbox, self.click_sound_combo, lambda: self._test_click_sound())
        form.addRow("Mouse Click", click_row)
        self._register_settings_search_target("audio.click_enabled", tab_key="audio", scroll=None, widget=self.click_enabled_checkbox)
        self._register_settings_search_target("audio.click_sound", tab_key="audio", scroll=None, widget=self.click_sound_combo)

        self.transition_enabled_checkbox = QCheckBox("Transition")
        self.transition_sound_combo = PopupMenuComboBox()
        self.transition_sound_combo.addItem("Simple woosh", "woosh")
        self.transition_sound_combo.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Transition sound",
                control=self.transition_sound_combo,
                fallback_value="woosh",
            )
        )
        self._apply_settings_input_chrome(self.transition_sound_combo)
        transition_row = self._audio_choice_row(
            self.transition_enabled_checkbox,
            self.transition_sound_combo,
            lambda: self._test_transition_sound(),
        )
        form.addRow("Transition", transition_row)
        self._register_settings_search_target("audio.transition_enabled", tab_key="audio", scroll=None, widget=self.transition_enabled_checkbox)
        self._register_settings_search_target("audio.transition_sound", tab_key="audio", scroll=None, widget=self.transition_sound_combo)

        self.notification_sound_combo = PopupMenuComboBox()
        self.notification_sound_combo.addItem("Default Windows", "windows")
        self.notification_sound_combo.addItem("Notify 1", "notify1")
        self.notification_sound_combo.addItem("Notify 2", "notify2")
        self.notification_sound_combo.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Notification sound",
                control=self.notification_sound_combo,
                fallback_value="windows",
            )
        )
        self._apply_settings_input_chrome(self.notification_sound_combo)
        notification_row = self._audio_choice_row(None, self.notification_sound_combo, lambda: self._test_notification_sound())
        form.addRow("Notification", notification_row)
        self._register_settings_search_target("audio.notification_sound", tab_key="audio", scroll=None, widget=self.notification_sound_combo)

        note = QLabel(
            "Mouse click sounds also apply to sliders. Custom notification sounds play with ONCard toast notifications; FTC finish notifications repeat custom sounds four times."
        )
        note.setObjectName("SmallMeta")
        note.setWordWrap(True)
        note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")

        layout.addWidget(surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _audio_choice_row(self, toggle: QCheckBox | None, combo: QComboBox, test_handler) -> QWidget:
        row = QWidget()
        row.setObjectName("SettingsAudioChoiceRow")
        row.setStyleSheet("QWidget#SettingsAudioChoiceRow { background: transparent; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if toggle is not None:
            toggle.setMinimumWidth(124)
            layout.addWidget(toggle, 0)
        combo.setMinimumWidth(180)
        layout.addWidget(combo, 1)
        test_btn = QPushButton("Test")
        test_btn.setProperty("skipClickSfx", True)
        test_btn.setFixedWidth(72)
        self._mark_settings_bordered_button(test_btn)
        test_btn.clicked.connect(test_handler)
        layout.addWidget(test_btn, 0)
        return row

    def _build_performance_tab(self) -> QWidget:
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)
        self._register_settings_search_target("tab.performance", tab_key="performance", scroll=None, widget=host)

        intro = QLabel("Control how aggressively ONCard warms caches, uses background workers, and handles motion.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet("QLabel#SectionText { font-size: 14px; line-height: 1.6; color: #475569; }")
        layout.addWidget(intro)

        perf_surface, perf_layout = self._settings_card(layout_type=QFormLayout)
        form_title = QLabel("Performance")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #627181; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        perf_layout.addRow(form_title)

        self.performance_mode = PopupMenuComboBox()
        self.performance_mode.addItem("Auto", "auto")
        self.performance_mode.addItem("Manual", "manual")
        self.performance_mode.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Performance mode",
                control=self.performance_mode,
                fallback_value="auto",
            )
        )
        self.performance_mode.currentIndexChanged.connect(self._refresh_performance_mode)
        self._apply_settings_input_chrome(self.performance_mode)

        self.startup_workers = SettingsSpinBox()
        self.startup_workers.setRange(1, 8)
        self.background_workers = SettingsSpinBox()
        self.background_workers.setRange(1, 8)
        self._apply_settings_input_chrome(self.startup_workers)
        self._apply_settings_input_chrome(self.background_workers)
        self.warm_cache_checkbox = QCheckBox("Warm SQL, card, and vector caches during startup")
        self.warm_cache_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        self.reduced_motion_checkbox = QCheckBox("Reduce motion and transition animations")
        self.reduced_motion_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )

        perf_layout.addRow("Mode", self.performance_mode)
        perf_layout.addRow("Startup workers", self.startup_workers)
        perf_layout.addRow("Background workers", self.background_workers)
        perf_layout.addRow("Startup warmup", self.warm_cache_checkbox)
        perf_layout.addRow("Reduced motion", self.reduced_motion_checkbox)
        self._register_settings_search_target("performance.group", tab_key="performance", scroll=None, widget=perf_surface)
        self._register_settings_search_target("performance.mode", tab_key="performance", scroll=None, widget=self.performance_mode)
        self._register_settings_search_target("performance.startup_workers", tab_key="performance", scroll=None, widget=self.startup_workers)
        self._register_settings_search_target("performance.background_workers", tab_key="performance", scroll=None, widget=self.background_workers)
        self._register_settings_search_target("performance.startup_warmup", tab_key="performance", scroll=None, widget=self.warm_cache_checkbox)
        self._register_settings_search_target("performance.reduced_motion", tab_key="performance", scroll=None, widget=self.reduced_motion_checkbox)

        note = QLabel(
            "Auto keeps ONCard on the recommended defaults. Manual lets you raise or lower the worker counts explicitly."
        )
        note.setObjectName("SmallMeta")
        note.setWordWrap(True)
        note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        layout.addWidget(perf_surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _build_model_row(self, spec: ModelSpec) -> dict[str, object]:
        container = QFrame()
        container.setObjectName("SettingsCard")
        container.setStyleSheet(
            """
            QFrame#SettingsCard {
                background: rgba(255, 255, 255, 0.46);
                border: 1px solid rgba(255, 255, 255, 0.62);
                border-radius: 16px;
            }
            """
        )
        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        copy_col = QVBoxLayout()
        copy_col.setContentsMargins(0, 0, 0, 0)
        copy_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        name_label = QLabel(spec.display_name)
        name_label.setObjectName("SectionTitle")
        name_label.setWordWrap(True)
        kind_label = QLabel("Required" if spec.required else "Optional")
        kind_label.setObjectName("CardMetaPill")
        title_row.addWidget(name_label)
        title_row.addWidget(kind_label, 0, Qt.AlignLeft)
        title_row.addStretch(1)

        meta_label = QLabel(f"Tag: {spec.primary_tag}  |  Size: {spec.size_label}")
        meta_label.setObjectName("SmallMeta")
        meta_label.setWordWrap(True)
        role_label = QLabel(MODEL_ROLE_COPY.get(spec.key, "Used by ONCard."))
        role_label.setObjectName("SectionText")
        role_label.setWordWrap(True)
        copy_col.addLayout(title_row)
        copy_col.addWidget(meta_label)
        copy_col.addWidget(role_label)

        side_col = QVBoxLayout()
        side_col.setContentsMargins(0, 0, 0, 0)
        side_col.setSpacing(8)
        side_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        status_label = QLabel("Checking...")
        status_label.setObjectName("CardMetaPill")
        install_btn = QPushButton("Install")
        reinstall_btn = QPushButton("Reinstall")
        delete_btn = QPushButton("Delete")
        self._mark_settings_bordered_button(install_btn)
        self._mark_settings_bordered_button(reinstall_btn)
        self._mark_settings_bordered_button(delete_btn)
        install_btn.clicked.connect(lambda _checked=False, key=spec.key: self._install_model(key))
        reinstall_btn.clicked.connect(lambda _checked=False, key=spec.key: self._install_model(key))
        delete_btn.clicked.connect(lambda _checked=False, key=spec.key: self._delete_model(key))
        reinstall_btn.setVisible(False)
        delete_btn.setVisible(False)
        for button in (install_btn, reinstall_btn, delete_btn):
            button.setFixedWidth(104)
        side_col.addWidget(status_label, 0, Qt.AlignmentFlag.AlignRight)
        side_col.addWidget(install_btn, 0, Qt.AlignmentFlag.AlignRight)
        side_col.addWidget(reinstall_btn, 0, Qt.AlignmentFlag.AlignRight)
        side_col.addWidget(delete_btn, 0, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(copy_col, 1)
        layout.addLayout(side_col, 0)
        return {
            "container": container,
            "status": status_label,
            "install_btn": install_btn,
            "reinstall_btn": reinstall_btn,
            "delete_btn": delete_btn,
            "spec": spec,
        }

    def _load(self) -> None:
        profile = self.datastore.load_profile()
        user_name = str(profile.get("name", "")).strip()
        profile_name = str(profile.get("profile_name", "")).strip() or user_name
        self.name_edit.setText(user_name)
        self.profile_name_edit.setText(profile_name)
        self.age_spin.setValue(self._coerce_age(profile.get("age")))
        self.hobbies_edit.setText(str(profile.get("hobbies", "")))
        self._set_gender_from_profile(str(profile.get("gender", "")).strip())
        if self._ensure_profile_avatar(profile):
            self.datastore.save_profile(profile)

        grade = str(profile.get("grade", "")).strip()
        if grade and self.grade_combo.findText(grade) < 0:
            self.grade_combo.addItem(grade)
        if grade:
            self.grade_combo.setCurrentText(grade)
        attention_value = int(profile.get("attention_span_minutes", profile.get("question_focus_level", 5)) or 5)
        attention_value = max(1, min(10, attention_value))
        self.attention_slider.setValue(attention_value)
        self._last_attention_value = attention_value
        self._update_attention_label(attention_value)

        ai_settings = self.datastore.load_ai_settings()
        for key, _label, _description, minimum in CONTEXT_LENGTH_SETTINGS:
            spin = self._context_length_spins.get(key)
            if spin is not None:
                value = int(ai_settings.get(key, minimum) or minimum)
                spin.setValue(max(MIN_CONTEXT_LENGTH, min(MAX_CONTEXT_LENGTH, value)))
        self._refresh_context_model_choices(ai_settings)
        tone_value = str(ai_settings.get("ask_ai_tone", ai_settings.get("assistant_tone", "warm"))).strip().lower() or "warm"
        tone_index = self.ask_ai_tone.findData(tone_value)
        if tone_index < 0:
            tone_index = self.ask_ai_tone.findData("warm")
        if tone_index < 0:
            tone_index = 0
        self.ask_ai_tone.setCurrentIndex(tone_index)
        emoji_value = max(1, min(4, int(ai_settings.get("ask_ai_emoji_level", 2) or 2)))
        self.ask_ai_emoji_slider.setValue(emoji_value)
        self._last_ask_ai_emoji_value = emoji_value
        self._update_ask_ai_emoji_label(emoji_value)
        self.neural_acceleration_checkbox.setChecked(bool(ai_settings.get("neural_acceleration", True)))
        self.image_search_term_count.setValue(max(2, min(6, int(ai_settings.get("image_search_term_count", 4) or 4))))
        cloud_enabled = bool(ai_settings.get("ollama_cloud_enabled", False))
        cloud_api_key = str(ai_settings.get("ollama_cloud_api_key", "")).strip()
        cloud_tag = str(ai_settings.get("ollama_cloud_selected_model_tag", "")).strip()
        self.cloud_enabled_checkbox.blockSignals(True)
        self.cloud_enabled_checkbox.setChecked(cloud_enabled)
        self.cloud_enabled_checkbox.blockSignals(False)
        self.cloud_api_key_edit.blockSignals(True)
        self.cloud_api_key_edit.setText(cloud_api_key)
        self.cloud_api_key_edit.blockSignals(False)
        self._cloud_model_tags = []
        self.cloud_model_combo.clear()
        if cloud_enabled and cloud_tag:
            self.cloud_model_combo.addItem(self._cloud_label_for_tag(cloud_tag), cloud_tag)
            self.cloud_model_combo.setCurrentIndex(0)
            self._cloud_model_tags = [cloud_tag]
        self._refresh_cloud_controls(force_reload_models=False, preferred_tag=cloud_tag)
        setup = self.datastore.load_setup()
        appearance = dict(setup.get("appearance", {}))
        theme_value = normalize_theme_mode(appearance.get("theme", "light"))
        theme_index = self.theme_combo.findData(theme_value)
        if theme_index < 0:
            theme_index = self.theme_combo.findData("light")
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        ftc_setup = dict(setup.get("ftc", {}))
        default_mode = str(ftc_setup.get("default_mode", "standard"))
        mode_index = self.ftc_default_mode.findData(default_mode)
        if mode_index < 0:
            mode_index = 0
        self.ftc_default_mode.setCurrentIndex(mode_index)
        self.ftc_questions_standard.setValue(max(1, min(30, int(ftc_setup.get("question_count_standard", 4) or 4))))
        self.ftc_questions_force.setValue(max(1, min(30, int(ftc_setup.get("question_count_force", 8) or 8))))
        difficulty_value = str(ftc_setup.get("difficulty", "normal")).strip().lower()
        difficulty_index = self.ftc_difficulty.findData(difficulty_value)
        if difficulty_index < 0:
            difficulty_index = self.ftc_difficulty.findData("normal")
        if difficulty_index < 0:
            difficulty_index = 2
        self.ftc_difficulty.setCurrentIndex(difficulty_index)
        use_ocr = ftc_setup.get("use_ocr", ai_settings.get("files_to_cards_ocr", True))
        self.ftc_ocr_checkbox.setChecked(bool(use_ocr))
        mcq_setup = dict(setup.get("mcq", {}))
        self.mcq_enabled_checkbox.setChecked(bool(mcq_setup.get("enabled", False)))
        mcq_difficulty = str(mcq_setup.get("difficulty", "slightly_harder")).strip() or "slightly_harder"
        difficulty_index = self.mcq_difficulty.findData(mcq_difficulty)
        if difficulty_index >= 0:
            self.mcq_difficulty.setCurrentIndex(difficulty_index)
        performance = dict(setup.get("performance", {}))
        self.performance_mode.setCurrentIndex(0 if str(performance.get("mode", "auto")) == "auto" else 1)
        self.startup_workers.setValue(max(1, min(8, int(performance.get("startup_workers", 8) or 8))))
        self.background_workers.setValue(max(1, min(8, int(performance.get("background_workers", 2) or 2))))
        self.warm_cache_checkbox.setChecked(bool(performance.get("warm_cache_on_startup", True)))
        self.reduced_motion_checkbox.setChecked(bool(performance.get("reduced_motion", False)))
        stats_setup = dict(setup.get("stats", {}))
        default_stats_range = str(stats_setup.get("default_range", "daily")).strip().lower() or "daily"
        stats_index = self.stats_default_range.findData(default_stats_range)
        if stats_index < 0:
            stats_index = self.stats_default_range.findData("daily")
        if stats_index < 0:
            stats_index = 1
        self.stats_default_range.setCurrentIndex(stats_index)
        audio_setup = dict(setup.get("audio", {}))
        self.audio_enabled_checkbox.setChecked(bool(audio_setup.get("enabled", True)))
        self.click_enabled_checkbox.setChecked(bool(audio_setup.get("click_enabled", True)))
        self._set_combo_data(self.click_sound_combo, str(audio_setup.get("click_sound", "click3")), "click3")
        self.transition_enabled_checkbox.setChecked(bool(audio_setup.get("transition_enabled", True)))
        self._set_combo_data(self.transition_sound_combo, str(audio_setup.get("transition_sound", "woosh")), "woosh")
        self._set_combo_data(self.notification_sound_combo, str(audio_setup.get("notification_sound", "windows")), "windows")
        self._refresh_performance_mode()
        self.ollama_status.setText("Model status will load after settings opens.")
        self.ollama_hint.setText("You can keep using these settings while ONCard checks Ollama.")
        self._refresh_text_model_choices_from_saved(ai_settings)
        self._refresh_sidebar_profile()
        self._refresh_avatar_grid()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findData(str(value or "").strip())
        if index < 0:
            index = combo.findData(fallback)
        if index < 0:
            index = 0
        combo.setCurrentIndex(index)

    def _cloud_mode_enabled(self) -> bool:
        return bool(self.cloud_enabled_checkbox.isChecked())

    def _open_ollama_cloud_keys(self) -> None:
        webbrowser.open(OLLAMA_CLOUD_KEYS_URL)

    def _on_cloud_mode_toggled(self, _checked: bool) -> None:
        self._refresh_cloud_controls(force_reload_models=self._cloud_mode_enabled())

    def _on_cloud_api_key_changed(self, _text: str) -> None:
        self._cloud_model_tags = []
        self.cloud_model_combo.clear()
        if self._cloud_mode_enabled():
            if self.cloud_api_key_edit.text().strip():
                self.cloud_status.setText("API key updated. Press Load cloud models.")
            else:
                self.cloud_status.setText("Paste your Ollama API key to load cloud models.")
        self._refresh_cloud_controls(force_reload_models=False)

    def _cloud_candidate_specs(self) -> list[ModelSpec]:
        return cloud_llm_specs()

    def _cloud_candidate_tags(self) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for spec in self._cloud_candidate_specs():
            for tag in [spec.primary_tag, *spec.candidate_tags]:
                clean = str(tag or "").strip()
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                tags.append(clean)
        return tags

    def _cloud_label_for_tag(self, model_tag: str) -> str:
        clean_tag = str(model_tag or "").strip()
        for spec in self._cloud_candidate_specs():
            if clean_tag == spec.primary_tag or clean_tag in spec.candidate_tags:
                return f"{spec.display_name} (Cloud)"
        return f"{clean_tag} (Cloud)" if clean_tag else "Cloud model"

    def _refresh_cloud_controls(self, *, force_reload_models: bool = False, preferred_tag: str = "") -> None:
        cloud_enabled = self._cloud_mode_enabled()
        key_present = bool(self.cloud_api_key_edit.text().strip())
        self.cloud_api_key_edit.setEnabled(cloud_enabled)
        self.refresh_cloud_models_btn.setEnabled(cloud_enabled and key_present and not self._loading_cloud_models)
        self.cloud_model_combo.setEnabled(cloud_enabled and self.cloud_model_combo.count() > 0)

        if not cloud_enabled:
            self.cloud_status.setText("Cloud service is off. ONCard uses local models.")
            self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0)
            return

        if not key_present:
            self.cloud_status.setText("Cloud mode is on. Paste an API key, then load cloud variants.")
            self.cloud_model_combo.setEnabled(False)
            self.selected_text_llm.setEnabled(False)
            return

        self.selected_text_llm.setEnabled(False)
        if force_reload_models:
            self._refresh_cloud_models(force=force_reload_models, preferred_tag=preferred_tag)
        elif self.cloud_model_combo.currentIndex() >= 0:
            current_label = str(self.cloud_model_combo.currentText() or "").strip()
            self.cloud_status.setText(
                f"Cloud model ready: {current_label}. Cloud mode overrides local model selection."
                if current_label
                else "Cloud model ready. Cloud mode overrides local model selection."
            )
        else:
            self.cloud_status.setText("Cloud mode is ready. Press Load cloud models.")

    def _refresh_cloud_models(self, *, force: bool = False, preferred_tag: str = "") -> None:
        if not self._cloud_mode_enabled():
            return
        api_key = self.cloud_api_key_edit.text().strip()
        if not api_key:
            self.cloud_status.setText("Paste your Ollama API key to load cloud models.")
            self.cloud_model_combo.clear()
            self.cloud_model_combo.setEnabled(False)
            return
        if self._loading_cloud_models:
            return
        if self._cloud_model_tags and not force:
            available_tags = list(self._cloud_model_tags)
        else:
            self._loading_cloud_models = True
            self.refresh_cloud_models_btn.setEnabled(False)
            self.cloud_status.setText("Loading cloud models...")
            try:
                tags = self.ollama.cloud_model_tags(api_key, timeout=8)
            except OllamaError as exc:
                self.cloud_status.setText(f"Cloud model lookup failed: {exc}")
                self.cloud_model_combo.clear()
                self.cloud_model_combo.setEnabled(False)
                self._cloud_model_tags = []
                self._loading_cloud_models = False
                self.refresh_cloud_models_btn.setEnabled(True)
                return
            available_tags = []
            for spec in self._cloud_candidate_specs():
                chosen = ""
                for tag in [spec.primary_tag, *spec.candidate_tags]:
                    clean_tag = str(tag or "").strip()
                    if clean_tag:
                        chosen = clean_tag
                        break
                if chosen:
                    available_tags.append(chosen)
            self._cloud_model_tags = list(available_tags)
            self._loading_cloud_models = False

        selected_before = preferred_tag.strip() or str(self.cloud_model_combo.currentData() or "").strip()
        self.cloud_model_combo.blockSignals(True)
        self.cloud_model_combo.clear()
        for tag in available_tags:
            self.cloud_model_combo.addItem(self._cloud_label_for_tag(tag), tag)
        chosen = selected_before if selected_before in available_tags else (available_tags[0] if available_tags else "")
        idx = self.cloud_model_combo.findData(chosen)
        if idx >= 0:
            self.cloud_model_combo.setCurrentIndex(idx)
        self.cloud_model_combo.blockSignals(False)
        self.cloud_model_combo.setEnabled(bool(available_tags))
        if available_tags:
            self.cloud_status.setText(
                f"Loaded {len(available_tags)} cloud variants for ONCard models. "
                "Cloud mode overrides local model selection."
            )
        else:
            self.cloud_status.setText("No matching cloud versions were found for ONCard's current text models.")
        self.refresh_cloud_models_btn.setEnabled(True)
        self.selected_text_llm.setEnabled(False)

    def _save(self) -> None:
        self._clear_backdrop()
        profile_name = self.name_edit.text().strip()
        if not profile_name:
            QMessageBox.warning(self, "Settings", "Name is required.")
            return
        if self.gender_combo.currentText().strip().lower() == "custom" and not self.gender_custom_edit.text().strip():
            QMessageBox.warning(self, "Settings", "Enter a custom gender and pronouns up to 64 characters.")
            return
        if self.session_controller is not None:
            try:
                self.session_controller.rename_active_account(profile_name)
            except Exception as exc:
                QMessageBox.warning(self, "Settings", str(exc))
                return

        profile = self.datastore.load_profile()
        profile["name"] = profile_name
        profile["profile_name"] = self.profile_name_edit.text().strip() or profile_name
        profile["age"] = str(self.age_spin.value())
        profile["hobbies"] = self.hobbies_edit.text().strip()
        profile["grade"] = self.grade_combo.currentText().strip()
        profile["gender"] = self._effective_gender_value()
        profile["attention_span_minutes"] = self.attention_slider.value()
        profile["question_focus_level"] = self.attention_slider.value()
        avatar_gender = self._avatar_filter_gender()
        if self._avatar_category not in self._avatar_allowed_categories_for_gender(avatar_gender):
            chosen = self._choose_random_avatar(avatar_gender)
            if chosen is not None:
                category, path = chosen
                self._set_current_avatar(category, path)
        profile["avatar_category"] = self._avatar_category
        profile["avatar_file"] = self._avatar_file
        profile["avatar_index"] = Path(self._avatar_file).stem if self._avatar_file else ""
        self.datastore.save_profile(profile)

        ai_settings = self.datastore.load_ai_settings()
        for key, _label, _description, minimum in CONTEXT_LENGTH_SETTINGS:
            spin = self._context_length_spins.get(key)
            if spin is not None:
                if key == "wiki_breakdown_context_length":
                    combo = self._context_model_combos.get(key)
                    if combo is not None and str(combo.currentData() or "").strip() == QN_SUMMARIZER_MODEL_KEY:
                        ai_settings[key] = QN_SUMMARIZER_CONTEXT_LENGTH
                    else:
                        ai_settings[key] = max(MIN_CONTEXT_LENGTH, min(MAX_CONTEXT_LENGTH, int(spin.value())))
                else:
                    ai_settings[key] = max(MIN_CONTEXT_LENGTH, min(MAX_CONTEXT_LENGTH, int(spin.value())))
            combo = self._context_model_combos.get(key)
            if combo is not None:
                ai_settings[feature_model_setting_key(key)] = str(combo.currentData() or "").strip()
        ai_settings["use_selected_llm_for_text_features"] = True
        cloud_enabled = self._cloud_mode_enabled()
        cloud_api_key = self.cloud_api_key_edit.text().strip()
        if cloud_enabled and not cloud_api_key:
            QMessageBox.warning(self, "Settings", "Cloud mode is enabled, but API key is empty.")
            return
        cloud_model_tag = str(self.cloud_model_combo.currentData() or "").strip()
        if not cloud_model_tag:
            cloud_model_tag = str(ai_settings.get("ollama_cloud_selected_model_tag", "")).strip()
        if cloud_enabled and not cloud_model_tag:
            QMessageBox.warning(self, "Settings", "Select a cloud model first, then save.")
            return
        selected_key = str(self.selected_text_llm.currentData() or "").strip()
        if cloud_enabled:
            mapped_key = text_llm_key_for_model_tag(cloud_model_tag)
            if mapped_key:
                ai_settings["selected_text_llm_key"] = mapped_key
        elif selected_key:
            ai_settings["selected_text_llm_key"] = selected_key
        selected_ocr_key = str(self.selected_ocr_llm.currentData() or "").strip()
        if selected_ocr_key:
            ai_settings["selected_ocr_llm_key"] = selected_ocr_key
        ai_settings["ollama_cloud_enabled"] = cloud_enabled
        ai_settings["ollama_cloud_api_key"] = cloud_api_key
        if cloud_model_tag:
            ai_settings["ollama_cloud_selected_model_tag"] = cloud_model_tag
        ai_settings["ask_ai_tone"] = str(self.ask_ai_tone.currentData() or "warm")
        ai_settings["assistant_tone"] = ai_settings["ask_ai_tone"]
        ai_settings["ask_ai_emoji_level"] = max(1, min(4, self.ask_ai_emoji_slider.value()))
        ai_settings.pop("ask_ai_stream_response", None)
        ai_settings.pop("wiki_summarizer_stream_response", None)
        ai_settings["neural_acceleration"] = bool(self.neural_acceleration_checkbox.isChecked())
        ai_settings["image_search_term_count"] = max(2, min(6, int(self.image_search_term_count.value())))
        ai_settings["files_to_cards_ocr"] = self.ftc_ocr_checkbox.isChecked()
        self.datastore.save_ai_settings(ai_settings)
        self.ollama.configure_from_ai_settings(ai_settings)
        self.preflight.invalidate()

        setup = self.datastore.load_setup()
        setup["appearance"] = {
            "theme": normalize_theme_mode(self.theme_combo.currentData() or "light"),
        }
        setup["ftc"] = {
            "default_mode": str(self.ftc_default_mode.currentData() or "standard"),
            "question_count_standard": int(self.ftc_questions_standard.value()),
            "question_count_force": int(self.ftc_questions_force.value()),
            "difficulty": str(self.ftc_difficulty.currentData() or "normal"),
            "use_ocr": bool(self.ftc_ocr_checkbox.isChecked()),
        }
        setup["mcq"] = {
            "enabled": bool(self.mcq_enabled_checkbox.isChecked()),
            "difficulty": str(self.mcq_difficulty.currentData() or "slightly_harder"),
        }
        setup["performance"] = {
            "mode": str(self.performance_mode.currentData() or "auto"),
            "startup_workers": self.startup_workers.value(),
            "background_workers": self.background_workers.value(),
            "warm_cache_on_startup": self.warm_cache_checkbox.isChecked(),
            "reduced_motion": self.reduced_motion_checkbox.isChecked(),
        }
        setup["stats"] = {
            "default_range": str(self.stats_default_range.currentData() or "daily"),
        }
        setup["audio"] = self._current_audio_setup()
        self.datastore.save_setup(setup)
        self.accept()

    def _current_audio_setup(self) -> dict:
        return {
            "enabled": bool(self.audio_enabled_checkbox.isChecked()),
            "click_enabled": bool(self.click_enabled_checkbox.isChecked()),
            "click_sound": str(self.click_sound_combo.currentData() or "click3"),
            "transition_enabled": bool(self.transition_enabled_checkbox.isChecked()),
            "transition_sound": str(self.transition_sound_combo.currentData() or "woosh"),
            "notification_sound": str(self.notification_sound_combo.currentData() or "windows"),
        }

    def _apply_audio_preview_config(self) -> None:
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "configure"):
            sounds.configure({"audio": self._current_audio_setup()})

    def _test_click_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click")

    def _test_transition_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("woosh")

    def _test_notification_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sound = str(self.notification_sound_combo.currentData() or "windows")
        if parent is not None and hasattr(parent, "show_audio_test_notification"):
            parent.show_audio_test_notification(sound)
            return
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play_notification(sound)

    def _play_click_sound(self, *, volume_scale: float = 1.0) -> None:
        if not self._sfx_ready:
            return
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click", volume_scale=volume_scale)

    def _play_slider_sound(self, *, volume_scale: float = 1.0) -> None:
        if not self._sfx_ready:
            return
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "play_slider_click"):
            sounds.play_slider_click(volume_scale=volume_scale)
        elif sounds is not None:
            sounds.play("click", volume_scale=volume_scale)

    def _on_attention_changed(self, value: int) -> None:
        if value != self._last_attention_value:
            self._play_slider_sound(volume_scale=1.25)
        self._last_attention_value = value
        self._update_attention_label(value)

    def _on_gender_mode_changed(self) -> None:
        is_custom = self.gender_combo.currentText().strip().lower() == "custom"
        self.gender_custom_edit.setVisible(is_custom)
        if hasattr(self, "avatar_grid"):
            allowed = self._avatar_allowed_categories_for_gender(self._avatar_filter_gender())
            if self._avatar_category and self._avatar_category not in allowed:
                chosen = self._choose_random_avatar(self._avatar_filter_gender())
                if chosen is not None:
                    category, path = chosen
                    self._set_current_avatar(category, path, refresh_grid=False)
            self._refresh_avatar_grid()

    def _on_ask_ai_emoji_changed(self, value: int) -> None:
        if value != self._last_ask_ai_emoji_value:
            self._play_slider_sound(volume_scale=1.1)
        self._last_ask_ai_emoji_value = value
        self._update_ask_ai_emoji_label(value)

    def _refresh_text_model_choices_from_saved(self, ai_settings: dict) -> None:
        setup = self.datastore.load_setup()
        installed_models = dict(setup.get("installed_models", {}))
        saved_key = str(ai_settings.get("selected_text_llm_key", "")).strip()
        installed_keys = [key for key in non_embedding_llm_keys() if bool(installed_models.get(key, False))]
        all_installed_keys = [key for key in MODELS if bool(installed_models.get(key, False))]
        self.selected_text_llm.blockSignals(True)
        self.selected_text_llm.clear()
        for key in installed_keys:
            spec = MODELS.get(key)
            if spec is not None:
                self.selected_text_llm.addItem(spec.display_name, key)
        selected_index = self.selected_text_llm.findData(saved_key)
        if selected_index < 0 and self.selected_text_llm.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            self.selected_text_llm.setCurrentIndex(selected_index)
        cloud_enabled = self._cloud_mode_enabled()
        self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0 and not cloud_enabled)
        self.selected_text_llm.setToolTip("Cloud mode is enabled. Use the Cloud model selector above." if cloud_enabled else "")
        self.selected_text_llm.blockSignals(False)
        self._refresh_context_model_choices(ai_settings, all_installed_keys)
        self._refresh_ocr_model_choices_from_keys(installed_keys, ai_settings)

    def _refresh_text_model_choices(self, snap=None) -> None:
        snapshot = snap or self.preflight.snapshot(force=False)
        ai_settings = self.datastore.load_ai_settings()
        saved_key = str(ai_settings.get("selected_text_llm_key", "")).strip()
        installed_keys = [key for key in non_embedding_llm_keys() if self._is_model_installed_ui(snapshot, key)]
        all_installed_keys = [key for key in MODELS if self._is_model_installed_ui(snapshot, key)]
        current_key = str(self.selected_text_llm.currentData() or saved_key).strip()
        target_key = saved_key if saved_key in installed_keys else (installed_keys[0] if installed_keys else "")
        self.selected_text_llm.blockSignals(True)
        self.selected_text_llm.clear()
        for key in installed_keys:
            spec = MODELS.get(key)
            if spec is None:
                continue
            self.selected_text_llm.addItem(spec.display_name, key)
        selected_index = self.selected_text_llm.findData(target_key)
        if selected_index < 0:
            selected_index = self.selected_text_llm.findData(current_key)
        if selected_index < 0 and self.selected_text_llm.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            self.selected_text_llm.setCurrentIndex(selected_index)
        cloud_enabled = self._cloud_mode_enabled()
        self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0 and not cloud_enabled)
        if cloud_enabled:
            self.selected_text_llm.setToolTip("Cloud mode is enabled. Use the Cloud model selector above.")
        else:
            self.selected_text_llm.setToolTip("")
        self.selected_text_llm.blockSignals(False)
        self._refresh_context_model_choices(ai_settings, all_installed_keys)
        self._refresh_ocr_model_choices_from_keys([key for key in ocr_llm_keys() if self._is_model_installed_ui(snapshot, key)], ai_settings)

    def _refresh_ocr_model_choices_from_keys(self, installed_keys: list[str], ai_settings: dict) -> None:
        supported_keys = [key for key in ocr_llm_keys() if key in set(installed_keys)]
        selected_key = resolve_active_ocr_llm_key(ai_settings, supported_keys)
        if selected_key not in supported_keys and supported_keys:
            selected_key = smallest_supported_ocr_llm_key(supported_keys)
        self.selected_ocr_llm.blockSignals(True)
        self.selected_ocr_llm.clear()
        for key in supported_keys:
            spec = MODELS.get(key)
            if spec is not None:
                self.selected_ocr_llm.addItem(spec.display_name, key)
        selected_index = self.selected_ocr_llm.findData(selected_key)
        if selected_index < 0 and self.selected_ocr_llm.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            self.selected_ocr_llm.setCurrentIndex(selected_index)
        self.selected_ocr_llm.setEnabled(self.selected_ocr_llm.count() > 0)
        self.selected_ocr_llm.setToolTip("" if self.selected_ocr_llm.count() > 0 else "Install a supported text model first.")
        self.selected_ocr_llm.blockSignals(False)
        current_key = str(self.selected_ocr_llm.currentData() or "").strip()
        if current_key and current_key != str(ai_settings.get("selected_ocr_llm_key", "")).strip():
            updated = dict(ai_settings)
            updated["selected_ocr_llm_key"] = current_key
            self.datastore.save_ai_settings(updated)

    def _is_model_installed_ui(self, snapshot, model_key: str) -> bool:
        spec = MODELS.get(model_key)
        if spec is None:
            return False
        if snapshot.cli_available:
            # Prefer live tag inspection whenever Ollama is present.
            if snapshot.installed_tags:
                probe_tags = [spec.primary_tag, *spec.candidate_tags]
                return any(tag in snapshot.installed_tags for tag in probe_tags)
            # If CLI exists but tag lookup failed, avoid stale reinstall/delete states.
            if snapshot.error:
                return False
        return bool(snapshot.installed_models.get(model_key, False))

    def _set_gender_from_profile(self, gender_value: str) -> None:
        gender = str(gender_value or "").strip()
        normalized = gender.lower()
        if normalized == "male":
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        elif normalized == "female":
            self.gender_combo.setCurrentText("Female")
            self.gender_custom_edit.clear()
        elif gender:
            self.gender_combo.setCurrentText("Custom")
            self.gender_custom_edit.setText(gender[:64])
        else:
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        self._on_gender_mode_changed()

    def _effective_gender_value(self) -> str:
        mode = self.gender_combo.currentText().strip()
        if mode.lower() == "custom":
            return self.gender_custom_edit.text().strip()[:64]
        return mode

    def _update_attention_label(self, value: int) -> None:
        self.attention_value.setText(f"Attention span per question: {value} min")

    def _update_ask_ai_emoji_label(self, value: int) -> None:
        self.ask_ai_emoji_value.setText(ASK_AI_EMOJI_LABELS.get(int(value), ASK_AI_EMOJI_LABELS[2]))

    def _set_account_actions_enabled(self, enabled: bool) -> None:
        for button in self._account_action_buttons:
            button.setEnabled(enabled)

    def _export_account_flow(self) -> bool:
        if self.session_controller is None:
            return False
        try:
            temp_zip = self.session_controller.create_temp_export()
        except Exception as exc:
            QMessageBox.warning(self, "Export account", str(exc))
            return False
        icons_root = getattr(getattr(self.parentWidget(), "paths", None), "icons", None)
        dialog = ExportAccountDialog(parent=self, blur_target=None, icons_root=icons_root)
        if dialog.exec_with_backdrop() != QDialog.DialogCode.Accepted or not dialog.download_requested():
            self._cleanup_temp_export(temp_zip)
            return False

        destination = Path.home() / "Downloads" / temp_zip.name

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_zip, destination)
        except Exception as exc:
            QMessageBox.warning(self, "Export account", f"Could not save export: {exc}")
            self._cleanup_temp_export(temp_zip)
            return False
        self._cleanup_temp_export(temp_zip)
        QMessageBox.information(self, "Export account", f"Account copy saved:\n{destination}")
        return True

    @staticmethod
    def _cleanup_temp_export(path: Path) -> None:
        parent = path.parent
        path.unlink(missing_ok=True)
        shutil.rmtree(parent, ignore_errors=True)

    def _delete_account_flow(self) -> None:
        if self.session_controller is None:
            return
        for step in range(1, 5):
            answer = QMessageBox.question(
                self,
                "Delete account",
                f"Your local account will be delete forever. Are you sure? [{step}/4]",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        final = QMessageBox(self)
        final.setWindowTitle("Delete account")
        final.setText("Got it! We will delete your data for you. Would you like to create a copy of your account before you do that?")
        copy_btn = final.addButton("Okay!", QMessageBox.AcceptRole)
        final.addButton("permentantly delete my data", QMessageBox.DestructiveRole)
        cancel_btn = final.addButton("Cancel", QMessageBox.RejectRole)
        final.exec()
        clicked = final.clickedButton()
        if clicked == cancel_btn:
            return
        if clicked == copy_btn and not self._export_account_flow():
            return
        try:
            self.session_controller.delete_current_account()
        except Exception as exc:
            QMessageBox.warning(self, "Delete account", str(exc))
            return
        self.accept()

    def _change_account_flow(self) -> None:
        if self.session_controller is None:
            return
        for _ in range(3):
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Change account")
            confirm.setText(
                "Changin the account will delete your data and overwrite it with the data given by the user. please confirm this message 3 times"
            )
            ok_btn = confirm.addButton("okay", QMessageBox.AcceptRole)
            confirm.addButton("cancel", QMessageBox.RejectRole)
            confirm.exec()
            if confirm.clickedButton() != ok_btn:
                return

        ready = QMessageBox(self)
        ready.setWindowTitle("Change account")
        ready.setText(
            "Got it! After you import your data from the other account, we will delete the in-app data and overwrite it with your new account"
        )
        okay_btn = ready.addButton("Okay", QMessageBox.AcceptRole)
        ready.addButton("Cancel", QMessageBox.RejectRole)
        ready.exec()
        if ready.clickedButton() != okay_btn:
            return

        archive_file, _ = QFileDialog.getOpenFileName(self, "Import account zip", "", "Zip files (*.zip)")
        if not archive_file:
            return
        try:
            self.session_controller.import_archive_into_current(Path(archive_file))
        except Exception as exc:
            QMessageBox.warning(self, "Change account", str(exc))
            return
        QMessageBox.information(self, "Change account", "Account data was imported and overwritten successfully.")
        self.accept()

    def _transfer_account_peer_flow(self) -> None:
        if self.session_controller is None:
            return
        dialog = TransferAccountPeerDialog(parent=self, session_controller=self.session_controller)
        dialog.exec()

    def _transfer_account_host_flow(self) -> None:
        if self.session_controller is None:
            return
        dialog = TransferAccountHostDialog(parent=self, session_controller=self.session_controller)
        dialog.exec()

    def _confirmation_icon_button(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("NewAccountConfirmIconButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(34, 34)
        button.setText("")
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        icon_provider = getattr(self.parentWidget(), "icons", None)
        if icon_provider is not None and hasattr(icon_provider, "icon"):
            button.setIcon(icon_provider.icon("common", icon_name, tooltip[:1]))
            button.setIconSize(QSize(15, 15))
        else:
            icon_root = getattr(getattr(self.parentWidget(), "paths", None), "icons", None)
            if isinstance(icon_root, Path):
                button.setIcon(QIcon(str(icon_root / "common" / f"{icon_name}.png")))
                button.setIconSize(QSize(15, 15))
        return button

    def _new_account_flow(self) -> None:
        if self.session_controller is None:
            return
        profile = self.datastore.load_profile()
        name = str(profile.get("name", "")).strip() or "Student"
        first = QMessageBox(self)
        first.setWindowTitle("New account")
        first.setText(
            f"Hey, {name}. It is nice to see you making another account. Creating a new account won't affect any of your existing account(s). you can change it anytime by pressing on the app icon > pressing accounts > and pressing on your prefered account"
        )
        yes_btn = self._confirmation_icon_button("check", "yes, I am in!")
        cancel_btn = self._confirmation_icon_button("cross_two", "cancel")
        first.addButton(yes_btn, QMessageBox.AcceptRole)
        first.addButton(cancel_btn, QMessageBox.RejectRole)
        first.exec()
        if first.clickedButton() != yes_btn:
            return

        second = QMessageBox(self)
        second.setWindowTitle("New account")
        second.setText("Nice! New account will be made. The app will open a new profile maker window for you to make a new account.")
        okay_btn = self._confirmation_icon_button("check", "Okay")
        nevermind_btn = self._confirmation_icon_button("cross_two", "nevermind, I changed my mind")
        second.addButton(okay_btn, QMessageBox.AcceptRole)
        second.addButton(nevermind_btn, QMessageBox.RejectRole)
        second.exec()
        if second.clickedButton() != okay_btn:
            return

        try:
            created = bool(self.session_controller.create_new_account_via_profile(self))
        except Exception as exc:
            QMessageBox.warning(self, "New account", str(exc))
            return
        if created:
            self.accept()

    def _refresh_model_status(self) -> None:
        snap = self.preflight.snapshot(force=True)
        if snap.cloud_mode:
            if not snap.cloud_key_present:
                self.ollama_status.setText("Cloud mode is enabled, but API key is missing.")
                self.ollama_hint.setText("Paste your API key in the Ollama cloud section above.")
            elif snap.error and not snap.installed_tags:
                self.ollama_status.setText("Cloud mode is enabled, but ONCard could not read cloud model tags.")
                self.ollama_hint.setText(snap.error or "Check the API key and internet connection, then refresh.")
            else:
                api_text = "Cloud API reachable." if snap.api_reachable else "Cloud API not responding yet."
                self.ollama_status.setText(f"Ollama Cloud is active. {api_text}")
                self.ollama_hint.setText("Install/Reinstall/Delete actions are disabled while cloud mode is active.")
        elif not snap.cli_available:
            self.ollama_status.setText("Ollama CLI was not found on this system.")
            self.ollama_hint.setText("Install Ollama first, then use this tab to install or refresh ONCard's models.")
        elif snap.error and not snap.installed_tags:
            self.ollama_status.setText("Ollama is installed, but ONCard could not read live model tags right now.")
            self.ollama_hint.setText(snap.error or "Make sure Ollama is running, then refresh model status.")
        else:
            api_text = "API reachable." if snap.api_reachable else "API not responding yet."
            self.ollama_status.setText(f"Ollama is installed. {api_text}")
            self.ollama_hint.setText("Model status below comes from the live Ollama tag list.")

        installing = bool(self._install_worker and self._install_worker.isRunning())
        text_keys = set(non_embedding_llm_keys())
        for key, spec in MODELS.items():
            row = self._model_rows[key]
            status_label = row["status"]
            install_btn = row["install_btn"]
            reinstall_btn = row["reinstall_btn"]
            delete_btn = row["delete_btn"]
            is_installed = self._is_model_installed_ui(snap, key)
            if snap.cloud_mode:
                if key in text_keys:
                    status_text = "Available in cloud" if is_installed else "Unavailable in cloud"
                else:
                    status_text = "Installed" if is_installed else "Not installed"
                install_btn.setVisible(False)
                reinstall_btn.setVisible(False)
                delete_btn.setVisible(False)
                install_btn.setEnabled(False)
                reinstall_btn.setEnabled(False)
                delete_btn.setEnabled(False)
                status_label.setText(status_text)
                continue
            if snap.error and not snap.installed_tags and snap.cli_available:
                status_text = "Saved installed" if is_installed else "Status unavailable"
            else:
                status_text = "Installed" if is_installed else "Not installed"
            status_label.setText(status_text)
            install_btn.setVisible(not is_installed)
            reinstall_btn.setVisible(is_installed)
            delete_btn.setVisible(is_installed)
            enabled = snap.cli_available and not installing
            install_btn.setEnabled(enabled)
            reinstall_btn.setEnabled(enabled)
            delete_btn.setEnabled(enabled)
        self._refresh_text_model_choices(snap)

    def _install_model(self, model_key: str) -> None:
        if self._install_worker and self._install_worker.isRunning():
            return
        if self._cloud_mode_enabled():
            QMessageBox.information(self, "Cloud mode active", "Turn off cloud mode to install local Ollama models.")
            return
        if shutil.which("ollama") is None:
            QMessageBox.warning(self, "Ollama missing", "Install Ollama first, then come back to install ONCard's models.")
            return
        if model_key not in MODELS:
            return

        self._install_target_key = model_key
        self._model_worker_action = "install"
        self.install_log.clear()
        self.install_log.append(f"Installing {MODELS[model_key].display_name}...")
        self.install_log.append("Press Ctrl + C twice in the terminal if you need to cancel the running Ollama action.")
        self._set_install_buttons_enabled(False)
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        worker = ModelInstallWorker([model_key], self.ollama, action="install")
        self._install_worker = worker
        worker.line.connect(self.install_log.append)
        worker.complete.connect(self._on_install_complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _delete_model(self, model_key: str) -> None:
        if self._install_worker and self._install_worker.isRunning():
            return
        if self._cloud_mode_enabled():
            QMessageBox.information(self, "Cloud mode active", "Turn off cloud mode to remove local Ollama models.")
            return
        spec = MODELS.get(model_key)
        if spec is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete model",
            f"Remove {spec.display_name} from Ollama?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        self._install_target_key = model_key
        self._model_worker_action = "remove"
        self.install_log.clear()
        self.install_log.append(f"Removing {spec.display_name}...")
        self.install_log.append("Press Ctrl + C twice in the terminal if you need to cancel the running Ollama action.")
        self._set_install_buttons_enabled(False)
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        worker = ModelInstallWorker([model_key], self.ollama, action="remove")
        self._install_worker = worker
        worker.line.connect(self.install_log.append)
        worker.complete.connect(self._on_install_complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_install_complete(self, status: dict) -> None:
        updated_setup = self.datastore.load_setup()
        installed_models = dict(updated_setup.get("installed_models", {}))
        selected_models = list(updated_setup.get("selected_models", []))
        ai_settings = self.datastore.load_ai_settings()

        successes = []
        failures = []
        for key, ok in status.items():
            if self._model_worker_action == "remove":
                if ok:
                    installed_models[key] = False
                    selected_models = [item for item in selected_models if item != key]
                    if str(ai_settings.get("selected_text_llm_key", "")).strip() == key:
                        replacement = ""
                        for llm_key in non_embedding_llm_keys():
                            if llm_key != key and bool(installed_models.get(llm_key, False)):
                                replacement = llm_key
                                break
                        ai_settings["selected_text_llm_key"] = replacement
                    if str(ai_settings.get("selected_ocr_llm_key", "")).strip() == key:
                        replacement_keys = [
                            llm_key
                            for llm_key in ocr_llm_keys()
                            if llm_key != key and bool(installed_models.get(llm_key, False))
                        ]
                        ai_settings["selected_ocr_llm_key"] = smallest_supported_ocr_llm_key(replacement_keys)
                    for context_key, _label, _description, _minimum in CONTEXT_LENGTH_SETTINGS:
                        model_setting_key = feature_model_setting_key(context_key)
                        if str(ai_settings.get(model_setting_key, "")).strip() == key:
                            ai_settings[model_setting_key] = ""
                    successes.append(MODELS[key].display_name)
                else:
                    failures.append(MODELS[key].display_name)
                continue
            installed_models[key] = bool(ok)
            if ok and key not in selected_models:
                selected_models.append(key)
                successes.append(MODELS[key].display_name)
            elif ok:
                successes.append(MODELS[key].display_name)
            else:
                failures.append(MODELS[key].display_name)
            if ok and key == QN_SUMMARIZER_MODEL_KEY:
                ai_settings["wiki_breakdown_model_key"] = QN_SUMMARIZER_MODEL_KEY
                ai_settings["wiki_breakdown_context_length"] = QN_SUMMARIZER_CONTEXT_LENGTH
                ai_settings[QN_SUMMARIZER_AUTO_SELECTED_SETTING] = True

        updated_setup["installed_models"] = installed_models
        updated_setup["selected_models"] = selected_models
        self.datastore.save_setup(updated_setup)
        self.datastore.save_ai_settings(ai_settings)
        self.preflight.invalidate()

        self._install_worker = None
        completed_action = self._model_worker_action
        self._model_worker_action = "install"
        self._set_install_buttons_enabled(True)
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._refresh_model_status()

        if completed_action == "remove" and successes and not failures:
            QMessageBox.information(self, "Model removed", f"{', '.join(successes)} removed successfully.")
        elif successes and not failures:
            QMessageBox.information(self, "Model installed", f"{', '.join(successes)} installed successfully.")
        elif failures and not successes:
            title = "Remove failed" if completed_action == "remove" else "Install failed"
            verb = "remove" if completed_action == "remove" else "install"
            QMessageBox.warning(self, title, f"Could not {verb} {', '.join(failures)}.")
        elif successes and failures:
            QMessageBox.warning(
                self,
                "Action partially failed",
                f"Completed: {', '.join(successes)}\nFailed: {', '.join(failures)}",
            )

    def _run_deferred_auto_install(self) -> None:
        key = self._auto_install_model_key
        self._auto_install_model_key = ""
        if key not in MODELS:
            return
        self._set_settings_page(4, animate=True)
        QTimer.singleShot(80, lambda model_key=key: self._scroll_to_model_install_section(model_key))
        QTimer.singleShot(160, lambda model_key=key: self._install_model(model_key))
        QTimer.singleShot(260, lambda model_key=key: self._scroll_to_model_install_section(model_key))

    def _scroll_to_model_install_section(self, model_key: str) -> None:
        scroll = self._settings_tab_scrolls.get("ai")
        if not isinstance(scroll, QScrollArea):
            return
        row = self._model_rows.get(str(model_key or "").strip(), {})
        widget = row.get("container") if isinstance(row, dict) else None
        if not isinstance(widget, QWidget):
            widget = getattr(self, "install_log", None)
        if not isinstance(widget, QWidget):
            return
        scroll.ensureWidgetVisible(widget, 24, 110)
        install_log = getattr(self, "install_log", None)
        if isinstance(install_log, QWidget):
            QTimer.singleShot(70, lambda: scroll.ensureWidgetVisible(install_log, 24, 72))
        self._sync_settings_bordered_widget_heights()

    def _set_install_buttons_enabled(self, enabled: bool) -> None:
        cli_installed = shutil.which("ollama") is not None
        cloud_mode = self._cloud_mode_enabled()
        for row in self._model_rows.values():
            row["install_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
            row["reinstall_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
            row["delete_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
        self.refresh_models_btn.setEnabled(enabled)

    def _refresh_performance_mode(self) -> None:
        manual = str(self.performance_mode.currentData() or "auto") == "manual"
        self.startup_workers.setEnabled(manual)
        self.background_workers.setEnabled(manual)

    def reject(self) -> None:
        if self._install_worker and self._install_worker.isRunning():
            QMessageBox.information(self, "Install in progress", "Wait for the current model installation to finish first.")
            return
        self._clear_backdrop()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "configure"):
            sounds.configure(self.datastore.load_setup())
        super().reject()

    @staticmethod
    def _coerce_age(value: object) -> int:
        try:
            age = int(str(value).strip())
        except (TypeError, ValueError):
            return 16
        return max(4, min(99, age))
